"""Creator scouting for the talent agency.

YouTube: real numbers from the channel page via yt-dlp (no API key needed): subscribers, recent
views, engagement (likes + comments per view), upload cadence and momentum.
Instagram: no public API, so follower counts are best-effort from Google's index.
Results are saved into the talent tracker automatically.
"""
import os
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from core import store

RECENT_FULL = 6     # videos fetched in detail for likes/comments/dates
RECENT_FLAT = 24    # videos fetched quickly for view counts


def _fmt_num(n) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit, div in (("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}".replace(".0", "")
    return str(int(n))


def _parse_count(s: str):
    m = re.search(r"([\d.,]+)\s*([KkMm]?)\s*(?:followers|Followers)", s or "")
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return int(n * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1))


def _yt_url(handle: str) -> str:
    h = handle.strip()
    if h.startswith("http"):
        return re.sub(r"/(videos|shorts|featured|streams)/?$", "", h.rstrip("/"))
    h = h.lstrip("@")
    return f"https://www.youtube.com/@{h}"


def _ydl(opts):
    import yt_dlp
    base = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20}
    base.update(opts)
    return yt_dlp.YoutubeDL(base)


def youtube_stats(handle: str) -> dict:
    url = _yt_url(handle)
    info, entries = None, []
    for tab in ("/videos", "/shorts"):
        with _ydl({"extract_flat": "in_playlist", "playlistend": RECENT_FLAT}) as y:
            info = y.extract_info(url + tab, download=False)
        entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
        if entries:
            break
    if not info:
        raise RuntimeError("Channel not found")
    subs = info.get("channel_follower_count")
    name = info.get("channel") or info.get("uploader") or info.get("title") or handle

    def detail(vid):
        try:
            with _ydl({}) as y:
                v = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            return {k: v.get(k) for k in ("view_count", "like_count", "comment_count", "upload_date", "title", "duration")}
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        details = [d for d in pool.map(detail, [e["id"] for e in entries[:RECENT_FULL]]) if d]

    flat_views = [e.get("view_count") for e in entries if e.get("view_count")]
    recent_views = [d["view_count"] for d in details if d.get("view_count")] or flat_views[:RECENT_FULL]
    older_views = flat_views[RECENT_FULL:]
    eng = [((d.get("like_count") or 0) + (d.get("comment_count") or 0)) / d["view_count"]
           for d in details if d.get("view_count")]
    dates = sorted((datetime.strptime(d["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc)
                    for d in details if d.get("upload_date")), reverse=True)
    gaps = [(dates[i] - dates[i + 1]).days for i in range(len(dates) - 1)]
    now = datetime.now(timezone.utc)
    out = {
        "platform": "YouTube", "name": name, "handle": "@" + url.rsplit("@", 1)[-1] if "@" in url else url,
        "url": url, "subscribers": subs, "videos_checked": len(entries),
        "median_views_recent": int(statistics.median(recent_views)) if recent_views else None,
        "median_views_older": int(statistics.median(older_views)) if older_views else None,
        "engagement_rate": round(100 * statistics.mean(eng), 2) if eng else None,
        "uploads_every_days": round(statistics.mean(gaps), 1) if gaps else None,
        "last_upload_days_ago": (now - dates[0]).days if dates else None,
        "recent_titles": [d.get("title") for d in details][:5],
    }
    if out["subscribers"] and out["median_views_recent"]:
        out["views_per_sub_pct"] = round(100 * out["median_views_recent"] / out["subscribers"], 1)
    if out["median_views_recent"] and out["median_views_older"]:
        out["momentum_pct"] = round(100 * (out["median_views_recent"] / out["median_views_older"] - 1))
    return out


def instagram_stats(handle: str) -> dict:
    from core import sources
    h = handle.strip().rstrip("/").split("/")[-1].lstrip("@")
    items = sources._serper("search", f"site:instagram.com/{h}", "in", 5) if os.getenv("SERPER_API_KEY") else []
    followers = None
    bio = ""
    for o in items:
        followers = followers or _parse_count(o.get("snippet", "") + " " + o.get("title", ""))
        bio = bio or o.get("snippet", "")
    return {"platform": "Instagram", "name": h, "handle": "@" + h, "url": f"https://www.instagram.com/{h}/",
            "followers_estimate": followers, "public_snippet": bio[:300],
            "note": "Instagram has no public API; followers are an estimate from Google's index. Engagement needs the creator's insights."}


def summarise(s: dict) -> str:
    if s["platform"] == "YouTube":
        lines = [f"{s['name']} ({s['handle']}) on YouTube",
                 f"Subscribers: {_fmt_num(s.get('subscribers'))}",
                 f"Median views, last {RECENT_FULL} videos: {_fmt_num(s.get('median_views_recent'))}"
                 + (f" ({s['views_per_sub_pct']}% of subs)" if s.get("views_per_sub_pct") is not None else ""),
                 f"Engagement (likes + comments / views): {s.get('engagement_rate', '?')}%",
                 f"Uploads: every {s.get('uploads_every_days', '?')} days, last {s.get('last_upload_days_ago', '?')} days ago"]
        if s.get("momentum_pct") is not None:
            lines.append(f"Momentum: recent videos {s['momentum_pct']:+d}% vs the ones before")
        if s.get("recent_titles"):
            lines.append("Recent videos: " + " | ".join(t for t in s["recent_titles"] if t))
        return "\n".join(lines)
    return (f"{s['name']} on Instagram\nFollowers (estimate): {_fmt_num(s.get('followers_estimate'))}\n"
            f"Public snippet: {s.get('public_snippet') or 'n/a'}\nNote: {s['note']}")


def scout(handle: str, platform: str = "") -> str:
    p = (platform or "").lower()
    is_ig = "instagram" in p or "instagram.com" in handle
    s = instagram_stats(handle) if is_ig else youtube_stats(handle)
    text = summarise(s)
    followers = s.get("subscribers") or s.get("followers_estimate")
    store.upsert_creator(
        s["name"], platform=s["platform"], handle=s["handle"], followers=_fmt_num(followers) if followers else "",
        notes=f"Scouted {datetime.now():%b %d}: " + text.split("\n", 1)[-1].replace("\n", "; ")[:600])
    store.kv_set(f"scout:{s['handle'].lower()}", s)
    return text + "\n\n(Saved to the talent tracker.)"


# ---------- content studio ----------

def save_brand_voice(sample: str) -> str:
    samples = store.kv_get("brand_voice", [])
    samples.append(sample.strip()[:2500])
    store.kv_set("brand_voice", samples[-10:])
    return f"Saved. I now have {len(samples[-10:])} brand voice sample(s)."


def get_brand_voice() -> str:
    samples = store.kv_get("brand_voice", [])
    if not samples:
        return ("No brand voice samples saved yet. Write in a punchy, conversational Indian creator style, and suggest "
                "the owner adds samples with /brandvoice add <a script or caption they've written>.")
    return "BRAND VOICE SAMPLES (match tone, rhythm, slang and structure; don't copy lines):\n\n" + \
        "\n\n---\n\n".join(samples)


def timestamped_transcript(url: str) -> str:
    from core.web import youtube_id
    vid = youtube_id(url) or url.strip()
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(vid, languages=["en", "en-IN", "hi", "ta"])
    except Exception:
        t = next(iter(api.list(vid)))
        try:
            t = t.translate("en")
        except Exception:
            pass
        fetched = t.fetch()
    out, bucket, start = [], [], None
    for snip in fetched:
        if start is None:
            start = snip.start
        bucket.append(snip.text)
        if snip.start - start >= 20:
            out.append(f"[{int(start // 60)}:{int(start % 60):02d}] {' '.join(bucket)}")
            bucket, start = [], None
    if bucket:
        out.append(f"[{int(start // 60)}:{int(start % 60):02d}] {' '.join(bucket)}")
    text = "\n".join(out)
    return text[:20000] + ("\n[transcript truncated]" if len(text) > 20000 else "")
