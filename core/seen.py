"""Never send the same story twice.

A story counts as already sent if its link was sent before, or if its headline is close to one sent in the last
REMEMBER_HOURS (the same story from a different outlet: "Verstappen wins in Austin" vs "Austin GP: Verstappen
takes the win"). Each feed keeps its own memory ("scope"), and a feed can also check other scopes.
"""
import hashlib
import re
import time

from core import store

REMEMBER_HOURS = 72
MAX_TITLES = 800

STOP = set("""a an the and or but of to in on at for with by from as is are was were be been has have had it its this
that these those after before over under into about amid says said say new news latest live update updates today report
reports vs v how why what who when where will would can could may might just more than out up down off""".split())


def _words(title: str) -> set:
    t = re.sub(r"[^a-z0-9ऀ-෿ ]+", " ", (title or "").lower())
    return {w for w in t.split() if w not in STOP and len(w) > 1}


def same_story(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if len(wa) < 2 or len(wb) < 2:
        return (a or "").strip().lower() == (b or "").strip().lower()
    inter = len(wa & wb)
    return inter / len(wa | wb) >= 0.5 or (inter >= 3 and inter / min(len(wa), len(wb)) >= 0.7)


def _url_key(item: dict) -> str:
    url = (item.get("url") or "").split("#")[0].rstrip("/")
    return "u:" + hashlib.sha1((url or item.get("title", "")).encode()).hexdigest()[:16]


def _titles(scope: str) -> list:
    cutoff = time.time() - REMEMBER_HOURS * 3600
    return [t for ts, t in store.kv_get(f"sent_titles:{scope}", []) if ts > cutoff]


def filter_new(scopes, items: list) -> list:
    """Items not sent before in any of `scopes`, with same-story duplicates inside the list removed too."""
    scopes = [scopes] if isinstance(scopes, str) else list(scopes)
    old_titles = [t for s in scopes for t in _titles(s)]
    out = []
    for it in items:
        if any(store.seen_before(s, _url_key(it)) for s in scopes):
            continue
        title = it.get("title", "")
        if any(same_story(title, t) for t in old_titles):
            continue
        if any(same_story(title, o.get("title", "")) for o in out):
            continue
        out.append(it)
    return out


def remember(scope: str, items: list):
    if not items:
        return
    store.mark_seen(scope, [_url_key(i) for i in items])
    now = time.time()
    cutoff = now - REMEMBER_HOURS * 3600
    kept = [[ts, t] for ts, t in store.kv_get(f"sent_titles:{scope}", []) if ts > cutoff]
    kept += [[now, i.get("title", "")] for i in items if i.get("title")]
    store.kv_set(f"sent_titles:{scope}", kept[-MAX_TITLES:])


def scopes_for(uid: str) -> list:
    """The owner gets several feeds (hourly latest, briefings, topic updates): none may repeat another."""
    return [uid, "owner|latest", "owner|brief"] if uid == "owner" else [uid]


def forget(scope: str):
    store.kv_set(f"sent_titles:{scope}", [])
