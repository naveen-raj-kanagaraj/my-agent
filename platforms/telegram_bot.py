import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters, ContextTypes
)
from core.agent import chat
from core.memory import Memory
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.WARNING)

memory = Memory()
ALLOWED = set(os.getenv("ALLOWED_TELEGRAM_IDS", "").split(","))


def allowed(update: Update) -> bool:
    return str(update.effective_user.id) in ALLOWED


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text(
        "Agent online.\n\n"
        "I am your Personal Strategic Operating System.\n\n"
        "I can:\n"
        "- Search the web for current news and research\n"
        "- Save and retrieve your notes and ideas\n"
        "- Help with strategy, content, academics, business\n"
        "- Do calculations\n"
        "- Remember our full conversation\n\n"
        "Commands:\n"
        "/clear - Reset memory\n"
        "/help - Show this message\n\n"
        "Just type to talk."
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    memory.clear(str(update.effective_user.id), "telegram")
    await update.message.reply_text("Memory cleared.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text(
        "Commands:\n"
        "/start - Wake agent\n"
        "/clear - Clear memory\n"
        "/help - Help\n\n"
        "Just type normally to talk."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.message.reply_text("Unauthorized.")
        return

    user_id = str(update.effective_user.id)
    text = update.message.text

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    response = chat(user_id, "telegram", text)
    await update.message.reply_text(response)


def run_telegram():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Telegram: running")
    app.run_polling()