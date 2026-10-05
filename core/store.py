"""SQLite storage for everything the agent remembers.

Tables: users, facts, notes, reminders, usage, conversations.
One connection shared across threads, guarded by a lock.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DB_PATH = os.getenv("AGENT_DB", os.path.join("data", "agent.db"))
OWNER_TZ = os.getenv("OWNER_TIMEZONE", "America/Chicago")

_lock = threading.RLock()
_conn = None


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _init(_conn)
        return _conn


def _init(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        uid TEXT PRIMARY KEY,            -- 'owner' or 'telegram:<id>' / 'discord:<id>'
        platform TEXT,
        chat_id TEXT,                    -- where to send news/reminders (Telegram chat id)
        name TEXT,
        username TEXT,
        state TEXT DEFAULT 'new',        -- new | awaiting_interests | active
        interests TEXT DEFAULT '[]',     -- JSON list
        profile TEXT DEFAULT '',         -- learned summary
        language TEXT DEFAULT '',
        timezone TEXT DEFAULT '',
        news_on INTEGER DEFAULT 1,
        last_news_key TEXT DEFAULT '',
        msg_count INTEGER DEFAULT 0,
        blocked INTEGER DEFAULT 0,
        created_at TEXT,
        last_seen TEXT
    );
    CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid TEXT, fact TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid TEXT, content TEXT, tag TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid TEXT, chat_id TEXT, text TEXT,
        due_utc TEXT, repeat TEXT DEFAULT '', done INTEGER DEFAULT 0, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS usage (
        uid TEXT, day TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (uid, day)
    );
    CREATE TABLE IF NOT EXISTS conversations (
        key TEXT PRIMARY KEY, messages TEXT
    );
    CREATE TABLE IF NOT EXISTS kv (
        key TEXT PRIMARY KEY, value TEXT
    );
    """)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
    for col, ddl in (("keywords", "TEXT DEFAULT '{}'"), ("custom_keywords", "TEXT DEFAULT '[]'")):
        if col not in cols:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
    c.commit()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- identity ----------

def owner_ids() -> dict:
    return {
        "telegram": {i.strip() for i in os.getenv("OWNER_TELEGRAM_ID", "").split(",") if i.strip()},
        "discord": {i.strip() for i in os.getenv("ALLOWED_DISCORD_IDS", "").split(",") if i.strip()},
        "whatsapp": {os.getenv("MY_WHATSAPP_NUMBER", "").replace("whatsapp:", "")} - {""},
    }


def is_owner(platform: str, user_id: str) -> bool:
    return str(user_id) in owner_ids().get(platform, set())


def uid_for(platform: str, user_id: str) -> str:
    """The owner is one identity across platforms; everyone else is per platform."""
    return "owner" if is_owner(platform, user_id) else f"{platform}:{user_id}"


# ---------- users ----------

def get_user(uid: str):
    with _lock:
        row = conn().execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else None


def ensure_user(uid: str, platform: str, chat_id: str = "", name: str = "", username: str = "") -> dict:
    with _lock:
        u = get_user(uid)
        stamp = iso(now_utc())
        if not u:
            state = "active" if uid == "owner" else "new"
            tz = OWNER_TZ if uid == "owner" else ""
            news_on = 0 if uid == "owner" else 1  # owner gets the full strategic digest instead
            conn().execute(
                "INSERT INTO users (uid, platform, chat_id, name, username, state, timezone, news_on, created_at, last_seen) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (uid, platform, str(chat_id), name, username, state, tz, news_on, stamp, stamp),
            )
        else:
            updates = {"last_seen": stamp}
            if name and not u.get("name"):
                updates["name"] = name
            if username:
                updates["username"] = username
            # Owner's Telegram chat is the delivery address for news and reminders.
            if chat_id and (platform == "telegram" or not u.get("chat_id")):
                updates["chat_id"] = str(chat_id)
            update_user(uid, **updates)
        conn().commit()
        return get_user(uid)


def update_user(uid: str, **fields):
    if not fields:
        return
    with _lock:
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = [json.dumps(v) if isinstance(v, (list, dict)) else v for v in fields.values()]
        conn().execute(f"UPDATE users SET {cols} WHERE uid=?", (*vals, uid))
        conn().commit()


def all_users():
    with _lock:
        return [dict(r) for r in conn().execute("SELECT * FROM users ORDER BY created_at")]


def interests(u: dict) -> list:
    try:
        return json.loads(u.get("interests") or "[]")
    except json.JSONDecodeError:
        return []


def keywords(u: dict) -> dict:
    try:
        return json.loads(u.get("keywords") or "{}")
    except json.JSONDecodeError:
        return {}


def custom_keywords(u: dict) -> list:
    try:
        return json.loads(u.get("custom_keywords") or "[]")
    except json.JSONDecodeError:
        return []


def user_tz(u: dict) -> ZoneInfo:
    try:
        return ZoneInfo(u.get("timezone") or OWNER_TZ)
    except Exception:
        return ZoneInfo(OWNER_TZ)


def forget_user(uid: str):
    """Erase everything learned about a user (keeps the account so limits still apply)."""
    with _lock:
        c = conn()
        c.execute("DELETE FROM facts WHERE uid=?", (uid,))
        c.execute("DELETE FROM notes WHERE uid=?", (uid,))
        c.execute("DELETE FROM reminders WHERE uid=?", (uid,))
        c.execute("DELETE FROM conversations WHERE key LIKE ?", (f"%|{uid}",))
        c.execute(
            "UPDATE users SET interests='[]', profile='', language='', msg_count=0, keywords='{}', custom_keywords='[]', "
            "state=CASE WHEN uid='owner' THEN 'active' ELSE 'awaiting_interests' END WHERE uid=?",
            (uid,),
        )
        c.commit()


# ---------- usage limits ----------

def owner_today() -> str:
    return datetime.now(ZoneInfo(OWNER_TZ)).strftime("%Y-%m-%d")


def usage_today(uid: str) -> int:
    with _lock:
        r = conn().execute("SELECT count FROM usage WHERE uid=? AND day=?", (uid, owner_today())).fetchone()
        return r["count"] if r else 0


def use_one(uid: str) -> int:
    with _lock:
        day = owner_today()
        conn().execute(
            "INSERT INTO usage (uid, day, count) VALUES (?,?,1) "
            "ON CONFLICT(uid, day) DO UPDATE SET count=count+1", (uid, day))
        conn().commit()
        return usage_today(uid)


# ---------- facts / notes ----------

def add_fact(uid: str, fact: str):
    with _lock:
        conn().execute("INSERT INTO facts (uid, fact, created_at) VALUES (?,?,?)", (uid, fact.strip()[:500], iso(now_utc())))
        conn().commit()


def get_facts(uid: str, limit: int = 40) -> list:
    with _lock:
        rows = conn().execute("SELECT id, fact FROM facts WHERE uid=? ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]


def delete_facts_matching(uid: str, text: str) -> int:
    with _lock:
        cur = conn().execute("DELETE FROM facts WHERE uid=? AND lower(fact) LIKE ?", (uid, f"%{text.lower()}%"))
        conn().commit()
        return cur.rowcount


def add_note(uid: str, content: str, tag: str) -> int:
    with _lock:
        cur = conn().execute("INSERT INTO notes (uid, content, tag, created_at) VALUES (?,?,?,?)",
                             (uid, content, tag or "general", iso(now_utc())))
        conn().commit()
        return cur.lastrowid


def get_notes(uid: str, tag: str = None, limit: int = 15) -> list:
    with _lock:
        if tag:
            rows = conn().execute("SELECT * FROM notes WHERE uid=? AND tag=? ORDER BY id DESC LIMIT ?", (uid, tag, limit))
        else:
            rows = conn().execute("SELECT * FROM notes WHERE uid=? ORDER BY id DESC LIMIT ?", (uid, limit))
        return [dict(r) for r in rows][::-1]


def delete_note(uid: str, note_id: int) -> bool:
    with _lock:
        cur = conn().execute("DELETE FROM notes WHERE uid=? AND id=?", (uid, note_id))
        conn().commit()
        return cur.rowcount > 0


# ---------- reminders ----------

def add_reminder(uid: str, chat_id: str, text: str, due_utc: str, repeat: str = "") -> int:
    with _lock:
        cur = conn().execute(
            "INSERT INTO reminders (uid, chat_id, text, due_utc, repeat, created_at) VALUES (?,?,?,?,?,?)",
            (uid, str(chat_id), text, due_utc, repeat, iso(now_utc())))
        conn().commit()
        return cur.lastrowid


def list_reminders(uid: str) -> list:
    with _lock:
        rows = conn().execute("SELECT * FROM reminders WHERE uid=? AND done=0 ORDER BY due_utc", (uid,))
        return [dict(r) for r in rows]


def cancel_reminder(uid: str, rid: int) -> bool:
    with _lock:
        cur = conn().execute("UPDATE reminders SET done=1 WHERE uid=? AND id=? AND done=0", (uid, rid))
        conn().commit()
        return cur.rowcount > 0


def due_reminders() -> list:
    with _lock:
        rows = conn().execute("SELECT * FROM reminders WHERE done=0 AND due_utc<=?", (iso(now_utc()),))
        return [dict(r) for r in rows]


def finish_reminder(rid: int, next_due: str = None):
    with _lock:
        if next_due:
            conn().execute("UPDATE reminders SET due_utc=? WHERE id=?", (next_due, rid))
        else:
            conn().execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
        conn().commit()


# ---------- conversations ----------

def load_conversation(key: str) -> list:
    with _lock:
        r = conn().execute("SELECT messages FROM conversations WHERE key=?", (key,)).fetchone()
        return json.loads(r["messages"]) if r else []


def save_conversation(key: str, messages: list):
    with _lock:
        conn().execute(
            "INSERT INTO conversations (key, messages) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET messages=excluded.messages", (key, json.dumps(messages)))
        conn().commit()


def delete_conversation(key: str):
    with _lock:
        conn().execute("DELETE FROM conversations WHERE key=?", (key,))
        conn().commit()


# ---------- key/value (digest bookkeeping) ----------

def kv_get(key: str, default=None):
    with _lock:
        r = conn().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default


def kv_set(key: str, value):
    with _lock:
        conn().execute("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))
        conn().commit()
