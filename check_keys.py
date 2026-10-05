"""Checks every key in .env with a free, read-only request. Never prints key values.
Run:  python check_keys.py
"""
import base64, json, urllib.request, urllib.error

env = {}
for line in open(".env"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")


def call(url, headers=None, data=None):
    try:
        req = urllib.request.Request(url, headers=headers or {}, data=data)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}
    except Exception as e:
        return None, {"error": str(e)}


def show(name, ok, detail):
    print(f"{'OK  ' if ok else 'FAIL'}  {name:<10} {detail}")


# Anthropic: list models (free)
s, b = call("https://api.anthropic.com/v1/models",
            {"x-api-key": env.get("ANTHROPIC_API_KEY", ""), "anthropic-version": "2023-06-01"})
show("Anthropic", s == 200, "key valid (check credits at console.anthropic.com)" if s == 200
     else b.get("error", {}).get("message", b))

# Telegram: getMe (free)
s, b = call(f"https://api.telegram.org/bot{env.get('TELEGRAM_BOT_TOKEN', '')}/getMe")
show("Telegram", bool(b.get("ok")), "@" + b["result"]["username"] if b.get("ok") else b.get("description", b))

# Serper: one search (uses 1 credit)
s, b = call("https://google.serper.dev/search",
            {"X-API-KEY": env.get("SERPER_API_KEY", ""), "Content-Type": "application/json"},
            json.dumps({"q": "test", "num": 1}).encode())
show("Serper", s == 200, "key valid" if s == 200 else b.get("message", b))

# Discord: who am I (free)
if env.get("DISCORD_BOT_TOKEN"):
    s, b = call("https://discord.com/api/v10/users/@me",
                {"Authorization": "Bot " + env["DISCORD_BOT_TOKEN"], "User-Agent": "DiscordBot (keycheck, 1.0)"})
    show("Discord", s == 200, b.get("username") if s == 200 else b.get("message", b))

# Twilio: account status (free)
if env.get("TWILIO_ACCOUNT_SID"):
    sid, tok = env["TWILIO_ACCOUNT_SID"], env.get("TWILIO_AUTH_TOKEN", "")
    auth = base64.b64encode(f"{sid}:{tok}".encode()).decode()
    s, b = call(f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json", {"Authorization": "Basic " + auth})
    show("Twilio", s == 200, f"account {b.get('status')}" if s == 200 else b.get("message", b))

print("\nAllowed Telegram IDs:", env.get("ALLOWED_TELEGRAM_IDS", "MISSING"))
