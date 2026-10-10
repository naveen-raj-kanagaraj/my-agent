"""News without link clutter.

News messages show short summaries only. Their links are kept here so the person can tap "Links" under the message,
or just ask the bot ("send me the link for the cricket one"): recent news is shown to the agent for 24h.
"""
import re
import secrets
import time

from core import store

KEEP = 30            # link sets kept per person
RECENT_HOURS = 24    # how long the agent remembers what news it sent
RECENT_MAX = 25

CITE = re.compile(r"\s*\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")


def save(uid: str, items: list) -> str:
    """Store the links for one news message; returns the key for its Links button."""
    rows = [[i.get("title", ""), i.get("url", ""), i.get("source", "")] for i in items if i.get("url")]
    if not rows:
        return ""
    key = secrets.token_urlsafe(5)
    sets = store.kv_get(f"newslinks:{uid}", {})
    sets[key] = {"at": time.time(), "items": rows}
    if len(sets) > KEEP:
        for old in sorted(sets, key=lambda k: sets[k]["at"])[:len(sets) - KEEP]:
            sets.pop(old)
    store.kv_set(f"newslinks:{uid}", sets)
    store.kv_set(f"newslinks_last:{uid}", key)
    cutoff = time.time() - RECENT_HOURS * 3600
    recent = [r for r in store.kv_get(f"recent_news:{uid}", []) if r[0] > cutoff]
    recent += [[time.time(), t, u, s] for t, u, s in rows]
    store.kv_set(f"recent_news:{uid}", recent[-RECENT_MAX:])
    return key


def last_key(uid: str) -> str:
    return store.kv_get(f"newslinks_last:{uid}") or ""


def links_text(uid: str, key: str) -> str:
    entry = store.kv_get(f"newslinks:{uid}", {}).get(key)
    if not entry:
        return "Those links have expired. Ask me about the story and I'll find it again."
    lines = [f"{n}. {t}" + (f" ({s})" if s else "") + f"\n{u}" for n, (t, u, s) in enumerate(entry["items"], 1)]
    return "Links\n\n" + "\n\n".join(lines)


def markup(key: str):
    """Inline keyboard as plain JSON (for the raw Bot API) or None."""
    return {"inline_keyboard": [[{"text": "Links", "callback_data": f"nl:{key}"}]]} if key else None


def recent_block(uid: str) -> str:
    """For the system prompt: what news we sent them lately, so 'link for that IPL story?' works."""
    cutoff = time.time() - RECENT_HOURS * 3600
    recent = [r for r in store.kv_get(f"recent_news:{uid}", []) if r[0] > cutoff]
    if not recent:
        return ""
    lines = "\n".join(f"- {t} ({s}): {u}" for _, t, u, s in recent[-RECENT_MAX:])
    return ("NEWS YOU SENT THEM RECENTLY (headline, source, link). If they ask about one of these or want a link, "
            "use this. Don't paste links unless they ask:\n" + lines)


def numbered(items: list) -> str:
    return "\n".join(f"[{n}] {i}" for n, i in enumerate(items, 1))


def take_citations(text: str, items: list) -> tuple:
    """The model ends each story with [n] item numbers. Returns (text without them, items it used)."""
    used, seen_n = [], set()
    for m in CITE.finditer(text):
        for n in re.split(r"\s*,\s*", m.group(1)):
            k = int(n)
            if 1 <= k <= len(items) and k not in seen_n:
                seen_n.add(k)
                used.append(items[k - 1])
    clean = CITE.sub("", text)
    clean = re.sub(r"https?://\S+", "", clean)          # just in case a link slipped through
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    return clean.strip(), used
