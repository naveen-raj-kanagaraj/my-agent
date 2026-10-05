# Personal Strategic Agent

A Claude-powered personal agent reachable on Telegram, Discord and WhatsApp, with web search, notes, memory, file reading (PDF, PPTX, DOCX, XLSX) and an hourly digest.

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

## Layout

- `main.py`: starts every platform whose keys are present in `.env`
- `core/agent.py`: system prompt and Claude tool loop
- `core/tools.py`: web search, notes, calculator, date/time
- `core/memory.py`: per-user conversation memory (`memory.json`)
- `digest.py`: hourly news digest
- `platforms/`: Telegram, Discord and WhatsApp front ends

## Never commit

`.env`, `memory.json`, `covered_news.json`, `venv/` (already in `.gitignore`).
