# Just Voice Type

**Local push-to-talk dictation for macOS**, powered by Whisper (Apple Silicon, MLX).
Hold Right Option, speak, release — your text is pasted wherever the cursor is. No cloud, no API keys, no subscriptions.

> A free, fully on-device alternative to Wispr Flow / Superwhisper. Works in English, Russian, and any other language Whisper supports.

## Features

- 🎙 **Menubar icon** with live status (idle, REC, processing, paused)
- ⌨️ **Push-to-talk** on any system key — switch it from the **Hotkey** menu (Right Option, Left Option, Fn, Cmd, Ctrl, Shift, F13–F19), applied instantly, no restart.
- 🧠 **MLX Whisper** (default `large-v3`) — fast on Apple Silicon. Falls back to `faster-whisper` on CPU.
- 🔀 **Switch models from the menu** — pick `large-v3-turbo` (fast, recommended), `large-v3`, `medium`, or `small` on the fly, no restart. The next dictation uses the new model.
- 🌐 **Pick the language from the menu** — your working ("favorite") languages plus **Auto** sit at the top; choose one to make it active. **All languages…** lists the full Whisper set (~99) where you check which languages to keep as favorites.
- 💾 **Settings persist** across restarts (favorite languages, active language, hotkey) in `~/.config/just-voice-type/config.json`.
- 📋 **Auto-paste** of recognized text via clipboard + `Cmd+V`, with original clipboard restored
- 🔔 macOS sounds on start/stop, optional notifications
- 🚀 **Autostart** as a LaunchAgent — the icon shows up right after login

## Requirements

- macOS on Apple Silicon (M1/M2/M3/M4)
- Python 3.10+
- First run downloads the Whisper model (~3 GB for `large-v3`) into `~/.cache/huggingface/`

## Install

```bash
git clone https://github.com/neodisa/just-voice-type.git
cd just-voice-type
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### macOS permissions (required)

`System Settings → Privacy & Security`:

- **Microphone** ✓
- **Accessibility** ✓ — without this, `pynput` can't see Right Option
- **Input Monitoring** ✓

Grant them to the process you're launching from: Terminal/iTerm while developing, or `~/just-voice-type/.venv/bin/python3` if you install the LaunchAgent.

After granting, **fully restart** Terminal (Cmd+Q, then reopen).

## Run

```bash
python3 voice_type.py
```

A 🎙 icon appears in the menubar. Hold Right Option — a capsule with a pulsing dot pops up at the bottom of the screen. Release it — the recognized text is pasted at the cursor.

### CLI flags

| Flag | Meaning |
|---|---|
| `--engine mlx \| faster` | Backend. Default `mlx` (fastest on Apple Silicon). |
| `--model <id>` | HF model id. Default `mlx-community/whisper-large-v3-mlx`. |
| `--lang en` | Language code. Default `ru`. Use `en`, `de`, `es`, etc. |
| `--hotkey right_option` | `right_option`, `left_option`, `fn`, `right_shift`, `f13`..`f20`. |
| `--no-paste` | Don't paste, only copy to clipboard. |
| `--no-restore-clipboard` | Don't restore the previous clipboard contents. |
| `--notify` | Show a macOS notification with the recognized text. |

`--lang` and `--hotkey` only **seed** the config on the very first run. After that, `~/.config/just-voice-type/config.json` (driven by the Language and Hotkey menus) is authoritative and the flags are ignored. Delete that file to reset to defaults.

There's also a headless CLI version, `voice_type_cli.py`, with the same flags and no menubar UI.

## Autostart on login

```bash
./install_autostart.sh
```

The script:
1. Renders `com.justvoicetype.local.plist` (a template) with your project's actual path.
2. Drops the result into `~/Library/LaunchAgents/`.
3. Registers it via `launchctl bootstrap` and starts it immediately.

After this, 🎙 appears automatically on every login. Logs live at `voice_type.log` and `voice_type.err.log` in the project root.

**Heads up:** once autostart is enabled, the macOS permissions (Accessibility / Input Monitoring / Microphone) must be granted to the `python3` binary inside `.venv` — not to Terminal — because launchd runs it directly. macOS will usually prompt you the first time it tries to read the keyboard or microphone.

### Remove autostart

```bash
./uninstall_autostart.sh
```

### Check status / tail logs

```bash
launchctl print gui/$(id -u)/com.justvoicetype.local | head -30
tail -f voice_type.log
tail -f voice_type.err.log
```

## Alternative models

The fastest way is the **Model** submenu in the 🎙 menubar icon — switch models live, no restart:

| Model | Notes |
|---|---|
| ⚡ `large-v3-turbo` | Fast, near-`large-v3` quality. **Recommended for speed.** (~1.5 GB) |
| 🎯 `large-v3` | Most accurate, slowest. Default on startup. (~3 GB) |
| `medium` | Balanced. |
| `small` | Fastest, less accurate (weak for non-English). |

The first dictation on a freshly picked model downloads it from HuggingFace; after that it's served from cache (`~/.cache/huggingface/`) and switching is instant.

You can also pin a model at launch via the CLI:

```bash
python3 voice_type.py --model mlx-community/whisper-large-v3-turbo    # fast, recommended
python3 voice_type.py --model mlx-community/whisper-medium-mlx        # faster, slightly less accurate
python3 voice_type.py --model mlx-community/whisper-small-mlx         # even faster
python3 voice_type.py --engine faster --model large-v3                # CPU faster-whisper fallback
```

## Troubleshooting

| Symptom | What to try |
|---|---|
| No menubar icon | Check Bartender/HiddenBar isn't hiding it. |
| Icon shows but the hotkey is dead | Accessibility / Input Monitoring not granted. Fully restart Terminal after granting. |
| Capsule doesn't show up | Tkinter wasn't built into your system Python. Install Python via Homebrew or python.org. |
| No sounds | `ls /System/Library/Sounds/` — make sure Tink/Pop exist. |
| Model takes forever to load | First run only (~3 GB). Use `medium` for speed. |
| Hallucinations like "Thanks for watching!" | Known Whisper artifact on silence. The most common ones are filtered out; for the rest, speak a bit longer. |
| LaunchAgent restarts in a loop | `launchctl print gui/$(id -u)/com.justvoicetype.local` shows the exit code. Usually missing permissions or no `.venv`. |

## License

[MIT](LICENSE)

