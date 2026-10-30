"""Minimal Groq-powered Telegram bot with a persona.

Setup:
    pip install telegroq
    export TELEGRAM_BOT_TOKEN="123456:ABC..."   # from @BotFather
    export GROQ_API_KEY="gsk_..."               # from console.groq.com
    python main.py
"""

import logging
import os
import sys

import telegroq

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
if not TELEGRAM_TOKEN or not GROQ_KEY:
    sys.exit("Set TELEGRAM_BOT_TOKEN and GROQ_API_KEY first (see the top of this file).")

# 1. Initialize the bot
bot = telegroq.createBot(TELEGRAM_TOKEN)
bot.set_groq_key(GROQ_KEY, model="llama-3.3-70b-versatile")

# 2. Define the AI persona (remembers the last 10 messages per user)
character = telegroq.setCh(
    system_prompt=(
        "You are a funny, witty, and energetic AI assistant. "
        "Keep answers short and punchy, and use plain text (no Markdown)."
    ),
    max_history=10,
)


# 3. Custom commands (the description shows up in Telegram's command menu)
@bot.cmd("/start", description="Say hello")
def start(user, msg):
    bot.send_message(user.id, f"Hello {user.first_name}! I am ready. Send me anything.")


@bot.cmd("/reset", description="Forget our conversation")
def reset(user, msg):
    character.clear_history(user.id)
    bot.send_message(user.id, "Conversation memory cleared!")


# 4. AI auto-responder: every text message that is not a command ends up here.
#    Photos, stickers and voice notes get a polite "text only" notice automatically.
@bot.on_message()
def chat_handler(user, msg):
    reply = character.get_response(user.id, msg.text)
    bot.reply(user.id, reply, message_id=msg.message_id)

    # Shorter alternative: replace this whole handler with  bot.auto_reply(character)


# 5. Launch (Ctrl+C to stop)
if __name__ == "__main__":
    bot.run()
