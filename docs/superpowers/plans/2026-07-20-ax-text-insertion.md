# AX Text Insertion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional "insert via Accessibility" mode that types recognized text straight into the focused field (no clipboard), falling back to the existing clipboard+Cmd+V path on any failure. Toggled from the menu, persisted in config; default stays clipboard paste.

**Architecture:** A new config key `insert_mode` (`"paste"` default | `"ax"`). `deliver_text()` gains an `insert_mode` parameter; in `"ax"` mode it calls `insert_via_ax(text)` (a signed-python subprocess using the macOS AX API), and on failure falls through to the current clipboard+Cmd+V code. A checkable menu item toggles the mode.

**Tech Stack:** Python 3, pyobjc `ApplicationServices` (AX API — already installed, no new dep), Quartz (existing), rumps (menu), stdlib `unittest`.

**Test command (from project root):** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v`

**Spec:** `docs/superpowers/specs/2026-07-20-ax-text-insertion-design.md`

**Verified fact:** AX symbols import via `from ApplicationServices import AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue, AXUIElementSetAttributeValue, kAXFocusedUIElementAttribute, kAXSelectedTextAttribute`; `pyobjc-framework-ApplicationServices` (12.1) is already in the venv. No dependency change needed.

---

## File Structure

- Modify: `config.py` — add `insert_mode` to defaults + validation.
- Modify: `voice_type.py` — add `_AX_INSERT_CODE`, `insert_via_ax()`, `insert_mode` param on `deliver_text()`, the `insert_mode` holder, a checkable menu item + setter, `persist()` payload, and the worker call.
- Modify: `tests/test_config.py` — `insert_mode` validation tests.
- Create: `tests/test_deliver_text.py` — `deliver_text` routing tests.
- Modify: `README.md` — document the Insert menu + trade-offs.

---

### Task 1: config `insert_mode`

**Files:**
- Modify: `config.py` (`DEFAULTS`, `_defaults_copy`, `_validate`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py` (before any `if __name__` block; if none, at end of file):

```python
class TestInsertMode(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old
        self._tmp.cleanup()

    def test_default_is_paste(self):
        self.assertEqual(config.load()["insert_mode"], "paste")

    def test_valid_ax_roundtrips(self):
        config.save({"insert_mode": "ax"})
        self.assertEqual(config.load()["insert_mode"], "ax")

    def test_invalid_falls_back_to_paste(self):
        config.save({"insert_mode": "nonsense"})
        self.assertEqual(config.load()["insert_mode"], "paste")
```

- [ ] **Step 2: Run to verify it fails**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_config.TestInsertMode -v`
Expected: FAIL — `KeyError: 'insert_mode'`.

- [ ] **Step 3: Add `insert_mode` to config**

In `config.py`, add to the `DEFAULTS` dict (after the `"model"` entry):

```python
    # Способ вставки текста: "paste" (буфер+Cmd+V) или "ax" (Accessibility API).
    "insert_mode": "paste",
```

In `_defaults_copy()`, add the key to the returned dict:

```python
        "insert_mode": DEFAULTS["insert_mode"],
```

In `_validate`, before `return cfg`, add:

```python
    mode = raw.get("insert_mode")
    if mode in ("paste", "ax"):
        cfg["insert_mode"] = mode
    else:
        cfg["insert_mode"] = DEFAULTS["insert_mode"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_config -v`
Expected: PASS (all config tests, including the existing `test_load_missing_returns_defaults_copy` which compares to `DEFAULTS`).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add insert_mode config key (paste|ax, default paste)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `insert_via_ax(text)` AX subprocess

**Files:**
- Modify: `voice_type.py` (add near `paste_via_cmd_v`, ~line 615-631)
- Test: `tests/test_deliver_text.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_deliver_text.py`:

```python
import unittest

import voice_type


class TestInsertViaAxGuards(unittest.TestCase):
    def test_empty_text_returns_false_without_subprocess(self):
        # Empty text must short-circuit to False and never spawn a subprocess.
        self.assertIs(voice_type.insert_via_ax(""), False)

    def test_returns_bool(self):
        self.assertIsInstance(voice_type.insert_via_ax(""), bool)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_deliver_text -v`
Expected: FAIL — `AttributeError: module 'voice_type' has no attribute 'insert_via_ax'`.

- [ ] **Step 3: Add `_AX_INSERT_CODE` and `insert_via_ax`**

In `voice_type.py`, immediately after `paste_via_cmd_v` (before `def deliver_text`), add:

```python
_AX_INSERT_CODE = (
    "import sys\n"
    "from ApplicationServices import (\n"
    "    AXUIElementCreateSystemWide,\n"
    "    AXUIElementCopyAttributeValue,\n"
    "    AXUIElementSetAttributeValue,\n"
    "    kAXFocusedUIElementAttribute,\n"
    "    kAXSelectedTextAttribute,\n"
    ")\n"
    "text = sys.stdin.buffer.read().decode('utf-8')\n"
    "try:\n"
    "    sw = AXUIElementCreateSystemWide()\n"
    "    err, focused = AXUIElementCopyAttributeValue(sw, kAXFocusedUIElementAttribute, None)\n"
    "    if err != 0 or focused is None:\n"
    "        sys.exit(1)\n"
    "    err = AXUIElementSetAttributeValue(focused, kAXSelectedTextAttribute, text)\n"
    "    sys.exit(0 if err == 0 else 1)\n"
    "except Exception:\n"
    "    sys.exit(1)\n"
)


def insert_via_ax(text: str) -> bool:
    """Insert `text` at the caret of the focused UI element via the macOS
    Accessibility API — WITHOUT touching the clipboard. Returns True on success.

    Runs in the same signed-python subprocess pattern as paste_via_cmd_v (doing
    AX work in-process next to the pynput listener and MLX/Metal is unsafe; the
    subprocess shares our TCC identity and needs only Accessibility). Any
    failure — no focused element, non-settable field, exception, or timeout —
    returns False so the caller can fall back to clipboard paste.
    """
    if not text:
        return False
    try:
        r = subprocess.run(
            [sys.executable, "-c", _AX_INSERT_CODE],
            input=text.encode("utf-8"),
            timeout=2.0,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"[!] AX insert failed: {e}", file=sys.stderr)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_deliver_text -v`
Expected: PASS (2 tests). (Empty text returns False without spawning a subprocess.)

- [ ] **Step 5: Commit**

```bash
git add voice_type.py tests/test_deliver_text.py
git commit -m "feat: add insert_via_ax (Accessibility API text insertion)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `deliver_text` insert_mode routing

**Files:**
- Modify: `voice_type.py` (`deliver_text`, ~line 633-659)
- Test: `tests/test_deliver_text.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_deliver_text.py` (before the `if __name__` block):

```python
class TestDeliverTextRouting(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig = {}
        for name in ("insert_via_ax", "copy_to_clipboard",
                     "paste_via_cmd_v", "read_clipboard"):
            self._orig[name] = getattr(voice_type, name)
        # read_clipboard echoes the text so deliver_text's "placed" check passes
        # and never triggers its retry-copy branch.
        voice_type.copy_to_clipboard = lambda t: self.calls.append(("copy", t))
        voice_type.paste_via_cmd_v = lambda: self.calls.append(("paste",))
        voice_type.read_clipboard = lambda: "hi"

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(voice_type, name, fn)

    def test_ax_success_skips_clipboard(self):
        voice_type.insert_via_ax = lambda t: (self.calls.append(("ax", t)) or True)
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax")
        self.assertEqual(self.calls, [("ax", "hi")])

    def test_ax_failure_falls_back_to_paste(self):
        voice_type.insert_via_ax = lambda t: (self.calls.append(("ax", t)) or False)
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax")
        self.assertEqual(self.calls, [("ax", "hi"), ("copy", "hi"), ("paste",)])

    def test_paste_mode_never_calls_ax(self):
        voice_type.insert_via_ax = lambda t: (self.calls.append(("ax", t)) or True)
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="paste")
        self.assertEqual([c[0] for c in self.calls], ["copy", "paste"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_deliver_text.TestDeliverTextRouting -v`
Expected: FAIL — `TypeError: deliver_text() got an unexpected keyword argument 'insert_mode'`.

- [ ] **Step 3: Add the `insert_mode` parameter and AX-first branch**

In `voice_type.py`, change the `deliver_text` signature and add the AX branch. Replace:

```python
def deliver_text(text: str, do_paste: bool, restore_clipboard: bool) -> None:
```
with:
```python
def deliver_text(
    text: str,
    do_paste: bool,
    restore_clipboard: bool,
    insert_mode: str = "paste",
) -> None:
```

Then, immediately after the `if not text: return` guard (before `previous = read_clipboard() ...`), insert:

```python
    # AX mode: try direct Accessibility insertion first (no clipboard touched).
    # On any failure, fall through to the clipboard+Cmd+V path below.
    if do_paste and insert_mode == "ax":
        if insert_via_ax(text):
            return
```

Leave the rest of the function unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_deliver_text -v`
Expected: PASS (5 tests total in this file).

- [ ] **Step 5: Run the full suite**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add voice_type.py tests/test_deliver_text.py
git commit -m "feat: route deliver_text through AX insertion when insert_mode=ax

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Menu toggle, holder, persist, worker wiring

**Files:**
- Modify: `voice_type.py` (startup holder ~line 854; `persist()` ~864-878; menu build ~980-990; a new setter near `_make_smart_setter` ~1099; worker call ~1298-1302)

- [ ] **Step 1: Add the `insert_mode` holder**

In `voice_type.py`, right after the `smart_mode = {"value": cfg["smart_mode"]}` line (~854), add:

```python
    insert_mode = {"value": cfg["insert_mode"]}
```

- [ ] **Step 2: Persist `insert_mode`**

In `persist()`, add `insert_mode` to the dict passed to `config.save(...)` (after the `"model"` line):

```python
                "insert_mode": insert_mode["value"],
```

- [ ] **Step 3: Add the checkable menu item**

In `_build_menu`, near the Smart items and "Edit vocabulary…" (~line 985-990), add a checkable "Insert via Accessibility" item. First READ how the neighboring items are constructed and attached to the menu (the file uses the `it = rumps.MenuItem(label, callback=...); it.state = 1 if ... else 0` pattern — e.g. the model/smart/hotkey items — and then adds `it` to the menu structure). Follow that exact pattern:

```python
                ax_item = rumps.MenuItem(
                    "Insert via Accessibility (no clipboard)",
                    callback=self._toggle_insert_mode,
                )
                ax_item.state = 1 if insert_mode["value"] == "ax" else 0
```

Then attach `ax_item` to the menu in the same way the adjacent items are attached (append to the same list / add via the same `self.menu` call the neighbors use). Place it right after the "Edit vocabulary…" item.

- [ ] **Step 4: Add the toggle setter**

In `voice_type.py`, immediately after the `_make_smart_setter` method (find where its inner `setter` returns, ~line 1104-1110), add a new method at the same indentation level:

```python
        def _toggle_insert_mode(self, _):
            insert_mode["value"] = "ax" if insert_mode["value"] == "paste" else "paste"
            persist()
            self._build_menu()
            print(f"[i] Insert mode: {insert_mode['value']}")
```

- [ ] **Step 5: Pass `insert_mode` to the worker's `deliver_text` call**

In the worker (~line 1298), change:

```python
                    deliver_text(
                        full,
                        do_paste=not args.no_paste,
                        restore_clipboard=args.restore_clipboard,
                    )
```
to:
```python
                    deliver_text(
                        full,
                        do_paste=not args.no_paste,
                        restore_clipboard=args.restore_clipboard,
                        insert_mode=insert_mode["value"],
                    )
```

- [ ] **Step 6: Verify import + full suite**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -c "import voice_type" && /Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v`
Expected: import OK; all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add voice_type.py
git commit -m "feat: menu toggle + wiring for AX insert mode (persisted)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Manual local validation (user runs)

**Files:** none (local validation on Apple Silicon).

- [ ] **Step 1: Relaunch the app** (main-repo copy, after this branch is merged locally) or run `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python voice_type.py`. Enable **🎙 → Insert via Accessibility (no clipboard)**.

- [ ] **Step 2: Test insertion in several apps** — TextEdit, Notes, a Safari text field, Terminal, Slack (Electron). For each, dictate and confirm text either inserts directly or falls back cleanly (text still lands).

- [ ] **Step 3: Confirm clipboard untouched on AX success** — put a known value on the clipboard, dictate into TextEdit with AX on, then paste (Cmd+V) elsewhere — it should still be your known value, not the dictated text.

- [ ] **Step 4: Record results** in `docs/superpowers/specs/2026-07-20-ax-text-insertion-design.md` under a new "Local results" section (which apps worked via AX, which fell back). Commit it.

---

### Task 6: Document the Insert menu in README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Features bullet.** In the Features list, add:

```
- ⌨️ **Insertion mode** — by default text is pasted via clipboard + Cmd+V (clipboard restored). Switch to **Insert via Accessibility** from the menu to type straight into the focused field without touching the clipboard; it falls back to paste automatically where AX insertion isn't supported.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document AX insertion mode

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- Line numbers are approximate (`~`) — anchor on the quoted code, not the number.
- The venv is at the MAIN repo root: `/Users/sergeyarkhipov/whisper_flow/.venv`. This worktree has none. Always run tests with that interpreter.
- Heavy/framework imports stay where they are; `import voice_type` must keep working headless (tests rely on it). `subprocess`, `sys`, `threading`, `time` are already imported at module top.
- `deliver_text` keeps `insert_mode="paste"` as the default parameter value so any other caller is unaffected.
- Tasks 1-4 and 6 are code/docs and unit-testable. Task 5 is manual on-device validation (needs focus + Accessibility permission) and is not automated.
