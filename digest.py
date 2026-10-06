import os
import requests
import schedule
import time
import threading
from datetime import datetime
from core.tools import web_search
from core import store
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from dotenv import load_dotenv
from core import llm
import re
import discord
import asyncio
import json

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_USER_ID = (os.getenv("ALLOWED_DISCORD_IDS") or "").split(",")[0]
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID")

# Where briefs go: telegram, discord, or both
DIGEST_TO = os.getenv("DIGEST_TO", "telegram").lower()
# Local times for the two daily briefs, and minutes between breaking-news checks
DIGEST_TIMES = [t.strip() for t in os.getenv("DIGEST_TIMES", "08:00,19:00").split(",") if t.strip()]
BREAKING_EVERY_MIN = int(os.getenv("BREAKING_EVERY_MIN", "60"))
client = llm.Client("digest")

NEWS_TIMES = [t.strip() for t in os.getenv("NEWS_TIMES", "08:00,19:00").split(",") if t.strip()]
RADAR_TIME = os.getenv("RADAR_TIME", "10:00")  # owner's local time; empty disables
NEWS_WINDOW_MIN = int(os.getenv("NEWS_CATCHUP_MIN", "180"))  # if the bot was down at 8:00, still send until 11:00
OFFLINE_ALERT_MIN = 10


def report_downtime(now: float = None):
    """On start-up, tell the owner how long the bot was offline (Mac asleep, Wi-Fi down, crash)."""
    now = now or time.time()
    last = store.kv_get("scheduler_tick")
    if not last or now - last < OFFLINE_ALERT_MIN * 60:
        return None
    mins = int((now - last) // 60)
    tz = store.user_tz({"timezone": store.OWNER_TZ})
    frm = datetime.fromtimestamp(last, tz).strftime("%a %I:%M %p")
    to = datetime.fromtimestamp(now, tz).strftime("%I:%M %p")
    dur = f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins} min"
    log = (store.kv_get("downtime_log", []) + [{"from": last, "to": now}])[-20:]
    store.kv_set("downtime_log", log)
    text = (f"I was offline for {dur} ({frm} to {to}). Reminders that came due are being sent now, and news "
            f"briefs missed in the last {NEWS_WINDOW_MIN // 60}h will catch up. Live updates and messages sent to me "
            "while I was down were not answered.")
    from core import alerts
    alerts.send_owner(text)
    return text


def load_covered_news() -> list:
    return store.kv_get("covered_news", [])


def save_covered_news(news: list):
    store.kv_set("covered_news", news[-100:])


def send_discord(message: str):
    try:
        async def _send():
            intents = discord.Intents.default()
            dc = discord.Client(intents=intents)

            @dc.event
            async def on_ready():
                user = await dc.fetch_user(int(DISCORD_USER_ID))
                dm = await user.create_dm()
                chunks = [message[i:i+2000] for i in range(0, len(message), 2000)]
                for chunk in chunks:
                    await dm.send(chunk)
                    await asyncio.sleep(0.5)
                await dc.close()

            await dc.start(DISCORD_BOT_TOKEN)

        asyncio.run(_send())
    except Exception as e:
        print(f"Discord send error: {e}")


def send_telegram(message: str, chat_id: str = None, html: bool = False) -> bool:
    """Send via the Bot API. Returns False if the chat can't be reached (e.g. user blocked the bot)."""
    chat_id = chat_id or OWNER_TELEGRAM_ID
    if not (TELEGRAM_BOT_TOKEN and chat_id):
        print("Telegram send skipped: TELEGRAM_BOT_TOKEN or chat id missing")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    ok = True
    for i in range(0, len(message), 4096):
        try:
            body = {"chat_id": chat_id, "text": message[i:i + 4096]}
            if html:
                body.update(parse_mode="HTML", disable_web_page_preview=True)
            r = requests.post(url, json=body, timeout=20)
            if not r.ok:
                print(f"Telegram send error to {chat_id}: {r.status_code} {r.text[:200]}")
                if r.status_code in (400, 403):
                    return False
                ok = False
        except Exception as e:
            print(f"Telegram send error: {e}")
            ok = False
        time.sleep(0.5)
    return ok


def deliver(message: str):
    if DIGEST_TO in ("telegram", "both"):
        send_telegram(message)
    if DIGEST_TO in ("discord", "both") and DISCORD_BOT_TOKEN:
        send_discord(message)


def search_clean(query: str) -> str:
    results = web_search(query)
    lines = []
    for line in results.split("\n"):
        if not line.startswith("URL:") and not line.startswith("http"):
            lines.append(line)
    return "\n".join(lines)[:600]


def check_breaking_news() -> str:
    breaking = search_clean("breaking news trending right now urgent")
    india_breaking = search_clean("India breaking news trending now")
    return f"{breaking}\n{india_breaking}"


def build_digest():
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    covered = load_covered_news()
    covered_context = "News already covered in previous briefs (do not repeat these): " + ", ".join(covered[-30:]) if covered else ""

    categories = {
        "World News": "breaking news today world",
        "India News": "India news today latest",
        "Tamil Nadu News": "Tamil Nadu news today latest",
        "Global Gaming and Esports": "global gaming esports news investments trends today",
        "Gaming Industry Investments": "gaming industry investments funding acquisitions deals today",
        "Geopolitics": "geopolitics international relations news today",
        "Stocks to Watch": "top stocks unusual movement volume gains today",
        "Crypto Today": "top cryptocurrency gains bitcoin market today",
        "Marketing and Creator Trends": "marketing creator economy social media trends today",
        "Tech and AI": "AI technology news trends today",
        "Finance and Economy": "global finance economy markets inflation interest rates today",
    }

    owner = store.get_user("owner") or {}
    known = " ".join(categories).lower()
    for topic in store.interests(owner)[:3]:
        if topic.lower() not in known:
            categories[topic] = f"{topic} news today"

    raw_data = {}
    for category, query in categories.items():
        google = search_clean(query)
        reddit = search_clean(f"site:reddit.com {query}")
        raw_data[category] = f"{google}\n{reddit}"

    combined = ""
    for category, data in raw_data.items():
        combined += f"\n{category}:\n{data}\n"

    response = client.messages.create(
        _uid="owner",
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": f"""You are a world-class strategic analyst, historian, and mentor. Write a sharp briefing for Naveen, a marketing analytics student at DePaul University who runs a gaming media brand and is building a talent agency, content house, and production studio.

STRICT RULES:
- Plain text only. Zero markdown. No ## no ** no -- no bullet points.
- No URLs or source names.
- Each topic is independent. Do not connect topics to each other.
- Do NOT repeat any news from previous briefs.
- For each topic: write what happened in detail, then the historical parallel, then the prediction. Then immediately write the SWOT for that topic only.
- Each topic section should be 6-10 sentences of detailed analysis. Never cut off mid-sentence.
- SWOT should be 3-4 sentences per quadrant covering that topic specifically.
- Add exactly two line breaks between each topic so it reads cleanly.
- No strategic take. No today's lesson. Do not include these unless asked.

{covered_context}

TOPICS IN ORDER (treat each as completely independent):
{chr(10).join(categories)}

AFTER ALL TOPICS write only:
Trend Radar: 5 early signals most people are missing right now across any of the topics. One sentence each. Each on its own line.

NEWS DATA:
{combined}

Current time: {now}"""
        }]
    )

    analysis = response.content[0].text
    analysis = re.sub(r'#{1,6}\s*', '', analysis)
    analysis = re.sub(r'\*{1,3}', '', analysis)
    analysis = re.sub(r'-{2,}', '', analysis)
    analysis = re.sub(r'\n{3,}', '\n\n', analysis)

    new_covered = []
    for data in raw_data.values():
        lines = [l for l in data.split("\n") if l.startswith("Title:")]
        for line in lines[:2]:
            new_covered.append(line.replace("Title:", "").strip()[:80])
    save_covered_news(covered + new_covered)

    final = f"BRIEFING\n{now}\n\n{analysis.strip()}"
    return final


def check_and_send_breaking():
    breaking = check_breaking_news()
    if not breaking:
        return

    covered = load_covered_news()
    covered_str = " ".join(covered[-30:]).lower()

    response = client.messages.create(
        _uid="owner",
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": f"""You are a breaking news analyst. Based on the news below, identify if there is anything genuinely urgent, trending suddenly, or breaking right now that has NOT already been covered.

Already covered: {covered_str}

New data: {breaking}

If there is something genuinely breaking or suddenly trending that was not covered before, write a brief 3-4 sentence alert starting with BREAKING NEWS. If nothing is new or urgent, respond with only the word NOTHING.

Plain text only. No markdown."""
        }]
    )

    result = response.content[0].text.strip()
    if result != "NOTHING" and "BREAKING" in result:
        deliver(result)
        print(f"Breaking news sent: {result[:100]}")


def send_digest():
    print(f"Sending digest at {datetime.now().strftime('%H:%M')}")
    try:
        digest = build_digest()
        deliver(digest)
        print(f"Digest sent to {DIGEST_TO}.")
    except Exception as e:
        print(f"Digest error: {e}")
        from core import alerts
        alerts.notify("digest", f"Your scheduled briefing failed: {str(e)[:200]}", 120)


def _next_repeat(due_utc: str, repeat: str, tzname: str):
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(tzname or store.OWNER_TZ)
    except Exception:
        tz = ZoneInfo(store.OWNER_TZ)
    due = datetime.fromisoformat(due_utc.replace("Z", "+00:00")).astimezone(tz)
    now = datetime.now(tz)
    step = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "weekdays": timedelta(days=1)}.get(repeat)
    if not step:
        return None
    while due <= now or (repeat == "weekdays" and due.weekday() >= 5):
        due += step
    return store.iso(due)


def send_due_reminders():
    for r in store.due_reminders():
        u = store.get_user(r["uid"]) or {}
        ok = send_telegram(f"Reminder: {r['text']}", r["chat_id"])
        nxt = _next_repeat(r["due_utc"], r["repeat"], u.get("timezone")) if ok or r["repeat"] else None
        store.finish_reminder(r["id"], nxt)


def _send_user_news(u: dict, key: str):
    from core.news import build_user_brief
    store.update_user(u["uid"], last_news_key=key)  # mark first so a slow build never double-sends
    try:
        brief = build_user_brief(u["uid"])
    except Exception as e:
        print(f"News for {u['uid']} failed: {e}")
        return
    if not send_telegram(brief, u["chat_id"]):
        store.update_user(u["uid"], news_on=0)  # they blocked the bot or the chat is gone
        print(f"News off for {u['uid']}: chat unreachable")


_pool = ThreadPoolExecutor(max_workers=3)


def send_user_news():
    for u in store.all_users():
        if not (u.get("news_on") and u.get("state") == "active" and u.get("chat_id")) or u.get("blocked"):
            continue
        if not store.interests(u):
            continue
        now = datetime.now(store.user_tz(u))
        from core.topics import slots_for
        for slot in slots_for(u.get("news_mode") or "both", NEWS_TIMES):
            try:
                hh, mm = map(int, slot.split(":"))
            except ValueError:
                continue
            start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            key = f"{now:%Y-%m-%d}-{slot}"
            if start <= now < start + timedelta(minutes=NEWS_WINDOW_MIN) and u.get("last_news_key") != key:
                _pool.submit(_send_user_news, u, key)


def send_radar():
    from core.radar import build_radar
    try:
        send_telegram(build_radar())
    except Exception as e:
        print(f"Radar error: {e}")
        from core import alerts
        alerts.notify("radar", f"The daily radar failed: {str(e)[:200]}", 360)


def start_digest_scheduler():
    try:
        report_downtime()
    except Exception as e:
        print(f"Downtime report failed: {e}")
    for t in DIGEST_TIMES:
        schedule.every().day.at(t).do(send_digest)
    if BREAKING_EVERY_MIN > 0:
        schedule.every(BREAKING_EVERY_MIN).minutes.do(check_and_send_breaking)
    if RADAR_TIME:
        schedule.every().day.at(RADAR_TIME).do(send_radar)
    print(f"Scheduler: owner briefs at {', '.join(DIGEST_TIMES)} to {DIGEST_TO}; breaking every {BREAKING_EVERY_MIN} min; "
          f"radar at {RADAR_TIME or 'off'}; user news at {', '.join(NEWS_TIMES)} local; reminders every 30 s")
    from core import alerts, talent, watch
    if watch.ALERT_EVERY_MIN > 0:
        schedule.every(watch.ALERT_EVERY_MIN).minutes.do(watch.run_watches, send_telegram)
    from core import topics
    if topics.LIVE_EVERY_MIN > 0:
        schedule.every(topics.LIVE_EVERY_MIN).minutes.do(
            lambda: _pool.submit(topics.run_live, lambda text, cid: send_telegram(text, cid, html=True)))
    schedule.every().monday.at(talent.WEEKLY_TIME).do(talent.send_weekly, send_telegram)
    from core import backup
    schedule.every().day.at(os.getenv("BACKUP_TIME", "03:00")).do(backup.nightly)
    schedule.every().day.at("03:30").do(store.prune_seen)
    schedule.every().day.at("03:35").do(store.prune_activity)
    while True:
        store.kv_set("scheduler_tick", time.time())
        for job in (schedule.run_pending, send_due_reminders, send_user_news):
            try:
                job()
            except Exception as e:
                name = getattr(job, "__name__", str(job))
                print(f"Scheduler error in {name}: {e}")
                alerts.notify(f"sched:{name}", f"Scheduled job '{name}' failed: {str(e)[:200]}", 120)
        time.sleep(30)


def run_digest():
    t = threading.Thread(target=start_digest_scheduler, daemon=True)
    t.start()