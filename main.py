import threading
import os
from dotenv import load_dotenv

load_dotenv()


def start_whatsapp():
    from platforms.whatsapp_bot import run_whatsapp
    run_whatsapp()


def start_discord():
    from platforms.discord_bot import run_discord
    run_discord()


if __name__ == "__main__":
    print("\nStarting your Personal Strategic Agent...\n")

    if os.getenv("ENABLE_WHATSAPP", "").lower() == "true" and os.getenv("TWILIO_ACCOUNT_SID"):
        print("Starting WhatsApp...")
        w = threading.Thread(target=start_whatsapp, daemon=True)
        w.start()

    if os.getenv("DISCORD_BOT_TOKEN"):
        print("Starting Discord...")
        d = threading.Thread(target=start_discord, daemon=True)
        d.start()

    if os.getenv("OWNER_TELEGRAM_ID"):
        print("Starting hourly digest...")
        from digest import run_digest
        run_digest()

    if os.getenv("TELEGRAM_BOT_TOKEN"):
        print("Starting Telegram...")
        from platforms.telegram_bot import run_telegram
        run_telegram()