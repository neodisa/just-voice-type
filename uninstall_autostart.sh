#!/bin/bash
# uninstall_autostart.sh — remove Just Voice Type LaunchAgent.

set -e

PLIST_NAME="com.whisperflow.local.plist"
TARGET_PLIST="${HOME}/Library/LaunchAgents/${PLIST_NAME}"
LABEL="com.whisperflow.local"

if launchctl print "gui/$(id -u)/${LABEL}" >/dev/null 2>&1; then
    echo "[+] Unloading from launchd..."
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
else
    echo "[·] LaunchAgent not registered, just removing the file."
fi

if [ -f "${TARGET_PLIST}" ]; then
    rm -f "${TARGET_PLIST}"
    echo "[+] Removed ${TARGET_PLIST}"
fi

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cat <<EOF
[✓] Autostart removed.
    Manual run still works:
      cd "${PROJECT_DIR}" && source .venv/bin/activate && python3 whisper_flow_app.py
EOF
