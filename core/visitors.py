"""Who is watching the public dashboard: privacy-friendly counts (no IPs, no cookies; a random per-tab id).

Country comes from Cloudflare's CF-IPCountry header. Live = pinged in the last 75s (pages ping every 30s).
"""
import threading
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from core import store

TZ = ZoneInfo("Asia/Kolkata")
ACTIVE_SEC = 75
_lock = threading.Lock()
_sess = {}            # sid -> {"first", "last", "country", "ref", "device", "day"}
_flush = {"ts": 0.0}
BOTS = ("bot", "crawl", "spider", "slurp", "preview", "headless", "facebookexternalhit", "whatsapp", "telegram")


def _day(ts=None):
    return datetime.fromtimestamp(ts or time.time(), TZ).strftime("%Y-%m-%d")


def hit(sid: str, country: str = "", ref: str = "", ua: str = "", width: int = 0):
    sid = (sid or "")[:40]
    ua_l = (ua or "").lower()
    if not sid or any(b in ua_l for b in BOTS):
        return
    now = time.time()
    with _lock:
        s = _sess.get(sid)
        if not s:
            if len(_sess) > 300000:
                return
            device = "mobile" if ("mobi" in ua_l or (width and width < 700)) else "desktop"
            ref = (ref or "").lower().replace("www.", "")[:60] or "direct"
            if "letsgrowesports" in ref:
                ref = "direct"
            s = _sess[sid] = {"first": now, "last": now, "country": (country or "??").upper()[:2], "ref": ref,
                              "device": device, "day": _day(now)}
        s["last"] = now
        active = sum(1 for x in _sess.values() if now - x["last"] < ACTIVE_SEC)
        best = store.kv_get("visitors_peak", {}) or {}
        if active > best.get("n", 0):
            store.kv_set("visitors_peak", {"n": active, "ts": int(now)})
        if now - _flush["ts"] > 30:
            _flush["ts"] = now
            _save(now)


def _save(now):
    today = _day(now)
    todays = [x for x in _sess.values() if x["day"] == today]
    hist = store.kv_get("visitors_days", {}) or {}
    hist[today] = max(hist.get(today, 0), len(todays))
    store.kv_set("visitors_days", dict(sorted(hist.items())[-60:]))
    for sid in [k for k, x in _sess.items() if now - x["last"] > 2 * 86400]:   # forget old tabs
        _sess.pop(sid, None)


def stats() -> dict:
    now = time.time()
    today = _day(now)
    with _lock:
        vals = list(_sess.values())
    act = [x for x in vals if now - x["last"] < ACTIVE_SEC]
    tod = [x for x in vals if x["day"] == today]
    return {"active": len(act), "today": max(len(tod), (store.kv_get("visitors_days", {}) or {}).get(today, 0)),
            "peak": store.kv_get("visitors_peak", {}) or {},
            "countries": Counter(x["country"] for x in tod).most_common(8),
            "refs": Counter(x["ref"] for x in tod).most_common(8),
            "devices": Counter(x["device"] for x in tod).most_common(),
            "active_countries": Counter(x["country"] for x in act).most_common(5),
            "avg_min": round(sum(x["last"] - x["first"] for x in tod) / len(tod) / 60, 1) if tod else 0,
            "days": store.kv_get("visitors_days", {}) or {}}


def summary() -> str:
    s = stats()
    pk = s["peak"]
    when = datetime.fromtimestamp(pk["ts"], TZ).strftime("%d %b, %I:%M %p IST") if pk.get("ts") else "-"
    fmtc = lambda pairs: ", ".join(f"{k} {v}" for k, v in pairs) or "-"
    lines = ["Dashboard visitors (live.letsgrowesports.com)",
             f"\nOn the page now: {s['active']}" + (f" ({fmtc(s['active_countries'])})" if s["active"] else ""),
             f"Visitors today (IST): {s['today']}",
             f"Most at once: {pk.get('n', 0)} at {when}",
             f"Average time on page today: {s['avg_min']} min",
             f"\nCountries today: {fmtc(s['countries'])}",
             f"Came from: {fmtc(s['refs'])}",
             f"Devices: {fmtc(s['devices'])}"]
    days = list(s["days"].items())[-7:]
    if len(days) > 1:
        lines.append("\nLast days: " + ", ".join(f"{d[5:]} {n}" for d, n in days))
    lines.append("\nCounted without cookies or IP addresses. A visitor = one browser tab session.")
    return "\n".join(lines)
