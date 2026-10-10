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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests

from core import store

POLL_SEC = int(os.getenv("EVENT_POLL_SEC", "60"))
RECHECK_MIN = 15          # re-check streams seen live within this many minutes that vanished from search
MAX_DIRECT_CHECKS = 20
REPORT_TZ = ZoneInfo(os.getenv("EVENT_TZ", "Asia/Kolkata"))
LIVE_FILTER = "EgJAAQ%253D%253D"     # YouTube search filter: live now
WATCH_PARTY = re.compile(r"watch\s*-?\s*party|co-?\s*stream|watch\s*-?\s*along|reaction|reacting|live\s+react", re.I)

PRESETS = {
    "bmsd": {
        "name": "BMSD 2026",
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

def relevant(ev: dict, s: dict) -> bool:
    if s["vid"] in ev.get("excluded", []) or (s.get("channel_id") and s["channel_id"] in ev.get("excluded", [])) \
            or s.get("channel", "").lower() in ev.get("excluded", []):
        return False
    if s["vid"] in ev.get("videos", []) or _forced_channel(ev, s):
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
    if WATCH_PARTY.search(s.get("title", "")):
        return "watch party"
    return "community"


# ---------- one poll ----------

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
    for ch in ev.get("channels", [])[:30]:
        s = check_channel(ch)
        if s and s["vid"] not in found and relevant(ev, s):
            found[s["vid"]] = s
    with store._lock:
        c = _db()
        recent = [dict(r) for r in c.execute(
            "SELECT vid, channel, channel_id, title FROM ev_streams WHERE event=? AND last_seen>?",
            (ev["key"], now - RECHECK_MIN * 60))]
    api = {}
    known = list({*found, *[r["vid"] for r in recent], *ev.get("videos", [])})
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
        missing += [v for v in ev.get("videos", []) if v not in found and v not in missing]
        if missing:
            with ThreadPoolExecutor(max_workers=6) as pool:
                for s in pool.map(lambda v: _safe(check_video, v), missing):
                    if s:
                        found[s["vid"]] = s
    streams = []
    for s in found.values():
        s["kind"] = kind_of(ev, s)
        streams.append(s)
    total = sum(s["viewers"] for s in streams)
    by = {k: sum(s["viewers"] for s in streams if s["kind"] == k) for k in ("official", "watch party", "community")}
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
                       s["viewers"], now))
        c.executemany("INSERT INTO ev_samples VALUES (?,?,?,?)", [(ev["key"], now, s["vid"], s["viewers"]) for s in streams])
        if streams or errors < len(ev["queries"][:8]):  # don't record a fake zero when every search failed
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
            "SELECT s.ts, s.vid, s.viewers, t.channel, t.title, t.kind FROM ev_samples s JOIN ev_streams t "
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
    days = {}
    for i, t in enumerate(ticks):
        d = datetime.fromtimestamp(t["ts"], REPORT_TZ).strftime("%a %d %b")
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
    out["live_now"] = sorted(live_now, key=lambda s: -s["viewers"])
    out["series"] = [(t["ts"], t["total"], t["official"], t["watch"], t["community"]) for t in ticks]
    return out


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
    lines = [f"{ev['name']} viewership (YouTube, all streams)"]
    if st["live_now"]:
        lines.append(f"\nLIVE NOW: {fmt_n(sum(s['viewers'] for s in st['live_now']))} viewers across "
                     f"{len(st['live_now'])} streams")
        for s in st["live_now"]:
            lines.append(f"  {fmt_n(s['viewers'])}  {s['channel']} ({s['kind']})\n     {yt_link(s['vid'])}")
    else:
        lines.append("\nNothing live right now.")
    sp = st["peak_split"]
    lines += [f"\nEvent so far: peak {fmt_n(st['peak'])} ({_when(st['peak_at'])})",
              f"  (official {fmt_n(sp['official'])}, watch parties {fmt_n(sp['watch'])}, community {fmt_n(sp['community'])})",
              f"  average {fmt_n(st['avg'])}, hours watched {fmt_n(st['hours_watched'])}, airtime {st['airtime_h']:.1f} h",
              f"\nYouTube, checked every {POLL_SEC}s. /event page for the dashboard."]
    for label, url in (ev.get("links") or {}).items():
        lines.append(f"{label}: {url}")
    return "\n".join(lines)


def tool_event_stats(name: str = "") -> str:
    """For the agent: 'what's the peak so far?'"""
    return summary(name or None, top=15)
