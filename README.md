# BMSD viewership tracker

Tracks every live YouTube stream of an esports event (official broadcast, watch parties, community streams) and
gives Esports-Charts-style numbers: peak viewers, average viewers, hours watched, airtime, by day, by channel.
Separate from the main agent: its own branch (bmsd-tracker, never merged into main), folder, database, Telegram bot and dashboard.

- New streams are found every 60s (YouTube live search for the event's phrases; no API key needed).
- Every live stream is re-counted every 10s, so short peaks are caught.
- Dashboard: http://localhost:8091 (refreshes every 30s). With cloudflared installed it also gets a public
  link you can open on your phone; the link is sent to you through your main agent's Telegram bot.
- Optional: its own Telegram bot for commands (TRACKER_BOT_TOKEN); not needed.

## Setup (Mac)

```
cd ~ && git clone -b bmsd-tracker --single-branch https://github.com/naveen-raj-kanagaraj/my-agent.git bmsd-tracker && cd bmsd-tracker
cp .env.example .env                     # nothing to fill in
brew install cloudflared                 # optional: public dashboard link for your phone
~/my-agent/venv/bin/python check.py      # confirms search + counting work from your network
bash scripts/autostart.sh install        # runs in the background, restarts on crash, keeps the Mac awake
```

Change the event in `data/config.json` (name, title phrases, search queries, official channels) or with the
Telegram commands. Numbers are YouTube only; Esports Charts covers all platforms (link in /stats).
