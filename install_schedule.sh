#!/bin/bash
# Sets up two background jobs on this Mac:
#   1. a daily check of all partners (default 08:00)
#   2. the dashboard at http://localhost:8765 (starts at login, restarts if it stops)
# Usage: ./install_schedule.sh [HOUR] [MINUTE]      Uninstall: ./install_schedule.sh --uninstall
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
CHECK=com.sellersjson.monitor
DASH=com.sellersjson.dashboard
PY="$(command -v python3)"

unload() { launchctl bootout "gui/$(id -u)" "$AGENTS/$1.plist" 2>/dev/null || true; }

if [ "$1" = "--uninstall" ]; then
  for L in $CHECK $DASH; do unload $L; rm -f "$AGENTS/$L.plist"; done
  echo "Removed the daily check and the dashboard."; exit 0
fi
HOUR=${1:-8}; MIN=${2:-0}
mkdir -p "$AGENTS"

cat > "$AGENTS/$CHECK.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$CHECK</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/sellers_monitor.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MIN</integer></dict>
  <key>StandardOutPath</key><string>$DIR/monitor.log</string>
  <key>StandardErrorPath</key><string>$DIR/monitor.log</string>
</dict></plist>
PL

cat > "$AGENTS/$DASH.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$DASH</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/server.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/dashboard.log</string>
  <key>StandardErrorPath</key><string>$DIR/dashboard.log</string>
</dict></plist>
PL

for L in $CHECK $DASH; do unload $L; launchctl bootstrap "gui/$(id -u)" "$AGENTS/$L.plist"; done
printf "Daily check at %02d:%02d. Dashboard: http://localhost:8765\n" "$HOUR" "$MIN"
