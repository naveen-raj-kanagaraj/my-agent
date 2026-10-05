"""Personalised news briefs for each user."""
import os
import threading
import time
from datetime import datetime

import anthropic
import requests

from core import store

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


def build_user_brief(uid: str) -> str:
    u = store.get_user(uid)
    if not u:
        return "I don't know you yet. Send /start first."
    topics = store.interests(u)[:MAX_TOPICS]
    if not topics:
        return "Tell me what you're interested in first: send /interests followed by your topics."
    region = _region(u.get("timezone"))
    sections = []
    for t in topics:
        items = google_news(t, region)
        if items:
            lines = "\n".join(f"- {i['title']} ({i['source']}, {i['date']}): {i['snippet']} [{i['link']}]" for i in items[:5])
            sections.append(f"TOPIC: {t}\n{lines}")
    if not sections:
        return "I couldn't find fresh news on your topics in the last day. Try again later, or broaden your /interests."

    tz = store.user_tz(u)
    now = datetime.now(tz)
    part = "Morning" if now.hour < 12 else ("Afternoon" if now.hour < 17 else "Evening")
    who = u.get("profile") or ""
    lang = u.get("language") or "English"
    resp = client.messages.create(
        model=NEWS_MODEL,
        max_tokens=1800,
        messages=[{"role": "user", "content": (
            f"Write a short personalised news brief for {u.get('name') or 'this reader'}.\n"
            f"About them: {who or 'no profile yet'}\nTheir topics: {', '.join(topics)}\n"
            f"Write in {lang}. Plain text only: no markdown, no asterisks, no bullet symbols.\n\n"
            "Format: a one-line greeting, then for each topic that has real news, the topic name on its own line, then "
            "the 1-3 most important stories in 2-3 sentences each: what happened, then why it matters to this person "
            "specifically. Put the single best source link after each story. Skip duplicates, filler and old news. "
            "End with one line starting 'Worth watching:' about an early signal. Keep it under 450 words.\n\n"
            f"NEWS FROM THE LAST 24 HOURS:\n{chr(10).join(sections)}"
        )}],
    )
    text = resp.content[0].text.strip().replace("**", "").replace("##", "")
    return f"{part} brief, {now.strftime('%a %b %d')}\n\n{text}\n\nChange topics with /interests, stop with /newsoff."
