"""Groq client construction and the process-wide default configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ConfigurationError

__all__ = ["DEFAULT_MODEL", "GroqConfig", "build_client", "configure_groq", "get_default"]

DEFAULT_MODEL = "llama-3.3-70b-versatile"


@dataclass(frozen=True)
class GroqConfig:
    """A Groq client together with the model to use by default."""

    client: Any
    model: str


_default: GroqConfig | None = None


def build_client(api_key: str, *, timeout: float = 30.0, max_retries: int = 2) -> Any:
    """Create a ``groq.Groq`` client (imports the SDK lazily).

    Raises:
        ConfigurationError: if ``api_key`` is empty.
        ImportError: if the ``groq`` package is not installed.
    """
    if not isinstance(api_key, str) or not api_key.strip():
        raise ConfigurationError("api_key must be a non-empty string")
    try:
        import groq
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("telegroq needs the Groq SDK. Install it with: pip install groq") from exc
    return groq.Groq(api_key=api_key.strip(), timeout=timeout, max_retries=max_retries)


def configure_groq(
    api_key: str,
    model: str = DEFAULT_MODEL,
    *,
    timeout: float = 30.0,
    max_retries: int = 2,
) -> GroqConfig:
    """Create a Groq client and make it the process-wide default.

    Characters that are not bound to a bot (or given an explicit ``client``) use
    the default. ``TeleGroqBot.set_groq_key`` calls this for you.
    """
    global _default
    config = GroqConfig(build_client(api_key, timeout=timeout, max_retries=max_retries), model)
    _default = config
    return config


def get_default() -> GroqConfig | None:
    """Return the most recently configured :class:`GroqConfig`, if any."""
    return _default
