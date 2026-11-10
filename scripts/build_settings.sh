#!/bin/bash
# Build the JustVoiceTypeSettings SwiftUI settings-window helper.
#   ./scripts/build_settings.sh [output_path]
# Default output: native/JustVoiceTypeSettings (dev). Pass the bundle path
#   .../Just Voice Type.app/Contents/MacOS/JustVoiceTypeSettings to install it.
# The fonts always go next to the binary as <binary>-Fonts/.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src_dir="$here/../native/settings"
out="${1:-$here/../native/JustVoiceTypeSettings}"
fonts_out="$out-Fonts"

mkdir -p "$(dirname "$out")"
xcrun swiftc -parse-as-library -O -target arm64-apple-macos14.0 \
  -o "$out" "$src_dir"/*.swift

rm -rf "$fonts_out"
mkdir -p "$fonts_out"
cp "$src_dir"/Fonts/*.ttf "$src_dir"/Fonts/*.txt "$fonts_out"/

codesign --force --sign - "$out"   # ad-hoc sign the helper itself
echo "built: $out"
echo "fonts: $fonts_out"

# Installing into an .app bundle invalidates its signature: re-sign the whole
# bundle (see scripts/build_syscap.sh and README → Bundle signing).
case "$out" in
  *.app/Contents/MacOS/*)
    app="${out%%.app/Contents/MacOS/*}.app"
    echo "re-signing bundle: $app"
    codesign --force --deep --sign - "$app"
    codesign --verify --verbose=2 "$app" 2>&1 | tail -2
    ;;
esac
