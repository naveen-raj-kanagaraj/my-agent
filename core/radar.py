"""Daily content radar for the owner's media ecosystem: media brand, talent agency,
content house and production studio. Topics are configurable (RADAR_TOPICS), and the
owner's learned interests are added automatically."""
import os
from datetime import datetime

import requests

from core import llm, profile, sources, store

client = llm.Client("radar")
RADAR_MODEL = "claude-sonnet-5-5"

DEFAULT_TOPICS = (
    "Indian creator economy, influencer marketing India, talent management and creator agencies, "
    "YouTube and Instagram platform changes, Indian entertainment and OTT, brand partnerships and sponsorships, "
    "Indian gaming and esports, Indian media and startup funding"
)
TOPICS = [t.strip() for t in os.getenv("RADAR_TOPICS", DEFAULT_TOPICS).split(",") if t.strip()][:10]
SUBREDDITS = [s.strip() for s in os.getenv(
    "RADAR_SUBREDDITS", "NewTubers,CreatorsAdvice,socialmedia,marketing,IndianGaming,bollywood,StartUpIndia"
).split(",") if s.strip()]
COMPETITORS = [c.strip() for c in os.getenv("RADAR_COMPETITORS", "").split(",") if c.strip()][:6]


def _serper(endpoint: str, q: str, num: int = 8) -> list:
    try:
        r = requests.post(
            f"https://google.serper.dev/{endpoint}",
            headers={"X-API-KEY": os.getenv("SERPER_API_KEY", ""), "Content-Type": "application/json"},
            json={"q": q, "num": num, "gl": "in", "tbs": "qdr:d"},
            timeout=15,
        )
        store.bump("serper")
        return r.json().get(endpoint, []) if r.ok else []
    except Exception:
        return []


def _reddit_latest(sub: str) -> list:
    out = []
    for it in sources.subreddit_latest(sub):
        age = ""
        if it.get("published"):
            mins = int((datetime.now(it["published"].tzinfo) - it["published"]).total_seconds() // 60)
            age = f"{mins // 60}h ago" if mins >= 60 else f"{mins}m ago"
        out.append(f"{it['source']} ({age}, {it['engagement']} engagement): {it['title']}")
    return out


def _topic_keywords(topics: list) -> dict:
    """Keywords per radar topic, expanded once and kept in the database."""
    saved = store.kv_get("radar_keywords", {})
    missing = [t for t in topics if t not in saved]
    if missing:
        try:
            saved.update(profile.expand_keywords(missing, "Indian media, creators, entertainment and business", "owner"))
            store.kv_set("radar_keywords", saved)
        except Exception as e:
            print(f"Radar keyword expansion failed: {e}")
    return saved


def build_radar() -> str:
    from core.news import _fmt
    owner = store.get_user("owner") or {}
    topics = list(dict.fromkeys(TOPICS + store.interests(owner)[:3]))
    kw = _topic_keywords(topics)
    lines = []
    for t in topics:
        items = sources.gather(t, kw.get(t, []), "in", limit=5)
        lines += [f"[{t}] " + _fmt(i)[2:] for i in items]
    for sub in SUBREDDITS:
        lines += _reddit_latest(sub)
    for c in COMPETITORS:
        for v in _serper("videos", c, 4):
            lines.append(f"COMPETITOR {c}: {v.get('title')} ({v.get('date', '')})")
    if not lines:
        return "Content radar: no data came back today (search or Reddit may be unavailable)."

    owner = store.get_user("owner") or {}
    resp = client.messages.create(
        _uid="owner",
        model=RADAR_MODEL,
        max_tokens=4000,                 # 2000 cut the radar off mid-way
        messages=[{"role": "user", "content": (
            "You are the content and business strategist for an Indian media founder. He runs a digital media brand "
            "(rooted in the Indian gaming ecosystem but growing beyond it) and is building a talent management "
            "agency, a content house and a production studio. Opportunities can come from any category: creators "
            "and influencers, entertainment, culture, brands and sponsorships, platforms, business, gaming.\n"
            f"What we know about the founder: {owner.get('profile') or 'n/a'}\n\n"
            "From today's signals below, write a content radar. Plain text only, no markdown or asterisks.\n"
            "Section 1, 'What's moving': the 5 strongest trends, favouring what surfaced in the last few hours, one or two sentences each, with why they're rising now.\n"
            "Section 2, 'Content to make': 5 ideas built to scale into a series, spread across categories (not all gaming). For each give: Hook (first 3 seconds or "
            "headline), Core idea, Format (short, long, series, live), Distribution angle (platform-specific edge), and "
            "Why now. Prefer angles competitors are missing.\n"
            "Section 3, 'Business moves': 2-3 opportunities for the talent agency, content house or production studio "
            "(creators to sign, brand categories spending, formats to produce).\n"
            "Section 4, 'Competitor watch': what competitors posted that worked and the gap it leaves (skip if no data).\n"
            "Be specific to India. No generic advice.\n\n"
            "SIGNALS:\n" + "\n".join(lines[:150])
        )}],
    )
    return f"CONTENT RADAR, {datetime.now().strftime('%a %b %d')}\n\n" + resp.content[0].text.strip().replace("**", "")
