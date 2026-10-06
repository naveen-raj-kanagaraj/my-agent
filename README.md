# Personal Strategic Agent

A Claude-powered agent on Telegram (open to anyone, with daily limits) and Discord (owner only).

What it does:
- Chat with a learned profile of each user: it asks new users what they're interested in, learns from their messages, files and images, and remembers facts long-term
- Personalised news for every user at 8 AM and 7 PM their local time, plus the owner's full strategic briefing and breaking-news alerts
- Reads links: articles, PDFs, YouTube transcripts
- Downloads videos from X, Instagram, TikTok, YouTube Shorts, Reddit, Facebook, Threads (up to 50 MB)
- Reads files (PDF, DOCX, PPTX, XLSX, CSV, TXT) and images; remembers images for follow-up questions
- Voice notes, transcribed on the machine with faster-whisper (free)
- Reminders (one-off, daily, weekdays, weekly), notes, calculator, web search
- Choice of model at the start of each conversation, kept until 2 hours of quiet or /switch: Claude Haiku 4.5, Sonnet 5.5, Opus 5.5, Fable 5.1; GPT-5.6 Luna, Terra, Sol; Gemini 3.1 Flash-Lite, 3.7 Flash, 3.1 Pro (pricier models use more of a user's daily requests)
- Web dashboard at http://localhost:8090: active sessions, requests and spend per user, spend by model, day and feature, source health
- Image generation (owner by default)
- Instant keyword alerts every 30 minutes from news sites, Reddit and Hacker News (free, no AI call)
- Talent agency tracker for the owner: creators, brand deals, stages, due dates, stale-deal follow-ups, weekly Monday summary
- Spend tracking per user and feature, a daily budget for other users, and Telegram alerts to the owner when anything breaks
- Daily content and business radar across the owner's topics (creator economy, talent, entertainment, brands, gaming and more), from news, Reddit, X, Instagram, YouTube and competitors

## Run on a Mac

```
cd ~/my-agent
python3 -m venv venv          # first time only
source venv/bin/activate
pip install -r requirements.txt   # first time only
cp .env.example .env              # first time only, then fill in keys
python main.py
```

Then send `/start` to the bot on Telegram. The bot runs only while this terminal stays open and the computer is awake.

## Telegram commands

Everyone: `/start`, `/news`, `/alert <keyword>`, `/alerts`, `/unalert <id>`, `/interests <topics>`, `/keywords`, `/newsoff`, `/newson`, `/profile`, `/forget`, `/clear`, `/help`, `/quick <q>`

Everyone also: `/model` (models and default), `/switch` (pick a different model), `/picker on|off`

Owner: `/deep <q>` (Sonnet 5.5), `/dashboard`, `/credits <balance>`, `/brief` (full briefing), `/radar` (content and business radar), `/pipeline` (talent tracker), `/status` (health), `/usage` (spend), `/users`, `/block <id>`, `/unblock <id>`

Non-owners get `DAILY_LIMIT` requests a day (default 20) and always use Haiku 4.5. The owner has no limit; quick
questions go to Haiku and strategy, writing and long messages to Sonnet 5.5.

## Data

Everything is in `data/agent.db` (SQLite): users, learned profiles, facts, notes, reminders, conversations, usage.
Users can see their data with `/profile` and erase it with `/forget`. Never commit `data/`.

## Health check

`python selftest.py` checks every live service (Anthropic, Telegram, Serper, Google News, Reddit, Hacker News, links, YouTube transcripts, yt-dlp, voice, database, scheduler) and prints a fix for anything broken.

## Run 24/7

See DEPLOY.md (free Oracle Cloud server).

## Layout

- `main.py`: starts every platform whose keys are present in `.env`
- `core/agent.py`: system prompt and Claude tool loop
- `core/tools.py`: web search, notes, calculator, date/time
- `core/store.py`: SQLite storage
- `core/llm.py`: every AI call (Claude, ChatGPT, Gemini), with cost tracking and budgets
- `core/models.py`: the models users can pick
- `platforms/dashboard.py`: web dashboard
- `core/alerts.py`: Telegram alerts to the owner
- `core/watch.py`: keyword alerts
- `core/talent.py`: talent agency tracker
- `selftest.py`: live health check
- `core/profile.py`: onboarding and learning about users
- `core/news.py`: personalised news
- `core/radar.py`: content radar
- `core/web.py`: link reading
- `core/voice.py`: voice transcription
- `core/context.py`: per-request user context
- `core/downloader.py`: video downloads via yt-dlp (bare links, plus the agent's `download_video` tool)
- `core/memory.py`: per-user conversation memory (`memory.json`)
- `digest.py`: hourly news digest
- `platforms/`: Telegram, Discord and WhatsApp front ends

## Maintenance

- Check API keys: `python check_keys.py`
- Downloads failing: `pip install -U yt-dlp`
- Instagram blocked: put a browser-exported `cookies.txt` in this folder

## Never commit

`.env`, `memory.json`, `covered_news.json`, `cookies.txt`, `venv/` (already in `.gitignore`).
