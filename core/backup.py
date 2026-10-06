"""Nightly backup of data/agent.db (users, profiles, memory, talent pipeline, everything).

Copies go to iCloud Drive (folder 'PesAgentBackups') when it exists on this Mac, otherwise to
data/backups. Set BACKUP_DIR in .env to choose another folder. The newest BACKUP_KEEP copies are kept.
Uses SQLite's online backup, so it's safe while the agent is running.
"""
import glob
import os
import sqlite3
from datetime import datetime

from core import store

ICLOUD = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")
KEEP = int(os.getenv("BACKUP_KEEP", "7"))


def backup_dir() -> str:
    d = os.getenv("BACKUP_DIR")
    if not d:
        d = os.path.join(ICLOUD, "PesAgentBackups") if os.path.isdir(ICLOUD) else os.path.join("data", "backups")
    os.makedirs(d, exist_ok=True)
    return d


def run_backup() -> str:
    d = backup_dir()
    path = os.path.join(d, f"agent-{datetime.now():%Y-%m-%d_%H%M}.db")
    with store._lock:
        dst = sqlite3.connect(path)
        try:
            store.conn().backup(dst)
        finally:
            dst.close()
    copies = sorted(glob.glob(os.path.join(d, "agent-*.db")))
    for old in copies[:-KEEP]:
        try:
            os.remove(old)
        except OSError:
            pass
    size = os.path.getsize(path) / 1024
    store.kv_set("last_backup", {"path": path, "at": store.iso(store.now_utc()), "kb": round(size)})
    return path


def nightly():
    from core import alerts
    try:
        path = run_backup()
        print(f"Backup saved: {path}")
    except Exception as e:
        alerts.notify("backup", f"Nightly backup failed: {str(e)[:200]}", 720)
