"""Live viewership tracker for events (tournaments) across every YouTube stream: official broadcast, watch parties
and community streams. Esports-Charts-style numbers: peak viewers, average viewers, hours watched, airtime, per
day, per channel.

How it works, every POLL_SEC seconds while an event is active:
  1. YouTube live search for the event's phrases (yt-dlp, no API key): finds new streams and gives their current
     viewer counts.
  2. Streams seen recently but missing from search this time are checked directly, so a stream dropping in the
     search ranking isn't counted as zero.
  3. With YOUTUBE_API_KEY set, every known stream's count comes from the official API instead (more exact; 1 quota
     unit per 50 streams).
Each poll stores one sample per live stream and one total ("tick").
"""
import os
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests

from core import store

POLL_SEC = int(os.getenv("EVENT_POLL_SEC", "60"))          # discovery: search YouTube for new streams
FAST_SEC = float(os.getenv("EVENT_FAST_SEC", "2"))          # live counter: re-count live streams this often
MINOR_SEC = 30                                              # streams under MINOR_VIEWERS are re-counted less often
MINOR_VIEWERS = 50
SAMPLE_EVERY = 30
ANOM_MIN = int(os.getenv("EVENT_ANOMALY_MIN", "2000"))      # a jump/drop this big ...
ANOM_PCT = float(os.getenv("EVENT_ANOMALY_PCT", "0.15"))    # ... and at least this share of the stream, within ~15s                                           # per-stream history is stored every 30s
_LIVE = {}      # event -> {vid: stream dict} from the latest discovery
_FAST = {}      # event -> {vid: {"viewers", "ts", "misses"}}
_FASTSTATE = {"method": "", "ok_ts": 0.0, "errors": 0}
_HIST = {}      # event -> {vid: deque[(ts, viewers)]} every live-counter reading (last ~3h), for streamer graphs
_ENDED = {}     # vid -> time the live counter saw it end (search results lag, so don't re-add it)
RECHECK_MIN = 15          # re-check streams seen live within this many minutes that vanished from search
MAX_DIRECT_CHECKS = 20
REPORT_TZ = ZoneInfo(os.getenv("EVENT_TZ", "Asia/Kolkata"))
LIVE_FILTER = "EgJAAQ%253D%253D"     # YouTube search filter: live now
WATCH_PARTY = re.compile(r"watch\s*-?\s*party|co-?\s*stream|watch\s*-?\s*along|reaction|reacting|live\s+react", re.I)

PRESETS = {
    "bmsd": {
        "name": "BMSD 2026",
        # only these watch-party channels are permitted to restream; everyone else is ignored (with official channels kept)
        "allowed": ["dynamo", "bixi", "zgod", "neyoo", "mizo", "mrspike", "lolzz", "sharkshe", "mafianinja", "ruthless",
                    "rakazone", "ansh", "casetoo", "sheek", "ipreeet", "shreeman", "mortal", "vaadhiyaar", "regaltos",
                    "snax", "sriop", "mayur", "neonxpawan", "pawanop", "ladypredator", "soulaman"],
        "videos_extra": ["kf7OYvjee_k"],        # specific streams to track (Soul Aman's finals stream)
        # checked directly every minute, even if search misses them
        "always_check": ["@ShreemanLegend", "@SoulAman", "@DynamoGaming", "@TheBixiOP", "@ZGODGAMING", "@NEYOOGAMINGYT", "@MizoPlays", "@MrSpike", "@LoLzZzGaming",
                         "@SHARKSHE", "@MafiaNinja", "@ImRuthlessceopubg", "@RakaZoneGaming", "@AnshYT", "@casetooop",
                         "@thecasetoopapa", "@sheekgaming", "@IPREEET.69", "@MortaLyt", "@soulregaltos9810", "@SnaxGaming",
                         "@sriop-sr70", "@MayurGaming", "@NEONXPAWANOP", "@LadyPredatorGaming", "@LadyPredator"],
        "next_start": "2026-10-16 14:30",       # IST; shown as a countdown while the official stream is offline
        "match": ["bmsd", "bgmi showdown", "battlegrounds mobile india showdown", "battlegrounds mobile showdown",
                  "bgmi show down", "bm showdown"],
        "queries": ["BMSD", "BMSD 2026", "BGMI Showdown", "Battlegrounds Mobile India Showdown", "BMSD watch party"],
        "official": ["krafton india esports", "battlegrounds mobile india"],
        "links": {"Esports Charts (official numbers, all platforms)":
                  "https://escharts.com/tournaments/bgmi/battlegrounds-mobile-india-showdown-2026-bgmi"},
    },
}


def yt_link(vid: str) -> str:
    return f"https://youtu.be/{vid}"


# ---------- storage ----------

def _db():
    c = store.conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS ev_streams (event TEXT, vid TEXT, channel TEXT, channel_id TEXT, title TEXT, kind TEXT,
        first_seen REAL, last_seen REAL, peak INTEGER DEFAULT 0, peak_at REAL, PRIMARY KEY (event, vid));
    CREATE TABLE IF NOT EXISTS ev_samples (event TEXT, ts INTEGER, vid TEXT, viewers INTEGER);
    CREATE INDEX IF NOT EXISTS ev_samples_ix ON ev_samples(event, ts);
    CREATE TABLE IF NOT EXISTS ev_anomalies (event TEXT, ts INTEGER, vid TEXT, channel TEXT, kind TEXT, before INTEGER,
        after INTEGER, change INTEGER, pct REAL, seconds INTEGER);
    CREATE TABLE IF NOT EXISTS ev_ticks (event TEXT, ts INTEGER, total INTEGER, live INTEGER, official INTEGER,
        watch INTEGER, community INTEGER, PRIMARY KEY (event, ts));
    """)
    return c


def events() -> dict:
    evs = store.kv_get("events", {})
    for k, ev in evs.items():  # events created before a preset gained new fields get them
        for field, val in PRESETS.get(k, {}).items():
            if field == "links" and not ev.get("links"):
                ev["links"] = dict(val)
    return evs


def save_events(evs: dict):
    store.kv_set("events", evs)


def get(key: str = None):
    evs = events()
    if key:
        return evs.get(key.lower())
    active = [e for e in evs.values() if e.get("active")]
    return active[0] if active else (list(evs.values())[-1] if evs else None)


def create(key: str, name: str = None, match: list = None, queries: list = None, official: list = None) -> dict:
    key = re.sub(r"[^a-z0-9_-]", "", key.lower())[:20] or "event"
    preset = PRESETS.get(key, {})
    ev = {"key": key, "name": name or preset.get("name") or key.upper(),
          "match": [m.lower() for m in (match or preset.get("match") or [key])],
          "queries": queries or preset.get("queries") or [key],
          "official": [o.lower() for o in (official or preset.get("official") or [])],
          "links": dict(preset.get("links") or {}),
          "channels": [], "videos": [], "excluded": [], "active": True, "created": time.time()}
    evs = events()
    if key in evs:
        evs[key].update(active=True)
        ev = evs[key]
    else:
        evs[key] = ev
    save_events(evs)
    return ev


def update(key: str, **fields):
    evs = events()
    if key in evs:
        evs[key].update(fields)
        save_events(evs)


# ---------- fetching ----------

def _ydl(flat=True):
    import yt_dlp
    from core.downloader import COOKIES_FILE
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20}
    if flat:
        opts.update(extract_flat="in_playlist", playlistend=80)
    if COOKIES_FILE.exists():
        opts["cookiefile"] = str(COOKIES_FILE)
    return yt_dlp.YoutubeDL(opts)


def search_live(query: str) -> list:
    """[{vid, title, channel, channel_id, viewers}] currently live for a search."""
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={LIVE_FILTER}"
    with _ydl() as y:
        info = y.extract_info(url, download=False)
    out = []
    for e in info.get("entries") or []:
        if not e or e.get("live_status") != "is_live" or not e.get("id") or e.get("concurrent_view_count") is None:
            continue  # only streams live right now with a live "watching" count
        out.append({"vid": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or "",
                    "channel_id": e.get("channel_id") or "", "viewers": int(e.get("concurrent_view_count") or 0)})
    return out


def check_video(vid: str):
    """Direct check of one stream: dict if live now, else None."""
    with _ydl(flat=False) as y:
        i = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    if not i.get("is_live"):
        return None
    return {"vid": vid, "title": i.get("title") or "", "channel": i.get("channel") or i.get("uploader") or "",
            "channel_id": i.get("channel_id") or "", "viewers": int(i.get("concurrent_view_count") or 0)}


def check_channel(handle: str):
    """A channel's current live stream, if any (@handle, channel URL or id)."""
    h = handle.strip()
    if h.startswith("http"):
        base = re.sub(r"/(live|streams|videos|featured)/?$", "", h.rstrip("/"))
    elif h.startswith("UC") and len(h) == 24:
        base = f"https://www.youtube.com/channel/{h}"
    else:
        base = f"https://www.youtube.com/@{h.lstrip('@')}"
    try:
        with _ydl(flat=False) as y:
            i = y.extract_info(base + "/live", download=False)
    except Exception:
        return None
    if not i.get("is_live"):
        return None
    return {"vid": i["id"], "title": i.get("title") or "", "channel": i.get("channel") or "",
            "channel_id": i.get("channel_id") or "", "viewers": int(i.get("concurrent_view_count") or 0)}


def api_counts(vids: list) -> dict:
    """{vid: viewers or None if not live} from the YouTube Data API (needs YOUTUBE_API_KEY)."""
    key = os.getenv("YOUTUBE_API_KEY")
    if not key or not vids:
        return {}
    out = {}
    for i in range(0, len(vids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                         params={"part": "liveStreamingDetails,snippet", "id": ",".join(vids[i:i + 50]), "key": key},
                         timeout=15)
        r.raise_for_status()
        for it in r.json().get("items", []):
            d = it.get("liveStreamingDetails") or {}
            live = d.get("actualStartTime") and not d.get("actualEndTime")
            out[it["id"]] = int(d["concurrentViewers"]) if live and d.get("concurrentViewers") else (0 if live else None)
    return out


# ---------- classification ----------

def _norm(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


def allowed_list(ev: dict) -> list:
    return ev.get("allowed") or PRESETS.get(ev.get("key", ""), {}).get("allowed") or []


def permitted(ev: dict, s: dict) -> bool:
    """With an allow-list: only official channels and the listed watch-party channels count."""
    al = allowed_list(ev)
    if not al or s.get("vid") in PRESETS.get(ev.get("key", ""), {}).get("videos_extra", []):
        return True
    ch = s.get("channel", "").lower()
    if any(o and o in ch for o in ev.get("official", [])) or (s.get("channel_id") or "").lower() in ev.get("official", []):
        return True
    n = _norm(s.get("channel", ""))
    return any(_norm(a) in n for a in al)


def relevant(ev: dict, s: dict) -> bool:
    if not permitted(ev, s):
        return False
    if s["vid"] in ev.get("excluded", []) or (s.get("channel_id") and s["channel_id"] in ev.get("excluded", [])) \
            or s.get("channel", "").lower() in ev.get("excluded", []):
        return False
    if s["vid"] in ev.get("videos", []) + PRESETS.get(ev.get("key", ""), {}).get("videos_extra", []) or _forced_channel(ev, s):
        return True
    text = f"{s.get('title', '')} {s.get('channel', '')}".lower()
    return any(m in text for m in ev["match"])


def _forced_channel(ev, s) -> bool:
    chans = [c.lower().lstrip("@") for c in ev.get("channels", [])]
    return bool(s.get("channel_id") and s["channel_id"].lower() in chans) or s.get("channel", "").lower() in chans


def kind_of(ev: dict, s: dict) -> str:
    ch = s.get("channel", "").lower()
    if any(o and o in ch for o in ev.get("official", [])) or (s.get("channel_id") or "").lower() in ev.get("official", []):
        return "official"
    if allowed_list(ev) or WATCH_PARTY.search(s.get("title", "")):
        return "watch party"
    return "community"


# ---------- one poll ----------

_ITV = {"clientName": "WEB", "clientVersion": "2.20251001.00.00", "hl": "en", "gl": "IN"}
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) "
       "Version/17.0 Safari/605.1.15")
_http = requests.Session()


def count_live(vid: str):
    """Current concurrent viewers from YouTube's live counter (what the player shows). None if not live.
    Raises if it can't be read (then the caller falls back to reading the page)."""
    r = _http.post("https://www.youtube.com/youtubei/v1/updated_metadata?prettyPrint=false",
                   json={"context": {"client": _ITV}, "videoId": vid},
                   headers={"User-Agent": _UA, "Content-Type": "application/json", "Origin": "https://www.youtube.com"},
                   timeout=6)
    r.raise_for_status()
    found = []

    def walk(o):
        if isinstance(o, dict):
            if "videoViewCountRenderer" in o:
                found.append(o["videoViewCountRenderer"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(r.json())
    for vc in found:
        txt = (vc.get("viewCount") or {}).get("simpleText") or "".join(
            x.get("text", "") for x in (vc.get("viewCount") or {}).get("runs", []))
        # Only "N watching" is a live concurrent count. After a stream ends YouTube shows "N views" and
        # originalViewCount becomes TOTAL views (that's how 2.3M got in), so anything else = not live.
        if vc.get("isLive") is False or "watching" not in txt.lower():
            return None
        digits = re.sub(r"[^\d]", "", txt)
        raw = vc.get("originalViewCount")
        if raw is not None and str(raw).isdigit() and digits and abs(int(raw) - int(digits)) <= max(1000, int(digits) * .1):
            return int(raw)
        return int(digits) if digits else 0
    raise ValueError("no live counter in response")


def _count_one(vid: str):
    try:
        n = count_live(vid)
        return vid, n, "YouTube live counter"
    except Exception:
        try:
            s = check_video(vid)
            return vid, (s["viewers"] if s else None), "watch page (slower)"
        except Exception:
            return vid, "err", ""


_fast_pool = ThreadPoolExecutor(max_workers=12)


def fast_tick(ev: dict, now: float = None) -> dict:
    """Re-count every live stream from its own live counter and record one total. Big streams every FAST_SEC,
    tiny ones every MINOR_SEC. Returns {'total', 'live'} or {} if nothing is known to be live."""
    key = ev["key"]
    now = now or time.time()
    live = {v: x for v, x in _LIVE.get(key, {}).items() if permitted(ev, x)}
    if not live:
        return {}
    fast = _FAST.setdefault(key, {})
    due = []
    for vid, st in live.items():
        f = fast.get(vid)
        big = (f["viewers"] if f else st.get("viewers", 0)) >= MINOR_VIEWERS or st.get("kind") == "official"
        if not f or now - f["ts"] >= (FAST_SEC if big else MINOR_SEC):
            due.append(vid)
    methods, errs, anomalies = [], 0, []
    for vid, n, how in _fast_pool.map(_count_one, due):
        if n == "err":
            _FASTSTATE["errors"] += 1
            errs += 1
            continue
        if n is None:
            f = fast.setdefault(vid, {"viewers": 0, "ts": now, "misses": 0})
            f["misses"] += 1
            if f["misses"] >= 3:          # ended
                _ENDED[vid] = now
                live.pop(vid, None)
                _LIVE.get(key, {}).pop(vid, None)
                fast.pop(vid, None)
            continue
        f = fast.get(vid)
        base = f["viewers"] if f else live.get(vid, {}).get("viewers", 0)
        if (base >= 500 and n > base * 2.5) or (base > 0 and n >= 20000 and n > base * 2.5):
            # impossible jump in a few seconds: almost always the stream ending and the counter turning into total views
            f = fast.setdefault(vid, {"viewers": base, "ts": now, "misses": 0})
            f["misses"] += 1
            if f["misses"] >= 3:
                _ENDED[vid] = now
                live.pop(vid, None)
                _LIVE.get(key, {}).pop(vid, None)
                fast.pop(vid, None)
            continue
        if f and not f.get("misses") and now - f["ts"] <= 15 and f["viewers"]:
            d = n - f["viewers"]
            if abs(d) >= ANOM_MIN and abs(d) >= f["viewers"] * ANOM_PCT:   # sudden bulk jump or drop
                anomalies.append((key, int(now), vid, live.get(vid, {}).get("channel", ""), live.get(vid, {}).get("kind", ""),
                                  f["viewers"], n, d, round(100 * d / f["viewers"], 1), int(now - f["ts"])))
        fast[vid] = {"viewers": n, "ts": now, "misses": 0}
        methods.append(how)
    if methods:
        _FASTSTATE.update(method=max(set(methods), key=methods.count), ok_ts=now)
    # if YouTube starts refusing (rate limit), slow down automatically; speed back up once it's fine
    if due and errs > len(due) // 2:
        _FASTSTATE["slow"] = min(_FASTSTATE.get("slow", 0) + 1, 3)
    elif due and not errs:
        _FASTSTATE["slow"] = max(_FASTSTATE.get("slow", 0) - 1, 0)
    rows = []
    for vid, st in live.items():
        f = fast.get(vid)
        if f and f["misses"]:
            v = 0                      # its counter says it's not live (ended or about to be dropped)
        else:
            v = f["viewers"] if f and now - f["ts"] < MINOR_SEC * 3 else st.get("viewers", 0)
        rows.append({**st, "viewers": v})
    if not rows:
        return {}
    total = sum(r["viewers"] for r in rows)
    by = {k: sum(r["viewers"] for r in rows if r["kind"] == k) for k in ("official", "watch party", "community")}
    if by["official"] <= 0:
        return {"total": total, "live": len(rows), "official_live": False}   # only record while the official broadcast is live
    if anomalies:
        with store._lock:
            c = _db()
            c.executemany("INSERT INTO ev_anomalies VALUES (?,?,?,?,?,?,?,?,?,?)", anomalies)
            c.commit()
    hist = _HIST.setdefault(key, {})
    for r in rows:
        if r["viewers"] > 0:
            hist.setdefault(r["vid"], deque(maxlen=5400)).append((int(now), r["viewers"]))
    write_samples = now - store.kv_get(f"event_last_sample:{key}", 0) >= SAMPLE_EVERY
    with store._lock:
        c = _db()
        c.execute("INSERT OR REPLACE INTO ev_ticks VALUES (?,?,?,?,?,?,?)",
                  (key, int(now), total, len(rows), by["official"], by["watch party"],
                   by["community"]))
        for r in rows:
            c.execute("""UPDATE ev_streams SET last_seen=?, peak_at=CASE WHEN ? > peak THEN ? ELSE peak_at END,
                         peak=MAX(peak, ?) WHERE event=? AND vid=?""",
                      (now, r["viewers"], now, r["viewers"], key, r["vid"]))
        if write_samples:
            c.executemany("INSERT INTO ev_samples VALUES (?,?,?,?)", [(key, int(now), r["vid"], r["viewers"]) for r in rows])
        c.commit()
    if write_samples:
        store.kv_set(f"event_last_sample:{key}", now)
    best = store.kv_get(f"event_peak_break:{key}") or {}
    if total > best.get("total", -1):  # remember exactly who made up the peak
        store.kv_set(f"event_peak_break:{key}", {"ts": int(now), "total": total, "streams": sorted(
            [{"vid": r["vid"], "viewers": r["viewers"], "channel": r.get("channel", ""), "title": r.get("title", ""),
              "kind": r["kind"]} for r in rows if r["viewers"] > 0], key=lambda x: -x["viewers"])})
    return {"total": total, "live": len(rows), "official_live": True}


def repair(key: str) -> dict:
    """One-time cleanup: drop readings where an ended stream's TOTAL views were counted as viewers, and every
    reading taken while the official broadcast wasn't live. Then recompute each stream's peak."""
    with store._lock:
        c = _db()
        rows = c.execute("SELECT rowid, ts, vid, viewers FROM ev_samples WHERE event=? ORDER BY vid, ts", (key,)).fetchall()
        kinds = dict(c.execute("SELECT vid, kind FROM ev_streams WHERE event=?", (key,)).fetchall())
        bad, badv, prev, run = [], {}, {}, {}
        since_fast = 1791713000   # live-counter era (11 Oct 2026); older search-based counts often repeat while live

        def mark(rid, vid, ts, v):
            bad.append(rid)
            badv.setdefault(vid, []).append((ts, v))
        last_ts = {}
        for rid, ts, vid, v in rows:
            p = prev.get(vid)
            gap = ts - last_ts.get(vid, ts)
            last_ts[vid] = ts
            if p is not None and v >= 20000 and v > max(p, 1) * 2.5 and gap <= 180:   # jump = total views after the stream ended
                mark(rid, vid, ts, v)
                continue
            # a live count always moves; the same big number 4+ readings in a row is a finished video's view count
            r = run.get(vid)
            if r and r["v"] == v and v >= 1000 and ts >= since_fast:
                r["items"].append((rid, ts))
                if len(r["items"]) == 4:
                    for x in r["items"]:
                        mark(x[0], vid, x[1], v)
                elif len(r["items"]) > 4:
                    mark(rid, vid, ts, v)
                continue
            run[vid] = {"v": v, "items": [(rid, ts)]}
            prev[vid] = v
        badset = set(bad)
        good = {}
        for rid, ts, vid, v in rows:
            if rid not in badset:
                good.setdefault(vid, []).append(ts)
        for i in range(0, len(bad), 500):
            c.execute(f"DELETE FROM ev_samples WHERE rowid IN ({','.join('?' * len(bad[i:i + 500]))})", bad[i:i + 500])
        # take those bogus numbers back out of the totals recorded at the same moments
        col = {"official": "official", "watch party": "watch", "community": "community"}
        fixed = 0
        for vid, pts in badv.items():
            k = col.get(kinds.get(vid, "community"), "community")
            pts.sort()
            for tid, tts in c.execute("SELECT rowid, ts FROM ev_ticks WHERE event=? AND ts BETWEEN ? AND ?",
                                      (key, pts[0][0] - 35, pts[-1][0] + 35)).fetchall():
                near = min(pts, key=lambda q: abs(q[0] - tts))
                good_near = min((abs(g - tts) for g in good.get(vid, [])), default=10 ** 9)
                if abs(near[0] - tts) <= 35 and abs(near[0] - tts) < good_near:   # this moment's reading was the bogus one
                    c.execute(f"UPDATE ev_ticks SET total=MAX(0,total-?), {k}=MAX(0,{k}-?), live=MAX(0,live-1) WHERE rowid=?",
                              (near[1], near[1], tid))
                    fixed += 1
        dropped = 0
        dropped += c.execute("DELETE FROM ev_ticks WHERE event=? AND official<=0", (key,)).rowcount
        # single readings far above their neighbours (a counter blip between two per-stream samples)
        tk = c.execute("SELECT rowid, ts, total FROM ev_ticks WHERE event=? ORDER BY ts", (key,)).fetchall()
        spikes, j0 = [], 0
        for i, (rid, ts, tot) in enumerate(tk):
            while tk[j0][1] < ts - 60:
                j0 += 1
            near = []
            j = j0
            while j < len(tk) and tk[j][1] <= ts + 60:
                if j != i:
                    near.append(tk[j][2])
                j += 1
            if len(near) >= 4:
                near.sort()
                med = near[len(near) // 2]
                if tot > med * 1.6 and tot - med > 20000:
                    spikes.append(rid)
        for i in range(0, len(spikes), 500):
            c.execute(f"DELETE FROM ev_ticks WHERE rowid IN ({','.join('?' * len(spikes[i:i + 500]))})", spikes[i:i + 500])
        dropped += len(spikes)
        # samples taken when no official reading exists close by
        c.execute("""DELETE FROM ev_samples WHERE event=? AND NOT EXISTS (SELECT 1 FROM ev_ticks t WHERE t.event=ev_samples.event
                     AND t.ts BETWEEN ev_samples.ts - 40 AND ev_samples.ts + 40)""", (key,))
        c.execute("UPDATE ev_streams SET peak=0 WHERE event=?", (key,))
        c.execute("""UPDATE ev_streams SET peak=(SELECT MAX(viewers) FROM ev_samples s WHERE s.event=ev_streams.event AND s.vid=ev_streams.vid),
                     peak_at=(SELECT ts FROM ev_samples s WHERE s.event=ev_streams.event AND s.vid=ev_streams.vid ORDER BY viewers DESC LIMIT 1)
                     WHERE event=? AND EXISTS (SELECT 1 FROM ev_samples s WHERE s.event=ev_streams.event AND s.vid=ev_streams.vid)""", (key,))
        c.commit()
    store.kv_set(f"event_peak_break:{key}", {})
    return {"bad_samples": len(bad), "totals_fixed": fixed, "readings_without_official_dropped": dropped}


def purge_unpermitted(key: str) -> dict:
    ev = get(key)
    if not ev or not allowed_list(ev):
        return {}
    with store._lock:
        c = _db()
        streams = c.execute("SELECT vid, channel, channel_id, kind FROM ev_streams WHERE event=?", (key,)).fetchall()
        bad = {r[0]: r[3] for r in streams if not permitted(ev, {"vid": r[0], "channel": r[1], "channel_id": r[2]})}
        col = {"official": "official", "watch party": "watch", "community": "community"}
        fixed = 0
        for vid, kind in bad.items():
            pts = c.execute("SELECT ts, viewers FROM ev_samples WHERE event=? AND vid=? ORDER BY ts", (key, vid)).fetchall()
            if not pts:
                continue
            k = col.get(kind, "community")
            for tid, tts in c.execute("SELECT rowid, ts FROM ev_ticks WHERE event=? AND ts BETWEEN ? AND ?",
                                      (key, pts[0][0] - 35, pts[-1][0] + 35)).fetchall():
                near = min(pts, key=lambda q: abs(q[0] - tts))
                if abs(near[0] - tts) <= 35 and near[1] > 0:
                    c.execute(f"UPDATE ev_ticks SET total=MAX(0,total-?), {k}=MAX(0,{k}-?), live=MAX(0,live-1) WHERE rowid=?",
                              (near[1], near[1], tid))
                    fixed += 1
        for vid in bad:
            c.execute("DELETE FROM ev_samples WHERE event=? AND vid=?", (key, vid))
            c.execute("DELETE FROM ev_streams WHERE event=? AND vid=?", (key, vid))
        # the permitted ones are watch parties
        for r in streams:
            if r[0] not in bad and r[3] == "community":
                c.execute("UPDATE ev_streams SET kind='watch party' WHERE event=? AND vid=?", (key, r[0]))
        c.execute("UPDATE ev_ticks SET watch=watch+community, community=0 WHERE event=? AND community>0", (key,))
        c.commit()
    store.kv_set(f"event_peak_break:{key}", {})
    return {"removed_streams": len(bad), "totals_fixed": fixed}


def repair_once():
    for k, ev in events().items():
        flag = f"event_repair_v2:{k}"
        if not store.kv_get(flag):
            try:
                print(f"Event {k} cleanup: {repair(k)}")
            except Exception as e:
                print(f"Event {k} cleanup failed: {str(e)[:150]}")
            store.kv_set(flag, True)
        flag = f"event_allow_v1:{k}"
        if not store.kv_get(flag):
            try:
                print(f"Event {k} allow-list cleanup: {purge_unpermitted(k)}")
            except Exception as e:
                print(f"Event {k} allow-list cleanup failed: {str(e)[:150]}")
            store.kv_set(flag, True)


def fast_healthy() -> bool:
    return time.time() - _FASTSTATE["ok_ts"] < max(FAST_SEC * 2 ** _FASTSTATE.get("slow", 0) * 5, 20)


def run_fast_forever():
    """Background thread: live counters for every active event."""
    repair_once()
    last_log = 0
    while True:
        if time.time() - last_log > 60:
            last_log = time.time()
            try:
                from core import eventlog
                for ev in events().values():
                    if ev.get("active"):
                        eventlog.check(ev)
            except Exception as e:
                print(f"Event log failed: {str(e)[:150]}")
        t0 = time.time()
        for ev in events().values():
            if ev.get("active") and _LIVE.get(ev["key"]):
                try:
                    fast_tick(ev)
                except Exception as e:
                    print(f"Live counter failed for {ev['key']}: {str(e)[:150]}")
        time.sleep(max(0.3, FAST_SEC * 2 ** _FASTSTATE.get("slow", 0) - (time.time() - t0)))


def poll(ev: dict, now: int = None) -> dict:
    """Find live streams, record viewers. Returns {'total', 'live', 'streams': [...]}."""
    now = now or int(time.time())
    found = {}
    errors = 0
    for q in ev["queries"][:8]:
        try:
            for s in search_live(q):
                if relevant(ev, s) and s["viewers"] >= found.get(s["vid"], {}).get("viewers", -1):
                    found[s["vid"]] = s
        except Exception as e:
            errors += 1
            print(f"Event search '{q}' failed: {str(e)[:120]}")
    chans = list(dict.fromkeys(ev.get("channels", []) + PRESETS.get(ev["key"], {}).get("always_check", [])))[:40]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for s in pool.map(check_channel, chans):
            if s and s["vid"] not in found and relevant(ev, s):
                found[s["vid"]] = s
    with store._lock:
        c = _db()
        recent = [dict(r) for r in c.execute(
            "SELECT vid, channel, channel_id, title FROM ev_streams WHERE event=? AND last_seen>?",
            (ev["key"], now - RECHECK_MIN * 60))]
    api = {}
    vids = ev.get("videos", []) + PRESETS.get(ev["key"], {}).get("videos_extra", [])
    known = list({*found, *[r["vid"] for r in recent], *vids})
    try:
        api = api_counts(known)
    except Exception as e:
        print(f"YouTube API failed: {str(e)[:120]}")
    if api:
        for r in recent:
            v = api.get(r["vid"])
            if v is not None and r["vid"] not in found:
                found[r["vid"]] = {**r, "viewers": v}
        for vid, v in api.items():
            if vid in found:
                if v is None:
                    found.pop(vid)          # API says it ended
                else:
                    found[vid]["viewers"] = v
    else:
        missing = [r["vid"] for r in recent if r["vid"] not in found][:MAX_DIRECT_CHECKS]
        missing += [v for v in vids if v not in found and v not in missing]
        if missing:
            with ThreadPoolExecutor(max_workers=6) as pool:
                for s in pool.map(lambda v: _safe(check_video, v), missing):
                    if s:
                        found[s["vid"]] = s
    for vid in [v for v in found if time.time() - _ENDED.get(v, 0) < 900]:
        found.pop(vid)                       # the live counter already saw these end
    streams = []
    fast = _FAST.get(ev["key"], {})
    for s in found.values():
        s["kind"] = kind_of(ev, s)
        f = fast.get(s["vid"])
        if f and now - f["ts"] < MINOR_SEC * 3:
            s["viewers"] = f["viewers"]      # the live counter is fresher than search results
        streams.append(s)
    _LIVE[ev["key"]] = {s["vid"]: s for s in streams}
    total = sum(s["viewers"] for s in streams)
    by = {k: sum(s["viewers"] for s in streams if s["kind"] == k) for k in ("official", "watch party", "community")}
    official_live = by["official"] > 0
    with store._lock:
        c = _db()
        for s in streams:
            c.execute("""INSERT INTO ev_streams (event, vid, channel, channel_id, title, kind, first_seen, last_seen,
                         peak, peak_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(event, vid) DO UPDATE SET last_seen=excluded.last_seen, title=excluded.title,
                         kind=excluded.kind,
                         peak_at=CASE WHEN excluded.peak > ev_streams.peak THEN excluded.peak_at ELSE ev_streams.peak_at END,
                         peak=MAX(ev_streams.peak, excluded.peak)""",
                      (ev["key"], s["vid"], s["channel"], s["channel_id"], s["title"], s["kind"], now, now,
                       s["viewers"] if official_live else 0, now))
        record = official_live and not fast_healthy()  # live counter records while it works; nothing when official is off
        if record:
            c.executemany("INSERT INTO ev_samples VALUES (?,?,?,?)", [(ev["key"], now, s["vid"], s["viewers"]) for s in streams])
        if record and (streams or errors < len(ev["queries"][:8])):  # never a fake zero
            c.execute("INSERT OR REPLACE INTO ev_ticks VALUES (?,?,?,?,?,?,?)",
                      (ev["key"], now, total, len(streams), by["official"], by["watch party"], by["community"]))
        c.commit()
    store.kv_set(f"event_last_poll:{ev['key']}", now)
    return {"total": total, "live": len(streams), "streams": sorted(streams, key=lambda s: -s["viewers"])}


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


def run_all():
    """Scheduler job: poll every active event."""
    for ev in events().values():
        if ev.get("active"):
            try:
                poll(ev)
            except Exception as e:
                print(f"Event {ev['key']} poll failed: {str(e)[:200]}")


# ---------- numbers ----------

def stats(key: str, since: float = 0, until: float = None) -> dict:
    """Peak, average, hours watched, airtime, by kind, by day, by channel, live now."""
    until = until or time.time() + 1
    with store._lock:
        c = _db()
        ticks = [dict(r) for r in c.execute("SELECT * FROM ev_ticks WHERE event=? AND ts>=? AND ts<=? ORDER BY ts",
                                             (key, since, until))]
        samples = [dict(r) for r in c.execute(
            "SELECT s.ts, s.vid, s.viewers, t.channel, t.title, t.kind, t.channel_id FROM ev_samples s JOIN ev_streams t "
            "ON t.event=s.event AND t.vid=s.vid WHERE s.event=? AND s.ts>=? AND s.ts<=? ORDER BY s.ts",
            (key, since, until))]
    out = {"ticks": len(ticks)}
    if not ticks:
        return out
    gap_cap = POLL_SEC * 3
    hw, air = 0.0, 0
    for i, t in enumerate(ticks):
        dt = min((ticks[i + 1]["ts"] - t["ts"]) if i + 1 < len(ticks) else POLL_SEC, gap_cap)
        if t["live"] > 0:
            hw += t["total"] * dt / 3600
            air += dt
    peak = max(ticks, key=lambda t: t["total"])
    out.update(peak=peak["total"], peak_at=peak["ts"], peak_split={k: peak[k] for k in ("official", "watch", "community")},
               hours_watched=hw, airtime_h=air / 3600, avg=(hw / (air / 3600)) if air else 0,
               last=ticks[-1], first_ts=ticks[0]["ts"])
    # per stream
    per = {}
    times = sorted({s["ts"] for s in samples})
    nxt = {t: min((times[i + 1] - t) if i + 1 < len(times) else POLL_SEC, gap_cap) for i, t in enumerate(times)}
    for s in samples:
        p = per.setdefault(s["vid"], {"vid": s["vid"], "channel": s["channel"], "title": s["title"], "kind": s["kind"],
                                      "peak": 0, "hw": 0.0, "air": 0})
        p["peak"] = max(p["peak"], s["viewers"])
        p["hw"] += s["viewers"] * nxt[s["ts"]] / 3600
        p["air"] += nxt[s["ts"]]
    chans = {}
    for p in per.values():
        ch = chans.setdefault(p["channel"], {"channel": p["channel"], "kind": p["kind"], "peak": 0, "hw": 0.0,
                                             "streams": 0, "air": 0})
        if p["hw"] >= ch.get("best_hw", -1):
            ch["best_hw"], ch["url"], ch["title"] = p["hw"], yt_link(p["vid"]), p["title"]
        ch["peak"] = max(ch["peak"], p["peak"])
        ch["hw"] += p["hw"]
        ch["streams"] += 1
        ch["air"] += p["air"]
    for ch in chans.values():
        ch["avg"] = ch["hw"] / (ch["air"] / 3600) if ch["air"] else 0
    out["channels"] = sorted(chans.values(), key=lambda c: -c["hw"])
    out["by_kind_hw"] = {k: sum(c["hw"] for c in chans.values() if c["kind"] == k)
                         for k in ("official", "watch party", "community")}
    # per day (event's local time)
    days, dayname = {}, {}

    def tday(t):   # one date conversion per half hour (IST is +5:30), not per 2s reading
        h = int(t["ts"]) // 1800
        if h not in dayname:
            dayname[h] = datetime.fromtimestamp(h * 1800, REPORT_TZ).strftime("%a %d %b")
        return dayname[h]
    for i, t in enumerate(ticks):
        d = tday(t)
        dd = days.setdefault(d, {"day": d, "peak": 0, "hw": 0.0, "air": 0})
        dt = min((ticks[i + 1]["ts"] - t["ts"]) if i + 1 < len(ticks) else POLL_SEC, gap_cap)
        dd["peak"] = max(dd["peak"], t["total"])
        if t["live"]:
            dd["hw"] += t["total"] * dt / 3600
            dd["air"] += dt
    for dd in days.values():
        dd["avg"] = dd["hw"] / (dd["air"] / 3600) if dd["air"] else 0
    out["days"] = list(days.values())
    # live now (last tick, if recent)
    last_ts = ticks[-1]["ts"]
    live_now = [s for s in samples if s["ts"] == last_ts] if time.time() - last_ts < POLL_SEC * 3 else []
    out["live_now"] = sorted((s for s in live_now if s["viewers"] > 0), key=lambda s: -s["viewers"])  # 0 = nobody watching
    # concurrent-viewer view: who made up the peak, each stream's own peak, averages while the official stream was on
    brk = store.kv_get(f"event_peak_break:{key}") or {}
    if brk.get("total") == peak["total"]:
        out["at_peak"] = brk["streams"]
    else:
        near = min({s["ts"] for s in samples} or {peak["ts"]}, key=lambda t: abs(t - peak["ts"]))
        out["at_peak"] = sorted((s for s in samples if s["ts"] == near), key=lambda s: -s["viewers"])
    fl = _FAST.get(key, {})
    if _LIVE.get(key) and fast_healthy():
        out["live_now"] = sorted(({**st, "viewers": fl[v]["viewers"]} for v, st in _LIVE[key].items()
                                  if v in fl and fl[v]["viewers"] > 0), key=lambda s: -s["viewers"])
    evx = get(key)
    if evx:
        out["live_now"] = [x for x in out["live_now"] if permitted(evx, x)]
    recent = time.time() - ticks[-1]["ts"] < 90 and not (_LIVE.get(key) and fast_healthy())
    if not out["live_now"] and recent:   # between per-stream saves: use each stream's latest saved reading
        lastv = {}
        for x in samples:
            if x["ts"] >= ticks[-1]["ts"] - 120:
                lastv[x["vid"]] = x
        out["live_now"] = sorted((x for x in lastv.values() if x["viewers"] > 0 and (not evx or permitted(evx, x))),
                                 key=lambda x: -x["viewers"])
    out["official_live"] = (recent and ticks[-1]["official"] > 0) or any(x["kind"] == "official" for x in out["live_now"])
    if not out["official_live"]:
        out["live_now"] = []          # only show streams while the official broadcast is on
    # broadcasts: runs of readings with no gap over 1 hour (restarts leave short gaps) (readings only exist while official was live)
    sess, cur = [], None
    for t in ticks:
        if cur and t["ts"] - cur["end"] <= 3600:
            cur["end"] = t["ts"]
            if t["total"] > cur["peak"]:
                cur.update(peak=t["total"], peak_at=t["ts"], split={k: t[k] for k in ("official", "watch", "community")})
        else:
            cur = {"start": t["ts"], "end": t["ts"], "peak": t["total"], "peak_at": t["ts"],
                   "split": {k: t[k] for k in ("official", "watch", "community")}}
            sess.append(cur)
    if sess:
        ls = dict(sess[-1])
        per, sums = {}, {}
        for x in samples:
            if ls["start"] - 60 <= x["ts"] <= ls["end"] + 60 and x["viewers"] > 0:
                a = sums.setdefault(x["vid"], [0, 0])
                a[0] += x["viewers"]
                a[1] += 1
            if ls["start"] - 60 <= x["ts"] <= ls["end"] + 60 and x["viewers"] > per.get(x["vid"], {}).get("peak", 0):
                per[x["vid"]] = {"vid": x["vid"], "channel": x["channel"], "title": x["title"], "kind": x["kind"],
                                 "channel_id": x.get("channel_id") or "",
                                 "peak": x["viewers"], "peak_at": x["ts"]}
        for v, p_ in per.items():
            p_["avg"] = round(sums[v][0] / sums[v][1]) if v in sums else 0
        ls["streams"] = sorted(per.values(), key=lambda p: -p["peak"])
        bt = [t for t in ticks if ls["start"] <= t["ts"] <= ls["end"]]
        hw = air = 0.0
        for i, t in enumerate(bt):
            dt = min((bt[i + 1]["ts"] - t["ts"]) if i + 1 < len(bt) else POLL_SEC, gap_cap)
            hw += t["total"] * dt
            air += dt
        ls["avg"] = hw / air if air else 0
        ls["peak_official"] = max((t["official"] for t in bt), default=0)
        ls["peak_watch"] = max((t["watch"] for t in bt), default=0)
        out["last_broadcast"] = ls
    out["method"] = (f"{_FASTSTATE['method']}, every {FAST_SEC * 2 ** _FASTSTATE.get('slow', 0):g}s" if fast_healthy()
                     else f"search results, every {POLL_SEC}s")
    with store._lock:
        out["stream_peaks"] = [dict(r) for r in _db().execute(
            "SELECT vid, channel, title, kind, peak, peak_at FROM ev_streams WHERE event=? AND peak>0 ORDER BY peak DESC",
            (key,))]
    bc = [(t, min((ticks[i + 1]["ts"] - t["ts"]) if i + 1 < len(ticks) else POLL_SEC, gap_cap))
          for i, t in enumerate(ticks) if t["official"] > 0]
    secs = sum(dt for _, dt in bc)
    out["avg_broadcast"] = sum(t["total"] * dt for t, dt in bc) / secs if secs else out["avg"]
    out["avg_official"] = sum(t["official"] * dt for t, dt in bc) / secs if secs else 0
    out["peak_official"] = max((t["official"] for t in ticks), default=0)
    out["peak_watch"] = max((t["watch"] for t in ticks), default=0)
    for d in out["days"]:
        day_bc = [(t, dt) for t, dt in bc if tday(t) == d["day"]]
        ds = sum(dt for _, dt in day_bc)
        d["avg_broadcast"] = sum(t["total"] * dt for t, dt in day_bc) / ds if ds else d["avg"]
        day_ticks = [t for t in ticks if tday(t) == d["day"]]
        top = max(day_ticks, key=lambda t: t["total"]) if day_ticks else None
        d["peak_at"] = top["ts"] if top else None
        d["split"] = {k: top[k] for k in ("official", "watch")} if top else {"official": 0, "watch": 0}
    out["series"] = [(t["ts"], t["total"], t["official"], t["watch"], t["community"]) for t in ticks]
    return out


_AV_BUSY = set()


def avatar(cid: str) -> str:
    """Channel logo URL (cached). Unknown ones are fetched in the background."""
    if not cid:
        return ""
    u = store.kv_get(f"ev_avatar:{cid}")
    if u is None and cid not in _AV_BUSY:
        _AV_BUSY.add(cid)

        def fetch():
            try:
                r = _http.get(f"https://www.youtube.com/channel/{cid}", headers={"User-Agent": _UA, "Accept-Language": "en"}, timeout=10)
                m = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
                store.kv_set(f"ev_avatar:{cid}", re.sub(r"=s\d+.*$", "=s88-c-k-c0x00ffffff-no-rj", m.group(1)) if m else "")
            except Exception:
                pass
            _AV_BUSY.discard(cid)
        _fast_pool.submit(fetch)
    return u or ""


def stream_series(key: str, vids: list, t0: float, t1: float, limit: int = 600) -> dict:
    """Per-stream viewer history (stored every ~30s) for the given streams."""
    if not vids:
        return {}
    with store._lock:
        rows = _db().execute(f"SELECT vid, ts, viewers FROM ev_samples WHERE event=? AND ts BETWEEN ? AND ? "
                             f"AND vid IN ({','.join('?' * len(vids))}) ORDER BY ts", (key, t0, t1, *vids)).fetchall()
    out = {}
    for vid, ts, v in rows:
        out.setdefault(vid, []).append([ts, v])
    for vid, pts in out.items():
        step = max(1, len(pts) // limit)
        out[vid] = pts[::step] + (pts[-1:] if (len(pts) - 1) % step else [])
    return out


def stream_tail(key: str, vids: list, n: int = 90) -> dict:
    h = _HIST.get(key, {})
    return {v: [list(x) for x in list(h[v])[-n:]] for v in vids if v in h}


ROSTER = [  # (match token, display name, channel handle) of the permitted watch-party streamers
    ("dynamo", "Dynamo Gaming", "@DynamoGaming"), ("bixi", "Bixi", "@TheBixiOP"), ("zgod", "ZGOD Gaming", "@ZGODGAMING"),
    ("neyoo", "Neyoo Gaming", "@NEYOOGAMINGYT"), ("mizo", "Mizo Plays", "@MizoPlays"), ("mrspike", "Mr Spike", "@MrSpike"),
    ("lolzz", "LoLzZz Gaming", "@LoLzZzGaming"), ("sharkshe", "Sharkshe", "@SHARKSHE"), ("mafianinja", "Mafia Ninja", "@MafiaNinja"),
    ("ruthless", "Im Ruthless", "@ImRuthlessceopubg"), ("rakazone", "RakaZone Gaming", "@RakaZoneGaming"), ("ansh", "Ansh YT", "@AnshYT"),
    ("casetoo", "Casetoo", "@casetooop"), ("sheek", "Sheek Gaming", "@sheekgaming"), ("ipreeet", "iPreeet", "@IPREEET.69"),
    ("shreeman", "Shreeman Legend", "@ShreemanLegend"), ("mortal", "MortaL", "@MortaLyt"), ("vaadhiyaar", "Vaadhiyaar", "channel/UC1ihHXPtRojN6ZBTjm1Sjog"),
    ("regaltos", "Soul Regaltos", "@soulregaltos9810"), ("snax", "Snax Gaming", "@SnaxGaming"), ("sriop", "SRI OP", "@sriop-sr70"),
    ("mayur", "Mayur Gaming", "@MayurGaming"), ("neonxpawan", "Neon X Pawan", "@NEONXPAWANOP"),
    ("ladypredator", "Lady Predator", "@LadyPredatorGaming"), ("soulaman", "Soul Aman", "@SoulAman")]
_RBUSY = set()


def channel_card(handle: str) -> dict:
    """{name, logo} for a channel handle (cached; fetched in the background the first time)."""
    if not handle:
        return {}
    v = store.kv_get(f"ev_rcard:{handle}")
    if v is None and handle not in _RBUSY:
        _RBUSY.add(handle)

        def fetch():
            try:
                r = _http.get(f"https://www.youtube.com/{handle}", headers={"User-Agent": _UA, "Accept-Language": "en"}, timeout=10)
                img = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
                name = re.search(r'<meta property="og:title" content="([^"]+)"', r.text)
                store.kv_set(f"ev_rcard:{handle}", {
                    "logo": re.sub(r"=s\d+.*$", "=s88-c-k-c0x00ffffff-no-rj", img.group(1)) if img else "",
                    "name": name.group(1).replace("&amp;", "&") if name else ""})
            except Exception:
                pass
            _RBUSY.discard(handle)
        _fast_pool.submit(fetch)
    return v or {}


def next_start(key: str):
    """Next scheduled official start (epoch) if it's in the future: set with /event next, else the preset."""
    v = store.kv_get(f"event_next:{key}") or PRESETS.get(key, {}).get("next_start")
    if not v:
        return None
    try:
        ts = datetime.strptime(v, "%Y-%m-%d %H:%M").replace(tzinfo=REPORT_TZ).timestamp() if isinstance(v, str) else float(v)
    except ValueError:
        return None
    return ts if ts > time.time() else None


def fmt_n(n) -> str:
    n = float(n or 0)
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e4:
        return f"{n / 1e3:.1f}K"
    return f"{int(round(n)):,}"


def _when(ts) -> str:
    return datetime.fromtimestamp(ts, REPORT_TZ).strftime("%a %d %b, %I:%M %p IST")


def summary(key: str = None, top: int = 10) -> str:
    ev = get(key)
    if not ev:
        return "No event is being tracked. Start one with /event start bmsd"
    st = stats(ev["key"])
    if not st.get("ticks"):
        return (f"{ev['name']}: tracking, but no data yet. The first numbers appear within {POLL_SEC}s of a "
                "live stream being found.")
    lines = [f"{ev['name']}: concurrent viewers (YouTube, all streams)"]
    if st["live_now"]:
        lines.append(f"\nLIVE NOW: {fmt_n(sum(s['viewers'] for s in st['live_now']))} viewers across "
                     f"{len(st['live_now'])} streams")
        for s in st["live_now"]:
            lines.append(f"  {fmt_n(s['viewers'])}  {s['channel']} ({s['kind']})\n     {yt_link(s['vid'])}")
    else:
        lines.append("\nOfficial broadcast is offline (numbers are recorded only while it's live).")
        lb = st.get("last_broadcast")
        if lb:
            lines.append(f"\nLAST BROADCAST ({_when(lb['start'])} to {datetime.fromtimestamp(lb['end'], REPORT_TZ).strftime('%I:%M %p')}):"
                         f"\n  peak {fmt_n(lb['peak'])} concurrent at {_when(lb['peak_at'])}")
            for x in lb["streams"][:8]:
                lines.append(f"  {fmt_n(x['peak'])}  {x['channel']} ({x['kind']})\n     {yt_link(x['vid'])}")
    sp = st["peak_split"]
    lines += [f"\nPEAK CONCURRENT: {fmt_n(st['peak'])} at {_when(st['peak_at'])}",
              f"  official {fmt_n(sp['official'])}, watch parties {fmt_n(sp['watch'])}, community {fmt_n(sp['community'])}"]
    lines += [f"\nAverage concurrent while the official broadcast was live: {fmt_n(st['avg_broadcast'])}",
              f"Official streams: peak {fmt_n(st['peak_official'])}, average {fmt_n(st['avg_official'])}",
              f"Watch parties combined: peak {fmt_n(st['peak_watch'])}"]
    if len(st["days"]) > 1:
        lines.append("\nBy day (IST): peak / average concurrent")
        lines += [f"  {d['day']}: {fmt_n(d['peak'])} / {fmt_n(d['avg_broadcast'])}" for d in st["days"]]
    lines.append(f"\nYouTube, counted from: {st.get('method')}. /event link for the live dashboard, /event chart for the graph.")
    for label, url in (ev.get("links") or {}).items():
        lines.append(f"{label}: {url}")
    return "\n".join(lines)


def tool_event_stats(name: str = "") -> str:
    """For the agent: 'what's the peak so far?'"""
    return summary(name or None, top=15)
