"""Learning about each user from what they say and send."""
import json
import re
import threading
from zoneinfo import ZoneInfo

import anthropic

from core import store

client = anthropic.Anthropic()
LEARN_MODEL = "claude-haiku-4-5-20251001"
LEARN_EVERY = 5          # update the profile after every N user messages
MAX_INTERESTS = 8


def _json_from(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _valid_tz(tz: str) -> str:
    try:
        ZoneInfo(tz)
        return tz
    except Exception:
        return ""


def _clean_interests(items) -> list:
    out = []
    for i in items or []:
        i = str(i).strip()[:60]
        if i and i.lower() not in [o.lower() for o in out]:
            out.append(i)
    return out[:MAX_INTERESTS]


def extract_onboarding(text: str) -> dict:
    """Turn a free-text answer ('BGMI, startups, F1. I'm in Chennai') into structured fields."""
    resp = client.messages.create(
        model=LEARN_MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": (
            "A new user of a personal assistant bot answered: 'What are you interested in, and which city are you in?'\n"
            f"Their answer:\n<<<\n{text[:2000]}\n>>>\n\n"
            "Return only JSON with keys:\n"
            '"interests": list of 2-8 specific news/learning topics they care about (short phrases, keep their specifics, e.g. "BGMI esports", "Indian startup funding"),\n'
            '"city": city or country if mentioned else "",\n'
            '"timezone": IANA timezone for that place (e.g. "Asia/Kolkata") or "" if unknown,\n'
            '"name": their name if they said it else "",\n'
            '"language": the language they wrote in (e.g. "English", "Tamil", "Hinglish").'
        )}],
    )
    data = _json_from(resp.content[0].text)
    return {
        "interests": _clean_interests(data.get("interests")),
        "city": str(data.get("city") or "")[:60],
        "timezone": _valid_tz(str(data.get("timezone") or "")),
        "name": str(data.get("name") or "")[:60],
        "language": str(data.get("language") or "")[:30],
    }


def apply_onboarding(uid: str, info: dict):
    fields = {"state": "active"}
    if info.get("interests"):
        fields["interests"] = info["interests"]
    if info.get("timezone"):
        fields["timezone"] = info["timezone"]
    if info.get("language"):
        fields["language"] = info["language"]
    u = store.get_user(uid) or {}
    if info.get("name") and not u.get("name"):
        fields["name"] = info["name"]
    store.update_user(uid, **fields)
    if info.get("city"):
        store.add_fact(uid, f"Based in {info['city']}")


def _learn(uid: str, recent_user_msgs: list):
    u = store.get_user(uid)
    if not u:
        return
    current = {
        "interests": store.interests(u),
        "profile": u.get("profile") or "",
        "timezone": u.get("timezone") or "",
        "language": u.get("language") or "",
    }
    convo = "\n---\n".join(m[:1500] for m in recent_user_msgs[-12:])
    try:
        resp = client.messages.create(
            model=LEARN_MODEL,
            max_tokens=700,
            messages=[{"role": "user", "content": (
                "You maintain a short profile of a user of a personal assistant so future answers and their daily news "
                "can be personalised. Update it using their recent messages (which may include text from files, links "
                "or images they shared).\n\n"
                f"Current profile JSON:\n{json.dumps(current, ensure_ascii=False)}\n\n"
                f"Their recent messages:\n<<<\n{convo}\n>>>\n\n"
                "Rules: keep what is still true, add what is new, drop interests they clearly lost interest in. "
                "Only record things they actually revealed; never guess sensitive traits (health, religion, politics, "
                "sexuality) unless they stated them and they matter for helping them. Profile is at most 120 words "
                "covering who they are, what they're working on, goals, and how they like answers. "
                f"Interests: at most {MAX_INTERESTS} specific topics for their news.\n"
                'Return only JSON: {"interests": [...], "profile": "...", "timezone": "IANA or empty", '
                '"language": "...", "new_facts": ["durable facts worth remembering, max 3, or empty"]}'
            )}],
        )
    except Exception as e:
        print(f"Profile learning failed for {uid}: {e}")
        return
    data = _json_from(resp.content[0].text)
    if not data:
        return
    fields = {}
    if data.get("interests"):
        fields["interests"] = _clean_interests(data["interests"])
    if isinstance(data.get("profile"), str) and data["profile"].strip():
        fields["profile"] = data["profile"].strip()[:1200]
    tz = _valid_tz(str(data.get("timezone") or ""))
    if tz and uid != "owner":
        fields["timezone"] = tz
    if data.get("language"):
        fields["language"] = str(data["language"])[:30]
    store.update_user(uid, **fields)
    existing = {f["fact"].lower() for f in store.get_facts(uid, 100)}
    for fact in (data.get("new_facts") or [])[:3]:
        fact = str(fact).strip()
        if fact and fact.lower() not in existing:
            store.add_fact(uid, fact)


def note_message(uid: str, history: list):
    """Call after each user message; every LEARN_EVERY messages, learn in the background."""
    u = store.get_user(uid)
    if not u:
        return
    count = (u.get("msg_count") or 0) + 1
    store.update_user(uid, msg_count=count)
    if count % LEARN_EVERY == 0:
        msgs = [m["content"] for m in history if m.get("role") == "user" and isinstance(m.get("content"), str)]
        threading.Thread(target=_learn, args=(uid, msgs), daemon=True).start()


def profile_block(uid: str) -> str:
    """What the agent knows about this user, added to the system prompt each turn."""
    u = store.get_user(uid)
    if not u:
        return ""
    lines = []
    if u.get("name"):
        lines.append(f"Name: {u['name']}")
    ints = store.interests(u)
    if ints:
        lines.append("Interests: " + ", ".join(ints))
    if u.get("language"):
        lines.append(f"Writes in: {u['language']} (reply in the same language they use)")
    if u.get("timezone"):
        lines.append(f"Timezone: {u['timezone']}")
    if u.get("profile"):
        lines.append(f"Profile: {u['profile']}")
    facts = store.get_facts(uid, 30)
    if facts:
        lines.append("Things they asked you to remember or you learned:\n" + "\n".join(f"- {f['fact']}" for f in facts))
    if not lines:
        return ""
    return "WHAT YOU KNOW ABOUT THIS USER (use it naturally, don't recite it):\n" + "\n".join(lines)
