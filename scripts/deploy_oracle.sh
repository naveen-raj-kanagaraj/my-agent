#!/bin/bash
# Move the agent from this Mac to your Oracle Cloud server. Run from ~/my-agent on the Mac:
#
#   bash scripts/deploy_oracle.sh <server public IP> <path to the private key you downloaded>
#   e.g. bash scripts/deploy_oracle.sh 129.146.10.20 ~/Downloads/ssh-key-2026-10-07.key
#
# It stops the agent on this Mac (two copies fight over Telegram messages), copies the code, your .env and
# your data (users, memory, reminders) to the server, installs everything, starts it, and runs the self-test.
set -e
cd "$(dirname "$0")/.."
IP="$1"; KEY_IN="$2"
if [ -z "$IP" ] || [ -z "$KEY_IN" ]; then
    echo "Use: bash scripts/deploy_oracle.sh <server IP> <private key file>"; exit 1
fi
[ -f "$KEY_IN" ] || { echo "Can't find the key file: $KEY_IN"; exit 1; }
[ -f .env ] || { echo "No .env here. Run this from ~/my-agent."; exit 1; }

# Keep the key somewhere safe and permanent (Downloads gets cleaned up).
mkdir -p "$HOME/.ssh"
KEY="$HOME/.ssh/pesagent.key"
[ "$(cd "$(dirname "$KEY_IN")" && pwd)/$(basename "$KEY_IN")" = "$KEY" ] || cp "$KEY_IN" "$KEY"
chmod 600 "$KEY"
printf 'IP=%s\nKEY=%s\nUSER_NAME=ubuntu\n' "$IP" "$KEY" > .server
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 ubuntu@$IP"

echo "==> 1/5 Checking the server..."
if ! $SSH 'echo ok' >/dev/null 2>&1; then
    echo "Can't log in to ubuntu@$IP."
    echo "Check: the instance is Running, the IP is the *Public* IP, the key is the one you downloaded for it,"
    echo "and your network allows SSH (some campus Wi-Fi blocks it; try a phone hotspot)."
    exit 1
fi
echo "    $($SSH 'uname -m; . /etc/os-release; echo $PRETTY_NAME; free -m | awk "/Mem/{print \$2\" MB RAM\"}"' | tr '\n' ' ')"

echo "==> 2/5 Stopping the agent on this Mac..."
if [ -f "$HOME/Library/LaunchAgents/com.pesagent.bot.plist" ]; then
    bash scripts/autostart.sh uninstall >/dev/null && echo "    Mac autostart turned off."
fi
if pgrep -f "python[0-9.]* (-u )?main\.py" >/dev/null; then
    pkill -f "python[0-9.]* (-u )?main\.py" || true
    sleep 3
    echo "    Stopped the running agent."
fi
pkill -f "cloudflared tunnel" 2>/dev/null && echo "    Stopped this Mac's dashboard tunnel." || true   # the server takes over the link
if command -v sqlite3 >/dev/null && [ -f data/agent.db ]; then
    sqlite3 data/agent.db "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null 2>&1 || true   # one clean file to copy
fi

echo "==> 3/5 Copying code, .env and your data..."
rsync -az -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
    --exclude venv --exclude __pycache__ --exclude .git --exclude .server --exclude '*.pyc' \
    --exclude data/backups --exclude data/server-backups --exclude 'data/agent.lock' --exclude 'data/agent.log*' --exclude '.DS_Store' \
    ./ "ubuntu@$IP:~/my-agent/"

if [ -d "$HOME/.cloudflared" ]; then   # the live.letsgrowesports.com tunnel login, so the server can serve that link
    rsync -az -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" "$HOME/.cloudflared/" "ubuntu@$IP:~/.cloudflared/"
    $SSH 'chmod 700 ~/.cloudflared && chmod 600 ~/.cloudflared/*'
    echo "    Copied the dashboard tunnel login."
fi

echo "==> 4/5 Installing on the server (5-10 minutes the first time)..."
$SSH 'cd ~/my-agent && bash setup_server.sh'

echo "==> 5/5 Self-test from the server..."
$SSH 'cd ~/my-agent && ./venv/bin/python selftest.py' || true

cat <<EOF

Done. The agent now runs on the server 24/7 and your Mac can sleep.
Message the bot on Telegram and send /status to confirm.

Manage it from this Mac with scripts/server.sh:
  bash scripts/server.sh status      running? recent log
  bash scripts/server.sh logs        live log (Ctrl+C to stop watching)
  bash scripts/server.sh restart     after editing .env on the server
  bash scripts/server.sh update      send code changes from this Mac and restart
  bash scripts/server.sh env         edit .env on the server
  bash scripts/server.sh dashboard   open the dashboard at http://localhost:8090
  bash scripts/server.sh backup      download a copy of the database
Don't start the agent on this Mac any more (no 'agent' command): two copies fight over messages.
EOF
