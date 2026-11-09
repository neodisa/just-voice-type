#!/bin/bash
# Build the WhisperFlowSysCap system-audio helper.
#   ./scripts/build_syscap.sh [output_path]
# Default output: native/WhisperFlowSysCap (dev). Pass the bundle path
#   .../Voice Type.app/Contents/MacOS/WhisperFlowSysCap to install it.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/../native/whisperflow_syscap.swift"
out="${1:-$here/../native/WhisperFlowSysCap}"
xcrun swiftc -O -framework CoreAudio -framework AVFoundation -o "$out" "$src"
codesign --force --sign - "$out"   # ad-hoc sign the helper itself
echo "built: $out"

# If we just installed into an .app bundle, the WHOLE bundle must be re-signed:
# modifying an unsigned/stale-signed bundle makes macOS drop TCC trust, which
# kills Accessibility/Input Monitoring and makes the mic permission prompt
# impossible to get back (see README → Bundle signing).
case "$out" in
  *.app/Contents/MacOS/*)
    app="${out%%.app/Contents/MacOS/*}.app"
    echo "re-signing bundle: $app"
    codesign --force --deep --sign - "$app"
    codesign --verify --verbose=2 "$app" 2>&1 | tail -2
    cat <<EOF

NOTE: re-signing resets this app's permissions. Grant them once:
  tccutil reset Accessibility com.whisperflow.local
  tccutil reset ListenEvent com.whisperflow.local
  tccutil reset Microphone com.whisperflow.local
  open "\$HOME/Applications/Voice Type.app"
then allow the mic prompt and re-enable Voice Type in Accessibility + Input Monitoring.
EOF
    ;;
esac
