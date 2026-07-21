# Replacements Dictionary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic `heard → wanted` replacements dictionary applied to the final transcript (after any LLM polish, before history/clipboard/insertion), so Russified IT anglicisms normalize consistently — engine-agnostic, works on Parakeet + Raw with no latency.

**Architecture:** A pure `apply_replacements(text, rules)` does one whole-word, case-insensitive, single-pass regex substitution. A new `replacements` config key holds the user's `{heard: wanted}` map, re-read from disk on each finalization for instant effect. A new "Edit replacements…" menu item opens config.json.

**Tech Stack:** Python 3, stdlib `re`/`json`/`unittest`, rumps (menu).

**Test command:** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v`

**Spec:** `docs/superpowers/specs/2026-07-20-replacements-dictionary-design.md`

**Verified anchors:** `config.py` DEFAULTS/`_defaults_copy`/`_validate` (mirror the existing `insert_mode` additions). Worker finalization is at `voice_type.py` ~1409-1434: `full = streaming.join_parts(parts)`, then optional `full = polish_text_safe(...)`, then `if full:` writes `last_text`, `history.add(full)`, `deliver_text(full, ...)`. `edit_vocabulary` (`voice_type.py:1248`) opens `config.config_path()` via `subprocess.Popen(["open", ...])` and lives in the menu class. Pure helper `polish_text_safe` is at ~865.

---

## File Structure

- Modify: `config.py` — add `replacements` to defaults + validation.
- Create: `voice_type.py` helper `apply_replacements` (near `polish_text_safe`, ~865).
- Modify: `voice_type.py` — apply in the worker finalization; add `edit_replacements` menu handler + menu item.
- Create: `tests/test_replacements.py` — `apply_replacements` unit tests.
- Modify: `tests/test_config.py` — `replacements` validation tests.
- Modify: `README.md` — document the replacements dictionary.
- Seed: the user's `~/.config/just-voice-type/config.json` with the approved starter set (runtime step, after the code lands).

---

### Task 1: config `replacements`

**Files:**
- Modify: `config.py` (`DEFAULTS`, `_defaults_copy`, `_validate`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_config.py` before any `if __name__` block:

```python
class TestReplacements(unittest.TestCase):
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

    def test_default_is_empty_dict(self):
        self.assertEqual(config.load()["replacements"], {})

    def test_valid_map_roundtrips(self):
        config.save({"replacements": {"апруф": "апрув"}})
        self.assertEqual(config.load()["replacements"], {"апруф": "апрув"})

    def test_non_dict_becomes_empty(self):
        config.save({"replacements": ["not", "a", "dict"]})
        self.assertEqual(config.load()["replacements"], {})

    def test_non_string_entries_dropped(self):
        config.save({"replacements": {"ok": "fine", "bad": 5, 7: "x", "": "y", "z": ""}})
        self.assertEqual(config.load()["replacements"], {"ok": "fine"})
```

- [ ] **Step 2: Run to verify it fails.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_config.TestReplacements -v` → KeyError: 'replacements'.

- [ ] **Step 3: Add `replacements` to config.py.**
- In `DEFAULTS`, after the `insert_mode` entry, add:
```python
    # Словарь замен «как распозналось» -> «как надо», применяется к финальному
    # тексту (см. apply_replacements). Пусто = ничего не заменяем.
    "replacements": {},
```
- In `_defaults_copy()`, add to the returned dict:
```python
        "replacements": dict(DEFAULTS["replacements"]),
```
- In `_validate`, before `return cfg`, add:
```python
    reps = raw.get("replacements")
    if isinstance(reps, dict):
        cfg["replacements"] = {
            k: v for k, v in reps.items()
            if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
        }
    else:
        cfg["replacements"] = {}
```

- [ ] **Step 4: Run tests → PASS.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_config -v` (including the existing `test_load_missing_returns_defaults_copy` which compares to DEFAULTS — DEFAULTS and `_defaults_copy` both now include `replacements`).

- [ ] **Step 5: Commit.**
```bash
git add config.py tests/test_config.py
git commit -m "feat: add replacements config key (heard->wanted map)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `apply_replacements` pure helper

**Files:**
- Modify: `voice_type.py` (add near `polish_text_safe`, ~865)
- Test: `tests/test_replacements.py` (create)

- [ ] **Step 1: Write the failing tests.** Create `tests/test_replacements.py`:

```python
import unittest

import voice_type


class TestApplyReplacements(unittest.TestCase):
    def test_no_rules_returns_unchanged(self):
        self.assertEqual(voice_type.apply_replacements("hello world", {}), "hello world")

    def test_empty_text_unchanged(self):
        self.assertEqual(voice_type.apply_replacements("", {"a": "b"}), "")

    def test_whole_word_replaced(self):
        self.assertEqual(
            voice_type.apply_replacements("надо апрув сделать", {"апрув": "approve"}),
            "надо approve сделать",
        )

    def test_substring_inside_word_not_touched(self):
        # rule "prove" must not fire inside "improve"
        self.assertEqual(
            voice_type.apply_replacements("improve it", {"prove": "XXX"}),
            "improve it",
        )

    def test_case_insensitive_literal_output(self):
        self.assertEqual(
            voice_type.apply_replacements("Апрув и апрув", {"апрув": "апрув!"}),
            "апрув! и апрув!",
        )

    def test_multiword_phrase(self):
        self.assertEqual(
            voice_type.apply_replacements("open a pull request now",
                                          {"pull request": "пул-реквест"}),
            "open a пул-реквест now",
        )

    def test_longest_key_wins(self):
        out = voice_type.apply_replacements(
            "make a pull request",
            {"pull": "П", "pull request": "ПР"},
        )
        self.assertEqual(out, "make a ПР")

    def test_single_pass_no_cascade(self):
        # "b"'s output "a" must NOT then be replaced by the "a" rule
        out = voice_type.apply_replacements("b", {"b": "a", "a": "z"})
        self.assertEqual(out, "a")

    def test_cyrillic_word_boundary(self):
        self.assertEqual(
            voice_type.apply_replacements("это задиплоить надо", {"задиплоить": "задеплоить"}),
            "это задеплоить надо",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_replacements -v` → AttributeError (apply_replacements not defined).

- [ ] **Step 3: Add `apply_replacements`.** In `voice_type.py`, near `polish_text_safe` (~865), add (`re` is stdlib — add `import re` at the top of the module if not already imported; check first):

```python
def apply_replacements(text: str, rules: "dict") -> str:
    """Replace user-defined terms in `text`: whole-word, case-insensitive,
    single pass. `rules` maps heard-form -> wanted-form. Output is the literal
    wanted value; a rule's output is never re-scanned by another rule.
    """
    if not text or not rules:
        return text
    # Longest keys first so multi-word phrases win over their prefixes.
    keys = sorted(rules.keys(), key=len, reverse=True)
    lookup = {k.lower(): v for k, v in rules.items()}
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: lookup[m.group(0).lower()], text)
```

- [ ] **Step 4: Run tests → PASS.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_replacements -v` (9 tests).

- [ ] **Step 5: Full suite.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v` → all PASS.

- [ ] **Step 6: Commit.**
```bash
git add voice_type.py tests/test_replacements.py
git commit -m "feat: add apply_replacements (whole-word, case-insensitive, single pass)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Apply in the worker + "Edit replacements…" menu

**Files:**
- Modify: `voice_type.py` (worker finalization ~1409-1434; menu class near `edit_vocabulary` ~1248 and its menu-item attachment in `_build_menu`)

- [ ] **Step 1: Apply replacements in the finalization.** In the worker, find the finalization block. After the optional polish and BEFORE the `if full:` block, insert the replacement step. The block currently looks like:

```python
                full = streaming.join_parts(parts)
                if smart_mode["value"] != "raw":
                    ...
                    full = polish_text_safe(...)
                    print(f"[i] polished ({smart_mode['value']}, {time.time() - t1:.1f}s)")

                if full:
                    last_text["value"] = full
                    history_items["value"] = history.add(full)
```
Insert, immediately before `if full:` (matching indentation):

```python
                # Детерминированные пользовательские замены (heard -> wanted),
                # перечитываем с диска ради мгновенного эффекта без рестарта.
                full = apply_replacements(full, config.load()["replacements"])
```

- [ ] **Step 2: Add the `edit_replacements` menu handler.** In the menu class, immediately after the `edit_vocabulary` method (~1248-1256), add:

```python
        def edit_replacements(self, _):
            # словарь замен правится прямо в конфиг-файле; открываем его
            persist()  # на случай первого запуска — гарантируем, что файл есть
            subprocess.Popen(["open", config.config_path()])
            notify(
                "Voice Type",
                'Edit the "replacements" map in config.json — applies on your next dictation',
            )
```

- [ ] **Step 3: Add the menu item.** Search for the `"Edit vocabulary…"` menu item in `_build_menu` and read exactly how it is constructed and attached. Immediately after it, add an "Edit replacements…" item using the identical idiom. If the neighbor reads `items.append(rumps.MenuItem("Edit vocabulary…", callback=self.edit_vocabulary))`, add:

```python
                items.append(rumps.MenuItem("Edit replacements…", callback=self.edit_replacements))
```
Match whatever attachment form the vocabulary item actually uses (list append vs `self.menu.add(...)`), placing the new item directly after it.

- [ ] **Step 4: Verify import + full suite.** `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -c "import voice_type" && /Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v` → import OK; all PASS.

- [ ] **Step 5: Commit.**
```bash
git add voice_type.py
git commit -m "feat: apply replacements at finalization; add Edit replacements menu

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: README note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Features bullet.** After the vocabulary/Smart-related content (or near the Auto-paste/Insertion bullets), add:

```
- 🔤 **Replacements** — a `heard → wanted` map in `config.json` (menu: **Edit replacements…**) rewrites fixed terms in the final text: dictate your IT anglicisms and have them always come out the way you want (e.g. `апруф → апрув`). Whole-word, case-insensitive, applied after transcription (and after any Smart polish) — works with the fast Parakeet model in Raw mode, no extra latency. Edits apply on your next dictation.
```

- [ ] **Step 2: Commit.**
```bash
git add README.md
git commit -m "docs: document the replacements dictionary

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Seed the user's config + manual verify

**Files:** the user's `~/.config/just-voice-type/config.json` (runtime; not in the repo). Requires Task 1's config support so `save`/`load` keep the key.

- [ ] **Step 1: Seed the approved starter set.** Merge the starter `replacements` map into the live config without clobbering other keys (run with the main-repo venv AFTER this branch is merged to local main so `config.py` supports the key):

```bash
/Users/sergeyarkhipov/whisper_flow/.venv/bin/python - <<'PY'
import json, os
p = os.path.expanduser("~/.config/just-voice-type/config.json")
cfg = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
cfg["replacements"] = {
    "approve": "апрув", "апруф": "апрув",
    "deploy": "деплой", "задиплоить": "задеплоить",
    "merge": "мёрдж", "смержить": "смёржить",
    "pull request": "пул-реквест", "пулреквест": "пул-реквест",
    "merge request": "мёрдж-реквест",
    "commit": "коммит", "rollback": "роллбэк", "release": "релиз",
    "rebase": "ребейз", "review": "ревью", "refactor": "рефактор",
    "endpoint": "эндпоинт", "backend": "бэкенд", "frontend": "фронтенд",
    "feature": "фича", "bug": "баг",
}
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(cfg, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("seeded", len(cfg["replacements"]), "replacement rules")
PY
```

- [ ] **Step 2: Manual verify (user, Apple Silicon).** Relaunch the app. On Parakeet + Raw, dictate the seed terms; watch `~/Library/Logs/WhisperFlow/whisper_flow.log` and the inserted text. For any term whose `heard` guess is wrong, note Parakeet's actual output and adjust the `heard` key via **Edit replacements…**. Confirm a normalization also survives Clean mode (applied after the LLM).

- [ ] **Step 3: Record findings** in `docs/superpowers/specs/2026-07-20-replacements-dictionary-design.md` under a "Local results" section (which guesses were right, which needed adjusting); commit.

---

## Notes for the implementer

- Line numbers are approximate (`~`) — anchor on quoted code.
- Test with the MAIN-repo venv: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python`.
- Check whether `import re` already exists at the top of `voice_type.py`; add it only if missing (stdlib).
- `config.load()` always returns a validated dict containing `replacements` (default `{}`) after Task 1, so the finalization read is safe.
- Do NOT put the starter set in code `DEFAULTS` — it stays `{}`; the seed lives only in the user's config (Task 5).
- Tasks 1-4 are unit-testable/mechanical. Task 5 step 1 (seeding) is a one-off runtime action; step 2 is manual on-device validation and is not automated.
