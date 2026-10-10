"""Live viewership tracker for one esports event across every YouTube stream (official, watch parties, community).

Two loops:
  discovery  every DISCOVER_SEC: YouTube live search for the event's phrases finds new streams (and their counts).
  counting   every FAST_SEC: re-counts every known live stream. Methods, best first:
               1. YouTube Data API (YOUTUBE_API_KEY): exact, 1 quota unit per 50 streams per check
               2. YouTube's own live-counter endpoint (what the watch page polls), no key
               3. yt-dlp page read (slowest), as a last resort
Totals are written every FAST_SEC, so short spikes are caught. YouTube itself refreshes live counts every few
seconds at most, so polling faster than ~10s adds requests, not accuracy.
"""
import json
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA, "tracker.db")
CONFIG_PATH = os.path.join(DATA, "config.json")
FAST_SEC = int(os.getenv("FAST_SEC", "10"))
DISCOVER_SEC = int(os.getenv("DISCOVER_SEC", "60"))
TZ = ZoneInfo(os.getenv("EVENT_TZ", "Asia/Kolkata"))
LIVE_FILTER = "EgJAAQ%253D%253D"
WATCH_PARTY = re.compile(r"watch\s*-?\s*party|co-?\s*stream|watch\s*-?\s*along|reaction|reacting|live\s+react", re.I)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) "
      "Version/17.0 Safari/605.1.15")
MISSES_TO_END = 3            # a stream is "ended" after this many checks in a row say it isn't live

DEFAULT_CONFIG = {
    "name": "BMSD 2026",
    "match": ["bmsd", "bgmi showdown", "battlegrounds mobile india showdown", "battlegrounds mobile showdown",
              "bgmi show down", "bm showdown"],
    "queries": ["BMSD", "BMSD 2026", "BGMI Showdown", "Battlegrounds Mobile India Showdown", "BMSD watch party"],
    "official": ["krafton india esports", "battlegrounds mobile india"],
    "channels": [], "videos": [], "excluded": [], "paused": False,
    "links": {"Esports Charts (official numbers, all platforms)":
              "https://escharts.com/tournaments/bgmi/battlegrounds-mobile-india-showdown-2026-bgmi"},
}

_lock = threading.RLock()
_live = {}        # vid -> {vid, title, channel, channel_id, kind, viewers, misses, last_ok}
_method = {"value": "", "errors": 0}


# ---------- config + storage ----------

def config() -> dict:
    os.makedirs(DATA, exist_ok=True)
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    merged = {**DEFAULT_CONFIG, **cfg}
    if merged != cfg:
        save_config(merged)
    return merged


def save_config(cfg: dict):
    os.makedirs(DATA, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def update_config(**fields):
    with _lock:
        cfg = config()
        cfg.update(fields)
        save_config(cfg)
        return cfg


_conn = None


def db():
    global _conn
    if _conn is None:
        os.makedirs(DATA, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS streams (vid TEXT PRIMARY KEY, channel TEXT, channel_id TEXT, title TEXT, kind TEXT,
            first_seen REAL, last_seen REAL, peak INTEGER DEFAULT 0, peak_at REAL, hw REAL DEFAULT 0, air REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS ticks (ts REAL PRIMARY KEY, total INTEGER, live INTEGER, official INTEGER,
            watch INTEGER, community INTEGER);
        CREATE TABLE IF NOT EXISTS samples (ts REAL, vid TEXT, viewers INTEGER);
        CREATE INDEX IF NOT EXISTS samples_vid ON samples(vid, ts);
        """)
    return _conn


# ---------- YouTube ----------

def _ydl(flat=True):
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20}
    if flat:
        opts.update(extract_flat="in_playlist", playlistend=80)
    cookies = os.path.join(BASE, "cookies.txt")
    if os.path.exists(cookies):
        opts["cookiefile"] = cookies
    return yt_dlp.YoutubeDL(opts)


def search_live(query: str) -> list:
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={LIVE_FILTER}"
    with _ydl() as y:
        info = y.extract_info(url, download=False)
    out = []
    for e in info.get("entries") or []:
        if e and e.get("live_status") == "is_live" and e.get("id"):
            out.append({"vid": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or "",
                        "channel_id": e.get("channel_id") or "", "viewers": int(e.get("concurrent_view_count") or 0)})
    return out


def check_channel(handle: str):
    h = handle.strip()
    base = (re.sub(r"/(live|streams|videos|featured)/?$", "", h.rstrip("/")) if h.startswith("http")
            else f"https://www.youtube.com/channel/{h}" if h.startswith("UC") and len(h) == 24
            else f"https://www.youtube.com/@{h.lstrip('@')}")
    try:
        with _ydl(flat=False) as y:
            i = y.extract_info(base + "/live", download=False)
    except Exception:
        return None
    if not i.get("is_live"):
        return None
    return {"vid": i["id"], "title": i.get("title") or "", "channel": i.get("channel") or "",
            "channel_id": i.get("channel_id") or "", "viewers": int(i.get("concurrent_view_count") or 0)}


def count_api(vids: list) -> dict:
    """{vid: viewers, or None if not live}. Needs YOUTUBE_API_KEY."""
    key = os.getenv("YOUTUBE_API_KEY")
    out = {}
    for i in range(0, len(vids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                         params={"part": "liveStreamingDetails", "id": ",".join(vids[i:i + 50]), "key": key},
                         timeout=10)
        r.raise_for_status()
        got = {it["id"]: it.get("liveStreamingDetails") or {} for it in r.json().get("items", [])}
        for v in vids[i:i + 50]:
            d = got.get(v)
            live = bool(d and d.get("actualStartTime") and not d.get("actualEndTime"))
            out[v] = int(d.get("concurrentViewers") or 0) if live else None
    return out


_ITV = {"clientName": "WEB", "clientVersion": "2.20251001.00.00", "hl": "en", "gl": "IN"}


def count_innertube(vid: str):
    """YouTube's live counter endpoint (what the watch page polls). viewers, None if not live; raises on error."""
    r = requests.post("https://www.youtube.com/youtubei/v1/updated_metadata?prettyPrint=false",
                      json={"context": {"client": _ITV}, "videoId": vid},
                      headers={"User-Agent": UA, "Content-Type": "application/json", "Origin": "https://www.youtube.com"},
                      timeout=8)
    r.raise_for_status()
    text = r.text
    if "updateViewershipAction" not in text:
        raise ValueError("no viewership in response")
    data = r.json()
    for a in data.get("actions", []):
        vc = (((a.get("updateViewershipAction") or {}).get("viewCount") or {}).get("videoViewCountRenderer") or {})
        if not vc:
            continue
        if vc.get("isLive") is False:
            return None
        raw = vc.get("originalViewCount")
        if raw is not None and str(raw).isdigit():
            return int(raw)
        txt = (vc.get("viewCount") or {}).get("simpleText") or "".join(
            r.get("text", "") for r in (vc.get("viewCount") or {}).get("runs", []))
        if "watching" not in txt.lower():
            return None
        digits = re.sub(r"[^\d]", "", txt)
        return int(digits) if digits else 0
    raise ValueError("no count found")


def count_ytdlp(vid: str):
    with _ydl(flat=False) as y:
        i = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    return int(i.get("concurrent_view_count") or 0) if i.get("is_live") else None


def count_all(vids: list) -> dict:
    """{vid: viewers | None (not live)}; vids that couldn't be checked are left out (keep last value)."""
    if not vids:
        return {}
    if os.getenv("YOUTUBE_API_KEY"):
        try:
            out = count_api(vids)
            _method.update(value="YouTube Data API", errors=0)
            return out
        except Exception as e:
            print(f"API count failed, falling back: {str(e)[:100]}")
    results = {}

    def one(v):
        try:
            return v, count_innertube(v), "live counter"
        except Exception:
            try:
                return v, count_ytdlp(v), "page read (slow)"
            except Exception:
                return v, "err", ""
    with ThreadPoolExecutor(max_workers=min(16, len(vids))) as pool:
        for v, n, how in pool.map(one, vids):
            if n != "err":
                results[v] = n
                _method["value"] = how
    _method["errors"] = len(vids) - len(results)
    return results


# ---------- classification ----------

def relevant(cfg, s) -> bool:
    exc = [e.lower() for e in cfg.get("excluded", [])]
    if s["vid"].lower() in exc or (s.get("channel_id") or "").lower() in exc or s.get("channel", "").lower() in exc:
        return False
    chans = [c.lower().lstrip("@") for c in cfg.get("channels", [])]
    if s["vid"] in cfg.get("videos", []) or s.get("channel", "").lower() in chans or \
            (s.get("channel_id") or "").lower() in chans:
        return True
    text = f"{s.get('title', '')} {s.get('channel', '')}".lower()
    return any(m in text for m in cfg["match"])


def kind_of(cfg, s) -> str:
    ch = s.get("channel", "").lower()
    if any(o and o in ch for o in cfg.get("official", [])) or (s.get("channel_id") or "").lower() in cfg.get("official", []):
        return "official"
    return "watch party" if WATCH_PARTY.search(s.get("title", "")) else "community"


# ---------- loops ----------

def discover():
    cfg = config()
    if cfg.get("paused"):
        return 0
    found = {}
    for q in cfg["queries"][:8]:
        try:
            for s in search_live(q):
                if relevant(cfg, s) and s["viewers"] >= found.get(s["vid"], {}).get("viewers", -1):
                    found[s["vid"]] = s
        except Exception as e:
            print(f"Search '{q}' failed: {str(e)[:120]}")
    for ch in cfg.get("channels", [])[:30]:
        s = check_channel(ch)
        if s and relevant(cfg, s):
            found.setdefault(s["vid"], s)
    for v in cfg.get("videos", []):
        if v not in found:
            found[v] = {"vid": v, "title": "", "channel": "", "channel_id": "", "viewers": 0}
    new = 0
    with _lock:
        for vid, s in found.items():
            s["kind"] = kind_of(cfg, s)
            if vid in _live:
                _live[vid].update({k: s[k] for k in ("title", "channel", "channel_id", "kind") if s.get(k)})
            else:
                _live[vid] = {**s, "misses": 0, "last_ok": time.time()}
                new += 1
    return new


_last_tick = {"ts": 0.0}


def count_tick(now: float = None) -> dict:
    """Count every known live stream and record one total. Returns {'total', 'live'}."""
    cfg = config()
    now = now or time.time()
    with _lock:
        vids = list(_live)
    counts = count_all(vids)
    rows = []
    with _lock:
        for v in vids:
            s = _live.get(v)
            if s is None:
                continue
            if v in counts:
                if counts[v] is None:
                    s["misses"] += 1
                    if s["misses"] >= MISSES_TO_END:
                        _live.pop(v, None)
                    continue
                s.update(viewers=counts[v], misses=0, last_ok=now)
            elif now - s["last_ok"] > 3 * max(FAST_SEC, 20):
                continue  # couldn't check it for a while: don't count stale numbers
            rows.append(dict(s))
    if cfg.get("paused"):
        return {"total": 0, "live": 0}
    total = sum(r["viewers"] for r in rows)
    by = {k: sum(r["viewers"] for r in rows if r["kind"] == k) for k in ("official", "watch party", "community")}
    prev = _last_tick["ts"]
    dt = min(now - prev, 3 * FAST_SEC) if prev else FAST_SEC
    with _lock:
        c = db()
        for r in rows:
            c.execute("""INSERT INTO streams (vid, channel, channel_id, title, kind, first_seen, last_seen, peak, peak_at, hw, air)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(vid) DO UPDATE SET channel=COALESCE(NULLIF(excluded.channel,''), streams.channel),
                         channel_id=COALESCE(NULLIF(excluded.channel_id,''), streams.channel_id),
                         title=COALESCE(NULLIF(excluded.title,''), streams.title), kind=excluded.kind,
                         last_seen=excluded.last_seen,
                         peak_at=CASE WHEN excluded.peak > streams.peak THEN excluded.peak_at ELSE streams.peak_at END,
                         peak=MAX(streams.peak, excluded.peak), hw=streams.hw + excluded.hw, air=streams.air + excluded.air""",
                      (r["vid"], r["channel"], r["channel_id"], r["title"], r["kind"], now, now, r["viewers"], now,
                       r["viewers"] * dt / 3600, dt))
        c.executemany("INSERT INTO samples VALUES (?,?,?)", [(now, r["vid"], r["viewers"]) for r in rows])
        c.execute("INSERT OR REPLACE INTO ticks VALUES (?,?,?,?,?,?)",
                  (now, total, len(rows), by["official"], by["watch party"], by["community"]))
        c.commit()
    _last_tick["ts"] = now
    return {"total": total, "live": len(rows)}


def run_forever():
    def loop(fn, every):
        while True:
            t0 = time.time()
            try:
                fn()
            except Exception as e:
                print(f"{fn.__name__} failed: {str(e)[:200]}")
            time.sleep(max(1.0, every - (time.time() - t0)))
    threading.Thread(target=loop, args=(discover, DISCOVER_SEC), daemon=True).start()
    time.sleep(2)
    threading.Thread(target=loop, args=(count_tick, FAST_SEC), daemon=True).start()


# ---------- numbers ----------

def fmt_n(n) -> str:
    n = float(n or 0)
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e4:
        return f"{n / 1e3:.1f}K"
    return f"{int(round(n)):,}"


def when(ts) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%a %d %b, %I:%M:%S %p IST")


def yt(vid: str) -> str:
    return f"https://youtu.be/{vid}"


def stats() -> dict:
    with _lock:
        c = db()
        ticks = [dict(r) for r in c.execute("SELECT * FROM ticks ORDER BY ts")]
        streams = [dict(r) for r in c.execute("SELECT * FROM streams")]
    out = {"ticks": len(ticks)}
    if not ticks:
        return out
    cap = 3 * FAST_SEC
    hw = air = 0.0
    days = {}
    for i, t in enumerate(ticks):
        dt = min((ticks[i + 1]["ts"] - t["ts"]) if i + 1 < len(ticks) else FAST_SEC, cap)
        d = datetime.fromtimestamp(t["ts"], TZ).strftime("%a %d %b")
        dd = days.setdefault(d, {"day": d, "peak": 0, "peak_at": t["ts"], "hw": 0.0, "air": 0.0})
        if t["total"] > dd["peak"]:
            dd["peak"], dd["peak_at"] = t["total"], t["ts"]
        if t["live"]:
            hw += t["total"] * dt / 3600
            air += dt
            dd["hw"] += t["total"] * dt / 3600
            dd["air"] += dt
    for dd in days.values():
        dd["avg"] = dd["hw"] / (dd["air"] / 3600) if dd["air"] else 0
    pk = max(ticks, key=lambda t: t["total"])
    chans = {}
    for s in streams:
        ch = chans.setdefault(s["channel"] or s["vid"], {"channel": s["channel"] or s["vid"], "kind": s["kind"], "peak": 0,
                                                          "hw": 0.0, "air": 0.0, "streams": 0, "url": yt(s["vid"]),
                                                          "best": -1})
        if s["hw"] > ch["best"]:
            ch["best"], ch["url"], ch["kind"] = s["hw"], yt(s["vid"]), s["kind"]
        ch["peak"] = max(ch["peak"], s["peak"])
        ch["hw"] += s["hw"]
        ch["air"] += s["air"]
        ch["streams"] += 1
    for ch in chans.values():
        ch["avg"] = ch["hw"] / (ch["air"] / 3600) if ch["air"] else 0
    with _lock:
        live = sorted((dict(s) for s in _live.values() if time.time() - s["last_ok"] < 3 * max(FAST_SEC, 20)),
                      key=lambda s: -s["viewers"])
    kinds_hw = {k: sum(c["hw"] for c in chans.values() if c["kind"] == k) for k in ("official", "watch party", "community")}
    out.update(peak=pk["total"], peak_at=pk["ts"], peak_split={"official": pk["official"], "watch party": pk["watch"],
                                                                  "community": pk["community"]},
               hw=hw, air_h=air / 3600, avg=hw / (air / 3600) if air else 0, days=list(days.values()),
               channels=sorted(chans.values(), key=lambda c: -c["hw"]), live=live, kinds_hw=kinds_hw,
               series=[(t["ts"], t["total"], t["official"], t["watch"], t["community"]) for t in ticks],
               last_ts=ticks[-1]["ts"])
    return out


def summary(top: int = 10) -> str:
    cfg = config()
    st = stats()
    head = f"{cfg['name']}: YouTube viewership, all streams" + (" (PAUSED)" if cfg.get("paused") else "")
    if not st.get("ticks"):
        return head + f"\n\nNo data yet. Searching every {DISCOVER_SEC}s; numbers start when a stream is live."
    lines = [head]
    if st["live"]:
        lines.append(f"\nLIVE NOW: {fmt_n(sum(s['viewers'] for s in st['live']))} across {len(st['live'])} streams")
        for s in st["live"][:8]:
            lines.append(f"  {fmt_n(s['viewers'])}  {s['channel']} ({s['kind']})\n     {yt(s['vid'])}")
    else:
        lines.append("\nNothing live right now.")
    sp = st["peak_split"]
    lines += [f"\nPeak viewers: {fmt_n(st['peak'])} at {when(st['peak_at'])}",
              f"  official {fmt_n(sp['official'])}, watch parties {fmt_n(sp['watch party'])}, community {fmt_n(sp['community'])}",
              f"Average viewers: {fmt_n(st['avg'])}", f"Hours watched: {fmt_n(st['hw'])}", f"Airtime: {st['air_h']:.1f} h"]
    tot = sum(st["kinds_hw"].values()) or 1
    lines.append("Hours watched share: " + ", ".join(f"{k} {100 * v / tot:.0f}%" for k, v in st["kinds_hw"].items()))
    if len(st["days"]) > 1:
        lines.append("\nBy day (IST): peak / average / hours watched")
        lines += [f"  {d['day']}: {fmt_n(d['peak'])} / {fmt_n(d['avg'])} / {fmt_n(d['hw'])}" for d in st["days"]]
    lines.append("\nTop channels by hours watched:")
    for n, c in enumerate(st["channels"][:top], 1):
        lines.append(f"  {n}. {c['channel']} ({c['kind']}): {fmt_n(c['hw'])} h, peak {fmt_n(c['peak'])}\n     {c['url']}")
    lines.append(f"\nCounted every {FAST_SEC}s ({_method['value'] or 'starting'}), new streams found every {DISCOVER_SEC}s.")
    lines += [f"{k}: {v}" for k, v in cfg.get("links", {}).items()]
    return "\n".join(lines)
