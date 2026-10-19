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


def start_dashboard():
    from platforms.dashboard import run_dashboard
    run_dashboard()


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


def single_instance():
    """Two copies polling Telegram fight each other ('Conflict' errors). Refuse to start a second one."""
    import fcntl
    os.makedirs("data", exist_ok=True)
    f = open("data/agent.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("The agent is already running (maybe started automatically at login).\n"
              "Check with: bash scripts/autostart.sh status   Stop autostart: bash scripts/autostart.sh uninstall")
        raise SystemExit(1)
    return f  # keep the file open for the life of the process


def rotate_log(path: str = "data/agent.log", max_mb: int = 20):
    try:
        if os.path.getsize(path) > max_mb * 1024 * 1024:
            import shutil
            shutil.copyfile(path, path + ".1")
            with open(path, "r+") as f:  # truncate in place: launchd keeps writing to the same file
                f.truncate(0)
    except OSError:
        pass


if __name__ == "__main__":
    _lock = single_instance()
    rotate_log()
    print("\nStarting your Personal Strategic Agent...\n")
    clear_legacy_data()

    if os.getenv("ENABLE_WHATSAPP", "").lower() == "true" and os.getenv("TWILIO_ACCOUNT_SID"):
        print("Starting WhatsApp...")
        w = threading.Thread(target=start_whatsapp, daemon=True)
        w.start()

    if os.getenv("DASHBOARD_ENABLED", "true").lower() == "true":
        threading.Thread(target=start_dashboard, daemon=True).start()

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