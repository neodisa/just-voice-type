# AX Sticky-Field + Clipboard-Safe Insertion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AX insertion land text in the field the user started dictating in (even if they switched windows) and never persistently change the clipboard.

**Architecture:** Capture the frontmost application's PID at record-start (serializable, unlike an AXUIElementRef). `insert_via_ax(text, target_pid)` returns a status (`ok` / `paste_fallback` / `history_only`): it inserts into the focused element when the target app is still frontmost, silently background-inserts into the original app when the user switched away, and reports `history_only` (no focus steal, no wrong-window paste) when background insert fails. `deliver_text` consumes the status and forces clipboard restore on the AX Cmd+V fallback.

**Tech Stack:** Python 3, pyobjc `ApplicationServices` (AX) + `AppKit` (NSWorkspace, already loaded by rumps), stdlib `unittest`.

**Test command:** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v`

**Spec:** `docs/superpowers/specs/2026-07-20-ax-sticky-clipboard-design.md`
**Builds on:** the base AX feature already on this branch (`insert_via_ax`, `deliver_text(insert_mode=...)`, the Smart-menu toggle).

**Verified anchors:** `notify(title, message)` is module-level (`voice_type.py:116`). Record start is the `if cmd == "start":` handler (`~1441`), where `recorder.start()` succeeds. `from AppKit import NSWorkspace; NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()` works in-process. `insert_via_ax` is at `~660`, `_AX_INSERT_CODE` at `~633`, the worker `deliver_text(...)` call at `~1381`.

**Note on task boundaries:** The `insert_via_ax` return-type change (`bool → str`) is a breaking contract change that its own guard tests AND `deliver_text`'s routing tests depend on. Task 2 therefore updates both functions and all their tests together, so every commit leaves the suite green.

---

## File Structure

- Modify: `voice_type.py` — add `frontmost_app_pid()`; rewrite `_AX_INSERT_CODE` + `insert_via_ax` (status + target_pid); extend `deliver_text` (status routing + forced restore); add `target_app` holder + capture at record-start; pass `target_pid` in the worker call.
- Modify: `tests/test_deliver_text.py` — add PID test; update guard + routing tests to the new contract; add status-routing + forced-restore tests.
- Modify: `README.md` — note sticky-field + clipboard-safe behavior.

---

### Task 1: `frontmost_app_pid()` + capture holder

**Files:**
- Modify: `voice_type.py` (helper near `notify` ~116; `target_app` holder near other holders ~854; capture in `cmd == "start"` handler ~1444)
- Test: `tests/test_deliver_text.py`

- [ ] **Step 1: Write the failing test.** Append to `tests/test_deliver_text.py` before the `if __name__` block:

```python
class TestFrontmostAppPid(unittest.TestCase):
    def test_returns_int_or_none(self):
        pid = voice_type.frontmost_app_pid()
        self.assertTrue(pid is None or isinstance(pid, int))
```

- [ ] **Step 2: Run to verify it fails.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_deliver_text.TestFrontmostAppPid -v` → AttributeError (not defined).

- [ ] **Step 3: Add the helper.** In `voice_type.py`, near `notify` (~116), add:

```python
def frontmost_app_pid():
    """PID of the current frontmost application, or None. AppKit is already
    loaded in-process by rumps, so this is a safe, instant read."""
    try:
        from AppKit import NSWorkspace  # type: ignore

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else None
    except Exception:
        return None
```

- [ ] **Step 4: Run test to verify it passes.** Same command → PASS.

- [ ] **Step 5: Add the `target_app` holder.** Find the holders block (`smart_mode = {"value": ...}`, `insert_mode = {"value": ...}`, ~854). After the `insert_mode` holder, add:

```python
    # PID приложения, активного на старте диктовки (для «прилипания» AX-вставки).
    target_app = {"pid": None}
```

- [ ] **Step 6: Capture the PID at record start.** In the `if cmd == "start":` handler (~1441), inside the `try:` right after `session["start_ts"] = time.time()`, add:

```python
                    target_app["pid"] = frontmost_app_pid()
```

- [ ] **Step 7: Verify import + suite.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -c "import voice_type" && /Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v` → import OK; all PASS.

- [ ] **Step 8: Commit.**
```bash
git add voice_type.py tests/test_deliver_text.py
git commit -m "feat: capture frontmost app PID at record start (AX sticky target)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `insert_via_ax` status contract + `deliver_text` routing (one atomic change)

Both functions and all their tests change together so the suite stays green in one commit.

**Files:**
- Modify: `voice_type.py` (`_AX_INSERT_CODE` ~633, `insert_via_ax` ~660, `deliver_text` ~685)
- Test: `tests/test_deliver_text.py` (`TestInsertViaAxGuards`, `TestDeliverTextRouting`)

- [ ] **Step 1: Update the guard tests to the new string contract.** In `tests/test_deliver_text.py`, replace the body of `TestInsertViaAxGuards` with:

```python
class TestInsertViaAxGuards(unittest.TestCase):
    def test_empty_text_returns_paste_fallback_without_subprocess(self):
        # Empty text short-circuits to a status string, never spawning a subprocess.
        self.assertEqual(voice_type.insert_via_ax(""), "paste_fallback")

    def test_returns_status_string(self):
        self.assertIn(voice_type.insert_via_ax(""),
                      ("ok", "paste_fallback", "history_only"))
```

- [ ] **Step 2: Rewrite the `TestDeliverTextRouting` class** to the new contract (status strings, 2-arg stub, notify stub, forced-restore assertions):

```python
class TestDeliverTextRouting(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig = {}
        for name in ("insert_via_ax", "copy_to_clipboard",
                     "paste_via_cmd_v", "read_clipboard", "notify"):
            self._orig[name] = getattr(voice_type, name)
        voice_type.copy_to_clipboard = lambda t: self.calls.append(("copy", t))
        voice_type.paste_via_cmd_v = lambda: self.calls.append(("paste",))
        voice_type.read_clipboard = lambda: (self.calls.append(("read",)) or "hi")
        voice_type.notify = lambda title, msg: self.calls.append(("notify", title, msg))

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(voice_type, name, fn)

    def _stub_ax(self, status):
        voice_type.insert_via_ax = lambda t, pid=None: (
            self.calls.append(("ax", t, pid)) or status)

    def test_ok_touches_nothing_else(self):
        self._stub_ax("ok")
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax", target_pid=123)
        self.assertEqual(self.calls, [("ax", "hi", 123)])

    def test_history_only_notifies_and_skips_clipboard(self):
        self._stub_ax("history_only")
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax", target_pid=123)
        ops = [c[0] for c in self.calls]
        self.assertEqual(ops, ["ax", "notify"])
        self.assertNotIn("copy", ops)
        self.assertNotIn("paste", ops)

    def test_paste_fallback_in_ax_mode_forces_restore(self):
        self._stub_ax("paste_fallback")
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax", target_pid=123)
        ops = [c[0] for c in self.calls]
        # restore forced despite restore_clipboard=False → read_clipboard runs
        # twice (previous + placed); copy + paste happen.
        self.assertEqual(ops.count("read"), 2)
        self.assertIn(("copy", "hi"), self.calls)
        self.assertIn(("paste",), self.calls)

    def test_paste_mode_unchanged_no_ax_no_forced_restore(self):
        self._stub_ax("ok")  # must never be called in paste mode
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="paste", target_pid=123)
        ops = [c[0] for c in self.calls]
        self.assertNotIn("ax", ops)
        # restore off in paste mode → read_clipboard only once (placed check)
        self.assertEqual(ops.count("read"), 1)
        self.assertIn(("copy", "hi"), self.calls)
        self.assertIn(("paste",), self.calls)
```

- [ ] **Step 3: Run to verify the tests fail.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_deliver_text -v` → `TestInsertViaAxGuards` and `TestDeliverTextRouting` FAIL (old `insert_via_ax` returns `False`/bool and 1-arg; `deliver_text` has no `target_pid`/status routing). `TestFrontmostAppPid` still PASSES.

- [ ] **Step 4: Rewrite `_AX_INSERT_CODE`.** Replace the entire `_AX_INSERT_CODE = (...)` string with:

```python
_AX_INSERT_CODE = (
    "import sys\n"
    "from ApplicationServices import (\n"
    "    AXUIElementCreateSystemWide,\n"
    "    AXUIElementCreateApplication,\n"
    "    AXUIElementCopyAttributeValue,\n"
    "    AXUIElementSetAttributeValue,\n"
    "    kAXFocusedUIElementAttribute,\n"
    "    kAXSelectedTextAttribute,\n"
    ")\n"
    "text = sys.stdin.buffer.read().decode('utf-8')\n"
    "target_pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0\n"
    "def set_on(el):\n"
    "    return AXUIElementSetAttributeValue(el, kAXSelectedTextAttribute, text) == 0\n"
    "try:\n"
    "    cur_pid = -1\n"
    "    try:\n"
    "        from AppKit import NSWorkspace\n"
    "        app = NSWorkspace.sharedWorkspace().frontmostApplication()\n"
    "        cur_pid = int(app.processIdentifier()) if app is not None else -1\n"
    "    except Exception:\n"
    "        cur_pid = -1\n"
    "    if target_pid > 0 and target_pid != cur_pid:\n"
    "        app_el = AXUIElementCreateApplication(target_pid)\n"
    "        err, focused = AXUIElementCopyAttributeValue(app_el, kAXFocusedUIElementAttribute, None)\n"
    "        if err == 0 and focused is not None and set_on(focused):\n"
    "            sys.exit(0)\n"
    "        sys.stderr.write('focus changed; background insert failed')\n"
    "        sys.exit(3)\n"
    "    sw = AXUIElementCreateSystemWide()\n"
    "    err, focused = AXUIElementCopyAttributeValue(sw, kAXFocusedUIElementAttribute, None)\n"
    "    if err == 0 and focused is not None and set_on(focused):\n"
    "        sys.exit(0)\n"
    "    sys.stderr.write('insert failed on frontmost (err=%s)' % err)\n"
    "    sys.exit(1)\n"
    "except Exception as e:\n"
    "    sys.stderr.write(repr(e))\n"
    "    sys.exit(1)\n"
)
```

- [ ] **Step 5: Rewrite `insert_via_ax`.** Replace the whole `def insert_via_ax(...)` function with:

```python
def insert_via_ax(text: str, target_pid: "Optional[int]" = None) -> str:
    """Insert `text` into the focused field via the macOS Accessibility API,
    WITHOUT touching the clipboard. Returns a status:

      "ok"             — inserted (into the frontmost focus, or silently into the
                         original app's field when focus had moved away).
      "history_only"   — the user switched to another app and the background
                         insert into the original app failed; caller must NOT
                         steal focus or paste elsewhere (text stays in history).
      "paste_fallback" — insertion failed while the target app is still frontmost
                         (or unknown); caller should fall back to clipboard+Cmd+V.

    `target_pid` is the app that was frontmost when dictation started (from
    frontmost_app_pid()). Runs in the signed-python subprocess pattern; the pid is
    passed as argv, text on stdin. Any failure/timeout → "paste_fallback".
    """
    if not text:
        return "paste_fallback"
    try:
        r = subprocess.run(
            [sys.executable, "-c", _AX_INSERT_CODE, str(target_pid or 0)],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=2.0,
        )
        if r.returncode == 0:
            return "ok"
        reason = (r.stderr or b"").decode("utf-8", "ignore").strip()
        tail = reason.splitlines()[-1] if reason else ""
        if r.returncode == 3:
            print(f"[i] AX: target window changed, kept in history: {tail}",
                  file=sys.stderr)
            return "history_only"
        print(f"[i] AX insert failed (falling back to paste): {tail}",
              file=sys.stderr)
        return "paste_fallback"
    except Exception as e:
        print(f"[!] AX insert failed: {e}", file=sys.stderr)
        return "paste_fallback"
```

- [ ] **Step 6: Update `deliver_text`.** Change the signature from:
```python
def deliver_text(
    text: str,
    do_paste: bool,
    restore_clipboard: bool,
    insert_mode: str = "paste",
) -> None:
```
to:
```python
def deliver_text(
    text: str,
    do_paste: bool,
    restore_clipboard: bool,
    insert_mode: str = "paste",
    target_pid: "Optional[int]" = None,
) -> None:
```

Replace the current AX branch:
```python
    # AX mode: try direct Accessibility insertion first (no clipboard touched).
    # On any failure, fall through to the clipboard+Cmd+V path below.
    if do_paste and insert_mode == "ax":
        if insert_via_ax(text):
            return
```
with:
```python
    # AX mode: try direct Accessibility insertion first (no clipboard touched).
    if do_paste and insert_mode == "ax":
        status = insert_via_ax(text, target_pid)
        if status == "ok":
            return
        if status == "history_only":
            # User moved to another app and background insert failed. Per design,
            # don't steal focus or paste into the wrong window — it's in history.
            notify("Voice Type", "Saved to history — target window changed")
            return
        # status == "paste_fallback": fall through to clipboard+Cmd+V below.
```

Replace the line:
```python
    previous = read_clipboard() if restore_clipboard else None
```
with:
```python
    # In AX mode the paste fallback must not clobber the clipboard, so restore
    # regardless of the restore_clipboard flag. Plain paste mode is unchanged.
    restore = restore_clipboard or (insert_mode == "ax")
    previous = read_clipboard() if restore else None
```

And change the restore-block guard from:
```python
    if restore_clipboard and previous is not None:
```
to:
```python
    if restore and previous is not None:
```

- [ ] **Step 7: Run the deliver_text tests.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_deliver_text -v` → PASS (guards + 4 routing + PID test).

- [ ] **Step 8: Full suite.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v` → all PASS.

- [ ] **Step 9: Commit.**
```bash
git add voice_type.py tests/test_deliver_text.py
git commit -m "feat: AX insert targets original app by PID; status-driven fallback; clipboard-safe

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Worker wiring — pass `target_pid`

**Files:**
- Modify: `voice_type.py` (worker `deliver_text(...)` call ~1381)

- [ ] **Step 1: Pass the captured pid.** In the worker, change:
```python
                    deliver_text(
                        full,
                        do_paste=not args.no_paste,
                        restore_clipboard=args.restore_clipboard,
                        insert_mode=insert_mode["value"],
                    )
```
to:
```python
                    deliver_text(
                        full,
                        do_paste=not args.no_paste,
                        restore_clipboard=args.restore_clipboard,
                        insert_mode=insert_mode["value"],
                        target_pid=target_app["pid"],
                    )
```

- [ ] **Step 2: Verify import + suite.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -c "import voice_type" && /Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v` → import OK; all PASS.

- [ ] **Step 3: Commit.**
```bash
git add voice_type.py
git commit -m "feat: pass captured target_pid into deliver_text (AX sticky wiring)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Manual validation (user runs)

**Files:** none (Apple Silicon, needs focus/permissions).

- [ ] **Step 1:** After merging to local main and relaunching the app, enable **Smart → Insert via Accessibility**.
- [ ] **Step 2: Sticky-field.** Dictate into app A (e.g. Notes), then immediately click into app B before transcription finishes. Confirm the text appears in **A**, not B, with no focus steal.
- [ ] **Step 3: History-only path.** Repeat with A = an app whose field doesn't accept background AX insert (e.g. Terminal / some Electron app). Confirm a "Saved to history — target window changed" notification, focus NOT stolen, dictation present in the History menu. Tail `~/Library/Logs/WhisperFlow/whisper_flow.log` for `[i] AX: target window changed…`.
- [ ] **Step 4: Clipboard preserved.** Copy a known value; dictate; then Cmd+V elsewhere — confirm your known value is intact (AX success never touches it; AX fallback restores it).
- [ ] **Step 5:** Record findings in `docs/superpowers/specs/2026-07-20-ax-sticky-clipboard-design.md` under a "Local results" section; commit.

---

### Task 5: README note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Extend the Insertion-mode bullet.** In README.md, replace the existing `- 📝 **Insertion mode**` bullet with:

```
- 📝 **Insertion mode** — by default text is pasted via clipboard + Cmd+V (and the previous clipboard is restored). Switch to **Insert via Accessibility** from the menu (under **Smart → Insert via Accessibility**) to type straight into the focused field. In this mode the dictation **lands in the field you started in** even if you switch windows (it inserts into that app in the background), and the **clipboard is never clobbered** — on any fallback the previous clipboard is restored, and every dictation is always kept in the History menu. If the original field can't accept a background insert, the text is kept in history and you get a notification (no window is yanked to the front).
```

- [ ] **Step 2: Commit.**
```bash
git add README.md
git commit -m "docs: document AX sticky-field + clipboard-safe behavior

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- Line numbers are approximate (`~`) — anchor on quoted code.
- Test with the MAIN-repo venv: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python` (this worktree has none).
- `Optional` is already imported at module top; `subprocess`, `sys`, `time`, `threading` too. `notify` is module-level (`voice_type.py:116`).
- Do NOT touch plain paste mode behavior or the `--restore-clipboard` default — clipboard-restore is forced ONLY when `insert_mode == "ax"`.
- Tasks 1-3 and 5 are unit-testable/mechanical. Task 4 is manual on-device validation (window-switch timing + per-app AX support) and is not automated — the subprocess AX code paths (background insert, focus-change detection) have no automated coverage by design.
