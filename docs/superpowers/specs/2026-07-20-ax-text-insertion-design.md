# Accessibility (AX) text insertion — design

**Date:** 2026-07-20
**Status:** Approved, pre-implementation

## Problem

We deliver recognized text by copying it to the clipboard and emulating Cmd+V
(`deliver_text` in `voice_type.py`). This clobbers the clipboard (we only
optionally restore it) and fails in apps that intercept Cmd+V. SuperDictate
instead inserts text directly into the focused field via the macOS Accessibility
(AX) API. We want that as an **optional** insertion mode.

## Chosen approach

Add an opt-in `insert_mode` (`"paste"` default | `"ax"`), toggled from the menu
and persisted in config. In `"ax"` mode, `deliver_text` tries a direct AX
insertion first and, on any failure, falls back to the existing clipboard+Cmd+V
path — so text always lands. On AX success the clipboard is never touched (the
whole point).

AX insertion runs in the same signed-python subprocess pattern already used for
Cmd+V: doing AppKit/AX work in the main process (next to the pynput listener and
MLX/Metal) is unsafe, and background processes are silently denied Automation.
The subprocess needs only Accessibility permission — the same grant the hotkey
already uses.

## Non-goals (YAGNI)

- Not replacing clipboard paste as the default (opt-in only).
- No per-app rules or heuristics about which apps support AX (try, fall back).
- No caret-following animation or UI (SuperDictate has one; out of scope).

## Components

### 1. `insert_via_ax(text: str) -> bool` (new, `voice_type.py`)

Runs a subprocess `sys.executable -c <AX_CODE>` that:
- `syswide = AXUIElementCreateSystemWide()`
- copies `kAXFocusedUIElementAttribute` → focused element
- attempts `AXUIElementSetAttributeValue(elem, kAXSelectedTextAttribute, text)`
  (inserts at the caret / replaces the current selection)
- exits `0` on success, non-zero on any failure (no focused element, attribute
  not settable, exception).

The text is passed to the subprocess **via stdin** (`subprocess.run(..., input=text)`),
NOT interpolated into the `-c` string — avoids quoting/injection and arg-length
issues. Parent returns `exit_code == 0`. The clipboard is never read or written here. A short subprocess
timeout (e.g. 2s) is treated as failure.

### 2. `deliver_text(text, do_paste, restore_clipboard, insert_mode)` (modify)

New `insert_mode` parameter. Logic:
- Empty text → return (unchanged).
- If `do_paste` and `insert_mode == "ax"`: call `insert_via_ax(text)`. On
  success, return (clipboard untouched, nothing to restore). On failure, fall
  through to the existing clipboard+Cmd+V path.
- Otherwise: existing behavior (copy to clipboard, optional Cmd+V, optional
  restore).

`--no-paste` means "clipboard only" and AX does not apply.

### 3. `config.py` (modify)

Add `insert_mode` to `DEFAULTS` (`"paste"`), `_defaults_copy()`, and `_validate`
(accept only `"paste"`/`"ax"`, else default). Persisted by `save()` alongside the
other keys.

### 4. Menu + persistence (`voice_type.py`, modify)

A checkable menu item **"Insert via Accessibility (no clipboard)"**: checked ⇔
`insert_mode == "ax"`. Clicking toggles the mode and calls `persist()`. Add
`insert_mode` to the `persist()` payload and read it into a mutable holder at
startup (same pattern as `smart_mode`, `current_model`).

### 5. Worker wiring (`voice_type.py`, modify)

The worker call to `deliver_text(...)` (~line 1300) passes the current
`insert_mode` from the holder.

## Data flow (only the last step changes)

transcribe → (stream join) → polish → `deliver_text(text, do_paste,
restore_clipboard, insert_mode)`. Queue/worker/streaming untouched.

## Error handling

- AX subprocess: exception / no focused element / non-settable attribute /
  timeout → non-zero exit → parent falls back to clipboard+Cmd+V. Text always
  lands.
- Empty text → early return.
- Fallback path logs a one-line note so AX failures are diagnosable.

## Risk to verify in the plan (first step)

Confirm the AX bindings (`AXUIElementCreateSystemWide`,
`AXUIElementCopyAttributeValue`, `AXUIElementSetAttributeValue`,
`kAXFocusedUIElementAttribute`, `kAXSelectedTextAttribute`) are importable in the
project venv (via `pyobjc-framework-ApplicationServices`). `Quartz`
(`pyobjc-framework-Quartz`) is already present for Cmd+V. If ApplicationServices
is missing, add it to `requirements.txt`.

## Testing

- **Unit tests** (`tests/`, no GUI/AX, pure logic):
  - `config`: `insert_mode` validation — valid `paste`/`ax`, invalid → default,
    missing → default; round-trips through `save`/`load`.
  - `deliver_text` routing: monkeypatch module-level `insert_via_ax`,
    `copy_to_clipboard`, `paste_via_cmd_v`. Assert: `insert_mode="ax"` +
    `insert_via_ax→True` ⇒ clipboard/paste NOT called; `→False` ⇒ clipboard+paste
    called; `insert_mode="paste"` ⇒ AX not called, clipboard+paste called.
- **Manual A/B (Apple Silicon, needs focus/permissions):** AX insertion in
  TextEdit, Notes, a Safari text field, Terminal, and Slack (Electron). Verify
  either direct insertion or graceful clipboard fallback, and that the clipboard
  is unchanged on AX success.

## Ship

After local validation: update README (new Insert menu + trade-offs), then a
GitHub update (commit + release, consistent with v0.8.0 flow).
