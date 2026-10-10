"""One-time login so the agent can read the Telegram channels you've joined (read-only).

Run on YOUR computer, inside ~/my-agent with the venv active:
    python scripts/telegram_login.py

Before that, put your app keys in .env (create them at https://my.telegram.org > API development tools):
    TG_API_ID=1234567
    TG_API_HASH=abcdef0123456789...

Telegram sends a login code to your Telegram app; type it here (and your 2-step password if you set one).
Never share the code or the session file (data/tg_user.session) with anyone: it gives access to your account.
To log out later: python scripts/telegram_login.py --logout
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()


async def main():
    try:
        from telethon import TelegramClient
    except ImportError:
        print("Telethon isn't installed. Run: pip install telethon")
        return 1
    api_id, api_hash = os.getenv("TG_API_ID"), os.getenv("TG_API_HASH")
    if not (api_id and api_hash):
        print("Add TG_API_ID and TG_API_HASH to .env first (https://my.telegram.org > API development tools).")
        return 1
    from core.channels import SESSION
    os.makedirs(os.path.dirname(SESSION), exist_ok=True)
    client = TelegramClient(SESSION, int(api_id), api_hash)
    if "--logout" in sys.argv:
        await client.connect()
        if await client.is_user_authorized():
            await client.log_out()
        print("Logged out. The agent no longer reads your channels.")
        return 0
    await client.start()  # asks for phone number, login code and 2-step password if needed
    me = await client.get_me()
    count = 0
    async for d in client.iter_dialogs(limit=500):
        if d.is_channel and not d.is_group and getattr(d.entity, "broadcast", False):
            count += 1
    await client.disconnect()
    try:
        os.chmod(SESSION + ".session", 0o600)
    except OSError:
        pass
    print(f"\nLogged in as {me.first_name} (@{me.username or '-'}). Found {count} channels you've joined.")
    print("Restart the agent; it will read them every 15 minutes (read-only). Archived channels are skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
