# Just Voice Type

**Local push-to-talk dictation for macOS**, powered by Whisper (Apple Silicon, MLX).
Hold Right Option and speak, or **double-tap** it for hands-free — your text is pasted wherever the cursor is. No cloud, no API keys, no subscriptions.

> A free, fully on-device alternative to Wispr Flow / Superwhisper. Works in English, Russian, and any other language Whisper supports.

## Features

- 🎙 **Menubar icon** with live status (idle, REC, processing, paused)
- ⌨️ **Push-to-talk** on any system key — switch it from the **Hotkey** menu (Right Option, Left Option, Fn, Cmd, Ctrl, Shift, F13–F19), applied instantly, no restart.
- 🙌 **Hands-free mode** — **double-tap** the hotkey and it keeps listening with the key released; **tap once** to stop. No need to hold the key through a long monologue. The menubar shows `🔴∞` while it's on. (Auto-stops after 5 min as a safety net.)
- 🌊 **Streaming transcription** — while you're still talking, long dictations are transcribed in the background in ~20s chunks, sliced at pauses so words aren't cut. By the time you stop there's almost nothing left to wait for — no more minute-long "frozen" transcribe on long recordings, and no runaway Whisper repetition loops.
- 🧠 **On-device ASR** — default `parakeet-tdt-0.6b-v3` (NVIDIA Parakeet via MLX): ~10× faster than Whisper, multilingual incl. RU/UK/EN, auto-detects language. Whisper `large-v3` is one menu click away when you want maximum accuracy. Falls back to `faster-whisper` on CPU. Models warm up in the background at startup, so the first dictation is as fast as the rest.
- 🔀 **Switch models from the menu** — pick `parakeet-v3` (fastest, default), `large-v3` (most accurate), `large-v3-turbo` (faster decode, weaker on Russian/Ukrainian), `medium`, or `small` on the fly, no restart. Your choice persists across restarts.
- 🌐 **Pick the language from the menu** — your working ("favorite") languages plus **Auto** sit at the top; choose one to make it active. **All languages…** lists the full Whisper set (~99) where you check which languages to keep as favorites.
- 🪄 **Smart modes** — pick **Raw** (verbatim), **Clean** (strip filler & fix punctuation), or **Prompt** (restructure your dictation into a clear instruction for an AI) from the **Smart** menu. Runs a small on-device LLM (`Qwen2.5-1.5B-Instruct-4bit` via `mlx_lm`) — still no cloud. Add domain terms via **Edit vocabulary…** so misheard names/jargon get fixed and bias Whisper itself.
- 💾 **Settings persist** across restarts (favorite languages, active language, hotkey, smart mode, vocabulary, model, insertion mode) in `~/.config/just-voice-type/config.json`.
- 📋 **Auto-paste** of recognized text via clipboard + `Cmd+V`, with original clipboard restored
- 📝 **Insertion mode** — by default text is pasted via clipboard + Cmd+V (and the previous clipboard is restored). Switch to **Insert via Accessibility** from the menu (under **Smart → Insert via Accessibility**) to type straight into the focused field. In this mode the dictation **lands in the field you started in** even if you switch windows (it inserts into that app in the background), and the **clipboard is never clobbered** — on any fallback the previous clipboard is restored, and every dictation is always kept in the History menu. If the original field can't accept a background insert, the text is kept in history and you get a notification (no window is yanked to the front).
- 🕘 **History menu** — the last 15 dictations, persisted across restarts (50 kept on disk in `~/.config/just-voice-type/history.json`); click any entry to copy it back to the clipboard
- 🔔 macOS sounds on start/stop, optional notifications
- 🚀 **Autostart** as a LaunchAgent — the icon shows up right after login

## Gestures

One hotkey, three gestures:

| Gesture | What it does |
|---|---|
| **Hold** (press, speak, release) | Push-to-talk — records while held, transcribes on release. |
| **Double-tap** | Hands-free — keeps recording with the key released. The menubar shows `🔴∞`. |
| **Single tap** (while hands-free) | Stops hands-free recording and transcribes. |

A quick single tap that *isn't* followed by a second tap is treated as a normal short dictation — recording keeps going for half a second so nothing is lost while it waits to see if you're double-tapping.

## Smart modes

The **Smart** menu controls a local LLM pass that runs *after* Whisper, on the recognized text:

- **Raw** *(default)* — no post-processing; you get Whisper's verbatim output instantly. Use it for names, passwords, or exact quotes. This is the default so updating users keep the old behavior and nothing downloads until you opt in.
- **Clean** — removes filler ("uh", "you know"), collapses self-corrections, fixes punctuation and capitalization. Words and meaning are preserved.
- **Prompt** — rewrites a rambly dictation into a single clear instruction for an AI assistant, fixing obviously misheard words along the way.

Notes:

- The LLM (`Qwen2.5-1.5B-Instruct-4bit`, ~1 GB) **downloads and warms up in the background** as soon as Clean/Prompt is selected (or at startup if it's already your mode). Raw never loads it.
- It runs **fully on-device** via `mlx_lm` — no cloud, no API keys, consistent with the rest of the app.
- Polishing **never blocks paste**: on any error or timeout it falls back to the raw Whisper text.
- **Edit vocabulary…** opens `config.json`; add your recurring terms/names to the `vocabulary` list. They feed both Whisper's `initial_prompt` (so it mishears them less) and the LLM (so it corrects them from context).

> **Parakeet note:** Parakeet auto-detects the language and doesn't take an
> `initial_prompt`, so the vocabulary list doesn't bias it the way it biases
> Whisper. The LLM correction pass (Clean/Prompt) still applies your vocabulary.
> Also, because Parakeet doesn't report the detected language, using it with
> language **Auto** *and* a non-Raw Smart mode can let the LLM translate your
> text to English — pick your language explicitly (not Auto) to avoid that.

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
| `--model <id>` | HF model id. Default `mlx-community/parakeet-tdt-0.6b-v3` (overrides the menu choice for this launch). |
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
| 🎯 `large-v3` | Most accurate. On Apple Silicon it's barely slower than turbo for dictation-length audio. (~3 GB) |
| ⚡ `parakeet-tdt-0.6b-v3` | **Default.** ~10× faster than Whisper (FastConformer-TDT). Multilingual incl. RU/UK/EN, auto-detects language. No vocabulary bias / no forced language. (~600 MB) |
| ⚡ `large-v3-turbo` | Faster decode, but noticeably weaker on Russian/Ukrainian morphology. (~1.5 GB) |
| `medium` | Balanced. |
| `small` | Fastest, less accurate (weak for non-English). |

The menu choice is saved to `config.json` and survives restarts. A freshly picked model downloads from HuggingFace and warms up in the background; after that it's served from cache (`~/.cache/huggingface/`) and switching is instant.

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

