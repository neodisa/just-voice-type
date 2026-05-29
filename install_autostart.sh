#!/bin/bash
# install_autostart.sh — install Just Voice Type as a LaunchAgent at login.
#
# What it does:
#   1) Renders com.whisperflow.local.plist (template) with this project's path
#   2) Copies it into ~/Library/LaunchAgents/
#   3) Registers it via `launchctl bootstrap` and starts it
#
# After install the 🎙 icon appears in the menubar on every login.
# Uninstall: ./uninstall_autostart.sh

set -e

# Resolve project dir from this script's location — no hardcoded paths.
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.whisperflow.local.plist"
SOURCE_PLIST="${PROJECT_DIR}/${PLIST_NAME}"
TARGET_PLIST="${HOME}/Library/LaunchAgents/${PLIST_NAME}"
LABEL="com.whisperflow.local"
HF_HOME_DEFAULT="${HF_HOME:-${HOME}/.cache/huggingface}"

# Sanity checks.
if [ ! -f "$SOURCE_PLIST" ]; then
    echo "[!] Template plist not found: ${SOURCE_PLIST}"
    exit 1
fi

if [ ! -x "${PROJECT_DIR}/.venv/bin/python3" ]; then
    echo "[!] No venv at ${PROJECT_DIR}/.venv"
    echo "    Run first:"
    echo "      cd ${PROJECT_DIR} && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install rumps"
    exit 1
fi

if [ ! -f "${PROJECT_DIR}/whisper_flow_app.py" ]; then
    echo "[!] Missing whisper_flow_app.py in ${PROJECT_DIR}"
    exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents"

# Drop existing registration if any.
if launchctl print "gui/$(id -u)/${LABEL}" >/dev/null 2>&1; then
    echo "[+] Unloading previous LaunchAgent..."
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
fi

# Render template — substitute placeholders with real paths.
# Use a delimiter unlikely to appear in paths.
echo "[+] Rendering plist → ${TARGET_PLIST}"
sed \
    -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    -e "s|__HF_HOME__|${HF_HOME_DEFAULT}|g" \
    "${SOURCE_PLIST}" > "${TARGET_PLIST}"

echo "[+] Registering with launchd..."
launchctl bootstrap "gui/$(id -u)" "${TARGET_PLIST}"

echo "[+] Enabling autostart..."
launchctl enable "gui/$(id -u)/${LABEL}"

echo "[+] Kickstarting now..."
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

cat <<EOF

[✓] Done.
    The 🎙 icon should appear in the menubar within a few seconds
    (longer on the very first run while the Whisper model downloads).

    Logs:    ${PROJECT_DIR}/whisper_flow.log
    Errors:  ${PROJECT_DIR}/whisper_flow.err.log
    Status:  launchctl print gui/\$(id -u)/${LABEL} | head -20

    Uninstall: ./uninstall_autostart.sh
EOF
