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


def clear_legacy_data():
    """One-time wipe of the old JSON data files (replaced by data/agent.db)."""
    from core import store
    if store.kv_get("legacy_cleared"):
        return
    removed = [f for f in ("memory.json", "notes.json", "covered_news.json") if os.path.exists(f)]
    for f in removed:
        os.remove(f)
    store.kv_set("legacy_cleared", True)
    if removed:
        print("Cleared old data: " + ", ".join(removed))


if __name__ == "__main__":
    print("\nStarting your Personal Strategic Agent...\n")
    clear_legacy_data()

    if os.getenv("ENABLE_WHATSAPP", "").lower() == "true" and os.getenv("TWILIO_ACCOUNT_SID"):
        print("Starting WhatsApp...")
        w = threading.Thread(target=start_whatsapp, daemon=True)
        w.start()

    if os.getenv("DISCORD_BOT_TOKEN"):
        print("Starting Discord...")
        d = threading.Thread(target=start_discord, daemon=True)
        d.start()

    if os.getenv("TELEGRAM_BOT_TOKEN"):
        print("Starting scheduler (briefs, news, reminders, radar)...")
        from digest import run_digest
        run_digest()

    if os.getenv("TELEGRAM_BOT_TOKEN"):
        print("Starting Telegram...")
        from platforms.telegram_bot import run_telegram
        run_telegram()