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
    CREATE TABLE IF NOT EXISTS spend (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT, uid TEXT, feature TEXT, model TEXT,
        input_tokens INTEGER, output_tokens INTEGER, cache_read INTEGER, cache_write INTEGER,
        cost REAL, created_at TEXT
    );
    CREATE INDEX IF NOT EXISTS spend_day ON spend(day);
    CREATE TABLE IF NOT EXISTS counters (
        day TEXT, name TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (day, name)
    );
    CREATE TABLE IF NOT EXISTS watches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid TEXT, chat_id TEXT, keyword TEXT, seeded INTEGER DEFAULT 0, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS alert_seen (
        uid TEXT, item_key TEXT, seen_at TEXT, PRIMARY KEY (uid, item_key)
    );
    CREATE TABLE IF NOT EXISTS creators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, platform TEXT, handle TEXT, followers TEXT, niche TEXT, rate TEXT,
        contact TEXT, status TEXT DEFAULT 'prospect', notes TEXT, created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS deals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator TEXT, brand TEXT, value TEXT, stage TEXT DEFAULT 'lead', due TEXT, notes TEXT,
        created_at TEXT, updated_at TEXT
    );
    """)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
    for col, ddl in (("keywords", "TEXT DEFAULT '{}'"), ("custom_keywords", "TEXT DEFAULT '[]'"),
                     ("last_model", "TEXT DEFAULT ''"), ("default_model", "TEXT DEFAULT 'auto'"),
                     ("picker_on", "INTEGER DEFAULT 1"), ("session_model", "TEXT DEFAULT ''"),
                     ("session_at", "REAL DEFAULT 0")):
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


# ---------- spend and counters ----------

def record_spend(uid: str, feature: str, model: str, usage: dict, cost: float):
    with _lock:
        conn().execute(
            "INSERT INTO spend (day, uid, feature, model, input_tokens, output_tokens, cache_read, cache_write, cost, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (owner_today(), uid, feature, model, usage.get("input", 0), usage.get("output", 0),
             usage.get("cache_read", 0), usage.get("cache_write", 0), cost, iso(now_utc())))
        conn().commit()


def spend_today(owner: bool = None) -> float:
    q = "SELECT COALESCE(SUM(cost),0) AS c FROM spend WHERE day=?"
    if owner is True:
        q += " AND uid='owner'"
    elif owner is False:
        q += " AND uid!='owner'"
    with _lock:
        return conn().execute(q, (owner_today(),)).fetchone()["c"]


def spend_breakdown(days: int = 1) -> dict:
    from datetime import timedelta as _td
    start = (datetime.now(ZoneInfo(OWNER_TZ)) - _td(days=days - 1)).strftime("%Y-%m-%d")
    with _lock:
        c = conn()
        by_feature = [dict(r) for r in c.execute(
            "SELECT feature, ROUND(SUM(cost),4) AS cost, COUNT(*) AS calls FROM spend WHERE day>=? "
            "GROUP BY feature ORDER BY cost DESC", (start,))]
        by_user = [dict(r) for r in c.execute(
            "SELECT uid, ROUND(SUM(cost),4) AS cost, COUNT(*) AS calls FROM spend WHERE day>=? "
            "GROUP BY uid ORDER BY cost DESC LIMIT 10", (start,))]
        total = c.execute("SELECT COALESCE(SUM(cost),0) AS c FROM spend WHERE day>=?", (start,)).fetchone()["c"]
    return {"total": total, "by_feature": by_feature, "by_user": by_user}


def bump(name: str, n: int = 1) -> int:
    with _lock:
        day = owner_today()
        conn().execute("INSERT INTO counters (day, name, count) VALUES (?,?,?) "
                       "ON CONFLICT(day, name) DO UPDATE SET count=count+?", (day, name, n, n))
        conn().commit()
        return conn().execute("SELECT count FROM counters WHERE day=? AND name=?", (day, name)).fetchone()["count"]


def counter(name: str, days: int = 1) -> int:
    from datetime import timedelta as _td
    start = (datetime.now(ZoneInfo(OWNER_TZ)) - _td(days=days - 1)).strftime("%Y-%m-%d")
    with _lock:
        return conn().execute("SELECT COALESCE(SUM(count),0) AS c FROM counters WHERE name=? AND day>=?",
                              (name, start)).fetchone()["c"]


# ---------- keyword watches ----------

def add_watch(uid: str, chat_id: str, keyword: str) -> int:
    with _lock:
        cur = conn().execute("INSERT INTO watches (uid, chat_id, keyword, created_at) VALUES (?,?,?,?)",
                             (uid, str(chat_id), keyword.strip()[:80], iso(now_utc())))
        conn().commit()
        return cur.lastrowid


def list_watches(uid: str = None) -> list:
    with _lock:
        if uid:
            rows = conn().execute("SELECT * FROM watches WHERE uid=? ORDER BY id", (uid,))
        else:
            rows = conn().execute("SELECT * FROM watches ORDER BY uid, id")
        return [dict(r) for r in rows]


def remove_watch(uid: str, what: str) -> int:
    with _lock:
        if str(what).isdigit():
            cur = conn().execute("DELETE FROM watches WHERE uid=? AND id=?", (uid, int(what)))
        else:
            cur = conn().execute("DELETE FROM watches WHERE uid=? AND lower(keyword)=?", (uid, what.lower().strip()))
        conn().commit()
        return cur.rowcount


def mark_watch_seeded(wid: int):
    with _lock:
        conn().execute("UPDATE watches SET seeded=1 WHERE id=?", (wid,))
        conn().commit()


def seen_before(uid: str, key: str) -> bool:
    with _lock:
        return conn().execute("SELECT 1 FROM alert_seen WHERE uid=? AND item_key=?", (uid, key)).fetchone() is not None


def mark_seen(uid: str, keys: list):
    with _lock:
        stamp = iso(now_utc())
        conn().executemany("INSERT OR IGNORE INTO alert_seen (uid, item_key, seen_at) VALUES (?,?,?)",
                           [(uid, k, stamp) for k in keys])
        conn().commit()


def prune_seen(days: int = 4):
    from datetime import timedelta as _td
    with _lock:
        conn().execute("DELETE FROM alert_seen WHERE seen_at < ?", (iso(now_utc() - _td(days=days)),))
        conn().commit()


# ---------- talent tracker ----------

CREATOR_FIELDS = ("platform", "handle", "followers", "niche", "rate", "contact", "status", "notes")
DEAL_FIELDS = ("value", "stage", "due", "notes")


def upsert_creator(name: str, **fields) -> tuple:
    fields = {k: str(v).strip() for k, v in fields.items() if k in CREATOR_FIELDS and v not in (None, "")}
    with _lock:
        c = conn()
        row = c.execute("SELECT * FROM creators WHERE lower(name)=?", (name.lower().strip(),)).fetchone()
        stamp = iso(now_utc())
        if row:
            if "notes" in fields and row["notes"]:
                fields["notes"] = (row["notes"] + " | " + fields["notes"])[-2000:]
            if fields:
                cols = ", ".join(f"{k}=?" for k in fields)
                c.execute(f"UPDATE creators SET {cols}, updated_at=? WHERE id=?", (*fields.values(), stamp, row["id"]))
            c.commit()
            return row["id"], False
        cols = ["name"] + list(fields) + ["created_at", "updated_at"]
        cur = c.execute(f"INSERT INTO creators ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        (name.strip(), *fields.values(), stamp, stamp))
        c.commit()
        return cur.lastrowid, True


def find_creators(query: str = "", status: str = "") -> list:
    q, args = "SELECT * FROM creators WHERE 1=1", []
    if query:
        q += " AND (lower(name) LIKE ? OR lower(niche) LIKE ? OR lower(handle) LIKE ? OR lower(platform) LIKE ? OR lower(notes) LIKE ?)"
        args += [f"%{query.lower()}%"] * 5
    if status:
        q += " AND lower(status)=?"
        args.append(status.lower())
    with _lock:
        return [dict(r) for r in conn().execute(q + " ORDER BY updated_at DESC LIMIT 30", args)]


def upsert_deal(creator: str, brand: str, deal_id: int = None, **fields) -> tuple:
    fields = {k: str(v).strip() for k, v in fields.items() if k in DEAL_FIELDS and v not in (None, "")}
    with _lock:
        c = conn()
        stamp = iso(now_utc())
        row = None
        if deal_id:
            row = c.execute("SELECT * FROM deals WHERE id=?", (int(deal_id),)).fetchone()
        if not row and creator and brand:
            row = c.execute("SELECT * FROM deals WHERE lower(creator)=? AND lower(brand)=? AND stage NOT IN ('paid','lost')",
                            (creator.lower().strip(), brand.lower().strip())).fetchone()
        if row:
            if "notes" in fields and row["notes"]:
                fields["notes"] = (row["notes"] + " | " + fields["notes"])[-2000:]
            if fields:
                cols = ", ".join(f"{k}=?" for k in fields)
                c.execute(f"UPDATE deals SET {cols}, updated_at=? WHERE id=?", (*fields.values(), stamp, row["id"]))
            c.commit()
            return row["id"], False
        cols = ["creator", "brand"] + list(fields) + ["created_at", "updated_at"]
        cur = c.execute(f"INSERT INTO deals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        (creator.strip(), brand.strip(), *fields.values(), stamp, stamp))
        c.commit()
        return cur.lastrowid, True


def all_deals(include_closed: bool = False) -> list:
    q = "SELECT * FROM deals" + ("" if include_closed else " WHERE stage NOT IN ('paid','lost')") + " ORDER BY updated_at DESC"
    with _lock:
        return [dict(r) for r in conn().execute(q)]


def all_creators() -> list:
    with _lock:
        return [dict(r) for r in conn().execute("SELECT * FROM creators ORDER BY updated_at DESC")]


# ---------- dashboard queries ----------

def _since(days: int) -> str:
    from datetime import timedelta as _td
    return (datetime.now(ZoneInfo(OWNER_TZ)) - _td(days=days - 1)).strftime("%Y-%m-%d")


def dashboard_users() -> list:
    today, week = owner_today(), _since(7)
    with _lock:
        c = conn()
        spend = {r["uid"]: dict(r) for r in c.execute(
            "SELECT uid, SUM(CASE WHEN day=? THEN cost ELSE 0 END) AS today, "
            "SUM(CASE WHEN day>=? THEN cost ELSE 0 END) AS week, SUM(cost) AS total, COUNT(*) AS calls "
            "FROM spend GROUP BY uid", (today, week))}
        reqs = {r["uid"]: r["count"] for r in c.execute("SELECT uid, count FROM usage WHERE day=?", (today,))}
        watches = {r["uid"]: r["n"] for r in c.execute("SELECT uid, COUNT(*) AS n FROM watches GROUP BY uid")}
        users = [dict(r) for r in c.execute("SELECT * FROM users")]
    out = []
    for u in users:
        s = spend.get(u["uid"], {})
        out.append({
            "uid": u["uid"], "name": u.get("name") or "", "username": u.get("username") or "",
            "platform": u.get("platform") or "", "timezone": u.get("timezone") or "",
            "last_seen": u.get("last_seen") or "", "created_at": u.get("created_at") or "",
            "last_model": u.get("last_model") or "", "state": u.get("state") or "",
            "requests_today": reqs.get(u["uid"], 0), "messages": u.get("msg_count") or 0,
            "spend_today": round(s.get("today") or 0, 5), "spend_week": round(s.get("week") or 0, 5),
            "spend_total": round(s.get("total") or 0, 5), "calls": s.get("calls") or 0,
            "news_on": bool(u.get("news_on")), "blocked": bool(u.get("blocked")),
            "alerts": watches.get(u["uid"], 0), "interests": interests(u),
        })
    return sorted(out, key=lambda x: x["last_seen"], reverse=True)


def spend_series(days: int = 14) -> list:
    with _lock:
        rows = conn().execute("SELECT day, model, SUM(cost) AS cost FROM spend WHERE day>=? GROUP BY day, model",
                              (_since(days),)).fetchall()
    return [dict(r) for r in rows]


def spend_by(field: str, days: int = 7) -> list:
    assert field in ("model", "feature")
    with _lock:
        rows = conn().execute(f"SELECT {field} AS k, SUM(cost) AS cost, COUNT(*) AS calls, "
                              f"SUM(input_tokens + cache_read + cache_write) AS tin, SUM(output_tokens) AS tout "
                              f"FROM spend WHERE day>=? GROUP BY {field} ORDER BY cost DESC", (_since(days),)).fetchall()
    return [dict(r) for r in rows]


def recent_calls(limit: int = 40) -> list:
    with _lock:
        rows = conn().execute("SELECT created_at, uid, feature, model, cost, input_tokens, output_tokens "
                              "FROM spend ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def spend_since(iso_ts: str, provider_prefix: str = "claude") -> float:
    with _lock:
        return conn().execute("SELECT COALESCE(SUM(cost),0) AS c FROM spend WHERE created_at>=? AND model LIKE ?",
                              (iso_ts, provider_prefix + "%")).fetchone()["c"]


def credit_estimate():
    """Anthropic balance estimate: the amount the owner entered with /credits minus Claude spend since."""
    base = kv_get("credit_baseline")
    if not base:
        return None
    left = base["amount"] - spend_since(base["set_at"])
    return {"entered": base["amount"], "set_at": base["set_at"], "left": round(left, 4)}
