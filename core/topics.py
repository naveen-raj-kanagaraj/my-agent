"""Topics people can follow, with ready-made keywords, plus live updates.

Live updates check the free sources (Google News, Reddit, Hacker News, your RSS feeds) every
LIVE_EVERY_MIN minutes, match each user's topic keywords, and send only items that are new to
them. No AI call, so they cost nothing. Capped per day and quiet at night (user's local time).
"""
import hashlib
import html
import os
from datetime import datetime, timezone

from core import sources, store

LIVE_EVERY_MIN = int(os.getenv("LIVE_EVERY_MIN", "30"))
LIVE_MAX_PER_DAY = int(os.getenv("LIVE_MAX_PER_DAY", "8"))
LIVE_MAX_AGE_HOURS = 4
QUIET_START, QUIET_END = 23, 7   # no live updates 11 PM - 7 AM local time
PER_TOPIC = 2
PER_MESSAGE = 6
# Preset topics are fetched once and shared by everyone (30-min cache). Typed-in topics each need their own
# fetches, so cap how many distinct topics one run may fetch; users beyond the cap go first next run.
LIVE_MAX_TOPICS_PER_RUN = int(os.getenv("LIVE_MAX_TOPICS_PER_RUN", "60"))

# Topic -> keywords that headlines and posts literally contain.
PRESETS = {
    "Cricket": ["cricket", "IPL", "BCCI", "Team India", "Virat Kohli", "Rohit Sharma", "T20", "Test match"],
    "Football": ["football", "Premier League", "Champions League", "ISL", "FIFA", "La Liga", "Messi", "Ronaldo"],
    "F1": ["Formula 1", "F1", "Grand Prix", "Verstappen", "Hamilton", "Ferrari", "McLaren", "Norris"],
    "Tech": ["smartphone", "iPhone", "Samsung", "Google", "Apple", "gadget", "laptop", "Pixel"],
    "AI": ["AI", "artificial intelligence", "OpenAI", "ChatGPT", "Claude", "Gemini", "Anthropic", "LLM"],
    "Startups": ["startup", "funding round", "Series A", "unicorn", "venture capital", "seed round", "IPO"],
    "Business": ["earnings", "merger", "acquisition", "Reliance", "Tata", "Adani", "quarterly results", "CEO"],
    "Stock markets": ["Sensex", "Nifty", "stock market", "NSE", "BSE", "Nasdaq", "S&P 500", "shares"],
    "Crypto": ["Bitcoin", "Ethereum", "crypto", "BTC", "Solana", "blockchain", "crypto ETF"],
    "Gaming": ["gaming", "PlayStation", "Xbox", "Nintendo", "Steam", "GTA", "video game"],
    "Esports": ["esports", "BGMI", "Valorant", "Free Fire", "CS2", "tournament", "League of Legends"],
    "Movies & OTT": ["box office", "Bollywood", "Netflix", "Prime Video", "trailer", "OTT", "Hotstar", "Kollywood"],
    "Music": ["album", "Spotify", "concert", "AR Rahman", "Anirudh", "Billboard", "Grammy"],
    "Fashion": ["fashion", "fashion week", "Sabyasachi", "sneakers", "luxury brand", "collection"],
    "Indian politics": ["Lok Sabha", "BJP", "Congress", "election", "Parliament", "Modi", "Rajya Sabha"],
    "World news": ["United Nations", "war", "summit", "ceasefire", "president", "prime minister", "sanctions"],
    "Science & space": ["ISRO", "NASA", "space", "rocket", "scientists", "discovery", "telescope"],
    "Health & fitness": ["health", "fitness", "nutrition", "workout", "study finds", "diet", "mental health"],
    "Cars & bikes": ["car launch", "EV", "electric vehicle", "Tata Motors", "Mahindra", "Tesla", "motorcycle"],
    "Creator economy": ["YouTube", "Instagram", "creator", "influencer", "MrBeast", "Reels", "creator fund"],
}

MODES = {
    "live": "Live updates as stories break, plus a morning brief",
    "both": "Morning and evening briefs",
    "morning": "Morning brief only",
    "off": "No updates, just chat",
}

TIMEZONES = [
    ("India", "Asia/Kolkata"), ("UAE", "Asia/Dubai"), ("Singapore", "Asia/Singapore"), ("UK", "Europe/London"),
    ("US East", "America/New_York"), ("US Central", "America/Chicago"), ("US West", "America/Los_Angeles"),
    ("Australia", "Australia/Sydney"),
]


def preset_for(name: str):
    return next((p for p in PRESETS if p.lower() == name.lower().strip()), None)


def toggle(uid: str, topic: str) -> list:
    """Add or remove a topic; preset topics bring their keywords with them."""
    u = store.get_user(uid) or {}
    ints = store.interests(u)
    kw = store.keywords(u)
    match = next((i for i in ints if i.lower() == topic.lower()), None)
    if match:
        ints.remove(match)
        kw.pop(match, None)
    else:
        ints.append(topic)
        if preset_for(topic):
            kw[topic] = PRESETS[preset_for(topic)]
    store.update_user(uid, interests=ints[:12], keywords=kw)
    store.kv_set(f"topics_pinned:{uid}", ints[:12])
    return ints


def add_custom(uid: str, text: str) -> list:
    """'Kabaddi, K-pop and Tesla' -> three topics (keywords are generated when first needed)."""
    import re
    parts = [p.strip(" .!") for p in re.split(r",|\band\b|\n|;", text) if p.strip(" .!")]
    u = store.get_user(uid) or {}
    ints = store.interests(u)
    kw = store.keywords(u)
    for p in parts[:8]:
        p = p[:40]
        preset = preset_for(p)
        name = preset or p
        if name.lower() not in [i.lower() for i in ints]:
            ints.append(name)
            if preset:
                kw[name] = PRESETS[preset]
    store.update_user(uid, interests=ints[:12], keywords=kw)
    store.kv_set(f"topics_pinned:{uid}", ints[:12])
    return ints


def attach_presets(uid: str):
    """After free-text topics (/interests ...), give any preset topic its ready-made keywords."""
    u = store.get_user(uid) or {}
    kw = store.keywords(u)
    ints = []
    for t in store.interests(u):
        p = preset_for(t)
        name = p or t
        if p and not kw.get(p):
            kw[p] = PRESETS[p]
        if name.lower() not in [i.lower() for i in ints]:
            ints.append(name)
    store.update_user(uid, interests=ints, keywords=kw)
    store.kv_set(f"topics_pinned:{uid}", ints)


def slots_for(mode: str, all_slots: list) -> list:
    if mode in ("live", "morning"):
        return all_slots[:1]
    if mode == "off":
        return []
    return all_slots


# ---------- live updates ----------

def _key(item: dict) -> str:
    return "live:" + hashlib.sha1((item.get("url") or item.get("title", "")).encode()).hexdigest()[:16]


def _age(item) -> str:
    if not item.get("published"):
        return ""
    mins = int((datetime.now(timezone.utc) - item["published"]).total_seconds() // 60)
    return f"{mins // 60}h ago" if mins >= 60 else f"{max(mins, 1)}m ago"


def collect_live(u: dict) -> list:
    """[(topic, item)] that are fresh, keyword-matched and new to this user."""
    from core.news import _region
    from core import profile
    kw = profile.ensure_keywords(u["uid"]) if store.interests(u) else {}
    region = _region(u.get("timezone"))
    now = datetime.now(timezone.utc)
    picked, seen_now = [], []
    for topic in store.interests(u)[:10]:
        items = sources.gather(topic, kw.get(topic, []), region, limit=8, free_only=True)
        fresh = [i for i in items if i.get("published")
                 and (now - i["published"]).total_seconds() < LIVE_MAX_AGE_HOURS * 3600]
        seen_now += [_key(i) for i in items]
        new = [i for i in fresh if not store.seen_before(u["uid"], _key(i))]
        picked += [(topic, i) for i in new[:PER_TOPIC]]
    store.mark_seen(u["uid"], seen_now)
    picked.sort(key=lambda ti: -ti[1].get("score", 0))
    return picked[:PER_MESSAGE]


def format_live(picked: list, heading: str = "Latest for you") -> str:
    """Telegram HTML: topic headings, linked headlines, source and age."""
    out, last = [f"<b>{html.escape(heading)}</b>"], None
    for topic, it in sorted(picked, key=lambda ti: ti[0]):
        if topic != last:
            out.append(f"\n<b>{html.escape(topic)}</b>")
            last = topic
        where = it["source"] if it["platform"] in ("News", "Web") else f"{it['platform']} {it['source']}".strip()
        age = _age(it)
        meta = html.escape(where + (", " + age if age else ""))
        out.append(f'• <a href="{html.escape(it["url"], quote=True)}">{html.escape(it["title"])}</a> ({meta})')
    out.append("\nChange topics: /interests   How often: /updates")
    return "\n".join(out)


def run_live(send):
    """Scheduler job. send(text, chat_id) -> bool."""
    users = store.all_users()
    start = store.kv_get("live_rotate", 0) % max(len(users), 1)
    users = users[start:] + users[:start]
    fetched = set()
    for n, u in enumerate(users):
        if u.get("blocked") or not u.get("news_on") or u.get("news_mode") != "live":
            continue
        if u.get("state") != "active" or not u.get("chat_id") or not store.interests(u):
            continue
        local = datetime.now(store.user_tz(u))
        if local.hour >= QUIET_START or local.hour < QUIET_END:
            continue
        day_key = f"live_count:{u['uid']}:{local:%Y-%m-%d}"
        if store.kv_get(day_key, 0) >= LIVE_MAX_PER_DAY:
            continue
        need = {t.lower() for t in store.interests(u)[:10]} - fetched
        if len(fetched | need) > LIVE_MAX_TOPICS_PER_RUN:
            store.kv_set("live_rotate", start + n)  # out of fetch budget: this user goes first next time
            print(f"Live updates: topic cap reached ({LIVE_MAX_TOPICS_PER_RUN}); continuing next run")
            return
        fetched |= need
        try:
            first_run = not store.kv_get(f"live_seeded:{u['uid']}")
            picked = collect_live(u)
            if first_run:
                store.kv_set(f"live_seeded:{u['uid']}", True)  # everything current is now "seen"
                continue
            if picked:
                if send(format_live(picked), u["chat_id"]):
                    store.kv_set(day_key, store.kv_get(day_key, 0) + 1)
                else:
                    store.update_user(u["uid"], news_on=0)
        except Exception as e:
            print(f"Live updates failed for {u['uid']}: {e}")
    store.kv_set("live_rotate", 0)


def latest_now(uid: str, per_topic: int = 2) -> str:
    """A quick 'here's what's happening' right after someone picks topics (free, no AI)."""
    u = store.get_user(uid) or {}
    from core.news import _region
    region = _region(u.get("timezone"))
    from core import profile
    kw = profile.ensure_keywords(uid)
    picked = []
    for topic in store.interests(u)[:6]:
        items = sources.gather(topic, kw.get(topic, []), region, limit=per_topic, free_only=True)
        picked += [(topic, i) for i in items[:per_topic]]
        store.mark_seen(uid, [_key(i) for i in items])
    if not picked:
        return ""
    store.kv_set(f"live_seeded:{uid}", True)
    return format_live(picked, "Here's what's happening right now")
