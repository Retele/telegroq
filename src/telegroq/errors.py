"""Exceptions raised by telegroq.

Only *developer* mistakes raise: bad arguments or a missing Groq configuration.
Runtime failures of the Groq API never raise out of
:meth:`telegroq.Character.get_response`; they turn into fallback messages
(see :mod:`telegroq.fallbacks`).
"""

from __future__ import annotations

__all__ = ["TeleGroqError", "ConfigurationError"]


class TeleGroqError(RuntimeError):
    """Base class of every exception raised deliberately by telegroq."""


class ConfigurationError(TeleGroqError):
    """Raised when telegroq is used incorrectly or has not been configured.

    Examples: calling ``get_response`` before ``set_groq_key``, passing an empty
    API key, registering a command with an invalid name.
    """
