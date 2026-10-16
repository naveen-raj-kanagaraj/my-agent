"""Predict & Win: a free, points-only prediction game for the live viewership site.

Players join with an Instagram handle + display name (no password). The server hands the browser a random
token and stores only its SHA-256 hash. Picks are enforced server side against each question's close time
(stored as UTC epoch seconds). Scoring: a correct pick earns 100 points plus an underdog bonus of
100 x (1 - share of players who picked the correct answer). Nothing about the player's network is stored.
"""
import hashlib
import json
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from core import store

IST = timezone(timedelta(hours=5, minutes=30))
EVENT_KEY = "bmsd"

DEFAULTS = {
    "teams": ["Meta Ninza", "8Bit Esports", "RNTX Esports", "Epigrotive", "TAG", "Nebula", "K9 Esports", "Blue Army",
              "Outrage", "GodLike", "Gladiators", "Soul", "Myth Esports", "Welt Esports", "Genesis", "Wyld Fangs"],
    "mvp": [],
    "buckets": [300, 400, 500, 600, 700],                         # thousands; labels are built from these
    "days": {"1": "2026-10-16", "2": "2026-10-17", "3": "2026-10-18"},
    "close": "14:45",                                             # IST, default close time on a match day
    "matches": 6,
    "prize": "Top 5 on the overall leaderboard win a gift card of their choice.",
    "record": 730000,                                             # BMPS 2026 peak, for the yes/no question
}

_init_done = False
_cache = {}
_clock = threading.Lock()


def _db():
    global _init_done
    c = store.conn()
    if not _init_done:
        with store._lock:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS pw_players (
                id INTEGER PRIMARY KEY AUTOINCREMENT, handle TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                token_hash TEXT, created REAL NOT NULL, hidden INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS pw_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, tag TEXT, title TEXT NOT NULL,
                day INTEGER DEFAULT 0, style TEXT DEFAULT 'buttons', options TEXT NOT NULL, close_ts REAL NOT NULL,
                locked INTEGER DEFAULT 0, answer TEXT, void INTEGER DEFAULT 0, meta TEXT DEFAULT '{}',
                sort INTEGER DEFAULT 0, created REAL NOT NULL, resolved_ts REAL);
            CREATE TABLE IF NOT EXISTS pw_picks (
                player_id INTEGER NOT NULL, qid INTEGER NOT NULL, option TEXT NOT NULL, ts REAL NOT NULL,
                PRIMARY KEY (player_id, qid));
            CREATE INDEX IF NOT EXISTS pw_picks_q ON pw_picks(qid);
            """)
            c.commit()
        _init_done = True
    return c


def _bust():
    _cache.clear()


# ---------------- settings ----------------
def settings() -> dict:
    s = dict(DEFAULTS)
    s.update(store.kv_get("pw_settings", {}) or {})
    return s


def save_settings(**kw) -> dict:
    s = store.kv_get("pw_settings", {}) or {}
    for k, v in kw.items():
        if k in DEFAULTS and v is not None:
            s[k] = v
    store.kv_set("pw_settings", s)
    _bust()
    return settings()


def bucket_labels(b=None) -> list:
    b = sorted(int(x) for x in (b or settings()["buckets"]))
    if not b:
        return []
    out = [f"Under {b[0]}K"] + [f"{b[i]}K-{b[i + 1]}K" for i in range(len(b) - 1)] + [f"{b[-1]}K+"]
    return out


def bucket_for(value: int, b=None) -> str:
    b = sorted(int(x) for x in (b or settings()["buckets"]))
    labels = bucket_labels(b)
    for i, t in enumerate(b):
        if value < t * 1000:
            return labels[i]
    return labels[-1]


def ist_ts(date: str, hhmm: str) -> float:
    """'2026-10-16', '14:45' (IST) -> UTC epoch seconds."""
    d = datetime.strptime(f"{date} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    return d.timestamp()


def fmt_ist(ts: float) -> str:
    return datetime.fromtimestamp(ts, IST).strftime("%a %d %b, %I:%M %p IST").replace(" 0", " ")


# ---------------- players ----------------
def norm_handle(raw: str) -> str:
    h = (raw or "").strip()
    m = re.search(r"instagram\.com/([^/?#\s]+)", h, re.I)
    if m:
        h = m.group(1)
    h = h.strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9._]{1,30}", h) or h.strip("._") == "":
        return ""
    return h


def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


class GameError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def join(handle: str, name: str, consent: bool) -> dict:
    h = norm_handle(handle)
    name = re.sub(r"\s+", " ", (name or "")).strip()[:32]
    if not h:
        raise GameError("Enter a valid Instagram handle (letters, numbers, . and _ only).")
    if not name:
        raise GameError("Enter a display name.")
    if not consent:
        raise GameError("Please tick the box to agree your handle, name and closed picks are shown publicly.")
    token = secrets.token_urlsafe(32)
    c = _db()
    with store._lock:
        r = c.execute("SELECT id, token_hash, hidden FROM pw_players WHERE handle=?", (h,)).fetchone()
        if r and r["token_hash"]:
            raise GameError("That handle is already playing on another device. If it's yours, DM "
                            "@letsgrowesports.igc on Instagram to release it.", 409)
        if r:   # released by the owner: claim it again from this device
            c.execute("UPDATE pw_players SET token_hash=?, name=? WHERE id=?", (_hash(token), name, r["id"]))
            pid = r["id"]
        else:
            pid = c.execute("INSERT INTO pw_players (handle, name, token_hash, created) VALUES (?,?,?,?)",
                            (h, name, _hash(token), time.time())).lastrowid
        c.commit()
    _bust()
    return {"token": token, "player": {"id": pid, "handle": h, "name": name}}


def player_by_token(token: str):
    if not token or len(token) > 200:
        return None
    with store._lock:
        r = _db().execute("SELECT id, handle, name, hidden FROM pw_players WHERE token_hash=?",
                          (_hash(token),)).fetchone()
    return dict(r) if r else None


def rename(token: str, name: str) -> dict:
    p = player_by_token(token)
    if not p:
        raise GameError("Join first.", 401)
    name = re.sub(r"\s+", " ", (name or "")).strip()[:32]
    if not name:
        raise GameError("Enter a display name.")
    with store._lock:
        _db().execute("UPDATE pw_players SET name=? WHERE id=?", (name, p["id"]))
        _db().commit()
    _bust()
    return {"ok": True}


# ---------------- questions ----------------
def _q(r) -> dict:
    q = dict(r)
    q["options"] = json.loads(q["options"])
    q["meta"] = json.loads(q.get("meta") or "{}")
    return q


def is_closed(q: dict, now: float = None) -> bool:
    return bool(q["locked"]) or (now or time.time()) >= q["close_ts"]


def add_question(kind: str, title: str, options: list, close_ts: float, day: int = 0, tag: str = "",
                 style: str = None, meta: dict = None, sort: int = 0) -> int:
    opts = []
    for o in options:
        o = str(o).strip()[:60]
        if o and o not in opts:
            opts.append(o)
    if len(opts) < 2:
        raise GameError("A question needs at least two options.")
    if not title.strip():
        raise GameError("Title is required.")
    style = style or ("dropdown" if len(opts) > 6 else "buttons")
    with store._lock:
        qid = _db().execute(
            "INSERT INTO pw_questions (kind, tag, title, day, style, options, close_ts, meta, sort, created) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (kind, tag.strip()[:24], title.strip()[:140], int(day), style, json.dumps(opts), float(close_ts),
             json.dumps(meta or {}), int(sort), time.time())).lastrowid
        _db().commit()
    _bust()
    return qid


def create_match_day(day: int, close_ts: float = None) -> list:
    s = settings()
    day = int(day)
    if str(day) not in s["days"]:
        raise GameError("Day must be 1, 2 or 3.")
    close_ts = close_ts or ist_ts(s["days"][str(day)], s["close"])
    with store._lock:
        have = {r["title"] for r in _db().execute("SELECT title FROM pw_questions WHERE kind='match' AND day=?", (day,))}
    ids = []
    for m in range(1, int(s["matches"]) + 1):
        title = f"Day {day} · Match {m}: Who wins?"
        if title in have:
            continue
        ids.append(add_question("match", title, s["teams"], close_ts, day, "MATCH WINNER", "dropdown",
                                {"match": m}, sort=m))
    return ids


def create_mvp(day: int = 0, close_ts: float = None) -> int:
    s = settings()
    if len(s["mvp"]) < 2:
        raise GameError("Paste the MVP candidates first (one per line).")
    day = int(day)
    if not close_ts:
        close_ts = ist_ts(s["days"][str(day or 1)], s["close"])
    title = f"Day {day} MVP: who takes it?" if day else "BMSD 2026 Grand Finals MVP"
    return add_question("mvp", title, s["mvp"], close_ts, day, "MVP", "dropdown", sort=50)


def create_peak(day: int, close_ts: float = None, auto: bool = True) -> int:
    s = settings()
    day = int(day)
    close_ts = close_ts or ist_ts(s["days"][str(day)], s["close"])
    return add_question("peak", f"What will Day {day} peak viewers be?", bucket_labels(), close_ts, day,
                        "PEAK VIEWERS", "buttons", {"date": s["days"][str(day)], "auto": bool(auto),
                                                    "buckets": s["buckets"]}, sort=60)


def create_record(close_ts: float = None) -> int:
    s = settings()
    close_ts = close_ts or ist_ts(s["days"]["1"], s["close"])
    rec = int(s["record"])
    return add_question("yesno", f"Will BMSD 2026 beat BMPS 2026's {rec // 1000}K peak?", ["Yes", "No"], close_ts,
                        0, "RECORD WATCH", "buttons", {"record": rec}, sort=70)


def get_question(qid: int) -> dict:
    with store._lock:
        r = _db().execute("SELECT * FROM pw_questions WHERE id=?", (int(qid),)).fetchone()
    if not r:
        raise GameError("No such question.", 404)
    return _q(r)


def questions() -> list:
    with store._lock:
        rows = _db().execute("SELECT * FROM pw_questions ORDER BY day=0, day, sort, close_ts, id").fetchall()
    return [_q(r) for r in rows]


def update_question(qid: int, action: str, value=None) -> dict:
    q = get_question(qid)
    c = _db()
    with store._lock:
        if action == "lock":
            c.execute("UPDATE pw_questions SET locked=1 WHERE id=?", (q["id"],))
        elif action == "reopen":
            close = float(value) if value else max(q["close_ts"], time.time() + 3600)
            c.execute("UPDATE pw_questions SET locked=0, answer=NULL, resolved_ts=NULL, void=0, close_ts=? WHERE id=?",
                      (close, q["id"]))
        elif action == "close_ts":
            c.execute("UPDATE pw_questions SET close_ts=? WHERE id=?", (float(value), q["id"]))
        elif action == "void":
            c.execute("UPDATE pw_questions SET void=1, locked=1 WHERE id=?", (q["id"],))
        elif action == "unvoid":
            c.execute("UPDATE pw_questions SET void=0 WHERE id=?", (q["id"],))
        elif action == "delete":
            c.execute("DELETE FROM pw_picks WHERE qid=?", (q["id"],))
            c.execute("DELETE FROM pw_questions WHERE id=?", (q["id"],))
        elif action == "answer":
            if value not in q["options"]:
                raise GameError("Answer must be one of the options.")
            c.execute("UPDATE pw_questions SET answer=?, locked=1, resolved_ts=? WHERE id=?",
                      (value, time.time(), q["id"]))
        elif action == "unresolve":
            c.execute("UPDATE pw_questions SET answer=NULL, resolved_ts=NULL WHERE id=?", (q["id"],))
        elif action == "title":
            c.execute("UPDATE pw_questions SET title=? WHERE id=?", (str(value).strip()[:140], q["id"]))
        else:
            raise GameError("Unknown action.")
        c.commit()
    _bust()
    return {"ok": True}


def resolve(qid: int, answer: str) -> dict:
    return update_question(qid, "answer", answer)


def tracker_answer(q: dict, st: dict = None):
    """What the viewership tracker says the answer is (peak / yesno questions), or None if not known yet."""
    if q["kind"] not in ("peak", "yesno"):
        return None
    if st is None:
        from core import events
        st = events.stats(EVENT_KEY) or {}
    if q["kind"] == "yesno":
        return "Yes" if int(st.get("peak") or 0) > int(q["meta"].get("record", settings()["record"])) else "No"
    label = datetime.strptime(q["meta"]["date"], "%Y-%m-%d").strftime("%a %d %b")
    d = next((d for d in st.get("days") or [] if d.get("day") == label), None)
    if not d or not d.get("peak"):
        return None
    return bucket_for(int(d["peak"]), q["meta"].get("buckets"))


def resolve_from_tracker(qid: int) -> dict:
    q = get_question(qid)
    a = tracker_answer(q)
    if a is None:
        raise GameError("The tracker has no reading for that day yet.")
    resolve(qid, a)
    return {"ok": True, "answer": a}


_last_auto = [0.0]


def auto_resolve(st: dict = None, now: float = None) -> list:
    """Resolve 'auto' peak questions 30 minutes after that day's broadcast ends. Cheap; throttled to once a minute."""
    now = now or time.time()
    if st is None and now - _last_auto[0] < 60:
        return []
    _last_auto[0] = now
    pend = [q for q in questions() if q["kind"] == "peak" and q["meta"].get("auto") and not q["answer"] and not q["void"]
            and is_closed(q, now)]
    if not pend:
        return []
    if st is None:
        try:
            from core import events
            st = events.stats(EVENT_KEY) or {}
        except Exception:
            return []
    done = []
    lb = st.get("last_broadcast") or {}
    for q in pend:
        label = datetime.strptime(q["meta"]["date"], "%Y-%m-%d").strftime("%a %d %b")
        end = lb.get("end") or 0
        ended_day = datetime.fromtimestamp(end, IST).strftime("%a %d %b") if end else ""
        if st.get("official_live") or ended_day != label or now - end < 1800:
            continue
        a = tracker_answer(q, st)
        if a:
            resolve(q["id"], a)
            done.append(q["id"])
    return done


# ---------------- picks ----------------
def pick(token: str, qid: int, option: str, now: float = None) -> dict:
    p = player_by_token(token)
    if not p:
        raise GameError("Join first.", 401)
    if p["hidden"]:
        raise GameError("This player has been removed from the game.", 403)
    q = get_question(qid)
    if q["void"]:
        raise GameError("This question was cancelled.", 409)
    if is_closed(q, now):
        raise GameError("Picks for this question are closed.", 409)
    if option not in q["options"]:
        raise GameError("Pick one of the options.")
    with store._lock:
        _db().execute("INSERT INTO pw_picks (player_id, qid, option, ts) VALUES (?,?,?,?) "
                      "ON CONFLICT(player_id, qid) DO UPDATE SET option=excluded.option, ts=excluded.ts",
                      (p["id"], q["id"], option, time.time()))
        _db().commit()
    _bust()
    return {"ok": True, "qid": q["id"], "option": option}


def _counts() -> dict:
    with store._lock:
        rows = _db().execute("SELECT k.qid, k.option, COUNT(*) n FROM pw_picks k JOIN pw_players p ON p.id=k.player_id "
                             "WHERE p.hidden=0 GROUP BY k.qid, k.option").fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["qid"], {})[r["option"]] = r["n"]
    return out


def points_for(q: dict, counts: dict) -> int:
    """Points a correct pick earns on a resolved question."""
    n = sum(counts.values())
    c = counts.get(q["answer"], 0)
    if not n or not c:
        return 100
    return 100 + round(100 * (1 - c / n))


def _scores():
    """{player_id: {'all': [pts, correct], 1: [...], 2: [...], 3: [...]}} for visible players."""
    qs = {q["id"]: q for q in questions() if q["answer"] and not q["void"]}
    counts = _counts()
    worth = {qid: points_for(q, counts.get(qid, {})) for qid, q in qs.items()}
    with store._lock:
        players = {r["id"]: dict(r) for r in _db().execute(
            "SELECT id, handle, name, created FROM pw_players WHERE hidden=0")}
        picks = _db().execute("SELECT player_id, qid, option FROM pw_picks").fetchall()
    sc = {pid: {"all": [0, 0], 1: [0, 0], 2: [0, 0], 3: [0, 0], "picks": 0} for pid in players}
    for k in picks:
        if k["player_id"] not in sc:
            continue
        sc[k["player_id"]]["picks"] += 1
        q = qs.get(k["qid"])
        if q and k["option"] == q["answer"]:
            for b in ("all", q["day"]) if q["day"] else ("all",):
                sc[k["player_id"]][b][0] += worth[q["id"]]
                sc[k["player_id"]][b][1] += 1
    return players, sc, worth


def _ranked(players, sc, board):
    rows = [{"id": pid, "handle": p["handle"], "name": p["name"], "pts": sc[pid][board][0],
             "correct": sc[pid][board][1], "created": p["created"]} for pid, p in players.items()]
    rows.sort(key=lambda r: (-r["pts"], -r["correct"], r["created"]))
    rank, prev = 0, None
    for i, r in enumerate(rows):
        key = (r["pts"], r["correct"])
        if key != prev:
            rank, prev = i + 1, key
        r["rank"] = rank
    return rows


def board(now: float = None) -> dict:
    """Public state: questions with crowd counts, top 10 per leaderboard. Cached for 3 seconds."""
    now = now or time.time()
    hit = _cache.get("board")
    if hit and now - hit[0] < 3:
        return hit[1]
    try:
        auto_resolve(now=now)
    except Exception:
        pass
    counts = _counts()
    players, sc, worth = _scores()
    qs = []
    for q in questions():
        cnt = counts.get(q["id"], {})
        qs.append({"id": q["id"], "kind": q["kind"], "tag": q["tag"], "title": q["title"], "day": q["day"],
                   "style": q["style"], "options": q["options"], "close_ts": q["close_ts"],
                   "closed": is_closed(q, now), "void": bool(q["void"]), "answer": q["answer"],
                   "counts": cnt, "total": sum(cnt.values()), "worth": worth.get(q["id"])})
    boards = {}
    for b in ("all", 1, 2, 3):
        boards[str(b)] = [{k: r[k] for k in ("rank", "handle", "name", "pts", "correct")}
                          for r in _ranked(players, sc, b) if r["pts"] > 0][:10]
    s = settings()
    out = {"now": now, "questions": qs, "boards": boards, "players": len(players), "prize": s["prize"],
           "days": s["days"]}
    _cache["board"] = (now, out)
    return out


def me(token: str) -> dict:
    p = player_by_token(token)
    if not p:
        raise GameError("Not joined.", 401)
    with store._lock:
        picks = {r["qid"]: r["option"] for r in _db().execute("SELECT qid, option FROM pw_picks WHERE player_id=?",
                                                               (p["id"],))}
    players, sc, _ = _scores()
    ranks = {}
    if p["id"] in players:
        for b in ("all", 1, 2, 3):
            r = next(r for r in _ranked(players, sc, b) if r["id"] == p["id"])
            ranks[str(b)] = {"rank": r["rank"], "pts": r["pts"], "correct": r["correct"]}
    return {"player": {"handle": p["handle"], "name": p["name"], "hidden": bool(p["hidden"])},
            "picks": {str(k): v for k, v in picks.items()}, "ranks": ranks, "of": len(players)}


def profile(handle: str, now: float = None) -> dict:
    """Public profile: picks only on questions that have closed."""
    h = norm_handle(handle)
    with store._lock:
        p = _db().execute("SELECT id, handle, name FROM pw_players WHERE handle=? AND hidden=0", (h,)).fetchone()
    if not p:
        raise GameError("No such player.", 404)
    qs = {q["id"]: q for q in questions()}
    counts = _counts()
    with store._lock:
        rows = _db().execute("SELECT qid, option FROM pw_picks WHERE player_id=?", (p["id"],)).fetchall()
    picks = []
    for r in rows:
        q = qs.get(r["qid"])
        if not q or not is_closed(q, now):
            continue
        ok = None if not q["answer"] or q["void"] else r["option"] == q["answer"]
        picks.append({"qid": q["id"], "title": q["title"], "tag": q["tag"], "day": q["day"], "pick": r["option"],
                      "answer": q["answer"], "void": bool(q["void"]), "correct": ok,
                      "pts": points_for(q, counts.get(q["id"], {})) if ok else 0})
    picks.sort(key=lambda x: (x["day"] == 0, x["day"], x["qid"]))
    players, sc, _ = _scores()
    r = next((r for r in _ranked(players, sc, "all") if r["id"] == p["id"]), None)
    return {"handle": p["handle"], "name": p["name"], "rank": r["rank"] if r else None, "pts": r["pts"] if r else 0,
            "correct": r["correct"] if r else 0, "picks": picks}


# ---------------- owner ----------------
def players_admin() -> list:
    with store._lock:
        rows = _db().execute("SELECT p.id, p.handle, p.name, p.created, p.hidden, p.token_hash IS NOT NULL bound, "
                             "(SELECT COUNT(*) FROM pw_picks k WHERE k.player_id=p.id) picks FROM pw_players p "
                             "ORDER BY p.created DESC").fetchall()
    players, sc, _ = _scores()
    out = []
    for r in rows:
        d = dict(r)
        d["pts"] = sc.get(r["id"], {}).get("all", [0, 0])[0]
        out.append(d)
    return out


def player_action(pid: int, action: str) -> dict:
    with store._lock:
        if action == "hide":
            _db().execute("UPDATE pw_players SET hidden=1 WHERE id=?", (int(pid),))
        elif action == "unhide":
            _db().execute("UPDATE pw_players SET hidden=0 WHERE id=?", (int(pid),))
        elif action == "release":
            _db().execute("UPDATE pw_players SET token_hash=NULL WHERE id=?", (int(pid),))
        else:
            raise GameError("Unknown action.")
        _db().commit()
    _bust()
    return {"ok": True}
