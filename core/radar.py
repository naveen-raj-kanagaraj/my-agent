"""Daily content radar for the owner's Indian gaming media brand."""
import os
from datetime import datetime

import anthropic
import requests

from core import store
from core.news import google_news

client = anthropic.Anthropic()
RADAR_MODEL = "claude-sonnet-5-5"

SUBREDDITS = [s.strip() for s in os.getenv("RADAR_SUBREDDITS", "IndianGaming,BGMI,esports").split(",") if s.strip()]
COMPETITORS = [c.strip() for c in os.getenv("RADAR_COMPETITORS", "").split(",") if c.strip()][:6]
NEWS_QUERIES = ["India gaming esports", "BGMI", "Indian gaming creators YouTube", "gaming industry India investment"]


def _serper(endpoint: str, q: str, num: int = 8) -> list:
    try:
        r = requests.post(
            f"https://google.serper.dev/{endpoint}",
            headers={"X-API-KEY": os.getenv("SERPER_API_KEY", ""), "Content-Type": "application/json"},
            json={"q": q, "num": num, "gl": "in", "tbs": "qdr:w"},
            timeout=15,
        )
        return r.json().get(endpoint, []) if r.ok else []
    except Exception:
        return []


def _reddit_top(sub: str) -> list:
    try:
        r = requests.get(
            f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=8",
            headers={"User-Agent": "pesagent-radar/1.0"}, timeout=15)
        if not r.ok:
            return []
        return [
            f"r/{sub}: {p['data']['title']} ({p['data']['score']} upvotes, {p['data']['num_comments']} comments)"
            for p in r.json()["data"]["children"]
        ]
    except Exception:
        return []


def build_radar() -> str:
    lines = []
    for q in NEWS_QUERIES:
        for i in google_news(q, "in", 5):
            lines.append(f"NEWS [{q}]: {i['title']} ({i['source']}, {i['date']})")
    for v in _serper("videos", "India gaming", 10):
        lines.append(f"VIDEO: {v.get('title')} by {v.get('channel', '')} ({v.get('date', '')})")
    for sub in SUBREDDITS:
        lines += _reddit_top(sub)
    for c in COMPETITORS:
        for v in _serper("videos", c, 4):
            lines.append(f"COMPETITOR {c}: {v.get('title')} ({v.get('date', '')})")
    if not lines:
        return "Content radar: no data came back today (search or Reddit may be unavailable)."

    owner = store.get_user("owner") or {}
    resp = client.messages.create(
        model=RADAR_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": (
            "You are the content strategist for an Indian gaming and esports digital media brand. Its founder is also "
            "building a talent agency, content house and production studio.\n"
            f"What we know about the founder: {owner.get('profile') or 'n/a'}\n\n"
            "From today's signals below, write a content radar. Plain text only, no markdown or asterisks.\n"
            "Section 1, 'What's moving': the 5 strongest trends, one or two sentences each, with why they're rising now.\n"
            "Section 2, 'Content to make': 5 ideas built to scale into a series. For each give: Hook (first 3 seconds or "
            "headline), Core idea, Format (short, long, series, live), Distribution angle (platform-specific edge), and "
            "Why now. Prefer angles competitors are missing.\n"
            "Section 3, 'Competitor watch': what competitors posted that worked and the gap it leaves (skip if no data).\n"
            "Be specific to India. No generic advice.\n\n"
            "SIGNALS:\n" + "\n".join(lines[:120])
        )}],
    )
    return f"CONTENT RADAR, {datetime.now().strftime('%a %b %d')}\n\n" + resp.content[0].text.strip().replace("**", "")
