#!/bin/bash
# Keep the agent running on this Mac: starts at login, restarts if it crashes, and stops the Mac
# from idle-sleeping while it's plugged in. Closing the lid still sleeps the Mac.
#
#   bash scripts/autostart.sh install    turn it on (and start now)
#   bash scripts/autostart.sh status     is it running? last log lines
#   bash scripts/autostart.sh logs       follow the log live (Ctrl+C to stop watching)
#   bash scripts/autostart.sh restart    restart after you change code or .env
#   bash scripts/autostart.sh uninstall  turn it off (run it by hand again with: agent)
set -e
LABEL="com.pesagent.bot"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$DIR/venv/bin/python"
LOG="$DIR/data/agent.log"
DOMAIN="gui/$(id -u)"

case "${1:-status}" in
  install)
    [ -x "$PY" ] || { echo "No venv at $DIR/venv. Create it first (see README)."; exit 1; }
    [ -f "$DIR/.env" ] || { echo "No .env in $DIR."; exit 1; }
    if pgrep -f "$DIR/venv/bin/python main.py" >/dev/null || pgrep -f "python main.py" >/dev/null; then
      echo "The agent is already running in a Terminal window. Stop it there (Ctrl+C) first, then run this again."
      exit 1
    fi
    mkdir -p "$HOME/Library/LaunchAgents" "$DIR/data"
    cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-is</string>
    <string>$PY</string><string>-u</string><string>main.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PL
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    sleep 5
    echo "Installed. The agent now starts at login and restarts itself if it crashes."
    "$0" status
    ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      state=$(launchctl print "$DOMAIN/$LABEL" | awk -F'= ' '/state =/{print $2; exit}')
      echo "Autostart: on (state: ${state:-unknown})"
    else
      echo "Autostart: off"
    fi
    [ -f "$LOG" ] && { echo "--- last log lines ---"; tail -n 15 "$LOG"; }
    ;;
  logs) tail -n 40 -f "$LOG" ;;
  restart) launchctl kickstart -k "$DOMAIN/$LABEL" && echo "Restarted." ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Autostart removed. Start the agent by hand with: agent"
    ;;
  *) echo "Use: install | status | logs | restart | uninstall" ;;
esac
