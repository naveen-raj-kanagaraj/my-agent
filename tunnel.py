"""Public link for the dashboard so you can open it on your phone from anywhere.

Uses a free Cloudflare quick tunnel (no account): needs `cloudflared` installed (brew install cloudflared).
The link changes when the tunnel restarts; each new link is sent to you on Telegram through your main agent's bot
(read from ~/my-agent/.env: TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_ID). Sending a message doesn't interfere with
the main agent. The page is read-only and shows only public YouTube numbers.
"""
import os
import re
import shutil
import subprocess
import threading
import time

import requests

import tracker as T

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
URL_FILE = os.path.join(T.DATA, "public_url.txt")


def _notify_creds():
    token = os.getenv("NOTIFY_BOT_TOKEN")
    chat = os.getenv("NOTIFY_CHAT_ID")
    if token and chat:
        return token, chat
    main_env = os.path.expanduser(os.getenv("MAIN_AGENT_ENV", "~/my-agent/.env"))
    vals = {}
    try:
        for line in open(main_env):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.split("#")[0].strip().strip('"').strip("'")
    except OSError:
        return None, None
    return vals.get("TELEGRAM_BOT_TOKEN"), (vals.get("OWNER_TELEGRAM_ID") or "").split(",")[0].strip() or None


def notify(text: str) -> bool:
    token, chat = _notify_creds()
    if not (token and chat):
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=15)
        return r.ok
    except requests.RequestException:
        return False


def public_url() -> str:
    try:
        return open(URL_FILE).read().strip()
    except OSError:
        return ""


def _run_once(port: int):
    proc = subprocess.Popen(["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        m = URL_RE.search(line)
        if m and m.group(0) != public_url():
            with open(URL_FILE, "w") as f:
                f.write(m.group(0))
            print(f"Public dashboard: {m.group(0)}")
            notify(f"{T.config()['name']} live dashboard (open on any device):\n{m.group(0)}\n\n"
                   "It refreshes every 30s. A new link is sent here if it changes.")
    proc.wait()


def start(port: int):
    if os.getenv("PUBLIC_DASHBOARD", "true").lower() != "true":
        return
    if not shutil.which("cloudflared"):
        print("Public link off: install cloudflared (brew install cloudflared) to open the dashboard from your phone.")
        return

    def loop():
        while True:
            try:
                _run_once(port)
            except Exception as e:
                print(f"Tunnel stopped: {str(e)[:120]}")
            time.sleep(15)  # restart the tunnel if it drops
    threading.Thread(target=loop, daemon=True).start()
