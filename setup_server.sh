#!/bin/bash
# Run ON the Oracle Cloud VM from inside the my-agent folder:
#   cd ~/my-agent && bash setup_server.sh
set -e

echo "==> Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y -q python3-venv python3-pip ffmpeg
# Ubuntu images on Oracle need the local timezone set for the 8 AM / 7 PM briefs
sudo timedatectl set-timezone "${OWNER_TIMEZONE:-America/Chicago}" || true

echo "==> Creating Python virtual environment..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

if [ ! -f .env ]; then
    echo "ERROR: .env file missing. Copy it from your Mac first (see DEPLOY.md)."
    exit 1
fi

echo "==> Creating systemd service (starts on boot, restarts on crash)..."
BOT_DIR="$(pwd)"
sudo tee /etc/systemd/system/pesagent.service > /dev/null <<UNIT
[Unit]
Description=Pes agent (Telegram, Discord, scheduler)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable pesagent
sudo systemctl restart pesagent
sleep 5
sudo systemctl status pesagent --no-pager -l | head -15
echo ""
echo "Logs:    sudo journalctl -u pesagent -f"
echo "Restart: sudo systemctl restart pesagent"
