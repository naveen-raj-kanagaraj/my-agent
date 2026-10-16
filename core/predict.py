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
import sqlite3
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
    "buckets": [350, 450, 500, 550, 600, 650, 700],                         # thousands; labels are built from these
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
# kinds: single-answer ('match', 'mvp', 'peak', 'yesno', 'team', 'other'), 'multi' (pick exactly meta.pick options),
# 'text' (free text, owner marks the accepted spellings).
def _q(r) -> dict:
    q = dict(r)
    q["options"] = json.loads(q["options"])
    q["meta"] = json.loads(q.get("meta") or "{}")
    return q


def ans_list(q: dict) -> list:
    """Accepted answers as a list (multi and text store a JSON list; others a plain string)."""
    a = q.get("answer")
    if not a:
        return []
    if q["kind"] in ("multi", "text"):
        try:
            v = json.loads(a)
            return v if isinstance(v, list) else [str(v)]
        except ValueError:
            return [a]
    return [a]


def tnorm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def is_closed(q: dict, now: float = None) -> bool:
    return bool(q["locked"]) or (now or time.time()) >= q["close_ts"]


def add_question(kind: str, title: str, options: list, close_ts: float, day: int = 0, tag: str = "",
                 style: str = None, meta: dict = None, sort: int = 0) -> int:
    opts = []
    for o in options or []:
        o = str(o).strip()[:60]
        if o and o not in opts:
            opts.append(o)
    meta = dict(meta or {})
    if kind == "text":
        opts, style = [], "text"
    elif len(opts) < 2:
        raise GameError("A question needs at least two options.")
    if kind == "multi":
        k = int(meta.get("pick") or 0)
        if not 2 <= k < len(opts):
            raise GameError("A multi-pick question needs 'pick' between 2 and the number of options minus 1.")
        style = "multi"
    if not title.strip():
        raise GameError("Title is required.")
    style = style or ("dropdown" if len(opts) > 6 else "buttons")
    with store._lock:
        qid = _db().execute(
            "INSERT INTO pw_questions (kind, tag, title, day, style, options, close_ts, meta, sort, created) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (kind, tag.strip()[:24], title.strip()[:140], int(day), style, json.dumps(opts), float(close_ts),
             json.dumps(meta), int(sort), time.time())).lastrowid
        _db().commit()
    _bust()
    return qid


def _close(day, close_ts=None):
    s = settings()
    return close_ts or ist_ts(s["days"][str(day or 1)], s["close"])


def create_match_day(day: int, close_ts: float = None) -> list:
    s = settings()
    day = int(day)
    if str(day) not in s["days"]:
        raise GameError("Day must be 1, 2 or 3.")
    close_ts = _close(day, close_ts)
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


def _exists(kind, title, day=None) -> bool:
    with store._lock:
        if day is None:
            return bool(_db().execute("SELECT 1 FROM pw_questions WHERE kind=? AND title=?", (kind, title)).fetchone())
        return bool(_db().execute("SELECT 1 FROM pw_questions WHERE kind=? AND title=? AND day=?",
                                  (kind, title, int(day))).fetchone())


def create_event_set(close_ts: float = None) -> list:
    """Whole-event questions: champion (open until the last day), top 3, BMIC qualifiers."""
    s = settings()
    first = _close(1, close_ts)
    last = ist_ts(s["days"]["3"], s["close"])
    spec = [("team", "Who will win the BMSD 2026 Grand Finals?", s["teams"], last, "CHAMPION", "grid", {}, 1),
            ("multi", "Which teams will finish in the top 3?", s["teams"], first, "TOP 3", "multi", {"pick": 3, "ranked": True}, 2),
            ("multi", "Which 6 teams will qualify for BMIC?", s["teams"], first, "BMIC", "multi", {"pick": 6}, 3)]
    ids = []
    for kind, title, opts, close, tag, style, meta, sort in spec:
        if not _exists(kind, title):
            ids.append(add_question(kind, title, opts, close, 0, tag, style, meta, sort))
    return ids


def create_day_set(day: int, close_ts: float = None) -> list:
    """Per-day questions: chicken dinner for each match, most chicken dinners that day, peak viewers (auto)."""
    s = settings()
    day = int(day)
    close = _close(day, close_ts)
    ids = []
    for m in range(1, int(s["matches"]) + 1):
        t = f"Match {m}: Which team gets the chicken dinner?"
        if not _exists("match", t, day):
            ids.append(add_question("match", t, s["teams"], close, day, f"MATCH {m}", "grid", {"match": m}, sort=m))
    t = f"Which team gets the most chicken dinners on Day {day}?"
    if not _exists("team", t, day):
        ids.append(add_question("team", t, s["teams"], close, day, "MOST CHICKEN DINNERS", "grid", sort=10))
    if not _exists("peak", f"How many people will watch at the peak on Day {day}?", day):
        ids.append(create_peak(day, close))
    return ids


def create_mvp(day: int = 0, close_ts: float = None) -> int:
    s = settings()
    if len(s["mvp"]) < 2:
        raise GameError("Paste the MVP candidates first (one per line).")
    day = int(day)
    title = f"Day {day} MVP: who takes it?" if day else "BMSD 2026 Grand Finals MVP"
    return add_question("mvp", title, s["mvp"], _close(day, close_ts), day, "MVP", "dropdown", sort=50)


def create_peak(day: int, close_ts: float = None, auto: bool = True) -> int:
    s = settings()
    day = int(day)
    return add_question("peak", f"How many people will watch at the peak on Day {day}?", bucket_labels(), _close(day, close_ts), day,
                        "PEAK VIEWERS", "buttons", {"date": s["days"][str(day)], "auto": bool(auto),
                                                    "buckets": s["buckets"]}, sort=60)


def create_record(close_ts: float = None) -> int:
    s = settings()
    rec = int(s["record"])
    return add_question("yesno", f"Will BMSD 2026 beat BMPS 2026's {rec // 1000}K peak?", ["Yes", "No"],
                        _close(1, close_ts), 0, "RECORD WATCH", "buttons", {"record": rec}, sort=70)


def get_question(qid: int) -> dict:
    with store._lock:
        r = _db().execute("SELECT * FROM pw_questions WHERE id=?", (int(qid),)).fetchone()
    if not r:
        raise GameError("No such question.", 404)
    return _q(r)


def questions() -> list:
    with store._lock:
        rows = _db().execute("SELECT * FROM pw_questions ORDER BY day=0 DESC, day, sort, close_ts, id").fetchall()
    return [_q(r) for r in rows]


def _clean_answer(q: dict, value):
    if q["kind"] == "multi":
        vals = value if isinstance(value, list) else [v for v in str(value or "").split("\n")]
        vals = [v.strip() for v in vals if v and v.strip()]
        if not vals or any(v not in q["options"] for v in vals):
            raise GameError("Pick the correct teams from the options.")
        return json.dumps(sorted(set(vals), key=q["options"].index))
    if q["kind"] == "text":
        vals = value if isinstance(value, list) else re.split(r"[,\n]", str(value or ""))
        vals = [v.strip()[:40] for v in vals if v and v.strip()]
        if not vals:
            raise GameError("Type the accepted name(s), separated by commas.")
        return json.dumps(vals)
    if value not in q["options"]:
        raise GameError("Answer must be one of the options.")
    return value


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
            c.execute("UPDATE pw_questions SET answer=?, locked=1, resolved_ts=? WHERE id=?",
                      (_clean_answer(q, value), time.time(), q["id"]))
        elif action == "unresolve":
            c.execute("UPDATE pw_questions SET answer=NULL, resolved_ts=NULL WHERE id=?", (q["id"],))
        elif action == "title":
            c.execute("UPDATE pw_questions SET title=? WHERE id=?", (str(value).strip()[:140], q["id"]))
        else:
            raise GameError("Unknown action.")
        c.commit()
    _bust()
    return {"ok": True}


def resolve(qid: int, answer) -> dict:
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
def _decode(q: dict, raw: str):
    if q["kind"] == "multi":
        try:
            return json.loads(raw)
        except ValueError:
            return []
    return raw


def pick(token: str, qid: int, option, now: float = None) -> dict:
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
    if q["kind"] == "multi":
        k = int(q["meta"]["pick"])
        vals = option if isinstance(option, list) else []
        vals = list(dict.fromkeys(str(v) for v in vals))
        if len(vals) != k or any(v not in q["options"] for v in vals):
            raise GameError(f"Pick exactly {k} teams.")
        stored, shown = json.dumps(vals if q["meta"].get("ranked") else sorted(vals, key=q["options"].index)), vals
    elif q["kind"] == "text":
        stored = re.sub(r"\s+", " ", str(option or "")).strip()[:40]
        if len(tnorm(stored)) < 2:
            raise GameError("Type a player name.")
        shown = stored
    else:
        if option not in q["options"]:
            raise GameError("Pick one of the options.")
        stored = shown = option
    with store._lock:
        try:   # picks are final: the first save wins
            _db().execute("INSERT INTO pw_picks (player_id, qid, option, ts) VALUES (?,?,?,?)",
                          (p["id"], q["id"], stored, time.time()))
        except sqlite3.IntegrityError:
            raise GameError("You've already made this pick. Picks can't be changed.", 409)
        _db().commit()
    _bust()
    return {"ok": True, "qid": q["id"], "option": shown}


def _qstats(qs: dict) -> dict:
    """Per question: n players who picked, and how many picked/included each option (text: by normalised name)."""
    with store._lock:
        rows = _db().execute("SELECT k.qid, k.option FROM pw_picks k JOIN pw_players p ON p.id=k.player_id "
                             "WHERE p.hidden=0").fetchall()
    out = {}
    for r in rows:
        q = qs.get(r["qid"])
        if not q:
            continue
        s = out.setdefault(q["id"], {"n": 0, "inc": {}, "names": {}})
        s["n"] += 1
        if q["kind"] == "multi":
            for v in _decode(q, r["option"]):
                s["inc"][v] = s["inc"].get(v, 0) + 1
        elif q["kind"] == "text":
            k = tnorm(r["option"])
            s["inc"][k] = s["inc"].get(k, 0) + 1
            s["names"].setdefault(k, r["option"])
        else:
            s["inc"][r["option"]] = s["inc"].get(r["option"], 0) + 1
    return out


def points_for(q: dict, st: dict, raw: str) -> int:
    """Points one pick earns on a settled question. 100 + underdog bonus 100 x (1 - share right);
    multi-pick splits that across the k picks, per correct team."""
    if not q.get("answer") or q.get("void"):
        return 0
    n = max(1, (st or {}).get("n", 0))
    inc = (st or {}).get("inc", {})
    ans = ans_list(q)
    if q["kind"] == "multi":
        k = int(q["meta"]["pick"])
        hit = [t for t in _decode(q, raw) if t in ans]
        return round(sum((100 + 100 * (1 - inc.get(t, 1) / n)) / k for t in hit))
    if q["kind"] == "text":
        acc = {tnorm(a) for a in ans}
        if tnorm(raw) not in acc:
            return 0
        c = sum(v for kk, v in inc.items() if kk in acc) or 1
        return 100 + round(100 * (1 - c / n))
    if raw != q["answer"]:
        return 0
    return 100 + round(100 * (1 - (inc.get(q["answer"], 1)) / n))


def _scores():
    """(players, {player_id: {'all': [pts, correct], 1: [...], 2: [...], 3: [...]}}, qstats, qs)"""
    qs = {q["id"]: q for q in questions()}
    st = _qstats(qs)
    with store._lock:
        players = {r["id"]: dict(r) for r in _db().execute(
            "SELECT id, handle, name, created FROM pw_players WHERE hidden=0")}
        picks = _db().execute("SELECT player_id, qid, option FROM pw_picks").fetchall()
    sc = {pid: {"all": [0, 0], 1: [0, 0], 2: [0, 0], 3: [0, 0]} for pid in players}
    for k in picks:
        q = qs.get(k["qid"])
        if k["player_id"] not in sc or not q or not q["answer"] or q["void"]:
            continue
        pts = points_for(q, st.get(q["id"]), k["option"])
        if pts:
            for b in ("all", q["day"]) if q["day"] else ("all",):
                sc[k["player_id"]][b][0] += pts
                sc[k["player_id"]][b][1] += 1
    return players, sc, st, qs


def _ranked(players, sc, board):
    rows = [{"id": pid, "handle": p["handle"], "name": p["name"], "pts": sc[pid][board][0],
             "correct": sc[pid][board][1], "created": p["created"]} for pid, p in players.items()]
    rows.sort(key=lambda r: (-r["pts"], -r["correct"], r["created"]))
    for i, r in enumerate(rows):   # unique ranks: ties go to more correct picks, then whoever joined first
        r["rank"] = i + 1
    return rows


def _public_counts(q: dict, s: dict, closed: bool) -> dict:
    if not s:
        return {}
    if q["kind"] == "text":   # free text is only shown after close, top 5 names
        if not closed:
            return {}
        top = sorted(s["inc"].items(), key=lambda kv: -kv[1])[:5]
        return {s["names"][k]: v for k, v in top}
    return dict(s["inc"])


def _pct(counts: dict, n: int) -> dict:
    """Crowd split as whole percentages only: the public never sees how many people play."""
    return {k: round(100 * v / n) for k, v in counts.items()} if n else {}


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
    players, sc, st, qmap = _scores()
    out_q = []
    for q in qmap.values():
        s = st.get(q["id"]) or {}
        closed = is_closed(q, now)
        best = None
        if q["answer"] and not q["void"]:
            n = max(1, s.get("n", 0))
            if q["kind"] == "multi":
                best = round(sum(100 + 100 * (1 - s.get("inc", {}).get(t, 1) / n) for t in ans_list(q)) / int(q["meta"]["pick"]))
            elif q["kind"] == "text":
                acc = {tnorm(a) for a in ans_list(q)}
                c = sum(v for k, v in s.get("inc", {}).items() if k in acc) or 1
                best = 100 + round(100 * (1 - c / n))
            else:
                best = 100 + round(100 * (1 - s.get("inc", {}).get(q["answer"], 1) / n))
        out_q.append({"id": q["id"], "kind": q["kind"], "tag": q["tag"], "title": q["title"], "day": q["day"],
                      "style": q["style"], "options": q["options"], "close_ts": q["close_ts"], "closed": closed,
                      "void": bool(q["void"]), "answer": ans_list(q) if q["kind"] in ("multi", "text") else q["answer"],
                      "pick": q["meta"].get("pick"), "ranked": bool(q["meta"].get("ranked")), "pct": _pct(_public_counts(q, s, closed), s.get("n", 0)),
                      "picked": bool(s.get("n")), "worth": best})
    out_q.sort(key=lambda q: (q["day"] != 0, q["day"], next(x["sort"] for x in qmap.values() if x["id"] == q["id"]), q["id"]))
    boards = {}
    for b in ("all", 1, 2, 3):
        boards[str(b)] = [{k: r[k] for k in ("rank", "handle", "name", "pts", "correct")}
                          for r in _ranked(players, sc, b) if r["pts"] > 0][:10]
    s = settings()
    out = {"now": now, "questions": out_q, "boards": boards, "prize": s["prize"], "days": s["days"]}
    _cache["board"] = (now, out)
    return out


def me(token: str) -> dict:
    p = player_by_token(token)
    if not p:
        raise GameError("Not joined.", 401)
    qs = {q["id"]: q for q in questions()}
    with store._lock:
        rows = _db().execute("SELECT qid, option FROM pw_picks WHERE player_id=?", (p["id"],)).fetchall()
    picks = {str(r["qid"]): _decode(qs[r["qid"]], r["option"]) for r in rows if r["qid"] in qs}
    players, sc, st, _ = _scores()
    ranks = {}
    if p["id"] in players:
        for b in ("all", 1, 2, 3):
            r = next(r for r in _ranked(players, sc, b) if r["id"] == p["id"])
            ranks[str(b)] = {"rank": r["rank"], "pts": r["pts"], "correct": r["correct"]}
    mypts = {str(r["qid"]): points_for(qs[r["qid"]], st.get(r["qid"]), r["option"]) for r in rows
             if r["qid"] in qs and qs[r["qid"]]["answer"]}
    return {"player": {"handle": p["handle"], "name": p["name"], "hidden": bool(p["hidden"])},
            "picks": picks, "pts": mypts, "ranks": ranks}


def profile(handle: str, now: float = None) -> dict:
    """Public profile: picks only on questions that have closed."""
    h = norm_handle(handle)
    with store._lock:
        p = _db().execute("SELECT id, handle, name FROM pw_players WHERE handle=? AND hidden=0", (h,)).fetchone()
    if not p:
        raise GameError("No such player.", 404)
    players, sc, st, qs = _scores()
    with store._lock:
        rows = _db().execute("SELECT qid, option FROM pw_picks WHERE player_id=?", (p["id"],)).fetchall()
    picks = []
    for r in rows:
        q = qs.get(r["qid"])
        if not q or not is_closed(q, now):
            continue
        v = _decode(q, r["option"])
        pts = points_for(q, st.get(q["id"]), r["option"])
        picks.append({"qid": q["id"], "title": q["title"], "tag": q["tag"], "day": q["day"],
                      "pick": ", ".join(v) if isinstance(v, list) else v,
                      "answer": ", ".join(ans_list(q)), "void": bool(q["void"]),
                      "correct": None if not q["answer"] or q["void"] else pts > 0, "pts": pts})
    picks.sort(key=lambda x: (x["day"] != 0, x["day"], x["qid"]))
    r = next((r for r in _ranked(players, sc, "all") if r["id"] == p["id"]), None)
    return {"handle": p["handle"], "name": p["name"], "rank": r["rank"] if r else None, "pts": r["pts"] if r else 0,
            "correct": r["correct"] if r else 0, "picks": picks}


# ---------------- owner ----------------
def players_admin() -> list:
    with store._lock:
        rows = _db().execute("SELECT p.id, p.handle, p.name, p.created, p.hidden, p.token_hash IS NOT NULL bound, "
                             "(SELECT COUNT(*) FROM pw_picks k WHERE k.player_id=p.id) picks FROM pw_players p "
                             "ORDER BY p.created DESC").fetchall()
    players, sc, _, _ = _scores()
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
        elif action == "delete":      # test entries: remove the player and their picks
            _db().execute("DELETE FROM pw_picks WHERE player_id=?", (int(pid),))
            _db().execute("DELETE FROM pw_players WHERE id=?", (int(pid),))
        elif action == "release":
            _db().execute("UPDATE pw_players SET token_hash=NULL WHERE id=?", (int(pid),))
        else:
            raise GameError("Unknown action.")
        _db().commit()
    _bust()
    return {"ok": True}
