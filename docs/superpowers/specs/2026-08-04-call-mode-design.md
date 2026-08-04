# Call Mode (record + transcribe calls) — design

**Date:** 2026-08-04
**Status:** Approved, pre-implementation
**Branch:** `claude/call-mode-transcription-eeea1b`

## Problem

The app only supports short push-to-talk / hands-free **dictation** from the
default microphone, capped at 5 minutes, delivered by pasting into the
frontmost field. The user wants to record their own calls (both sides — them
and the other participant), get a running transcript for the whole call, and
end up with the final text somewhere they can copy and paste into any AI tool
for analysis afterward.

Two things the current pipeline can't do: (1) capture anything other than the
microphone — a call's other-party audio is system output, not an input
device — and (2) run for call-length durations with a delivery mechanism other
than "paste into the field I started in."

## Goal

A second, independent recording mode — **Call Mode** — that:

- Captures **both sides** of a call (the user's mic + the call app's system
  audio) as one merged mono stream.
- Streams chunked transcription for however long the call runs (up to a
  multi-hour safety cap), reusing the existing pause-chunking pipeline.
- On stop, delivers the full transcript to a file on disk and the clipboard
  (no auto-paste), and lists it in a "Calls" menu for later retrieval.

### Non-goals (v1)

- Speaker diarization / "Я:" vs "Собеседник:" labels.
- Live growing-text display during the call (menubar indicator + timer only).
- Saving the raw audio (`.wav`).
- In-app AI summarization (the user pastes the raw transcript into their own
  AI).
- Automating the one-time macOS audio setup (Aggregate Device / Multi-Output
  Device) — this is inherently a manual, per-machine OS configuration step;
  documented, not scripted.
- Running dictation and a call recording at the same time.

## Decisions (from brainstorming)

- **Audio source:** both sides, via a macOS **Aggregate Device** (mic +
  a virtual loopback device, e.g. the user's existing VB-Cable) selected as
  input. Requires one-time manual setup in Audio MIDI Setup + routing the call
  app's output through a Multi-Output Device so the user still hears the call.
  This only works on machines with that setup done — documented as a
  precondition, not auto-configured.
  App-agnostic by construction — capture happens at the OS audio layer, so it
  works the same for Teams, WhatsApp, Zoom, a browser tab, etc. Both **Teams**
  (Settings → Devices → Speaker, or in-call ⋯ → Show Device Settings) and
  **WhatsApp Desktop** (its own mic/speaker menu on the call screen) let you
  pick the Multi-Output Device as *that app's own* output, instead of
  switching the Mac's system-wide output — the recommended default, since it
  only captures the call itself rather than every system sound. Only apps
  without a per-app output picker fall back to changing the system default
  output for the duration of the call.
- **No speaker labels** — merged plain text, no diarization dependency.
- **Start/stop:** both a menu item (**Call → Start/Stop Call Recording**) and
  a dedicated toggle hotkey — not the hold/double-tap dictation gesture, since
  a call has unpredictable, often long duration.
- **No live transcript view** — menubar shows a recording indicator + elapsed
  timer only; full text is revealed at Stop.
- **Delivery:** transcript file on disk (`~/Documents/JustVoiceType/Calls/`) +
  automatic clipboard copy at Stop, plus a **Calls** menu (mirrors **History**)
  to re-copy any past call's transcript.
- **No raw audio saved.**
- **Same transcription model** as the active Model-menu selection — no
  separate model choice for calls.
- **No Smart LLM polish** for calls (Raw text + `apply_replacements` only) —
  Clean/Prompt don't make sense at call length, and the user wants text
  suitable for pasting into their own AI unaltered beyond anglicism
  normalization.
- **Mutually exclusive with dictation** — starting one blocks the other, to
  avoid two concurrent PortAudio streams / transcriber calls fighting over the
  same background thread and model.
- **Incremental durability:** each transcribed chunk is appended to the
  transcript file as it lands, not just assembled at Stop — so a crash mid-call
  doesn't lose the whole recording.

## Config (`config.py`)

Two new keys, validated like the existing `hotkey`/`model`:

```python
"call_hotkey": "f13",   # default toggle key for Call Mode
"call_device": None,    # input device name for Call Mode; None = not configured
```

- `call_hotkey`: non-empty string, parseable by `parse_hotkey` (reuses the
  existing hotkey name space — `f13`..`f19`, `right_option`, etc.). Falls back
  to the default (`"f13"`) on invalid input, mirroring `_resolve_hotkey`'s
  existing fallback-and-persist pattern. If `call_hotkey == hotkey`
  (collision with the dictation key) on load, fall back `call_hotkey` to
  `"f13"` (or `"f14"` if that's *also* the dictation key) and log a warning —
  same "clean up a bad config value" spirit as the existing hotkey validation.
- `call_device`: any non-empty string (device name from `sd.query_devices()`)
  or `None`. Not validated against the live device list at load time (the
  device may be unplugged/renamed between runs) — resolved lazily at call
  start instead (see Error handling).

## Components

### 1. `Recorder` device selection (`voice_type.py:148`)

Two new optional constructor fields, defaulting to today's behavior:

```python
@dataclass
class Recorder:
    sample_rate: int = SAMPLE_RATE
    device: "Optional[str | int]" = None   # None = system default input
    all_channels: bool = False             # False = cap to 1 channel (today's behavior)
```

- `_detect_native_params` (`:179`): query `self.device` if set, else
  `sd.default.device[0]` as today. Channel count: `max_in` when
  `all_channels=True`, else the existing `1 if max_in >= 1 else max_in` cap.
- `_try_open` (`:222`): pass `kwargs["device"] = self.device` when set, in
  each of the tried `(sr, ch)` combinations, same fallback ladder as today.
- No change to `_to_mono_native` — it already averages all channels
  (`raw.mean(axis=1)`) down to mono, which is exactly what merges "mic
  channel(s)" + "loopback channel(s)" of an Aggregate Device into one stream
  once `all_channels=True` stops clipping the request to 1 channel.
- Regular dictation's `Recorder()` keeps `device=None, all_channels=False` —
  zero behavior change there.

### 2. `calls.py` (new module, mirrors `history.py`)

```python
CALLS_SUBDIR = "Calls"                 # ~/Documents/JustVoiceType/Calls/
CALLS_FILE_NAME = "calls.json"         # metadata, in config.config_dir()
MAX_ITEMS = 30
MENU_ITEMS = 10

def calls_dir() -> str: ...            # ~/Documents/JustVoiceType/Calls, created on demand
def transcript_path(ts: float) -> str: ...  # call-YYYY-MM-DD_HH-MM.txt, de-duped with -2, -3…

def start_transcript(ts: float) -> str: ...       # create empty file, return its path
def append_chunk(path: str, text: str) -> None: ...  # append one chunk (durability)
def finalize(path: str, full_text: str) -> None: ...  # overwrite with the final joined+cleaned text

def load() -> list[dict]: ...          # calls.json: [{ts, duration_sec, path, preview}, ...]
def save(items: list[dict]) -> None: ...
def add(path: str, full_text: str, duration_sec: float, now=None) -> list[dict]: ...
def clear() -> None: ...
def label(index: int, item: dict, max_len=60) -> str: ...  # "1.  14:32 (12 мин)  <preview>…"
```

- `append_chunk` is called from the worker as each non-final call chunk is
  transcribed, so the on-disk file always has "everything transcribed so
  far." `finalize` then overwrites it once with the fully joined + replaced
  text (chunk boundaries can split a word oddly; the final joined text is
  the canonical version).
- Metadata (`calls.json`) stores a short preview + the file path, **not** the
  full text — keeps the JSON small regardless of call length. Clicking a
  Calls-menu entry reads the `.txt` file from disk at click time.
- `config.config_dir()` (already imported) is reused for `calls.json`;
  `calls_dir()` is new and lives under `~/Documents/JustVoiceType/Calls`
  (visible, Finder-browsable — unlike the dotfile config dir — since this is
  the thing the user goes and grabs manually).

### 3. Call toggle gesture (`gestures.py`)

A minimal state machine, simpler than `GestureRecognizer` (no hold/double-tap
distinction — just a debounced press-to-toggle):

```python
class CallToggle:
    """Toggle on each real key-down; swallows OS auto-repeat while held."""

    def __init__(self):
        self.active = False
        self._key_down = False

    def on_press(self, now: float) -> "Optional[str]":
        if self._key_down:
            return None  # auto-repeat while held — ignore
        self._key_down = True
        self.active = not self.active
        return "call_start" if self.active else "call_stop"

    def on_release(self, now: float) -> None:
        self._key_down = False
```

### 4. Wiring in `run_app` (`voice_type.py:894`)

- `call_recorder_holder = {"obj": None}` — a fresh `Recorder(device=call_device_name, all_channels=True)`
  is built on each call start (mirrors how `recorder` is a long-lived single
  instance, but the call device can change between calls via the menu, so
  rebuild it per-session rather than caching).
- `call_session = {"active": False, "id": 0, "start_ts": 0.0, "path": None}`,
  parallel to the existing `session` dict. `call_state = {"value": "idle"}`
  (values `idle` / `recording` / `transcribing`) parallels `state`, so the
  menubar can show a distinct icon while the final chunk is still being
  transcribed after Stop, same as dictation's `"transcribing"` state — set to
  `"recording"` on `"call_start"`, `"transcribing"` on `"call_stop"`, and back
  to `"idle"` in the worker's `finally` once the `mode == "call"` finalize
  branch completes (mirrors `:1487-1489`'s `state["value"] = "idle"`).
- `ctrl` queue (`:957`) gains two new commands: `"call_start"` / `"call_stop"`
  — same queue as `"start"`/`"stop"`, since `control_loop` is deliberately the
  **only** thread touching PortAudio (see the comment at `:1516`); adding call
  commands to the same serialized queue keeps that invariant free.
- `control_loop` (`:1516`): after the existing dictation `if session["active"]`
  chunk-polling block, add a parallel block:
  ```python
  if call_session["active"]:
      if time.time() - call_session["start_ts"] > MAX_CALL_SESSION_SEC:
          log("[call] hit safety cap — auto-stopping")
          ctrl.put("call_stop")
      else:
          chunk = call_recorder.take_chunk(
              min_sec=streaming.CHUNK_SEC,
              target_sec=streaming.CHUNK_SEC,
              hard_max_sec=streaming.CHUNK_HARD_MAX_SEC,
          )
          if chunk is not None and not streaming.is_silent(chunk):
              jobs.put({"audio": chunk, "sid": call_session["id"], "mode": "call", "final": False})
  ```
  `MAX_CALL_SESSION_SEC = 4 * 3600` (vs. dictation's 5-minute `MAX_SESSION_SEC`).
- `"call_start"` handling: resolve `call_device` from config, refuse with a
  notification if unset/not found (see Error handling), else
  `call_recorder.start()`, bump `call_session["id"]`, create the transcript
  file via `calls.start_transcript(now)`, store its path in
  `call_session["path"]`.
- `"call_stop"` handling: `call_recorder.stop()`, push a final job
  `{"audio": rest, "sid": call_session["id"], "mode": "call", "final": True, "path": ...}`.
- `worker` (`:1401`) job dict gains `"mode"` (default `"dictation"` for
  existing dictation jobs — no change to that path). At finalize
  (`if not final: continue` / else-branch, `:1441` onward):
  - `mode == "dictation"`: **unchanged** — smart polish → replacements →
    history → `deliver_text`.
  - `mode == "call"`: join parts → `apply_replacements` (**no** smart polish)
    → `calls.finalize(path, full)` → `copy_to_clipboard(full)` →
    `calls.add(path, full, duration_sec)` → `menu_dirty` → `SOUND_DONE` →
    `notify("Voice Type", f"Звонок расшифрован ({mm:ss}) — скопировано в буфер")`
    → `finally: call_state["value"] = "idle"`.
  - Non-final call chunks (`final=False`) additionally call
    `calls.append_chunk(call_session["path"], text)` right after the existing
    `session_parts.setdefault(...).append(text)` line, for the incremental-durability decision.
- Mutual exclusion: in `on_press` (dictation hotkey, `:1630`) add
  `if call_session["active"]: return` before the existing gesture dispatch.
  In the new call-hotkey `on_press`, add the mirror check against
  `session["active"]` (dictation gesture in flight). Both are simple guards,
  no new locking — `control_loop` already serializes the actual PortAudio
  calls.
- A second `keyboard.Listener`-routed check: `on_press`/`on_release` (`:1630`,
  `:1640`) already dispatch on `key == hotkey_obj_holder["key"]`; add a
  parallel `elif key == call_hotkey_obj_holder["key"]:` branch calling into
  `CallToggle`, translating its `"call_start"`/`"call_stop"` return value into
  `ctrl.put(...)` (mirroring `_apply_actions`, but there's no timer/ARM state
  to manage here).

### 5. Menu (`_build_menu`, `:1062`)

- New **Call** section: a single toggle item
  (`"Start Call Recording"` / `"■ Stop Call Recording"`, driven by
  `call_session["active"]`, rebuilt via the existing `menu_dirty` flag on
  every start/stop transition — same mechanism History already uses, no
  per-tick menu rebuild needed).
- `_call_hotkey_menu()` — mirrors `_hotkey_menu()` (`:1090`), same
  `HOTKEY_PRESETS` pool, checkmarking `call_hotkey` instead of `hotkey`.
- `_call_device_menu()` — new: enumerate `sd.query_devices()`, filter
  `max_input_channels > 0`, one `MenuItem` per device name; selecting
  persists `call_device`. Current selection checkmarked; if the configured
  device isn't currently present, show it anyway (dimmed via a
  "⚠️ <name> (not connected)" label) so the user isn't silently reset.
- `_calls_menu()` — mirrors `_history_menu()` (`:1144`): `calls.label(...)`
  per item, click copies that call's `.txt` contents to the clipboard; plus
  an "Open Calls folder…" item (`subprocess.Popen(["open", calls.calls_dir()])`)
  and a "Clear calls list…" item (metadata only — mirrors `clear_history`,
  does not delete the `.txt` files).

### 6. Menubar icon (`_on_tick`, `:1315`)

`call_state["value"]` (see §4) is checked **before** the dictation branch in
`_on_tick` — the two never overlap in practice (mutual exclusion), so no
priority conflict, just an ordering choice:

```python
if call_state["value"] == "recording":
    elapsed = int(now - call_session["start_ts"])
    blink = "🔴" if int(now * 2) % 2 == 0 else "⭕"
    self.title = f"📞{blink} {elapsed // 60:02d}:{elapsed % 60:02d}"
elif call_state["value"] == "transcribing":
    dots = "." * (int(now * 2) % 4)
    self.title = f"📞⏳{dots}"
elif state["value"] == "recording":
    ...  # existing dictation branch, unchanged
```

## Error handling

- **No `call_device` configured**, or the configured name isn't in
  `sd.query_devices()` at start time → refuse to start, `notify("Voice Type",
  "Выберите Call Device в меню перед началом записи звонка")`, no recorder
  opened.
- **Device disappears mid-call** (unplugged, app crash) → `take_chunk`/`stop`
  raise inside `control_loop`'s existing try/except around recorder calls;
  log + `notify(...)` + treat as an implicit `call_stop` (finalize whatever
  was captured so far — don't spin forever failing silently).
- **Entire call is silence** (started by accident) → same per-chunk
  `streaming.is_silent` guard as dictation; if the final joined text is empty,
  skip `calls.finalize`/`add`/clipboard entirely and
  `notify("Voice Type", "Пустой звонок — ничего не сохранено")`, same spirit
  as today's `else: print("[·] Empty.")` dictation path. The empty transcript
  file created at start is deleted in this case.
- **Disk write failure** (`calls.append_chunk`/`finalize` hits `OSError`) →
  catch, log, but still `copy_to_clipboard(full)` — the clipboard is the
  fallback delivery even when the file can't be written, so the user never
  loses the text outright; notify separately that the file save failed.
- **Hotkey collision** (`call_hotkey == hotkey`) → handled at config load per
  the Config section above; also re-checked when the user picks a new value
  from either Hotkey menu (refuse + notify if it would collide with the
  other).

## Testing

- **`tests/test_calls.py`** (new, mirrors `tests/test_history.py`'s
  `XDG_CONFIG_HOME`-tempdir pattern):
  - `load`/`save`/`add`/`clear` roundtrip, newest-first, capped at `MAX_ITEMS`.
  - `transcript_path` de-dupes filenames on collision (`-2`, `-3`…).
  - `start_transcript` creates an empty file; `append_chunk` appends text;
    `finalize` overwrites with the final text (not append).
  - `label` formats duration + preview, truncates long previews.
- **`tests/test_gestures.py`** (extend): `CallToggle` — first press → active +
  `"call_start"`; press while held (repeat) → `None`, no state change;
  release then press → toggles off (`"call_stop"`); release is a no-op event.
- **`tests/test_config.py`** (extend): `call_hotkey`/`call_device` validation
  — valid values round-trip; invalid `call_hotkey` falls back to default;
  `call_hotkey == hotkey` on load resolves the collision; `call_device` accepts
  any non-empty string and `null`.
- **Recorder device/`all_channels` plumbing**: no new automated test — the
  existing `Recorder` has zero unit tests today (it's a live-hardware class,
  not mocked anywhere in the suite), and the new fields are a straight
  pass-through to `sounddevice` calls. Covered by the manual QA pass instead.
- **Manual QA** (requires the real Aggregate Device setup):
  1. Build the Aggregate Device (mic + VB-Cable) and Multi-Output Device per
     the README steps; select it as Call Device.
  2. Start a call recording, speak, play some other audio through the call
     app (or a video) as the "other side," Stop — confirm the transcript
     contains both, merged, in one file, and is on the clipboard.
  3. Confirm the file at `~/Documents/JustVoiceType/Calls/` grows during the
     call (incremental `append_chunk`), not just at Stop.
  4. Try starting dictation while a call is recording (and vice versa) —
     confirm the second one is blocked.
  5. Unset Call Device → confirm Start refuses with a notification.
  6. Temporarily lower `MAX_CALL_SESSION_SEC` to test the safety-cap auto-stop
     path without waiting 4 hours.

## Ship

Ships on `claude/call-mode-transcription-eeea1b`. README gets a new "Call
Mode" feature section (what it does + the one-time Audio MIDI Setup walkthrough:
Aggregate Device, Multi-Output Device, routing the call app's output — with
Teams/WhatsApp-specific per-app-output steps called out as the recommended
path, system-default output as the fallback) and a new row in the
persisted-settings list (`call_hotkey`, `call_device`). Version bump
(`0.9.0` → `0.10.0`) after implementation, following the existing
per-feature bump convention.
