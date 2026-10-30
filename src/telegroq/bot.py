"""The :class:`TeleGroqBot` class: routing, sending helpers and the polling loop."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

import telebot
from telebot import types, util
from telebot.apihelper import ApiTelegramException

from . import _groq
from .character import Character
from .errors import ConfigurationError
from .message import CallbackContext, Message

__all__ = ["TeleGroqBot", "createBot"]

logger = logging.getLogger("telegroq")

Handler = Callable[[types.User, Message], Any]
CallbackHandler = Callable[[types.User, CallbackContext], Any]
ErrorHandler = Callable[[BaseException, types.User, Message | CallbackContext], Any]

_NON_TEXT_TYPES = [t for t in util.content_type_media if t != "text"]
_COMMAND_NAME = re.compile(r"^[a-z0-9_]{1,32}$")
_HAS_REPLY_PARAMETERS = hasattr(types, "ReplyParameters")


def _quote_kwargs(message_id: int) -> dict[str, Any]:
    """Keyword arguments that make ``send_message`` quote ``message_id``."""
    if _HAS_REPLY_PARAMETERS:
        return {"reply_parameters": types.ReplyParameters(message_id, allow_sending_without_reply=True)}
    return {"reply_to_message_id": message_id, "allow_sending_without_reply": True}  # pragma: no cover


class TeleGroqBot:
    """A Telegram bot (wrapping ``telebot.TeleBot``) with Groq helpers.

    Create it with :func:`telegroq.createBot`. The underlying ``TeleBot`` is
    available as :attr:`telebot`, and unknown attributes (``bot.send_photo``,
    ``bot.get_me`` ...) are forwarded to it, so everything telebot can do is
    still within reach.

    Handlers registered with :meth:`cmd`, :meth:`on_message` and :meth:`callback`
    are called as ``handler(user, msg)`` / ``handler(user, call)``; an exception
    inside one is logged and never stops the polling loop.

    Args:
        token: Telegram bot token from @BotFather (``"<digits>:<secret>"``).
        non_text_reply: Sent in private chats for media nobody handles
            (photos, stickers, voice notes ...). ``None`` stays silent.
        error_reply: Sent when one of your handlers raises. ``None`` stays
            silent. Ignored once you register :meth:`on_error`.
        **telebot_kwargs: Passed to ``telebot.TeleBot`` (``parse_mode``,
            ``threaded``, ``num_threads`` ...). ``num_threads`` defaults to 8
            because Groq calls block a worker thread.
    """

    def __init__(
        self,
        token: str,
        *,
        non_text_reply: str | None = "I can only read text messages for now. \U0001f4dd",
        error_reply: str | None = "Oops, something went wrong on my side. Please try again.",
        **telebot_kwargs: Any,
    ) -> None:
        telebot_kwargs.setdefault("num_threads", 8)
        self.telebot = telebot.TeleBot(token, **telebot_kwargs)
        self.groq_client: Any | None = None
        self.model: str = _groq.DEFAULT_MODEL
        self.non_text_reply = non_text_reply
        self.error_reply = error_reply
        self._commands: set[str] = set()
        self._menu: dict[str, str] = {}
        self._claimed_types: set[str] = set()
        self._fallback_registered = False
        self._error_handler: ErrorHandler | None = None

    def __getattr__(self, name: str) -> Any:
        # Only reached for attributes TeleGroqBot does not define itself.
        if name == "telebot" or (name.startswith("__") and name.endswith("__")):
            raise AttributeError(name)
        return getattr(self.telebot, name)

    def __repr__(self) -> str:
        return f"<TeleGroqBot id={self.telebot.bot_id} model={self.model!r}>"

    # ------------------------------------------------------------------- Groq
    def set_groq_key(
        self,
        api_key: str,
        model: str = _groq.DEFAULT_MODEL,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> TeleGroqBot:
        """Create the Groq client used by every :class:`~telegroq.Character`.

        A character uses the client of the bot it is bound to (``setCh(...,
        bot=bot)`` or ``character.bind(bot)``), otherwise that of the most
        recently configured bot.

        Args:
            api_key: Groq API key (``gsk_...``).
            model: Default model id, e.g. ``"llama-3.3-70b-versatile"``.
            timeout: Per-request timeout in seconds.
            max_retries: Automatic retries done by the Groq SDK.

        Returns:
            The bot itself, so calls can be chained.

        Raises:
            ConfigurationError: if ``api_key`` is empty.
            ImportError: if the ``groq`` package is missing.
        """
        config = _groq.configure_groq(api_key, model, timeout=timeout, max_retries=max_retries)
        self.groq_client, self.model = config.client, config.model
        return self

    # ---------------------------------------------------------------- routing
    def cmd(
        self,
        *names: str,
        description: str | None = None,
        chat_types: list[str] | None = None,
    ) -> Callable[[Handler], Handler]:
        """Register ``handler(user, msg)`` for one or more commands.

        ``@bot.cmd("/start")``, ``@bot.cmd("start")`` and ``@bot.cmd("help", "about")``
        all work, in any letter case. Arguments are in ``msg.args``.

        Args:
            *names: Command names, with or without the leading slash.
            description: Optional text for Telegram's command menu (the "/" button);
                published for the first name by :meth:`publish_commands` / :meth:`run`.
            chat_types: Restrict to e.g. ``["private"]``.

        Raises:
            ConfigurationError: for an empty or invalid name (Telegram allows
                lowercase letters, digits and underscores, up to 32 characters).
        """
        cleaned = [n.strip().lstrip("/").lower() for n in names if n and n.strip().lstrip("/")]
        if not cleaned:
            raise ConfigurationError("cmd() needs at least one command name, e.g. @bot.cmd('/start')")
        for name in cleaned:
            if not _COMMAND_NAME.match(name):
                raise ConfigurationError(f"invalid command name {name!r}: use a-z, 0-9 and _ (max 32 chars)")
        self._commands.update(cleaned)
        if description:
            self._menu[cleaned[0]] = description
        wanted = set(cleaned)

        def matches(m: types.Message) -> bool:
            # telebot's own ``commands=`` filter is case-sensitive; Telegram clients are not.
            if m.content_type != "text" or not m.text:
                return False
            name = util.extract_command(m.text)
            return name is not None and name.lower() in wanted

        def decorator(fn: Handler) -> Handler:
            self.telebot.message_handler(content_types=["text"], chat_types=chat_types, func=matches)(
                self._guard(fn)
            )
            return fn

        return decorator

    def on_message(
        self,
        content_types: list[str] | None = None,
        *,
        chat_types: list[str] | None = None,
        regexp: str | None = None,
        func: Callable[[types.Message], bool] | None = None,
        typing: bool = True,
    ) -> Callable[[Handler], Handler]:
        """Register a wildcard ``handler(user, msg)`` (text messages by default).

        Registered commands are never routed here, whatever the registration
        order. Pass ``content_types=["text", "photo"]`` to receive other kinds
        too (``msg.text`` is ``""`` for those).

        Args:
            content_types: Telegram content types to accept (default ``["text"]``).
            chat_types: Restrict to e.g. ``["private"]`` (recommended in groups).
            regexp: Only messages whose text matches this regular expression.
            func: Extra filter ``(telebot_message) -> bool``.
            typing: Show "typing..." while your handler (and thus Groq) works.
        """
        accepted = list(content_types or ["text"])
        self._claimed_types.update(accepted)

        def not_a_command(m: types.Message) -> bool:
            if m.content_type == "text" and m.text:
                name = util.extract_command(m.text)
                if name is not None and name.lower() in self._commands:
                    return False
            return func(m) if func else True

        def decorator(fn: Handler) -> Handler:
            self.telebot.message_handler(
                content_types=accepted, chat_types=chat_types, regexp=regexp, func=not_a_command
            )(self._guard(fn, typing=typing))
            return fn

        return decorator

    def auto_reply(
        self,
        character: Character,
        *,
        chat_types: list[str] | None = None,
        quote: bool | None = None,
        typing: bool = True,
    ) -> Handler:
        """Answer every non-command text message with ``character`` (the few-lines path).

        Equivalent to a hand-written ``@bot.on_message()`` handler that calls
        ``character.get_response`` and replies.

        Args:
            character: The persona that answers.
            chat_types: Restrict to e.g. ``["private"]``.
            quote: Quote the user's message in the reply. Default: only in groups.
            typing: Show "typing..." while waiting for Groq.

        Returns:
            The registered handler function.
        """

        def _auto_reply(user: types.User, msg: Message) -> None:
            answer = character.get_response(user.id, msg.text)
            if quote or (quote is None and not msg.is_private):
                msg.reply(answer)
            else:
                self.send_message(msg.chat_id, answer)

        self.on_message(chat_types=chat_types, typing=typing)(_auto_reply)
        return _auto_reply

    def callback(
        self,
        *data: str,
        prefix: str | None = None,
        regex: str | None = None,
        func: Callable[[types.CallbackQuery], bool] | None = None,
    ) -> Callable[[CallbackHandler], CallbackHandler]:
        """Register ``handler(user, call)`` for presses of inline-keyboard buttons.

        Pick at most one selector; with none, the handler receives every press
        that no earlier handler took.

        * ``@bot.callback("menu:help")``: exact ``callback_data`` (several allowed)
        * ``@bot.callback(prefix="persona:")``: starts with; ``call.args`` is the rest
        * ``@bot.callback(regex=r"^vote:(yes|no)$")``: ``re.search`` on the data

        ``call`` is a :class:`~telegroq.CallbackContext`. The query is answered
        automatically when the handler returns, unless you called ``call.answer()``.

        Raises:
            ConfigurationError: if more than one selector is given.
        """
        if sum(bool(x) for x in (data, prefix, regex)) > 1:
            raise ConfigurationError("callback(): use only one of exact data, prefix= or regex=")
        pattern = re.compile(regex) if regex else None

        def matches(call: types.CallbackQuery) -> bool:
            value = call.data or ""
            if data and value not in data:
                return False
            if prefix and not value.startswith(prefix):
                return False
            if pattern and not pattern.search(value):
                return False
            return func(call) if func else True

        def decorator(fn: CallbackHandler) -> CallbackHandler:
            self.telebot.callback_query_handler(func=matches)(self._guard_callback(fn, prefix))
            return fn

        return decorator

    def on_error(self, fn: ErrorHandler) -> ErrorHandler:
        """Register ``fn(exc, user, update)`` to run when one of your handlers raises.

        ``update`` is the :class:`~telegroq.Message` or :class:`~telegroq.CallbackContext`.
        It replaces the default ``error_reply``; the exception is logged either way.
        """
        self._error_handler = fn
        return fn

    # ------------------------------------------------------- handler plumbing
    def _guard(self, fn: Handler, *, typing: bool = False) -> Callable[[types.Message], None]:
        # NB: no functools.wraps - telebot inspects the handler's signature and
        # would follow __wrapped__ to the 2-argument user function.
        def handler(raw: types.Message) -> None:
            user = raw.from_user
            if user is None:  # channel posts / anonymous admins have no sender
                return
            msg = Message(raw, self)
            try:
                if typing:
                    self._typing(raw.chat.id)
                fn(user, msg)
            except Exception as exc:  # noqa: BLE001 - never let a handler kill the polling loop
                self._handle_error(fn, exc, user, msg)

        handler.__name__ = getattr(fn, "__name__", "handler")
        return handler

    def _guard_callback(self, fn: CallbackHandler, prefix: str | None) -> Callable[[types.CallbackQuery], None]:
        def handler(raw: types.CallbackQuery) -> None:
            user = raw.from_user
            if user is None:  # pragma: no cover - Telegram always sends one
                return
            call = CallbackContext(raw, self, prefix)
            try:
                fn(user, call)
            except Exception as exc:  # noqa: BLE001
                self._handle_error(fn, exc, user, call)
            finally:
                if not call.answered:  # stop the button's loading spinner
                    try:
                        call.answer()
                    except Exception:  # noqa: BLE001 - e.g. "query is too old"
                        logger.debug("Could not answer callback query", exc_info=True)

        handler.__name__ = getattr(fn, "__name__", "handler")
        return handler

    def _handle_error(
        self, fn: Callable[..., Any], exc: Exception, user: types.User, update: Message | CallbackContext
    ) -> None:
        logger.error("Unhandled error in handler %r", getattr(fn, "__name__", fn), exc_info=exc)
        try:
            if self._error_handler is not None:
                self._error_handler(exc, user, update)
            elif self.error_reply:
                if isinstance(update, CallbackContext):
                    update.answer(self.error_reply, alert=True)
                else:
                    self.telebot.send_message(update.chat_id, self.error_reply)
        except Exception:  # noqa: BLE001
            logger.exception("The error handling itself failed")

    def _typing(self, chat_id: int) -> None:
        try:
            self.telebot.send_chat_action(chat_id, "typing")
        except Exception:  # noqa: BLE001 - cosmetic only
            logger.debug("send_chat_action failed", exc_info=True)

    def _register_non_text_fallback(self) -> None:
        """Answer media nobody asked for, in private chats only (never spams groups).

        Registered lazily from :meth:`run` so it is tested *after* user handlers.
        """
        if self._fallback_registered or not self.non_text_reply:
            return
        self._fallback_registered = True
        unclaimed = [t for t in _NON_TEXT_TYPES if t not in self._claimed_types]
        if not unclaimed:
            return

        @self.telebot.message_handler(content_types=unclaimed, chat_types=["private"])
        def _non_text(raw: types.Message) -> None:
            try:
                self.telebot.send_message(raw.chat.id, self.non_text_reply)
            except Exception:  # noqa: BLE001
                logger.exception("Could not send the non-text notice")

    # ---------------------------------------------------------------- sending
    def send_message(self, user_id: int | str, text: str, **kwargs: Any) -> types.Message | None:
        """Send ``text`` to a chat.

        Texts above Telegram's 4096-character limit are split into several
        messages (``reply_markup`` goes on the last one). If ``parse_mode`` is
        given and Telegram cannot parse the entities (typical for LLM output with
        stray ``*`` or ``_``), the text is re-sent as plain text.

        Args:
            user_id: Chat id (the user's id in private chats) or ``"@channel"``.
            text: What to send. Empty or blank text sends nothing.
            **kwargs: Passed to ``telebot.TeleBot.send_message``.

        Returns:
            The last sent message, or ``None`` if nothing was sent.
        """
        return self._send(user_id, text, None, kwargs)

    def reply(
        self,
        user_id: int | str,
        text: str,
        message_id: int | None = None,
        **kwargs: Any,
    ) -> types.Message | None:
        """Like :meth:`send_message`, quoting ``message_id`` on the first part."""
        return self._send(user_id, text, message_id, kwargs)

    def _send(self, chat_id: int | str, text: str, message_id: int | None, kwargs: dict[str, Any]) -> Any:
        if not text or not text.strip():
            return None
        chunks = util.smart_split(text)
        markup = kwargs.pop("reply_markup", None)
        sent = None
        for index, chunk in enumerate(chunks):
            options = dict(kwargs)
            if index == 0 and message_id is not None:
                for key, value in _quote_kwargs(message_id).items():
                    options.setdefault(key, value)
            if index == len(chunks) - 1 and markup is not None:
                options["reply_markup"] = markup
            sent = self._send_chunk(chat_id, chunk, options)
        return sent

    def _send_chunk(self, chat_id: int | str, text: str, options: dict[str, Any]) -> Any:
        try:
            return self.telebot.send_message(chat_id, text, **options)
        except ApiTelegramException as exc:
            description = str(getattr(exc, "description", "")).lower()
            if options.get("parse_mode") and "can't parse entities" in description:
                logger.warning("Telegram could not parse the formatting; resending as plain text")
                plain = {k: v for k, v in options.items() if k != "parse_mode"}
                return self.telebot.send_message(chat_id, text, **plain)
            raise

    # -------------------------------------------------------------- lifecycle
    def publish_commands(self) -> bool:
        """Publish commands registered with a ``description`` to Telegram's command menu.

        Called by :meth:`run`. Returns ``True`` if the menu was updated.
        """
        if not self._menu:
            return False
        try:
            self.telebot.set_my_commands([types.BotCommand(c, d) for c, d in self._menu.items()])
        except Exception:  # noqa: BLE001
            logger.warning("Could not publish the command menu", exc_info=True)
            return False
        return True

    def run(
        self,
        *,
        skip_pending: bool = True,
        timeout: int = 20,
        long_polling_timeout: int = 20,
        set_commands: bool = True,
    ) -> None:
        """Start long polling and keep going through network and API errors.

        Blocks until interrupted (Ctrl+C).

        Args:
            skip_pending: Ignore messages sent while the bot was offline.
            timeout: Connection timeout of each request, in seconds.
            long_polling_timeout: Server-side wait of each ``getUpdates`` call.
            set_commands: Publish described commands to the command menu first.
        """
        self._register_non_text_fallback()
        if set_commands:
            self.publish_commands()
        try:
            logger.info("telegroq started as @%s", self.telebot.get_me().username)
        except Exception as exc:  # noqa: BLE001 - infinity_polling keeps retrying anyway
            logger.warning("Could not reach Telegram yet (%s); will keep retrying.", exc)
        try:
            self.telebot.infinity_polling(
                timeout=timeout,
                long_polling_timeout=long_polling_timeout,
                skip_pending=skip_pending,
                logger_level=logging.ERROR,
            )
        except KeyboardInterrupt:
            logger.info("Stopped by user")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop polling (safe to call from another thread or handler)."""
        self.telebot.stop_polling()


def createBot(token: str, **kwargs: Any) -> TeleGroqBot:
    """Create a :class:`TeleGroqBot`.

    Args:
        token: Telegram bot token from @BotFather.
        **kwargs: ``non_text_reply``, ``error_reply`` and anything ``telebot.TeleBot`` accepts.
    """
    return TeleGroqBot(token, **kwargs)
