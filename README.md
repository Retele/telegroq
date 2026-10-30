# telegroq

**A Groq-powered Telegram bot with its own personality in a few lines of Python.**

`telegroq` bridges [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI) (`telebot`) and the
[Groq API](https://console.groq.com/docs). You get decorators for commands, messages and inline buttons,
characters with per-user memory, and sensible behaviour when things go wrong (rate limits, bad keys,
photos and stickers instead of text) - without writing the glue yourself.

> Unofficial project. Not affiliated with or endorsed by Telegram or Groq.

## Install

```bash
pip install telegroq
```

Requires Python 3.10+. You need a Telegram bot token from [@BotFather](https://t.me/BotFather) and a Groq API key from
[console.groq.com](https://console.groq.com/keys).

## Quickstart

```python
import telegroq

bot = telegroq.createBot("123456:TELEGRAM_BOT_TOKEN")
bot.set_groq_key("gsk_...", model="llama-3.3-70b-versatile")

character = telegroq.setCh(
    system_prompt="You are a funny, witty, and energetic AI assistant.",
    max_history=10,
)

@bot.cmd("/start")
def start(user, msg):
    bot.send_message(user.id, f"Hello {user.first_name}! I am ready.")

@bot.cmd("/reset")
def reset(user, msg):
    character.clear_history(user.id)
    bot.send_message(user.id, "Conversation memory cleared!")

@bot.on_message()
def chat(user, msg):
    bot.reply(user.id, character.get_response(user.id, msg.text), message_id=msg.message_id)

bot.run()
```

Even shorter - let telegroq answer every text message for you: replace the `chat` handler with
`bot.auto_reply(character)`.

Keep secrets out of your code: read them from environment variables (see [`examples/main.py`](examples/main.py)).

## Concepts

### Handlers receive `(user, msg)`

* `user` is telebot's `User` (`.id`, `.username`, `.first_name`, ...).
* `msg` is a `telegroq.Message`. `msg.text` is **always a string** (`""` for photos, stickers and voice notes),
  `msg.args` is the text after a command, `msg.chat_id` / `msg.is_private` describe the chat, and
  `msg.reply(text)` answers in the chat the message came from. Everything else (`msg.message_id`,
  `msg.caption`, `msg.photo`, ...) is forwarded to the raw telebot message (`msg.raw`).

> **Groups:** `bot.send_message(user.id, ...)` writes to the user's *private* chat. In group chats use
> `msg.reply(...)` or `bot.send_message(msg.chat_id, ...)`. Restrict AI handlers with
> `@bot.on_message(chat_types=["private"])` if you do not want the bot to answer everything in a group.

### Commands

```python
@bot.cmd("/start", description="Say hello")   # description appears in Telegram's command menu
@bot.cmd("help", "about")                     # several names, slash optional, any letter case
```

Registered commands are never delivered to `@bot.on_message()`, whatever order you declare them in.

### Characters (personas with memory)

```python
character = telegroq.setCh("You are a pirate.", max_history=10, temperature=0.9, model="llama-3.1-8b-instant")

character.get_response(user.id, "Hi!")       # -> str (never raises on Groq errors)
character.ask(user.id, "Hi!")                # -> Reply(text, ok, error_kind, error)
await character.aget_response(user.id, "Hi") # async variant (runs in a worker thread)
character.clear_history(user.id)
character.get_history(user.id)
```

* History is kept **per user id** and trimmed to the last `max_history` messages (`0` = stateless).
  Calls for the same user are serialised, so quick successive messages cannot scramble the conversation.
* `system_prompt` may also be a callable `(user_id) -> str` for per-user prompts.
* `extra_params={"top_p": 0.9}` is forwarded to `chat.completions.create`.
* Pass `client=` to use your own Groq-compatible client, or `bot=` / `.bind(bot)` to pick which bot's key is used.
  Without either, the most recently configured key is used.

### Inline buttons and callbacks

```python
from telegroq import inline_keyboard

@bot.cmd("persona")
def choose(user, msg):
    bot.send_message(msg.chat_id, "Who am I?", reply_markup=inline_keyboard(
        [("Pirate", "persona:pirate"), ("Poet", "persona:poet")],
    ))

@bot.callback(prefix="persona:")          # or @bot.callback("exact:data") / @bot.callback(regex=...)
def picked(user, call):
    call.answer(f"OK, {call.args}!")      # optional: telegroq answers for you if you don't
    call.edit(f"Persona: {call.args}")    # edit the message that holds the buttons
```

`call` is a `CallbackContext` with `.data`, `.args` (data after the prefix), `.message`, `.answer()`,
`.edit()`, `.edit_keyboard()` and `.reply()`. The button's loading spinner is cleared automatically.
`button(text, callback_data)` enforces Telegram's 64-byte limit; `button(text, url=...)` makes link buttons.

### Persistent memory

```python
from telegroq import SQLiteHistoryStore

character = telegroq.setCh("...", store=SQLiteHistoryStore("history.db"))
```

Implement `telegroq.HistoryStore` (`load`, `save`, `clear`) to use Redis, Postgres, etc. The default
`MemoryHistoryStore` forgets everything on restart.

### Errors never take the bot down

| Situation | What happens |
|---|---|
| Groq rate limit, bad key, timeout, outage | The user gets a friendly fallback message; the failed turn is not saved. Customise with `setCh(..., fallbacks={"rate_limit": "..."})`. |
| Your handler raises | The error is logged, the user gets `bot.error_reply` (or run your own `@bot.on_error`), polling continues. |
| Photo, sticker, voice note, ... | `msg.text == ""`; in private chats the user gets `bot.non_text_reply` unless you handle that type (`@bot.on_message(content_types=["photo"])`). Set it to `None` to stay silent. |
| Model output breaks Markdown/HTML | `send_message(..., parse_mode=...)` retries as plain text. |
| Reply longer than 4096 characters | Split into several messages automatically. |
| Network errors while polling | `bot.run()` keeps retrying. |

Forgetting `set_groq_key` raises `telegroq.ConfigurationError` - a setup bug, not a runtime failure.

### Logging

telegroq logs to the `telegroq` logger and is silent by default. Enable it with
`logging.basicConfig(level=logging.INFO)`.

## API summary

| | |
|---|---|
| `telegroq.createBot(token, **telebot_kwargs)` | Create a `TeleGroqBot` (wraps `telebot.TeleBot`, available as `bot.telebot`; unknown attributes forward to it). |
| `bot.set_groq_key(api_key, model=...)` | Create the Groq client (`timeout`, `max_retries` optional). |
| `telegroq.setCh(system_prompt, max_history=10, **opts)` | Create a `Character`. |
| `@bot.cmd(*names, description=None, chat_types=None)` | Command handler `fn(user, msg)`. |
| `@bot.on_message(content_types=None, chat_types=None, regexp=None, func=None, typing=True)` | Wildcard handler `fn(user, msg)`. |
| `bot.auto_reply(character, ...)` | Answer every text message with a character. |
| `@bot.callback(*data, prefix=None, regex=None)` | Inline-button handler `fn(user, call)`. |
| `@bot.on_error` | `fn(exc, user, update)` called when a handler raises. |
| `bot.send_message(user_id, text, **kw)` / `bot.reply(user_id, text, message_id=None, **kw)` | Sending helpers (splitting, plain-text retry). |
| `bot.run()` / `bot.stop()` | Start / stop long polling. |
| `telegroq.button`, `telegroq.inline_keyboard` | Keyboard helpers. |
| `HistoryStore`, `MemoryHistoryStore`, `SQLiteHistoryStore` | Conversation storage. |

Every public function and class has a docstring; try `help(telegroq.Character)`.

## Development

```bash
git clone https://github.com/YOUR-USERNAME/telegroq && cd telegroq
python -m pip install -e ".[dev]"
pytest          # no network or API keys needed (Telegram and Groq are faked)
ruff check .
```

### Releasing to PyPI

1. Bump `src/telegroq/_version.py` and add a section to `CHANGELOG.md`.
2. Build and check: `python -m build && twine check --strict dist/*`.
3. Try it on TestPyPI first: `twine upload --repository testpypi dist/*`.
4. Publish: `twine upload dist/*`, or create a GitHub release and let
   `.github/workflows/publish.yml` publish via PyPI trusted publishing.

## License

MIT - see [LICENSE](LICENSE).
