"""Public https link for the event dashboard via a free Cloudflare quick tunnel (no account needed).

Uses `cloudflared` if installed; otherwise downloads Cloudflare's official binary once into data/bin.
The link changes when the tunnel restarts; every new link is sent to the owner on Telegram.
"""
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import time

import requests

from core import store

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bin")
RELEASE = "https://github.com/cloudflare/cloudflared/releases/latest/download/"
_state = {"status": "off", "url": ""}


def public_url() -> str:
    return store.kv_get("event_public_url", "") or ""


def status() -> str:
    return _state["status"]


def _find() -> str:
    for p in (shutil.which("cloudflared"), "/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared",
              os.path.join(BIN_DIR, "cloudflared")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return ""


def _download() -> str:
    """Cloudflare's official release from GitHub, for this OS/CPU."""
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"
    system = platform.system().lower()
    os.makedirs(BIN_DIR, exist_ok=True)
    dest = os.path.join(BIN_DIR, "cloudflared")
    name = f"cloudflared-darwin-{arch}.tgz" if system == "darwin" else f"cloudflared-linux-{arch}"
    r = requests.get(RELEASE + name, timeout=120)
    r.raise_for_status()
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(r.content)
    if name.endswith(".tgz"):
        with tarfile.open(tmp) as t:
            m = next(m for m in t.getmembers() if m.isfile() and os.path.basename(m.name) == "cloudflared")
            with t.extractfile(m) as src, open(dest, "wb") as out:
                out.write(src.read())
        os.remove(tmp)
    else:
        os.replace(tmp, dest)
    os.chmod(dest, 0o755)
    return dest


def _notify(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = (os.getenv("OWNER_TELEGRAM_ID") or "").split(",")[0].strip()
    if not (token and chat):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=15)
    except requests.RequestException:
        pass


def _run_once(binary: str, port: int):
    proc = subprocess.Popen([binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    _state["status"] = "starting"
    for line in proc.stdout:
        m = URL_RE.search(line)
        if m:
            url = m.group(0)
            _state.update(status="on", url=url)
            if url != public_url():
                store.kv_set("event_public_url", url)
                print(f"Public event dashboard: {url}")
                _notify(f"Live viewership dashboard (opens on any device, updates every 2s):\n{url}\n\n"
                        "If the link changes, the new one is sent here. /event link shows the current one.")
    proc.wait()
    _state["status"] = "restarting"


def start(port: int):
    if os.getenv("EVENT_PUBLIC_LINK", "true").lower() != "true":
        return

    def loop():
        binary = _find()
        if not binary:
            try:
                _state["status"] = "downloading cloudflared"
                binary = _download()
            except Exception as e:
                _state["status"] = f"off: couldn't get cloudflared ({str(e)[:80]}). Install it: brew install cloudflared"
                print(f"Public link off: {_state['status']}")
                return
        while True:
            try:
                _run_once(binary, port)
            except Exception as e:
                _state["status"] = f"restarting ({str(e)[:80]})"
            time.sleep(10)  # restart if the tunnel drops
    threading.Thread(target=loop, daemon=True).start()
