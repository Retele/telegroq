"""Small helpers for building inline keyboards.

Example::

    from telegroq import button, inline_keyboard

    markup = inline_keyboard(
        [("Funny", "persona:funny"), ("Serious", "persona:serious")],
        [button("Docs", url="https://console.groq.com/docs")],
    )
    bot.send_message(user.id, "Pick a persona:", reply_markup=markup)
"""

from __future__ import annotations

from collections.abc import Iterable

from telebot import types

__all__ = ["button", "inline_keyboard", "MAX_CALLBACK_DATA_BYTES"]

#: Telegram rejects ``callback_data`` longer than this many bytes (UTF-8).
MAX_CALLBACK_DATA_BYTES = 64

ButtonLike = types.InlineKeyboardButton | tuple[str, str]


def button(text: str, callback_data: str | None = None, *, url: str | None = None) -> types.InlineKeyboardButton:
    """Create one inline button: either a callback button or a URL button.

    Args:
        text: Label on the button.
        callback_data: Payload delivered to your ``@bot.callback`` handler.
        url: Open this URL instead (mutually exclusive with ``callback_data``).

    Raises:
        ValueError: if neither or both of ``callback_data`` / ``url`` are given,
            or if ``callback_data`` exceeds 64 bytes (Telegram's limit).
    """
    if (callback_data is None) == (url is None):
        raise ValueError("give exactly one of callback_data or url")
    if callback_data is not None and len(callback_data.encode("utf-8")) > MAX_CALLBACK_DATA_BYTES:
        raise ValueError(f"callback_data is longer than {MAX_CALLBACK_DATA_BYTES} bytes: {callback_data!r}")
    if url is not None:
        return types.InlineKeyboardButton(text, url=url)
    return types.InlineKeyboardButton(text, callback_data=callback_data)


def inline_keyboard(*rows: Iterable[ButtonLike]) -> types.InlineKeyboardMarkup:
    """Build an inline keyboard from rows of buttons.

    Each row is an iterable of ready-made buttons or ``(text, callback_data)``
    tuples. Empty rows are skipped.
    """
    markup = types.InlineKeyboardMarkup()
    for row in rows:
        buttons = [b if isinstance(b, types.InlineKeyboardButton) else button(b[0], b[1]) for b in row]
        if buttons:
            markup.row(*buttons)
    return markup
