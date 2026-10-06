"""Tell the owner on Telegram when something breaks. Rate-limited per problem so a
failing source pings once an hour, not every minute."""
import os
import threading
import time

import requests

from core import store

_lock = threading.Lock()
_last = {}
STARTED = time.time()


def send_owner(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    ok = False
    for oid in store.owner_ids()["telegram"]:
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": oid, "text": text[:4000]}, timeout=15)
            ok = ok or r.ok
        except Exception:
            pass
    return ok


def notify(key: str, text: str, every_minutes: int = 60) -> bool:
    """Send `text` to the owner unless the same `key` was reported recently."""
    now = time.time()
    with _lock:
        if now - _last.get(key, 0) < every_minutes * 60:
            return False
        _last[key] = now
    print(f"ALERT [{key}] {text[:200]}")
    return send_owner("Agent alert: " + text)
