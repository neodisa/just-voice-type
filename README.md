# Just Voice Type

**Local push-to-talk dictation for macOS**, powered by Whisper (Apple Silicon, MLX).
Hold Right Option and speak, or **double-tap** it for hands-free — your text is pasted wherever the cursor is. No cloud, no API keys, no subscriptions.

> A free, fully on-device alternative to Wispr Flow / Superwhisper. Works in English, Russian, and any other language Whisper supports.

## Features

- 🎙 **Menubar icon** with live status — monochrome SF Symbols that follow the light/dark menu bar, live red level bars while recording, a red phone + timer during a call; fixed width, so neighbouring icons don't jump. The first menu line spells out the state (*Ready · hold right ⌥*, *Recording · 0:07*, *Downloading model…*).
- 🧭 **Short menu, full settings window** — the menu keeps what you use while working: **Record call**, your **three latest calls** (click copies the transcript, hold ⌥ to open the file), **Copy last dictation**, **Dictation history**, **Add term…**, pause, **Settings… ⌘,**. Everything you set once lives in the [Settings window](#settings-window).
- ⌨️ **Push-to-talk** on any system key — switch it in **Settings → General** (Right Option, Left Option, Fn, Cmd, Ctrl, Shift, F13–F19), applied instantly, no restart.
- 🙌 **Hands-free mode** — **double-tap** the hotkey and it keeps listening with the key released; **tap once** to stop. No need to hold the key through a long monologue. The menubar shows `🔴∞` while it's on. (Auto-stops after 5 min as a safety net.)
- 🌊 **Streaming transcription** — while you're still talking, long dictations are transcribed in the background in ~20s chunks, sliced at pauses so words aren't cut. By the time you stop there's almost nothing left to wait for — no more minute-long "frozen" transcribe on long recordings, and no runaway Whisper repetition loops.
- 🧠 **On-device ASR** — default `parakeet-tdt-0.6b-v3` (NVIDIA Parakeet via MLX): ~10× faster than Whisper, multilingual incl. RU/UK/EN, auto-detects language. Whisper `large-v3` is one click away in **Settings → Recognition** when you want maximum accuracy. Falls back to `faster-whisper` on CPU. Models warm up in the background at startup, so the first dictation is as fast as the rest.
- 🔀 **Switch models in Settings → Recognition** — pick `parakeet-v3` (fastest, default), `large-v3` (most accurate), `large-v3-turbo` (faster decode, weaker on Russian/Ukrainian), `medium`, or `small` on the fly, no restart. Your choice persists across restarts.
- 🌐 **Pick the speech language in Settings → Recognition** — **Auto** plus your favourite languages as quick buttons; **More languages…** opens a searchable list of the full Whisper set (~99) where you check favourites.
- 🪄 **Smart modes** — pick **Raw** (verbatim), **Clean** (strip filler & fix punctuation), or **Prompt** (restructure your dictation into a clear instruction for an AI) in **Settings → Recognition → Text processing**. Runs a small on-device LLM (`Qwen2.5-1.5B-Instruct-4bit` via `mlx_lm`) — still no cloud. Add domain terms as **Recognition hints** so misheard names/jargon get fixed and bias Whisper itself.
- ⚡ **Live typing** — text appears in the focused field while you talk, **sentence by sentence** (Parakeet + Raw). Every ~0.4 s the last seconds of audio are re-transcribed with a full model pass; a sentence is typed once its end (. ? !) is the same in two passes and confirmed by the next word or a pause, using the freshest pass — so each sentence is recognized with its full context and you don't get «. и» / «, Но» glitches at the seams (typed text can't be corrected in another app's field). A very long sentence without a period is typed up to its last confirmed comma. Typed as keystrokes, so it works in Electron apps and terminals; the held hotkey's modifier is not applied to typed text. If you switch windows mid-dictation, typing stops and the full text is in **Copy last text**. Toggle: **Smart → Печатать по ходу речи**. Off = the whole text is inserted at the end, as before.
- 🔤 **Terms / replacements** — a `heard → wanted` map in `config.json` rewrites terms in the text. Add one from the menu with **Add term…** (`фигма = Figma`, `хавар = ховер`) or manage the whole table in **Settings → Terms** (search, inline edit, delete with undo). Declined forms of a dictionary-form key are matched too: `фигма = Figma` also fixes «в фигме», «фигму»; `хавар = ховер` turns «хавару» into «ховеру». A key that's already an inflected form (e.g. `пройде`) only matches exactly, so real words aren't touched. Applied after transcription (and after any Smart polish), also to live typing — no extra latency. Edits apply on your next dictation.
- 📞 **Call Mode** — a second, independent recording mode for calls: captures both sides (your mic + the call's system audio — **automatically on macOS 14.4+ via a Core Audio tap**, no loopback driver needed; virtual-loopback fallback for older macOS), transcribes continuously in the background, and on stop saves a timestamped transcript (`[MM:SS] text`) to `~/Documents/JustVoiceType/Calls/` **and** copies it to the clipboard — paste into any AI for analysis. Survives headphone / audio-routing changes mid-call. Independent Start/Stop hotkey (**Settings → Calls → Call key**, default `F13`) and the **Record call** menu item; recording one mode blocks the other. See [Call Mode](#call-mode) below. No speaker labels, no live transcript view, no raw audio saved.
- 💾 **Settings persist** across restarts (favorite languages, active language, hotkey, smart mode, vocabulary, model, insertion mode, replacements, call hotkey, call device, auto system-audio capture, live typing) in `~/.config/just-voice-type/config.json`.
- 📋 **Auto-paste** of recognized text via clipboard + `Cmd+V`, with original clipboard restored
- 📝 **Insertion mode** — by default text is pasted via clipboard + Cmd+V (and the previous clipboard is restored). Switch **Settings → General → Text insertion** to **Directly into the field** to type straight into the focused field. In this mode the dictation **lands in the field you started in** even if you switch windows (it inserts into that app in the background), and the **clipboard is never clobbered** — on any fallback the previous clipboard is restored, and every dictation is always kept in the History menu. If the original field can't accept a background insert, the text is kept in history and you get a notification (no window is yanked to the front).
- 🕘 **History menu** — the last 15 dictations, persisted across restarts (50 kept on disk in `~/.config/just-voice-type/history.json`); click any entry to copy it back to the clipboard
- 🔔 Sounds on start, stop and when the text is in: four styles from [cuelume](https://github.com/danielwh2/cuelume), the old macOS sounds, or none (**Settings → General → Sounds**). Optional notifications.
- 🚀 **Autostart** as a LaunchAgent — the icon shows up right after login

## Settings window

**Settings… (⌘,)** opens a native SwiftUI window (dark, the *console* look) with five sections:

- **General** — dictation key, *type as you speak*, text insertion, sounds, interface language (follows macOS, or pick Русский / English), open at login.
- **Recognition** — model list with sizes and download/loading state, speech language, text processing mode, recognition hints.
- **Calls** — recent calls with copy / open / search, call key, hidden recording, automatic capture or a manual device.
- **Terms** — the `heard → written` table with search, inline editing and undo.
- **About** — version, update check against the latest GitHub release, links, author.

Changes apply immediately, there is no Save button. The window is a small helper process (`JustVoiceTypeSettings`) that only draws; all logic stays in Python and talks to it over JSON lines (see `native/settings/PROTOCOL.md`). When running from source, build it once:

```bash
./scripts/build_settings.sh
```

Without it, **Settings…** shows a notification with this command. `JustVoiceTypeSettings --demo` opens the window on sample data, without the app.

## Gestures

One hotkey, three gestures:

| Gesture | What it does |
|---|---|
| **Hold** (press, speak, release) | Push-to-talk — records while held, transcribes on release. |
| **Double-tap** | Hands-free — keeps recording with the key released. The menubar shows `🔴∞`. |
| **Single tap** (while hands-free) | Stops hands-free recording and transcribes. |

A quick single tap that *isn't* followed by a second tap is treated as a normal short dictation — recording keeps going for half a second so nothing is lost while it waits to see if you're double-tapping.

## Smart modes

**Settings → Recognition → Text processing** controls a local LLM pass that runs *after* Whisper, on the recognized text:

- **Raw** *(default)* — no post-processing; you get Whisper's verbatim output instantly. Use it for names, passwords, or exact quotes. This is the default so updating users keep the old behavior and nothing downloads until you opt in.
- **Clean** — removes filler ("uh", "you know"), collapses self-corrections, fixes punctuation and capitalization. Words and meaning are preserved.
- **Prompt** — rewrites a rambly dictation into a single clear instruction for an AI assistant, fixing obviously misheard words along the way.

Notes:

- The LLM (`Qwen2.5-1.5B-Instruct-4bit`, ~1 GB) **downloads and warms up in the background** as soon as Clean/Prompt is selected (or at startup if it's already your mode). Raw never loads it.
- It runs **fully on-device** via `mlx_lm` — no cloud, no API keys, consistent with the rest of the app.
- Polishing **never blocks paste**: on any error or timeout it falls back to the raw Whisper text.
- **Recognition hints** (Settings → Recognition) hold your recurring terms/names (the `vocabulary` list in `config.json`). They feed both Whisper's `initial_prompt` (so it mishears them less) and the LLM (so it corrects them from context).

> **Parakeet note:** Parakeet auto-detects the language and doesn't take an
> `initial_prompt`, so the vocabulary list doesn't bias it the way it biases
> Whisper. The LLM correction pass (Clean/Prompt) still applies your vocabulary.
> Also, because Parakeet doesn't report the detected language, using it with
> language **Auto** *and* a non-Raw Smart mode can let the LLM translate your
> text to English — pick your language explicitly (not Auto) to avoid that.

## Call Mode

A second, independent recording mode for calls (Teams, WhatsApp, Zoom, anything). Unlike dictation, Call Mode:

- Records **both sides** — your microphone and the call's system audio. With automatic capture each side is transcribed on its own (so the other party's language doesn't hijack recognition of yours) and the utterances are merged chronologically as `[MM:SS] text` lines.
- Recovers on its own when the audio route changes mid-call (headphones plugged in, Bluetooth switching); a `[⚠ пропуск записи ~Ns]` marker shows any short gap.
- Runs for as long as the call lasts (up to a 4-hour safety cap), transcribing in the background the same way long dictations do.
- On stop, saves the full transcript to `~/Documents/JustVoiceType/Calls/` **and** copies it to the clipboard — paste it into any AI tool for analysis. No auto-paste into a field. Click the «Call transcribed» notification to see the file selected in Finder (the first launch asks to allow notifications for Voice Type).
- Starts/stops via the **Record call** menu item (turns into **Stop call** while active), or a dedicated toggle hotkey (**Settings → Calls → Call key**, default `F13`) — independent of the dictation hotkey. Starting one mode blocks the other.
- Past calls are listed under **Calls** — click one to copy its transcript back to the clipboard, or use **Open Calls folder…**.
- **Hidden recording** (**Settings → Calls**): the menubar icon stays the plain microphone while a call records and transcribes; open the menu to see the timer and stop it. Call sounds and call notifications stay quiet. The orange macOS microphone dot is a system indicator and still shows, as it does for every dictation.
- Recording a call may require the other party's consent depending on your jurisdiction — check your local law before you start.
- With **automatic system-audio capture** on (see below), a call recording captures **everything playing on your Mac** during the call — not just the call app. Mute or quit other audio sources if you don't want them in the transcript.

Call Mode does **not** do speaker labels, a live growing transcript, or save the raw audio.

### Setup

**Automatic (macOS 14.4+, default) — no setup.** Call Mode captures the whole system output via a Core Audio process tap and mixes in your microphone, so you get both sides with **no loopback driver and no Audio MIDI Setup**. The first time you start a call, macOS shows a one-time **"Voice Type wants to record this computer's audio"** prompt — allow it. Toggle this off anytime in **Settings → Calls** (*Capture the other side automatically*) (then it uses the manual path below).

> Packaging note: the tap is read by a small Swift helper, `WhisperFlowSysCap`. Build it from source with `scripts/build_syscap.sh` (needs Xcode Command Line Tools) — by default into `native/WhisperFlowSysCap` (used when running from source), or pass `".../Voice Type.app/Contents/MacOS/WhisperFlowSysCap"` to install it into the app bundle. The bundle's `Contents/Info.plist` must carry an `NSAudioCaptureUsageDescription` string. Without the helper or that key the app silently falls back to the manual path.

**Manual fallback (older macOS, or when auto-capture is off).** Capturing the other side then requires a virtual audio loopback device — a one-time setup:

1. Install a virtual audio driver if you don't already have one — e.g. [VB-Cable](https://vb-audio.com/Cable/) or [BlackHole](https://github.com/ExistentialAudio/BlackHole) (free).
2. Open **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup") and create an **Aggregate Device** combining your Mac's microphone and the virtual cable (e.g. "MacBook Pro Microphone" + "VB-Cable"). This becomes your input — select it in **Settings → Calls → Manual device**.
3. Create a **Multi-Output Device** combining your speakers/headphones and the same virtual cable, so you keep hearing the call while it's captured.
4. Route the call app's own audio output to that Multi-Output Device — preferred over changing the whole Mac's system output, since it only captures the call itself:
   - **Teams:** Settings → Devices → Speaker (or, mid-call, the ⋯ menu → Show Device Settings).
   - **WhatsApp Desktop:** the call screen has its own speaker-selection menu.
   - Apps without a per-app output picker: change **System Settings → Sound → Output** to the Multi-Output Device for the duration of the call, then switch it back afterward.

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

The fastest way is **Settings → Recognition → Model** — switch models live, no restart:

| Model | Notes |
|---|---|
| 🎯 `large-v3` | Most accurate. On Apple Silicon it's barely slower than turbo for dictation-length audio. (~3 GB) |
| ⚡ `parakeet-tdt-0.6b-v3` | **Default.** ~10× faster than Whisper (FastConformer-TDT). Multilingual incl. RU/UK/EN, auto-detects language. No vocabulary bias / no forced language. (~600 MB) |
| ⚡ `large-v3-turbo` | Faster decode, but noticeably weaker on Russian/Ukrainian morphology. (~1.5 GB) |
| `medium` | Balanced. |
| `small` | Fastest, less accurate (weak for non-English). |

The choice is saved to `config.json` and survives restarts. A freshly picked model downloads from HuggingFace and warms up in the background; after that it's served from cache (`~/.cache/huggingface/`) and switching is instant.

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
| No sounds | Check **Settings → General → Sounds** isn't *No sounds*. The styles play `sounds/<style>/*.wav` through `afplay`; *macOS system sounds* need Tink/Pop in `/System/Library/Sounds/`. |
| Model takes forever to load | First run only (~3 GB). Use `medium` for speed. |
| Hallucinations like "Thanks for watching!" | Known Whisper artifact on silence. The most common ones are filtered out; for the rest, speak a bit longer. |
| LaunchAgent restarts in a loop | `launchctl print gui/$(id -u)/com.justvoicetype.local` shows the exit code. Usually missing permissions or no `.venv`. |
| "Микрофон завис в CoreAudio — перезапускаю" notification | macOS CoreAudio wedged while closing/opening the mic stream. The app relaunches itself (up to 3 times per 15 min); repeat the dictation once the 🎙 is back. Diagnostics: `[recovery]` thread stacks in `whisper_flow.err.log` and native stacks in `~/Library/Logs/WhisperFlow/hang-*.txt`. If it keeps happening, reboot or run `sudo killall coreaudiod`. |
| Recording works but every capture is silent (`RMS=0.0000`) and no permission prompt ever appears | The `.app` bundle lost (or never had) a code signature — macOS then denies microphone access instantly, with no dialog, and the app can't be added manually. See **Bundle signing** below. |

### Bundle signing (required after any bundle change)

The packaged `Voice Type.app` **must be code-signed**, otherwise macOS TCC breaks in a way you cannot recover from the UI: permission prompts stop appearing, `AVCaptureDevice.requestAccessForMediaType` returns *denied* immediately, captures return digital silence, and System Settings → Microphone offers no way to add the app. Editing an unsigned bundle (adding a binary to `Contents/MacOS/`, changing `Info.plist`) also silently drops Accessibility / Input Monitoring.

Ad-hoc signing is free and enough:

```bash
codesign --force --deep --sign - "$HOME/Applications/Voice Type.app"
```

Re-signing resets the app's permissions, so grant them once afterwards:

```bash
tccutil reset Accessibility com.whisperflow.local
tccutil reset ListenEvent com.whisperflow.local
tccutil reset Microphone com.whisperflow.local
open "$HOME/Applications/Voice Type.app"
```

then allow the microphone prompt and re-enable **Voice Type** in **Privacy & Security → Accessibility** and **Input Monitoring**. A paid Apple **Developer ID** certificate makes grants survive bundle updates and enables notarization — worth it if you change the bundle often.

## License

[MIT](LICENSE)

The sounds in `sounds/` are rendered from [cuelume](https://github.com/danielwh2/cuelume) 0.2.8 by Daniel Belyi, MIT — see `sounds/LICENSE-cuelume.txt`. To re-render them: `.venv/bin/python scripts/render_sounds.py` and open the printed address in a browser.

