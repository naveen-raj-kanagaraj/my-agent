import os
import random
import asyncio
import logging
import tempfile
import fitz
from pptx import Presentation
from docx import Document
import openpyxl
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters, ContextTypes
)
from core.agent import chat
from core import downloader
from core.memory import Memory
from dotenv import load_dotenv
import anthropic
import base64

load_dotenv()
logging.basicConfig(level=logging.WARNING)

memory = Memory()
client = anthropic.Anthropic()
ALLOWED = set(os.getenv("ALLOWED_TELEGRAM_IDS", "").split(","))


def allowed(update: Update) -> bool:
    return str(update.effective_user.id) in ALLOWED


def extract_pdf(path: str) -> str:
    doc = fitz.open(path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text[:8000]


def extract_pptx(path: str) -> str:
    prs = Presentation(path)
    text = ""
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text += shape.text + "\n"
    return text[:8000]


def extract_docx(path: str) -> str:
    doc = Document(path)
    text = "\n".join([p.text for p in doc.paragraphs])
    return text[:8000]


def extract_txt(path: str) -> str:
    with open(path, "r", errors="ignore") as f:
        return f.read()[:8000]


def extract_excel(path: str) -> str:
    wb = openpyxl.load_workbook(path)
    text = ""
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        text += f"Sheet: {sheet}\n"
        for row in ws.iter_rows(values_only=True):
            row_text = " | ".join([str(cell) for cell in row if cell is not None])
            if row_text.strip():
                text += row_text + "\n"
    return text[:8000]


def summarize_text(user_id: str, text: str, filename: str) -> str:
    message = f"I am sending you the content of a file called '{filename}'. Please read it and summarize the key points, insights, and anything important.\n\nFile content:\n{text}"
    return chat(user_id, "telegram", message)


def summarize_image(path: str) -> str:
    with open(path, "rb") as f:
        image_data = f.read()
    ext = path.split(".")[-1].lower()
    media_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif", "webp": "image/webp"
    }
    media_type = media_map.get(ext, "image/jpeg")
    b64 = base64.standard_b64encode(image_data).decode("utf-8")
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64}
                },
                {
                    "type": "text",
                    "text": "Describe this image in detail. If there is any text, extract it. Summarize everything important."
                }
            ]
        }]
    )
    return response.content[0].text


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text(
        "Agent online.\n\n"
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
        "/start - Wake agent\n"
        "/clear - Clear memory\n"
        "/help - Help\n\n"
        "Send any file and I will read it.\n"
        "Send an X, Instagram, TikTok or YouTube Shorts link and I will download the video.\n"
        "Just type normally to talk."
    )


async def send_long(update: Update, text: str):
    for i in range(0, len(text), 4096):
        await update.message.reply_text(text[i:i + 4096])


async def send_downloaded(update: Update, result: dict):
    try:
        with open(result["path"], "rb") as f:
            await update.message.reply_video(
                video=f,
                duration=result["duration"] or None,
                width=result["width"] or None,
                height=result["height"] or None,
                supports_streaming=True,
                read_timeout=300,
                write_timeout=300,
            )
    except Exception as e:
        await update.message.reply_text(f"Upload failed: {str(e)[:200]}")
    finally:
        downloader.cleanup(result)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.message.reply_text("Unauthorized.")
        return

    user_id = str(update.effective_user.id)
    text = update.message.text

    # Fast path: a bare video link gets downloaded directly, no AI call.
    if downloader.is_bare_link(text):
        url = downloader.find_url(text)
        status = await update.message.reply_text("Downloading...")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_video")
        try:
            result = await asyncio.to_thread(downloader.download_video, url)
        except downloader.DownloadFailed as e:
            await status.edit_text(str(e))
            return
        except Exception as e:
            await status.edit_text(f"Something went wrong: {str(e)[:200]}")
            return
        await status.edit_text(f"Uploading {result['size_mb']} MB...")
        await send_downloaded(update, result)
        try:
            await status.delete()
        except Exception:
            pass
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    # Run the agent in a thread so a long download or search does not freeze the bot.
    response = await asyncio.to_thread(chat, user_id, "telegram", text)
    await send_long(update, response)

    # Send any videos the agent downloaded with its download_video tool.
    for result in downloader.take_outbox("telegram", user_id):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_video")
        await send_downloaded(update, result)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return

    user_id = str(update.effective_user.id)
    doc = update.message.document
    filename = doc.file_name.lower()

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )
    await update.message.reply_text("Reading your file...")

    file = await context.bot.get_file(doc.file_id)

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
        await file.download_to_drive(tmp.name)
        tmp_path = tmp.name

    try:
        if filename.endswith(".pdf"):
            text = extract_pdf(tmp_path)
            response = summarize_text(user_id, text, doc.file_name)
        elif filename.endswith((".pptx", ".ppt")):
            text = extract_pptx(tmp_path)
            response = summarize_text(user_id, text, doc.file_name)
        elif filename.endswith((".docx", ".doc")):
            text = extract_docx(tmp_path)
            response = summarize_text(user_id, text, doc.file_name)
        elif filename.endswith((".txt", ".csv")):
            text = extract_txt(tmp_path)
            response = summarize_text(user_id, text, doc.file_name)
        elif filename.endswith((".xlsx", ".xls")):
            text = extract_excel(tmp_path)
            response = summarize_text(user_id, text, doc.file_name)
        elif filename.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            response = summarize_image(tmp_path)
        else:
            response = "File type not supported. Send PDF, Word, PowerPoint, Excel, image, or text files."
    except Exception as e:
        response = f"Could not read file: {str(e)}"
    finally:
        os.unlink(tmp_path)

    if len(response) <= 4096:
        await update.message.reply_text(response)
    else:
        for i in range(0, len(response), 4096):
            await update.message.reply_text(response[i:i+4096])


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return

    user_id = str(update.effective_user.id)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )
    await update.message.reply_text("Reading your image...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        await file.download_to_drive(tmp.name)
        tmp_path = tmp.name

    try:
        response = summarize_image(tmp_path)
    except Exception as e:
        response = f"Could not read image: {str(e)}"
    finally:
        os.unlink(tmp_path)

    await update.message.reply_text(response)


def run_telegram():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("Telegram: running")
    app.run_polling()