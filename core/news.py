"""Personalised news briefs for each user."""
import os
import threading
import time
from datetime import datetime

import anthropic
import requests

from core import profile, sources, store

client = anthropic.Anthropic()
NEWS_MODEL = "claude-haiku-4-5-20251001"
MAX_TOPICS = 5
CACHE_SECONDS = 3 * 3600

_cache = {}
_cache_lock = threading.Lock()


def _region(tz: str) -> str:
    tz = tz or ""
    if tz.startswith("Asia/Kolkata") or tz.startswith("Asia/Calcutta"):
        return "in"
    if tz.startswith("Europe/London"):
        return "gb"
    if tz.startswith("Australia/"):
        return "au"
    if tz.startswith("Asia/Singapore"):
        return "sg"
    if tz.startswith("Asia/Dubai"):
        return "ae"
    return "us"


def google_news(query: str, region: str = "us", num: int = 6) -> list:
    """Recent (past day) news via Serper, cached so users with the same topic share one search."""
    key = (query.lower().strip(), region)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        r = requests.post(
            "https://google.serper.dev/news",
            headers={"X-API-KEY": os.getenv("SERPER_API_KEY", ""), "Content-Type": "application/json"},
            json={"q": query, "num": num, "tbs": "qdr:d", "gl": region},
            timeout=15,
        )
        items = r.json().get("news", []) if r.ok else []
    except Exception as e:
        print(f"News search failed for '{query}': {e}")
        items = []
    items = [{k: i.get(k, "") for k in ("title", "snippet", "source", "date", "link")} for i in items]
    with _cache_lock:
        _cache[key] = (time.time(), items)
    return items


def _fmt(it: dict) -> str:
    when = ""
    if it.get("published"):
        hours = (datetime.now(it["published"].tzinfo) - it["published"]).total_seconds() / 3600
        when = f"{int(hours)}h ago" if hours >= 1 else "just now"
    also = f"; also on {', '.join(it['also_on'])}" if it.get("also_on") else ""
    buzz = f"; {it['engagement']} engagement" if it.get("engagement") else ""
    return (f"- [{it['platform']} | {it['source']}{', ' + when if when else ''}{buzz}{also}] {it['title']}"
            f"{': ' + it['snippet'][:200] if it['snippet'] else ''} <{it['url']}>")


def collect_for_user(uid: str) -> dict:
    """{topic: [items]} from every source, matched on the user's keywords."""
    u = store.get_user(uid) or {}
    topics = store.interests(u)[:MAX_TOPICS]
    kw = profile.ensure_keywords(uid) if topics else {}
    region = _region(u.get("timezone"))
    found = {}
    for t in topics:
        items = sources.gather(t, kw.get(t, []), region)
        if items:
            found[t] = items
    custom = store.custom_keywords(u)
    if custom:
        items = sources.gather(custom[0], custom[1:], region)
        if items:
            found["Your keywords (" + ", ".join(custom[:4]) + ")"] = items
    return found


def build_user_brief(uid: str) -> str:
    u = store.get_user(uid)
    if not u:
        return "I don't know you yet. Send /start first."
    if not store.interests(u) and not store.custom_keywords(u):
        return "Tell me what you're interested in first: send /interests followed by your topics."
    found = collect_for_user(uid)
    if not found:
        return "I couldn't find fresh news on your topics in the last day. Try again later, or broaden your /interests."
    sections = [f"TOPIC: {t}\n" + "\n".join(_fmt(i) for i in items) for t, items in found.items()]

    tz = store.user_tz(u)
    now = datetime.now(tz)
    part = "Morning" if now.hour < 12 else ("Afternoon" if now.hour < 17 else "Evening")
    lang = u.get("language") or "English"
    resp = client.messages.create(
        model=NEWS_MODEL,
        max_tokens=1800,
        messages=[{"role": "user", "content": (
            f"Write a short personalised news brief for {u.get('name') or 'this reader'}.\n"
            f"About them: {u.get('profile') or 'no profile yet'}\nTheir topics: {', '.join(found)}\n"
            f"Write in {lang}. Plain text only: no markdown, no asterisks, no bullet symbols.\n\n"
            "The items come from news sites, Reddit, Hacker News, X, Instagram, Threads and YouTube, already matched "
            "to the reader's keywords and ranked. Format: a one-line greeting, then for each topic with real news, "
            "the topic name on its own line, then the 1-3 most important stories in 2-3 sentences each, favouring the newest developments: what "
            "happened, then why it matters to this person. Say where it's buzzing when that's informative (for "
            "example 'big thread on r/india' or 'trending on X'). Treat social posts as claims, not confirmed "
            "facts, unless a news outlet also reports them. Put the single best link after each story. Skip "
            "duplicates and filler. End with one line starting 'Worth watching:'. Under 450 words.\n\n"
            f"ITEMS FROM THE LAST DAY:\n{chr(10).join(sections)}"
        )}],
    )
    text = resp.content[0].text.strip().replace("**", "").replace("##", "")
    return (f"{part} brief, {now.strftime('%a %b %d')}\n\n{text}\n\n"
            "Change topics with /interests, add keywords with /keywords, stop with /newsoff.")
