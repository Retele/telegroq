"""AI personas with per-user conversation memory."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import _groq
from .errors import ConfigurationError
from .fallbacks import DEFAULT_FALLBACKS, classify_error
from .storage import HistoryStore, MemoryHistoryStore

if TYPE_CHECKING:  # pragma: no cover
    from .bot import TeleGroqBot

__all__ = ["Character", "Reply"]

logger = logging.getLogger("telegroq")


@dataclass(frozen=True)
class Reply:
    """Outcome of :meth:`Character.ask`.

    Attributes:
        text: What to show the user: the model's answer, or a fallback message.
        ok: ``True`` when ``text`` is a real model answer.
        error_kind: ``None`` on success, otherwise a key of ``DEFAULT_FALLBACKS``.
        error: The underlying exception, if there was one.
    """

    text: str
    ok: bool = True
    error_kind: str | None = None
    error: BaseException | None = None

    def __str__(self) -> str:
        return self.text


class Character:
    """A persona: a system prompt plus a per-user conversation memory.

    Create one with :func:`telegroq.setCh`. Each user's history is a list of
    ``{"role": ..., "content": ...}`` dicts trimmed to the last ``max_history``
    messages; the system prompt is sent on every request and is not counted.

    Args:
        system_prompt: The persona's instructions, or a callable
            ``(user_id) -> str`` to build a per-user prompt.
        max_history: How many past messages (user + assistant) to remember per
            user. ``0`` makes the character stateless.
        bot: Use this bot's Groq client (see also :meth:`bind`).
        client: Use this Groq-compatible client directly (anything with
            ``client.chat.completions.create``). Wins over ``bot``.
        model: Model for this character; defaults to the bot's/default model.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in a reply.
        extra_params: Extra keyword arguments for ``chat.completions.create``
            (``top_p``, ``stop`` ...).
        fallbacks: Overrides for :data:`~telegroq.DEFAULT_FALLBACKS`.
        store: Where conversations are kept. Defaults to
            :class:`~telegroq.MemoryHistoryStore`.

    Raises:
        ValueError: if ``max_history`` is negative.
    """

    def __init__(
        self,
        system_prompt: str | Callable[[int], str],
        max_history: int = 10,
        *,
        bot: TeleGroqBot | None = None,
        client: Any | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        extra_params: dict[str, Any] | None = None,
        fallbacks: dict[str, str] | None = None,
        store: HistoryStore | None = None,
    ) -> None:
        if max_history < 0:
            raise ValueError("max_history must be >= 0 (0 disables memory)")
        self.system_prompt = system_prompt
        self.max_history = max_history
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_params: dict[str, Any] = dict(extra_params or {})
        self.fallbacks: dict[str, str] = {**DEFAULT_FALLBACKS, **(fallbacks or {})}
        self.store: HistoryStore = store if store is not None else MemoryHistoryStore()
        self._bot = bot
        self._client = client
        self._user_locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ wiring
    def bind(self, bot: TeleGroqBot) -> Character:
        """Use ``bot``'s Groq client (instead of the most recently configured one)."""
        self._bot = bot
        return self

    def _resolve(self) -> tuple[Any, str]:
        """Pick (client, model): explicit client > bound bot > process default."""
        if self._client is not None:
            return self._client, self.model or _groq.DEFAULT_MODEL
        if self._bot is not None and self._bot.groq_client is not None:
            return self._bot.groq_client, self.model or self._bot.model
        default = _groq.get_default()
        if default is not None:
            return default.client, self.model or default.model
        raise ConfigurationError("Groq is not configured. Call bot.set_groq_key('<GROQ_API_KEY>') first.")

    # ----------------------------------------------------------------- history
    def get_history(self, user_id: int) -> list[dict[str, str]]:
        """Return a copy of the stored conversation with ``user_id``."""
        return self.store.load(user_id)

    def clear_history(self, user_id: int) -> None:
        """Forget the conversation with ``user_id``."""
        with self._lock_for(user_id):
            self.store.clear(user_id)

    def _lock_for(self, user_id: int) -> threading.Lock:
        with self._guard:
            return self._user_locks.setdefault(user_id, threading.Lock())

    def _prompt_for(self, user_id: int) -> str:
        prompt = self.system_prompt
        return prompt(user_id) if callable(prompt) else prompt

    def _remember(self, user_id: int, history: list[dict[str, str]], user_text: str, reply: str) -> None:
        if self.max_history == 0:
            return
        history = [*history, {"role": "user", "content": user_text}, {"role": "assistant", "content": reply}]
        del history[: max(0, len(history) - self.max_history)]
        if history and history[0]["role"] == "assistant":  # keep turns aligned
            del history[0]
        try:
            self.store.save(user_id, history)
        except Exception:  # noqa: BLE001 - a storage hiccup must not lose the reply
            logger.exception("Could not save history for user %s", user_id)

    # -------------------------------------------------------------------- chat
    def ask(self, user_id: int, user_message: str) -> Reply:
        """Like :meth:`get_response` but returns a :class:`Reply` with status details.

        Calls for the same user are serialised so rapid-fire messages cannot
        interleave their history. A failed call is not stored in the history.

        Raises:
            ConfigurationError: if Groq has not been configured (a setup bug).
        """
        client, model = self._resolve()
        text = (user_message or "").strip()
        if not text:
            return Reply(self.fallbacks["empty"], ok=False, error_kind="empty")

        with self._lock_for(user_id):
            try:
                history = self.store.load(user_id) if self.max_history else []
            except Exception:  # noqa: BLE001
                logger.exception("Could not load history for user %s; continuing without it", user_id)
                history = []
            messages: list[dict[str, str]] = []
            prompt = self._prompt_for(user_id)
            if prompt:
                messages.append({"role": "system", "content": prompt})
            messages += history
            messages.append({"role": "user", "content": text})
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **self.extra_params,
                )
                answer = (completion.choices[0].message.content or "").strip()
            except Exception as exc:  # noqa: BLE001 - deliberately broad: never crash the bot
                kind = classify_error(exc)
                logger.warning("Groq request failed (%s): %s: %s", kind, type(exc).__name__, exc)
                return Reply(self.fallbacks[kind], ok=False, error_kind=kind, error=exc)
            if not answer:
                logger.warning("Groq returned an empty completion")
                return Reply(self.fallbacks["unknown"], ok=False, error_kind="unknown")
            self._remember(user_id, history, text, answer)
            return Reply(answer)

    def get_response(self, user_id: int, user_message: str) -> str:
        """Send ``user_message`` to Groq (with history) and return the reply text.

        Groq failures (rate limits, bad keys, timeouts, outages ...) never raise:
        a friendly fallback string is returned instead. Use :meth:`ask` if you
        need to tell the two apart.

        Raises:
            ConfigurationError: if Groq has not been configured (a setup bug).
        """
        return self.ask(user_id, user_message).text

    async def aget_response(self, user_id: int, user_message: str) -> str:
        """Async flavour of :meth:`get_response` (runs it in a worker thread)."""
        return await asyncio.to_thread(self.get_response, user_id, user_message)

    async def aask(self, user_id: int, user_message: str) -> Reply:
        """Async flavour of :meth:`ask` (runs it in a worker thread)."""
        return await asyncio.to_thread(self.ask, user_id, user_message)

    def __repr__(self) -> str:
        prompt = self.system_prompt if isinstance(self.system_prompt, str) else "<callable>"
        return f"<Character max_history={self.max_history} prompt={prompt[:40]!r}>"
