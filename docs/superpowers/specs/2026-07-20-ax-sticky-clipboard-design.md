# AX insertion: stick to the original field + preserve the clipboard — design

**Date:** 2026-07-20
**Status:** Approved, pre-implementation
**Builds on:** `2026-07-20-ax-text-insertion-design.md` (same branch, not yet shipped)

## Problem

The AX insertion mode (just added) inserts into whatever field is focused **at
insertion time**. If the user switches windows while transcription finishes, the
text lands in the wrong place. Separately, the user's real pain: dictations
**clobber the clipboard** — in the default paste path the recognized text is left
on the clipboard (`--restore-clipboard` is off by default), overwriting whatever
the user had copied.

Goal: make AX mode **non-intrusive** — land the text in the field the user was in
when they started dictating, and never persistently change the clipboard.
Dictations are always in the history regardless, so nothing is lost.

## Key constraint

AX insertion runs in a subprocess, and an `AXUIElementRef` is an opaque pointer
that is **not valid across processes**. So we cannot capture the focused element
at record-start and hand it to the insert subprocess. Instead we capture the
**target application PID** (a serializable int) and re-address that app at
insertion time via `AXUIElementCreateApplication(pid)`.

## Decisions (from brainstorming)

- If the user moved to another app and a **silent background insert** into the
  original app fails: **do not steal focus** and do not paste into the current
  (wrong) window — save to history and notify.
- Clipboard preservation applies to **AX mode only**; the plain paste mode and the
  global `--restore-clipboard` default are unchanged.
- History already records every dictation (`history.add` in the worker) — no
  change needed there.

## Behavior

At dictation **start**: capture the frontmost application's PID → `target_app`.

At **insertion** (AX mode):
1. If the target app is still frontmost (user didn't switch, or switched back):
   insert into the system-wide focused element. On failure → clipboard-restore
   Cmd+V into that same (frontmost) app.
2. If the user switched to a different app: try a **silent background insert** into
   the *original* app's focused element (`AXUIElementCreateApplication(pid)` →
   `kAXFocusedUIElementAttribute` → set `kAXSelectedText`), **without activating**
   it. On success, text lands in the original field with no focus change.
3. If that background insert fails: **history only** — notify the user, do not
   steal focus, do not paste elsewhere.

**Clipboard:** AX success never touches it; the Cmd+V fallback (case 1 failure)
always restores the previous contents; the history-only path never touches it.

## Components

### 1. `frontmost_app_pid() -> Optional[int]` + `target_app` holder

Reads the frontmost app PID via `NSWorkspace.sharedWorkspace().frontmostApplication()`.
AppKit is already loaded in-process by rumps, so this is a safe, instant in-process
read. Returns `None` on any error. A `target_app = {"pid": None}` holder is set at
record-start (when the recorder starts) and read by the worker at delivery. If it's
`None`, behavior degrades to the current AX mode (insert into whatever is focused now).

### 2. `insert_via_ax(text: str, target_pid: Optional[int] = None) -> str`

Returns a status string: `"ok"` | `"paste_fallback"` | `"history_only"`.

Runs the subprocess `sys.executable -c _AX_INSERT_CODE` with the text on stdin and
`target_pid` passed as `argv` (e.g. `["-c", CODE, str(target_pid or 0)]`). Subprocess
logic:
- `cur_pid = NSWorkspace.frontmostApplication().processIdentifier()` (or -1).
- If `target_pid` (>0) and `target_pid != cur_pid` → **focus changed**: build
  `AXUIElementCreateApplication(target_pid)`, get its `kAXFocusedUIElementAttribute`,
  set `kAXSelectedText`. Exit 0 on success; else write reason to stderr, exit **3**.
- Else (target is frontmost, or unknown) → system-wide focused element, set
  `kAXSelectedText`. Exit 0 on success; else write reason, exit **1**.
- Any exception → write `repr(e)`, exit **1**.

Parent maps exit codes → status: `0 → "ok"`, `3 → "history_only"`,
`1/other → "paste_fallback"`. Empty text → returns `"paste_fallback"` without
spawning (caller's existing empty-text guard returns before this anyway; keep the
guard). Subprocess timeout (2s) or spawn exception → `"paste_fallback"`.

### 3. `deliver_text(text, do_paste, restore_clipboard, insert_mode="paste", target_pid=None)`

- Empty text → return (unchanged).
- If `do_paste and insert_mode == "ax"`:
  - `status = insert_via_ax(text, target_pid)`
  - `"ok"` → return.
  - `"history_only"` → `notify("Voice Type", "Saved to history — target window changed")`; return (clipboard untouched).
  - `"paste_fallback"` → fall through to the clipboard path below.
- Clipboard path: compute `restore = restore_clipboard or (insert_mode == "ax")`
  and use `restore` everywhere the function currently uses `restore_clipboard`
  (read previous, and the restore thread). This forces clipboard restore on the AX
  fallback while leaving plain paste mode governed by `restore_clipboard`.

`notify` is a module-level function already used by the worker; `deliver_text` runs
on the worker thread, so calling it here is consistent. (Plan verifies it's
module-level.)

### 4. Worker wiring

The worker's `deliver_text(...)` call passes `target_pid=target_app["pid"]`. The
recorder-start path sets `target_app["pid"] = frontmost_app_pid()`.

## Data flow

hotkey press → recorder start (**capture target_app pid**) → record → transcribe →
polish → `history.add` (unchanged) → `deliver_text(..., insert_mode, target_pid)`.

## Error handling

- `target_pid=None` (capture failed/not ready) → AX targets current focus (today's
  behavior); text still lands or falls back.
- AX subprocess exception/timeout → `"paste_fallback"` (text lands in current focus,
  clipboard restored).
- `history_only` → notify; text preserved in history; nothing pasted, clipboard
  untouched.

## Breaking-change note (existing tests must be updated)

Changing `insert_via_ax` from `-> bool` to `-> str` (status) is a contract change.
The plan MUST update the tests written for the base AX feature:
- `TestInsertViaAxGuards` (asserted `insert_via_ax("") is False` / `isinstance(..., bool)`)
  → now `insert_via_ax("") == "paste_fallback"` (a str), still without spawning a
  subprocess.
- `TestDeliverTextRouting` monkeypatched `insert_via_ax` to return `True`/`False`
  → now returns `"ok"` / `"paste_fallback"` / `"history_only"`; and `deliver_text`'s
  call becomes `insert_via_ax(text, target_pid)` (two args), so the stubs must accept
  the extra argument.

## Testing

- **Unit** (`tests/test_deliver_text.py`, monkeypatch module-level fns):
  - `insert_via_ax → "ok"`: no clipboard, no paste, no notify.
  - `→ "history_only"`: `notify` called once; no copy/paste; clipboard untouched.
  - `→ "paste_fallback"` with `insert_mode="ax"`: copy + paste happen AND the
    clipboard is restored (previous content re-copied) even though
    `restore_clipboard=False` — assert the restore path ran.
  - `insert_mode="paste"` unchanged: AX never called; restore governed by
    `restore_clipboard` (still off by default).
  - Exit-code → status mapping for `insert_via_ax` is covered by monkeypatching at
    the `deliver_text` layer; the subprocess code itself is validated manually.
- **Manual** (Apple Silicon): dictate in app A, switch to app B before it finishes;
  confirm (a) silent insert into A where supported (Notes/TextEdit/Safari), (b)
  history-only + notification where background insert isn't supported (Terminal,
  some Electron), (c) staying in A still inserts, (d) the clipboard is never left
  holding the dictation in any AX path.

## Non-goals (YAGNI)

- No activation/focus-steal fallback (user chose "don't steal focus").
- No change to plain paste mode or the global `--restore-clipboard` default.
- No per-window (only per-app) targeting — window refs aren't serializable and app
  focus is sufficient for the "field I started in" case.

## Ship

Lands on the same branch as the base AX feature; ship together as one GitHub update
(push + release, likely v0.9.0) after manual validation.
