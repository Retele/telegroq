"""Streamlined wrappers handed to handlers: :class:`Message` and :class:`CallbackContext`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from telebot import types, util
from telebot.apihelper import ApiTelegramException

if TYPE_CHECKING:  # pragma: no cover
    from .bot import TeleGroqBot

__all__ = ["Message", "CallbackContext"]


class Message:
    """A ``telebot.types.Message`` with the rough edges sanded off.

    ``text`` is always a ``str`` (``""`` for photos, stickers, voice notes ...);
    every other attribute (``message_id``, ``caption``, ``photo`` ...) is
    forwarded to the raw telebot message, which is also available as :attr:`raw`.
    """

    def __init__(self, raw: types.Message, bot: TeleGroqBot) -> None:
        self.raw = raw
        self._bot = bot

    @property
    def text(self) -> str:
        """The message text, or ``""`` when the message has none."""
        return getattr(self.raw, "text", None) or ""

    @property
    def is_text(self) -> bool:
        """``True`` for a non-empty plain text message."""
        return getattr(self.raw, "content_type", None) == "text" and bool(self.text)

    @property
    def args(self) -> str:
        """Text after the command: ``"/cmd some args"`` gives ``"some args"``."""
        return (util.extract_arguments(self.text) or "") if self.text else ""

    @property
    def chat_id(self) -> int:
        """Id of the chat the message was sent in (equals the user id in private chats)."""
        return self.raw.chat.id

    @property
    def chat_type(self) -> str:
        """``"private"``, ``"group"``, ``"supergroup"`` or ``"channel"``."""
        return self.raw.chat.type

    @property
    def is_private(self) -> bool:
        return self.chat_type == "private"

    def reply(self, text: str, **kwargs: Any) -> types.Message | None:
        """Reply to this message in its own chat (the right call in groups)."""
        return self._bot.reply(self.chat_id, text, message_id=self.raw.message_id, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if name in ("raw", "_bot"):  # not initialised yet (copy / pickle safety)
            raise AttributeError(name)
        return getattr(self.raw, name)

    def __repr__(self) -> str:
        return f"<telegroq.Message id={self.raw.message_id} text={self.text[:40]!r}>"


class CallbackContext:
    """What a ``@bot.callback`` handler receives: a pressed inline button.

    Telegram shows a loading spinner on the button until the query is answered.
    telegroq answers it automatically when your handler returns, unless you
    already did with :meth:`answer`.

    Attributes:
        raw: The underlying ``telebot.types.CallbackQuery``.
        user: Who pressed the button.
        data: The button's ``callback_data``.
        args: ``data`` without the registered prefix (``""`` for exact matches).
        answered: Whether the query has been answered.
    """

    def __init__(self, raw: types.CallbackQuery, bot: TeleGroqBot, prefix: str | None = None) -> None:
        self.raw = raw
        self._bot = bot
        self.answered = False
        self.data: str = raw.data or ""
        self.args: str = self.data[len(prefix) :] if prefix and self.data.startswith(prefix) else ""

    @property
    def user(self) -> types.User:
        return self.raw.from_user

    @property
    def id(self) -> str:
        """The callback query id."""
        return self.raw.id

    @property
    def message(self) -> Message | None:
        """The message the button is attached to (``None`` for inline-mode buttons)."""
        return Message(self.raw.message, self._bot) if self.raw.message is not None else None

    @property
    def chat_id(self) -> int | None:
        return self.raw.message.chat.id if self.raw.message is not None else None

    @property
    def message_id(self) -> int | None:
        return self.raw.message.message_id if self.raw.message is not None else None

    def answer(self, text: str | None = None, alert: bool = False, **kwargs: Any) -> bool:
        """Answer the query: optional toast ``text`` (or a modal popup if ``alert``)."""
        self.answered = True
        return self._bot.telebot.answer_callback_query(
            self.raw.id, text=text, show_alert=True if alert else None, **kwargs
        )

    def edit(self, text: str, **kwargs: Any) -> types.Message | bool | None:
        """Edit the text of the message holding the button (and optionally its keyboard).

        Returns ``None`` instead of raising when Telegram says the new content is
        identical to the old one (a common case when a button is pressed twice).
        """
        return self._edit(self._bot.telebot.edit_message_text, text, **kwargs)

    def edit_keyboard(self, reply_markup: types.InlineKeyboardMarkup | None) -> types.Message | bool | None:
        """Replace (or with ``None``, remove) the inline keyboard of the message."""
        return self._edit(self._bot.telebot.edit_message_reply_markup, reply_markup=reply_markup)

    def reply(self, text: str, **kwargs: Any) -> types.Message | None:
        """Send a new message in the chat of the button (or privately to the user)."""
        return self._bot.send_message(self.chat_id if self.chat_id is not None else self.user.id, text, **kwargs)

    def _edit(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        if self.raw.message is not None:
            kwargs.update(chat_id=self.chat_id, message_id=self.message_id)
        elif getattr(self.raw, "inline_message_id", None):
            kwargs.update(inline_message_id=self.raw.inline_message_id)
        try:
            return method(*args, **kwargs)
        except ApiTelegramException as exc:
            if "message is not modified" in str(getattr(exc, "description", "")).lower():
                return None
            raise

    def __repr__(self) -> str:
        return f"<telegroq.CallbackContext data={self.data!r} user={self.user.id}>"
