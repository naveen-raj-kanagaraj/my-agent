import os
import requests
import schedule
import time
import threading
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi
from youtubesearchpython import VideosSearch
from core.tools import web_search
from dotenv import load_dotenv
import anthropic
import re
import discord
import asyncio
import json

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_USER_ID = os.getenv("ALLOWED_DISCORD_IDS")
client = anthropic.Anthropic()

COVERED_NEWS_FILE = "covered_news.json"


def load_covered_news() -> list:
    if os.path.exists(COVERED_NEWS_FILE):
        with open(COVERED_NEWS_FILE, "r") as f:
            return json.load(f)
    return []


def save_covered_news(news: list):
    with open(COVERED_NEWS_FILE, "w") as f:
        json.dump(news[-100:], f)


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


def get_youtube_transcript(query: str) -> str:
    try:
        search = VideosSearch(query, limit=1)
        results = search.result()
        if not results["result"]:
            return ""
        video_id = results["result"][0]["id"]
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join([t["text"] for t in transcript[:20]])
        return text
    except Exception:
        return ""


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

    raw_data = {}
    for category, query in categories.items():
        google = search_clean(query)
        reddit = search_clean(f"site:reddit.com {query}")
        yt = get_youtube_transcript(query)
        raw_data[category] = f"{google}\n{reddit}\n{yt}"

    combined = ""
    for category, data in raw_data.items():
        combined += f"\n{category}:\n{data}\n"

    response = client.messages.create(
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
World News
India News
Tamil Nadu
Global Gaming and Esports
Gaming Industry Investments
Geopolitics
Stocks to Watch
Crypto Today
Marketing and Creator Trends
Tech and AI
Finance and Economy

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
        send_discord(result)
        print(f"Breaking news sent: {result[:100]}")


def send_digest():
    print(f"Sending digest at {datetime.now().strftime('%H:%M')}")
    try:
        digest = build_digest()
        send_discord(digest)
        print("Digest sent to Discord.")
    except Exception as e:
        print(f"Digest error: {e}")


def start_digest_scheduler():
    schedule.every(2).hours.do(send_digest)
    schedule.every(15).minutes.do(check_and_send_breaking)
    while True:
        schedule.run_pending()
        time.sleep(60)


def run_digest():
    t = threading.Thread(target=start_digest_scheduler, daemon=True)
    t.start()