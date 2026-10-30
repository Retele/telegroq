"""Inline buttons choose the persona; conversations survive restarts (SQLite).

Setup:
    pip install telegroq
    export TELEGRAM_BOT_TOKEN="123456:ABC..."
    export GROQ_API_KEY="gsk_..."
    python persona_switcher.py

Try /persona, press a button, then chat.
"""

import logging
import os
import sys

import telegroq
from telegroq import SQLiteHistoryStore, inline_keyboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
if not TELEGRAM_TOKEN or not GROQ_KEY:
    sys.exit("Set TELEGRAM_BOT_TOKEN and GROQ_API_KEY first (see the top of this file).")

bot = telegroq.createBot(TELEGRAM_TOKEN)
bot.set_groq_key(GROQ_KEY)

PROMPTS = {
    "pirate": "You are a swashbuckling pirate. Answer in pirate speak, briefly.",
    "teacher": "You are a patient teacher. Explain step by step, in simple words.",
    "poet": "You are a poet. Reply in a short rhyming verse.",
}
# One character per persona; one SQLite file, one table per persona.
personas = {
    name: telegroq.setCh(prompt, max_history=12, store=SQLiteHistoryStore("history.db", table=name))
    for name, prompt in PROMPTS.items()
}
chosen: dict[int, str] = {}  # user id -> persona name (use a database for real deployments)


@bot.cmd("start", description="Start the bot")
@bot.cmd("persona", description="Choose who I am")
def persona_menu(user, msg):
    keyboard = inline_keyboard([(name.title(), f"persona:{name}") for name in personas])
    bot.send_message(msg.chat_id, "Who should I be?", reply_markup=keyboard)


@bot.callback(prefix="persona:")
def persona_chosen(user, call):
    chosen[user.id] = call.args  # e.g. "persona:pirate" -> "pirate"
    call.answer(f"Now chatting with the {call.args}!")
    call.edit(f"Persona: {call.args.title()}. Say something!")


@bot.cmd("reset", description="Forget our conversation")
def reset(user, msg):
    personas[chosen.get(user.id, "pirate")].clear_history(user.id)
    msg.reply("Memory cleared.")


@bot.on_message(chat_types=["private"])
def chat(user, msg):
    character = personas[chosen.get(user.id, "pirate")]
    msg.reply(character.get_response(user.id, msg.text))


@bot.on_error
def log_errors(exc, user, update):
    logging.getLogger(__name__).error("handler failed for user %s: %r", user.id, exc)
    update.reply("Sorry, that went wrong. Try again?")  # works for messages and button presses


if __name__ == "__main__":
    bot.run()
