import os
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    print("\nStarting your Personal Strategic Agent...\n")

    if os.getenv("TELEGRAM_BOT_TOKEN"):
        print("Starting Telegram...")
        from platforms.telegram_bot import run_telegram
        run_telegram()
    else:
        print("No Telegram token found in .env")