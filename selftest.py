"""Check every live service the agent depends on. Run from the my-agent folder:

    source venv/bin/activate
    python selftest.py           # quick check (costs under $0.001 and 2 Serper searches)
    python selftest.py --voice   # also downloads/loads the voice model (~150 MB the first time)

Prints OK / WARN / FAIL for each part with a fix for anything broken.
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()
results = []


def check(name, fn, fix="", warn_only=False):
    t = time.time()
    try:
        detail = fn() or ""
        results.append(("OK", name, detail, ""))
    except Exception as e:
        results.append(("WARN" if warn_only else "FAIL", name, f"{type(e).__name__}: {str(e)[:150]}", fix))
    status, _, detail, fx = results[-1]
    print(f"{status:<5} {name} ({time.time() - t:.1f}s) {detail}")
    if fx and status != "OK":
        print(f"      fix: {fx}")


def env_keys():
    need = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID", "SERPER_API_KEY"]
    missing = [k for k in need if not os.getenv(k)]
    if missing:
        raise RuntimeError("missing " + ", ".join(missing))
    return "all required keys set"


def anthropic_call():
    from core import llm
    c = llm.Client("selftest")
    r = c.messages.create(_uid="owner", model="claude-haiku-4-5-20251001", max_tokens=5,
                          messages=[{"role": "user", "content": "Reply with OK"}])
    return f"Haiku replied '{r.content[0].text.strip()}'"


def sonnet_call():
    from core import llm
    c = llm.Client("selftest")
    r = c.messages.create(_uid="owner", model="claude-sonnet-5-5", max_tokens=5,
                          messages=[{"role": "user", "content": "Reply with OK"}])
    return f"Sonnet 5.5 replied '{r.content[0].text.strip()}'"


def telegram():
    import requests
    r = requests.get(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/getMe", timeout=15).json()
    if not r.get("ok"):
        raise RuntimeError(r.get("description"))
    return "@" + r["result"]["username"]


def serper():
    from core.tools import web_search
    out = web_search("India news today")
    if out.startswith("Search failed") or out == "No results found.":
        raise RuntimeError(out[:150])
    return "search works"


def gnews():
    from core import sources
    items = sources.google_news("India", "in")
    if not items:
        raise RuntimeError("no items returned")
    return f"{len(items)} stories"


def reddit():
    from core import sources
    items = sources._reddit_get("/search", {"q": "India", "sort": "new", "t": "day", "limit": 5})
    if not items:
        raise RuntimeError("no posts returned")
    return f"{len(items)} posts ({'official API' if os.getenv('REDDIT_CLIENT_ID') else 'public access'})"


def hn():
    from core import sources
    sources.hacker_news("AI")
    h = sources.HEALTH.get("hn", {})
    if h.get("fails"):
        raise RuntimeError(h.get("err"))
    return "reachable"


def social():
    from core import sources
    items = sources.social('"India"', "in")
    h = sources.HEALTH.get("social", {})
    if h.get("fails"):
        raise RuntimeError(h.get("err"))
    return f"{len(items)} indexed posts from X/Instagram/Threads"


def read_link():
    from core.web import read_url
    out = read_url("https://example.com")
    if "Example Domain" not in out:
        raise RuntimeError(out[:150])
    return "web pages readable"


def transcript():
    from core.web import youtube_transcript
    text = youtube_transcript("dQw4w9WgXcQ")
    return f"{len(text.split())} words"


def ytdlp():
    import yt_dlp
    return f"version {yt_dlp.version.__version__}"


def voice_ready():
    from core import voice
    if not voice.available():
        raise RuntimeError("faster-whisper not installed")
    if "--voice" in sys.argv:
        voice._get_model()
        return f"model '{voice.WHISPER_MODEL}' loaded"
    return "installed (run with --voice to load the model)"


def database():
    from core import store
    store.kv_set("selftest", time.time())
    return f"{len(store.all_users())} users, {len(store.list_watches())} alerts"


def scheduler():
    from core import store
    tick = store.kv_get("scheduler_tick")
    if not tick:
        raise RuntimeError("never ran (is the agent running?)")
    age = time.time() - tick
    if age > 300:
        raise RuntimeError(f"last ran {int(age // 60)} min ago (agent stopped or Mac was asleep)")
    return f"last ran {int(age)}s ago"


if __name__ == "__main__":
    print("Agent self-test\n")
    check(".env keys", env_keys, "copy missing keys from .env.example into .env")
    check("Anthropic (Haiku)", anthropic_call, "run python check_keys.py; top up at console.anthropic.com")
    check("Anthropic (Sonnet 5.5)", sonnet_call, "your account may not have this model yet; tell Claude")
    check("Telegram bot", telegram, "get a new token from @BotFather (/mybots > API Token)")
    check("Serper web search", serper, "check credits at serper.dev")
    check("Google News", gnews, "check your internet connection")
    check("Reddit", reddit, "add REDDIT_CLIENT_ID/SECRET (reddit.com/prefs/apps, 'script' app)", warn_only=True)
    check("Hacker News", hn, "", warn_only=True)
    check("X/Instagram/Threads", social, "needs Serper credits; or set NEWS_SOCIAL=false", warn_only=True)
    check("Read links", read_link, "check your internet connection")
    check("YouTube transcripts", transcript, "YouTube sometimes blocks; usually temporary", warn_only=True)
    check("Video downloads (yt-dlp)", ytdlp, "pip install -U yt-dlp")
    check("Voice notes", voice_ready, "pip install faster-whisper", warn_only=True)
    check("Database", database, "check the data/ folder is writable")
    check("Scheduler", scheduler, "start the agent with python main.py, then rerun", warn_only=True)

    bad = [r for r in results if r[0] == "FAIL"]
    warn = [r for r in results if r[0] == "WARN"]
    print(f"\n{len(results) - len(bad) - len(warn)} OK, {len(warn)} warnings, {len(bad)} failed")
    sys.exit(1 if bad else 0)
