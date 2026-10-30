"""Friendly fallback texts and Groq error classification."""

from __future__ import annotations

__all__ = ["DEFAULT_FALLBACKS", "classify_error"]

#: Texts shown to the end user when Groq cannot answer, keyed by error kind.
#: Override per character with ``setCh(..., fallbacks={"rate_limit": "..."})``.
DEFAULT_FALLBACKS: dict[str, str] = {
    "rate_limit": "I'm getting a lot of requests right now. Please try again in a moment.",
    "auth": "My AI backend rejected its credentials. Please let the bot owner know.",
    "timeout": "The AI took too long to answer. Please try again.",
    "connection": "I couldn't reach my AI backend. Please try again in a moment.",
    "server": "My AI backend is having trouble right now. Please try again shortly.",
    "bad_request": "I couldn't process that message. Try rephrasing it, or use /reset.",
    "empty": "I didn't get anything to respond to. Send me some text!",
    "unknown": "Sorry, something went wrong while thinking. Please try again.",
}


def classify_error(exc: BaseException) -> str:
    """Map an exception raised by the Groq SDK to a key of :data:`DEFAULT_FALLBACKS`.

    Classification uses the HTTP ``status_code`` and the exception *class name*
    (``RateLimitError``, ``APITimeoutError`` ...), so it works with every Groq SDK
    version and does not need the SDK to be importable.

    Args:
        exc: The exception to classify.

    Returns:
        One of ``rate_limit``, ``auth``, ``timeout``, ``connection``, ``server``,
        ``bad_request`` or ``unknown``.
    """
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    if status == 429 or name == "RateLimitError":
        return "rate_limit"
    if status in (401, 403) or name in ("AuthenticationError", "PermissionDeniedError"):
        return "auth"
    if name == "APITimeoutError":
        return "timeout"
    if name == "APIConnectionError":
        return "connection"
    if isinstance(status, int) and status >= 500:
        return "server"
    if status in (400, 404, 413, 422) or name in (
        "BadRequestError",
        "NotFoundError",
        "UnprocessableEntityError",
    ):
        return "bad_request"
    return "unknown"
