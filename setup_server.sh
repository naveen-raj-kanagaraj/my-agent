#!/bin/bash
# Runs ON the Oracle Cloud server, from inside ~/my-agent. scripts/deploy_oracle.sh calls it for you.
# Safe to run again: it only adds what's missing and restarts the service.
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "ERROR: .env is missing. Run scripts/deploy_oracle.sh from your Mac, it copies it up."
    exit 1
fi

# Small (1 GB) servers run out of memory installing packages: add 2 GB of swap once.
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 3000 ] && ! swapon --show | grep -q /swapfile; then
    echo "==> Low memory (${mem_mb} MB): adding 2 GB swap..."
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
    grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Installing system packages (a few minutes the first time)..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip ffmpeg sqlite3 >/dev/null
sudo timedatectl set-timezone "$(grep -E '^OWNER_TIMEZONE=' .env | cut -d= -f2 | tr -d '\"' || echo America/Chicago)" 2>/dev/null || true

echo "==> Python packages..."
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt
./venv/bin/pip install -q -U yt-dlp   # sites change often; always take the newest

mkdir -p data
chmod 600 .env

echo "==> Service (starts on boot, restarts on crash)..."
BOT_DIR="$(pwd)"
sudo tee /etc/systemd/system/pesagent.service > /dev/null <<UNIT
[Unit]
Description=Pes agent (Telegram, scheduler, dashboard)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python -u main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable -q pesagent
sudo systemctl restart pesagent
sleep 8
if systemctl is-active -q pesagent; then
    echo "==> The agent is running."
else
    echo "==> The agent did not start. Last log lines:"
    sudo journalctl -u pesagent -n 30 --no-pager
    exit 1
fi
