# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-30

### Added
- `telegroq.createBot(token)` returning `TeleGroqBot`, a wrapper around `telebot.TeleBot`.
- `bot.set_groq_key(api_key, model=...)` and `telegroq.configure_groq(...)`.
- `telegroq.setCh(system_prompt, max_history)` returning `Character`: per-user memory,
  `get_response` / `ask` (with a `Reply` status object), async variants, `clear_history`.
- Friendly fallback messages for Groq rate limits, bad keys, timeouts and outages.
- `@bot.cmd`, `@bot.on_message`, `@bot.callback` (exact / prefix / regex), `@bot.on_error`,
  `bot.auto_reply(character)`; handlers receive `(user, msg)` / `(user, call)`.
- `Message` and `CallbackContext` wrappers (`msg.text` is always a `str`, `call.edit()`,
  automatic callback answers).
- Inline keyboard helpers `button()` and `inline_keyboard()`.
- Pluggable history stores: `MemoryHistoryStore`, `SQLiteHistoryStore`, `HistoryStore` base class.
- `bot.send_message` / `bot.reply`: automatic splitting of long texts, plain-text retry on
  formatting errors, `reply_markup` on the last part.
- Command menu publishing (`@bot.cmd("start", description="...")`), non-text message notice.
