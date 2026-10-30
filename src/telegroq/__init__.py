"""telegroq: a Groq-powered Telegram bot with a custom persona in a few lines.

A thin, friendly bridge between `pyTelegramBotAPI <https://github.com/eternnoir/pyTelegramBotAPI>`_
and the `Groq API <https://console.groq.com/docs>`_::

    import telegroq

    bot = telegroq.createBot("123456:TELEGRAM_TOKEN")
    bot.set_groq_key("gsk_...", model="llama-3.3-70b-versatile")
    character = telegroq.setCh("You are a witty assistant.", max_history=10)

    bot.auto_reply(character)   # or write your own @bot.on_message() handler
    bot.run()

Public API
----------
Factories: :func:`createBot`, :func:`setCh`
Classes: :class:`TeleGroqBot`, :class:`Character`, :class:`Reply`,
:class:`Message`, :class:`CallbackContext`
Keyboards: :func:`button`, :func:`inline_keyboard`
Storage: :class:`HistoryStore`, :class:`MemoryHistoryStore`, :class:`SQLiteHistoryStore`
Misc: :func:`configure_groq`, :data:`DEFAULT_FALLBACKS`, :class:`TeleGroqError`,
:class:`ConfigurationError`
"""

from __future__ import annotations

import logging
from typing import Any

from ._groq import DEFAULT_MODEL, configure_groq
from ._version import __version__
from .bot import TeleGroqBot, createBot
from .character import Character, Reply
from .errors import ConfigurationError, TeleGroqError
from .fallbacks import DEFAULT_FALLBACKS, classify_error
from .keyboards import button, inline_keyboard
from .message import CallbackContext, Message
from .storage import HistoryStore, MemoryHistoryStore, SQLiteHistoryStore

# Library etiquette: stay silent unless the application configures logging.
logging.getLogger("telegroq").addHandler(logging.NullHandler())


def setCh(system_prompt: Any, max_history: int = 10, **kwargs: Any) -> Character:
    """Create a :class:`Character` (an AI persona with per-user memory).

    Args:
        system_prompt: The persona's instructions (or a callable ``(user_id) -> str``).
        max_history: Messages remembered per user (``0`` = stateless).
        **kwargs: ``bot``, ``client``, ``model``, ``temperature``, ``max_tokens``,
            ``extra_params``, ``fallbacks``, ``store``. See :class:`Character`.
    """
    return Character(system_prompt, max_history, **kwargs)


__all__ = [
    "__version__",
    "DEFAULT_FALLBACKS",
    "DEFAULT_MODEL",
    "CallbackContext",
    "Character",
    "ConfigurationError",
    "HistoryStore",
    "MemoryHistoryStore",
    "Message",
    "Reply",
    "SQLiteHistoryStore",
    "TeleGroqBot",
    "TeleGroqError",
    "button",
    "classify_error",
    "configure_groq",
    "createBot",
    "inline_keyboard",
    "setCh",
]
