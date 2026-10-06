"""Multi-source news gathering with keyword matching.

Sources (free unless noted):
  Google News RSS  - thousands of news websites, no key
  Reddit           - public search JSON, or official API if REDDIT_CLIENT_ID/SECRET are set
  Hacker News      - Algolia API, no key
  X / Instagram / Threads - public posts that Google has indexed (Serper, 1 credit per query)
  YouTube          - recent videos (Serper, 1 credit per query)
  Your own RSS feeds - NEWS_FEEDS in .env (comma-separated URLs)

Every item is scored against the user's keywords: title hits count most, then how recent it is
(newest first), then snippet hits and engagement. Near-duplicate stories across sources are merged.
"""
import html
import math
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

import requests


def store_bump(name):
    try:
        from core import store
        store.bump(name)
    except Exception:
        pass

UA = "pesagent-news/1.0 (personal news assistant)"
# How far back to look, and how long to reuse a search before checking again.
MAX_AGE_HOURS = int(os.getenv("NEWS_WINDOW_HOURS", "24"))
CACHE_SECONDS = int(os.getenv("NEWS_CACHE_MINUTES", "30")) * 60

SOCIAL = os.getenv("NEWS_SOCIAL", "true").lower() == "true"      # X/IG/Threads via Google index
YOUTUBE = os.getenv("NEWS_YOUTUBE", "true").lower() == "true"
FEEDS = [f.strip() for f in os.getenv("NEWS_FEEDS", "").split(",") if f.strip()]

_cache = {}
_lock = threading.Lock()
# Per-source health for /status: {kind: {"ok": ts, "fail": ts, "err": str, "fails": consecutive}}
HEALTH = {}
SOURCE_NAMES = {"gnews": "Google News", "reddit": "Reddit", "subreddit": "Reddit", "hn": "Hacker News",
                "social": "X/Instagram/Threads (Serper)", "youtube": "YouTube (Serper)", "feed": "Your RSS feeds"}
_reddit_token = {"value": None, "exp": 0}


def _cached(key, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    kind = key[0]
    try:
        val = fn()
        with _lock:
            h = HEALTH.setdefault(kind, {})
            h.update(ok=time.time(), fails=0)
    except Exception as e:
        err = str(e)[:160]
        print(f"Source {kind} failed for '{key[1]}': {err}")
        val = []
        with _lock:
            h = HEALTH.setdefault(kind, {})
            h.update(fail=time.time(), err=err, fails=h.get("fails", 0) + 1)
            fails = h["fails"]
        if fails >= 3:
            from core import alerts
            hint = ""
            if kind in ("reddit", "subreddit") and ("403" in err or "429" in err):
                hint = " Reddit may be blocking this network; add REDDIT_CLIENT_ID/SECRET to .env."
            alerts.notify(f"source:{kind}", f"{SOURCE_NAMES.get(kind, kind)} has failed {fails} times in a row "
                          f"({err[:120]}). News still works from the other sources.{hint}", 360)
    with _lock:
        _cache[key] = (time.time(), val)
    return val


def _item(title, url, source, platform, published=None, snippet="", engagement=0):
    return {
        "title": html.unescape(re.sub(r"<[^>]+>", "", title or "")).strip(),
        "snippet": html.unescape(re.sub(r"<[^>]+>", " ", snippet or "")).strip()[:400],
        "url": url or "",
        "source": source or "",
        "platform": platform,
        "published": published,
        "engagement": engagement or 0,
    }


def _parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _relative_date(s):
    """Serper gives '3 hours ago' style dates."""
    if not s:
        return None
    m = re.match(r"(\d+)\s+(minute|hour|day|week)s?\s+ago", s.lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n),
             "day": timedelta(days=n), "week": timedelta(weeks=n)}[unit]
    return datetime.now(timezone.utc) - delta


# ---------- sources ----------

GN_LOCALE = {"in": ("en-IN", "IN", "IN:en"), "us": ("en-US", "US", "US:en"), "gb": ("en-GB", "GB", "GB:en"),
             "au": ("en-AU", "AU", "AU:en"), "sg": ("en-SG", "SG", "SG:en"), "ae": ("en-AE", "AE", "AE:en")}


def google_news(query: str, region: str = "us") -> list:
    hl, gl, ceid = GN_LOCALE.get(region, GN_LOCALE["us"])

    def fetch():
        window = f"{MAX_AGE_HOURS}h" if MAX_AGE_HOURS <= 24 else f"{math.ceil(MAX_AGE_HOURS / 24)}d"
        url = (f"https://news.google.com/rss/search?q={quote_plus(query + ' when:' + window)}"
               f"&hl={hl}&gl={gl}&ceid={ceid}")
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        r.raise_for_status()
        out = []
        for it in ET.fromstring(r.content).iter("item"):
            title = it.findtext("title") or ""
            src = it.find("source")
            source = src.text if src is not None else ""
            if source and title.endswith(" - " + source):
                title = title[: -len(source) - 3]
            out.append(_item(title, it.findtext("link"), source, "News",
                             _parse_date(it.findtext("pubDate")), it.findtext("description") or ""))
        out.sort(key=lambda i: i["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return out[:20]  # newest first
    return _cached(("gnews", query, region), fetch)


def _reddit_oauth():
    cid, secret = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    if _reddit_token["value"] and time.time() < _reddit_token["exp"] - 60:
        return _reddit_token["value"]
    r = requests.post("https://www.reddit.com/api/v1/access_token", auth=(cid, secret),
                      data={"grant_type": "client_credentials"}, headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    data = r.json()
    _reddit_token.update(value=data["access_token"], exp=time.time() + data.get("expires_in", 3600))
    return _reddit_token["value"]


def _reddit_get(path: str, params: dict) -> list:
    token = _reddit_oauth()
    if token:
        r = requests.get(f"https://oauth.reddit.com{path}", params=params,
                         headers={"User-Agent": UA, "Authorization": f"bearer {token}"}, timeout=15)
    else:
        r = requests.get(f"https://www.reddit.com{path}.json", params=params, headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    out = []
    for c in r.json().get("data", {}).get("children", []):
        p = c["data"]
        if p.get("over_18") or p.get("stickied"):
            continue
        out.append(_item(
            p.get("title"), "https://www.reddit.com" + p.get("permalink", ""), f"r/{p.get('subreddit')}",
            "Reddit", datetime.fromtimestamp(p.get("created_utc", 0), timezone.utc),
            p.get("selftext", ""), p.get("score", 0) + 2 * p.get("num_comments", 0)))
    return out


def reddit(query: str) -> list:
    """Newest matching posts across all of Reddit, plus what's rising today."""
    def fetch():
        base = {"q": query, "t": "day", "limit": 20, "type": "link"}
        newest = _reddit_get("/search", {**base, "sort": "new"})
        try:
            rising = _reddit_get("/search", {**base, "sort": "hot", "limit": 10})
        except Exception:
            rising = []
        return newest + rising
    return _cached(("reddit", query, ""), fetch)


def subreddit_latest(sub: str, limit: int = 15) -> list:
    """Newest posts in one subreddit, plus its current hot posts."""
    def fetch():
        newest = _reddit_get(f"/r/{sub}/new", {"limit": limit})
        try:
            hot = _reddit_get(f"/r/{sub}/hot", {"limit": 8})
        except Exception:
            hot = []
        return newest + hot
    return _cached(("subreddit", sub, ""), fetch)


def hacker_news(query: str) -> list:
    def fetch():
        since = int(time.time() - MAX_AGE_HOURS * 3600)
        r = requests.get("https://hn.algolia.com/api/v1/search_by_date",  # newest first
                         params={"query": query, "tags": "story", "numericFilters": f"created_at_i>{since}",
                                 "hitsPerPage": 10}, timeout=15)
        r.raise_for_status()
        return [_item(h.get("title"), h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                      "Hacker News", "Hacker News",
                      datetime.fromtimestamp(h.get("created_at_i", 0), timezone.utc), "",
                      (h.get("points") or 0) + 2 * (h.get("num_comments") or 0))
                for h in r.json().get("hits", [])]
    return _cached(("hn", query, ""), fetch)


def _serper(endpoint: str, q: str, region: str, num: int = 10) -> list:
    key = os.getenv("SERPER_API_KEY")
    if not key:
        return []
    r = requests.post(f"https://google.serper.dev/{endpoint}",
                      headers={"X-API-KEY": key, "Content-Type": "application/json"},
                      json={"q": q, "num": num, "tbs": "qdr:d", "gl": region}, timeout=15)
    store_bump("serper")
    if r.status_code in (400, 401, 403) and "credit" in r.text.lower():
        from core import alerts
        alerts.notify("serper_credits", "Serper is out of credits, so web search, X/Instagram and YouTube results "
                      "are off. Top up at serper.dev, or set NEWS_SOCIAL=false and NEWS_YOUTUBE=false.", 360)
    r.raise_for_status()
    return r.json().get("organic" if endpoint == "search" else endpoint, [])


def _platform_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("x.com") or host.endswith("twitter.com"):
        return "X"
    if "instagram.com" in host:
        return "Instagram"
    if "threads.net" in host or "threads.com" in host:
        return "Threads"
    return "Web"


def social(query: str, region: str = "us") -> list:
    """Public X, Instagram and Threads posts from Google's index (one Serper credit)."""
    if not SOCIAL:
        return []

    def fetch():
        q = f"{query} (site:x.com OR site:instagram.com OR site:threads.net)"
        return [_item(o.get("title"), o.get("link"), _platform_of(o.get("link", "")), _platform_of(o.get("link", "")),
                      _relative_date(o.get("date")), o.get("snippet", ""))
                for o in _serper("search", q, region)]
    return _cached(("social", query, region), fetch)


def youtube(query: str, region: str = "us") -> list:
    if not YOUTUBE:
        return []

    def fetch():
        return [_item(v.get("title"), v.get("link"), v.get("channel", "YouTube"), "YouTube",
                      _relative_date(v.get("date")), v.get("snippet", ""))
                for v in _serper("videos", query, region, 8)]
    return _cached(("youtube", query, region), fetch)


def custom_feeds() -> list:
    """Items from the RSS/Atom feeds listed in NEWS_FEEDS (filtered by keywords later)."""
    items = []
    for feed in FEEDS:
        def fetch(feed=feed):
            r = requests.get(feed, headers={"User-Agent": UA}, timeout=15)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            out = []
            name = urlparse(feed).hostname or feed
            for it in root.iter("item"):  # RSS
                out.append(_item(it.findtext("title"), it.findtext("link"), name, "Web",
                                 _parse_date(it.findtext("pubDate")), it.findtext("description") or ""))
            ns = "{http://www.w3.org/2005/Atom}"
            for e in root.iter(ns + "entry"):  # Atom
                link = e.find(ns + "link")
                out.append(_item(e.findtext(ns + "title"), link.get("href") if link is not None else "", name, "Web",
                                 _parse_date(e.findtext(ns + "updated") or e.findtext(ns + "published")),
                                 e.findtext(ns + "summary") or ""))
            return out[:40]
        items += _cached(("feed", feed, ""), fetch)
    return items


# ---------- matching ----------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9ऀ-෿ ]+", " ", (s or "").lower())


def _hits(text: str, keywords: list) -> int:
    t = f" {_norm(text)} "
    return sum(1 for k in keywords if f" {_norm(k).strip()} " in t)


def score(item: dict, keywords: list) -> float:
    title_hits = _hits(item["title"], keywords)
    body_hits = _hits(item["snippet"], keywords)
    if title_hits + body_hits == 0:
        return 0.0
    s = 3.0 * title_hits + 1.0 * body_hits
    if item.get("published"):
        age_h = (datetime.now(timezone.utc) - item["published"]).total_seconds() / 3600
        if age_h > MAX_AGE_HOURS:
            return 0.0
        s += 4.0 * max(0.0, 1.0 - age_h / MAX_AGE_HOURS)  # up to +4: newest posts rank first
    s += min(2.0, math.log10(1 + item.get("engagement", 0)) / 2)  # up to +2 for buzz
    return s


def _similar(a: str, b: str) -> bool:
    ta, tb = set(_norm(a).split()), set(_norm(b).split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) > 0.55


def dedupe(items: list) -> list:
    """Keep the best-scoring copy of each story; remember where else it appeared."""
    out = []
    for it in sorted(items, key=lambda x: -x["score"]):
        dup = next((o for o in out if _similar(o["title"], it["title"])), None)
        if dup:
            if it["platform"] not in dup["also_on"] and it["platform"] != dup["platform"]:
                dup["also_on"].append(it["platform"])
            continue
        out.append({**it, "also_on": []})
    return out


def gather(topic: str, keywords: list, region: str = "us", limit: int = 6, free_only: bool = False) -> list:
    """All sources for one topic, scored against its keywords."""
    keywords = [k for k in dict.fromkeys([topic] + keywords) if k.strip()][:8]
    # Search with the two strongest phrasings; match against all keywords.
    queries = keywords[:2]
    items = []
    for q in queries:
        items += google_news(q, region)
        items += reddit(q)
    items += hacker_news(keywords[0])
    if not free_only:  # X/IG/Threads and YouTube cost Serper credits
        items += social(" OR ".join(f'"{k}"' for k in keywords[:3]), region)
        items += youtube(keywords[0], region)
    items += custom_feeds()
    seen, scored = set(), []
    for it in items:
        if not it["url"] or it["url"] in seen:
            continue
        seen.add(it["url"])
        s = score(it, keywords)
        if s > 0:
            scored.append({**it, "score": s})
    return dedupe(scored)[:limit]
