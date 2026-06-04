# Language Picker + Hotkey Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick any Whisper language (full ~99 set, with "favorite" working languages pinned to the top of the menu) and switch the push-to-talk hotkey from the menubar, with both choices persisted across restarts.

**Architecture:** Two new pure modules — `languages.py` (data + ordering helpers) and `config.py` (JSON load/save/validate at `~/.config/just-voice-type/config.json`). `voice_type.py` loads config at startup, builds the rumps menu from current state via a single `_build_menu()` method, and rewrites it on every change.

**Tech Stack:** Python 3, rumps (menubar UI), stdlib `json`/`unittest`. No new dependencies.

**Test command (from project root):** `.venv/bin/python -m unittest discover -s tests -t . -v`

---

## File Structure

- **Create `languages.py`** — `WHISPER_LANGUAGES` dict (code→name) + pure helpers `is_valid`, `display_name`, `sorted_all`, `top_section_codes`. No third-party deps. Unit-tested.
- **Create `config.py`** — `config_path`, `load`, `save`, `_validate`, `DEFAULTS`. Depends only on `languages`. Unit-tested.
- **Create `tests/__init__.py`**, `tests/test_languages.py`, `tests/test_config.py`.
- **Modify `voice_type.py`** — import the two modules; load config + seed holders in `run_app`; rewrite `VoiceTypeApp` to build the menu from state; add language/hotkey setters; remove the hardcoded `LANG_FLAGS`/`LANG_NAMES` and `(None,"uk","en","ru")` list.
- **Modify `README.md`** — update the Menu description.

---

## Task 1: `languages.py` — data + pure helpers

**Files:**
- Create: `languages.py`
- Create: `tests/__init__.py`
- Test: `tests/test_languages.py`

- [ ] **Step 1: Write the failing test**

Create `tests/__init__.py` (empty file).

Create `tests/test_languages.py`:

```python
import unittest

import languages


class TestLanguages(unittest.TestCase):
    def test_dict_has_expected_entries(self):
        self.assertGreater(len(languages.WHISPER_LANGUAGES), 90)
        for code in ("ru", "en", "uk"):
            self.assertIn(code, languages.WHISPER_LANGUAGES)
        for name in languages.WHISPER_LANGUAGES.values():
            self.assertIsInstance(name, str)
            self.assertTrue(name)

    def test_is_valid(self):
        self.assertTrue(languages.is_valid("ru"))
        self.assertFalse(languages.is_valid("zzz"))

    def test_display_name(self):
        self.assertEqual(languages.display_name(None), "Auto")
        self.assertEqual(languages.display_name("ru"), "Russian")
        self.assertEqual(languages.display_name("zzz"), "zzz")

    def test_sorted_all_is_sorted_by_name(self):
        names = [name for _, name in languages.sorted_all()]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertEqual(len(names), len(languages.WHISPER_LANGUAGES))

    def test_top_section_codes(self):
        # Auto first; favorites + active, sorted by display name
        self.assertEqual(
            languages.top_section_codes(["ru", "en"], "uk"),
            [None, "en", "ru", "uk"],
        )
        # active already in favorites -> no duplicate
        self.assertEqual(
            languages.top_section_codes(["ru", "en"], "ru"),
            [None, "en", "ru"],
        )
        # active None -> only Auto + favorites
        self.assertEqual(
            languages.top_section_codes(["ru", "en"], None),
            [None, "en", "ru"],
        )
        # invalid codes dropped
        self.assertEqual(
            languages.top_section_codes(["ru", "zzz"], None),
            [None, "ru"],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_languages -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'languages'`.

- [ ] **Step 3: Write minimal implementation**

Create `languages.py`:

```python
"""Whisper-supported languages (code -> display name) + pure menu helpers.

Pure data and functions, no third-party deps — unit-testable without a GUI.
The code list mirrors openai-whisper's tokenizer LANGUAGES set.
"""
from __future__ import annotations

from typing import Optional

WHISPER_LANGUAGES: dict[str, str] = {
    "en": "English", "zh": "Chinese", "de": "German", "es": "Spanish",
    "ru": "Russian", "ko": "Korean", "fr": "French", "ja": "Japanese",
    "pt": "Portuguese", "tr": "Turkish", "pl": "Polish", "ca": "Catalan",
    "nl": "Dutch", "ar": "Arabic", "sv": "Swedish", "it": "Italian",
    "id": "Indonesian", "hi": "Hindi", "fi": "Finnish", "vi": "Vietnamese",
    "he": "Hebrew", "uk": "Ukrainian", "el": "Greek", "ms": "Malay",
    "cs": "Czech", "ro": "Romanian", "da": "Danish", "hu": "Hungarian",
    "ta": "Tamil", "no": "Norwegian", "th": "Thai", "ur": "Urdu",
    "hr": "Croatian", "bg": "Bulgarian", "lt": "Lithuanian", "la": "Latin",
    "mi": "Maori", "ml": "Malayalam", "cy": "Welsh", "sk": "Slovak",
    "te": "Telugu", "fa": "Persian", "lv": "Latvian", "bn": "Bengali",
    "sr": "Serbian", "az": "Azerbaijani", "sl": "Slovenian", "kn": "Kannada",
    "et": "Estonian", "mk": "Macedonian", "br": "Breton", "eu": "Basque",
    "is": "Icelandic", "hy": "Armenian", "ne": "Nepali", "mn": "Mongolian",
    "bs": "Bosnian", "kk": "Kazakh", "sq": "Albanian", "sw": "Swahili",
    "gl": "Galician", "mr": "Marathi", "pa": "Punjabi", "si": "Sinhala",
    "km": "Khmer", "sn": "Shona", "yo": "Yoruba", "so": "Somali",
    "af": "Afrikaans", "oc": "Occitan", "ka": "Georgian", "be": "Belarusian",
    "tg": "Tajik", "sd": "Sindhi", "gu": "Gujarati", "am": "Amharic",
    "yi": "Yiddish", "lo": "Lao", "uz": "Uzbek", "fo": "Faroese",
    "ht": "Haitian Creole", "ps": "Pashto", "tk": "Turkmen", "nn": "Nynorsk",
    "mt": "Maltese", "sa": "Sanskrit", "lb": "Luxembourgish", "my": "Myanmar",
    "bo": "Tibetan", "tl": "Tagalog", "mg": "Malagasy", "as": "Assamese",
    "tt": "Tatar", "haw": "Hawaiian", "ln": "Lingala", "ha": "Hausa",
    "ba": "Bashkir", "jw": "Javanese", "su": "Sundanese", "yue": "Cantonese",
}

AUTO_LABEL = "Auto"


def is_valid(code: str) -> bool:
    return code in WHISPER_LANGUAGES


def display_name(code: Optional[str]) -> str:
    if code is None:
        return AUTO_LABEL
    return WHISPER_LANGUAGES.get(code, code)


def sorted_all() -> "list[tuple[str, str]]":
    """All languages as (code, name) pairs sorted by display name."""
    return sorted(WHISPER_LANGUAGES.items(), key=lambda kv: kv[1].lower())


def top_section_codes(favorites, active):
    """Ordered codes for the top of the Language menu.

    Returns [None] (Auto) followed by favorite languages plus the active
    language (if it is a real language), de-duplicated and sorted by display
    name. Invalid codes are dropped.
    """
    codes = {c for c in favorites if is_valid(c)}
    if active is not None and is_valid(active):
        codes.add(active)
    ordered = sorted(codes, key=lambda c: display_name(c).lower())
    return [None] + ordered
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_languages -v`
Expected: PASS (5 tests OK).

- [ ] **Step 5: Commit**

```bash
git add languages.py tests/__init__.py tests/test_languages.py
git commit -m "feat: add languages module with Whisper language set + menu helpers"
```

---

## Task 2: `config.py` — persistent settings

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import json
import os
import tempfile
import unittest

import config


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_xdg
        self._tmp.cleanup()

    def test_load_missing_returns_defaults_copy(self):
        cfg = config.load()
        self.assertEqual(cfg, config.DEFAULTS)
        cfg["hotkey"] = "mutated"
        self.assertNotEqual(config.DEFAULTS["hotkey"], "mutated")

    def test_save_then_load_roundtrip(self):
        config.save(
            {"favorite_languages": ["en", "de"], "active_language": "de", "hotkey": "f19"}
        )
        cfg = config.load()
        self.assertEqual(cfg["favorite_languages"], ["en", "de"])
        self.assertEqual(cfg["active_language"], "de")
        self.assertEqual(cfg["hotkey"], "f19")

    def test_save_creates_valid_json_file(self):
        config.save(config.DEFAULTS)
        with open(config.config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["hotkey"], "right_option")

    def test_corrupt_file_falls_back_to_defaults(self):
        os.makedirs(config.config_dir(), exist_ok=True)
        with open(config.config_path(), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(config.load(), config.DEFAULTS)

    def test_validate_drops_invalid_languages_and_dedups(self):
        config.save(
            {"favorite_languages": ["ru", "zzz", "ru", "en"], "active_language": "ru", "hotkey": "fn"}
        )
        cfg = config.load()
        self.assertEqual(cfg["favorite_languages"], ["ru", "en"])

    def test_invalid_active_becomes_none(self):
        config.save({"favorite_languages": [], "active_language": "zzz", "hotkey": "fn"})
        self.assertIsNone(config.load()["active_language"])

    def test_invalid_hotkey_becomes_default(self):
        config.save({"favorite_languages": [], "active_language": None, "hotkey": ""})
        self.assertEqual(config.load()["hotkey"], "right_option")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_config -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Write minimal implementation**

Create `config.py`:

```python
"""Persistent settings for Just Voice Type.

Stored as JSON at ~/.config/just-voice-type/config.json (honors
$XDG_CONFIG_HOME). Pure I/O + validation, no GUI deps — unit-testable.
Depends only on the `languages` module.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any, Optional

import languages

APP_DIR_NAME = "just-voice-type"
CONFIG_FILE_NAME = "config.json"

DEFAULTS = {
    "favorite_languages": ["ru", "uk", "en"],
    "active_language": None,
    "hotkey": "right_option",
}


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), CONFIG_FILE_NAME)


def _validate(raw: Any) -> "dict[str, Any]":
    cfg = {
        "favorite_languages": list(DEFAULTS["favorite_languages"]),
        "active_language": DEFAULTS["active_language"],
        "hotkey": DEFAULTS["hotkey"],
    }
    if not isinstance(raw, dict):
        return cfg

    favs = raw.get("favorite_languages")
    if isinstance(favs, list):
        seen = []
        for c in favs:
            if isinstance(c, str) and languages.is_valid(c) and c not in seen:
                seen.append(c)
        cfg["favorite_languages"] = seen

    active = raw.get("active_language")
    if active is None or (isinstance(active, str) and languages.is_valid(active)):
        cfg["active_language"] = active
    else:
        cfg["active_language"] = None

    hk = raw.get("hotkey")
    if isinstance(hk, str) and hk.strip():
        cfg["hotkey"] = hk.strip()

    return cfg


def load() -> "dict[str, Any]":
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {
            "favorite_languages": list(DEFAULTS["favorite_languages"]),
            "active_language": DEFAULTS["active_language"],
            "hotkey": DEFAULTS["hotkey"],
        }
    except (json.JSONDecodeError, OSError) as e:
        print(f"[!] config load failed ({e}); using defaults", file=sys.stderr)
        return {
            "favorite_languages": list(DEFAULTS["favorite_languages"]),
            "active_language": DEFAULTS["active_language"],
            "hotkey": DEFAULTS["hotkey"],
        }
    return _validate(raw)


def save(cfg: "dict[str, Any]") -> None:
    clean = _validate(cfg)
    d = config_dir()
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".config-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_path())
    except OSError as e:
        print(f"[!] config save failed: {e}", file=sys.stderr)
```

Note: `test_load_missing_returns_defaults_copy` compares against `config.DEFAULTS`; the returned dict equals it by value but is a fresh copy, so mutating the result does not change `DEFAULTS`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_config -v`
Expected: PASS (7 tests OK).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add config module for persistent language/hotkey settings"
```

---

## Task 3: Wire config + languages into `voice_type.py` startup

**Files:**
- Modify: `voice_type.py` (imports near top; `run_app` body; remove old lang globals)

- [ ] **Step 1: Add module imports**

In `voice_type.py`, the existing stdlib import block ends around line 32 (`from typing import Optional`). Immediately after it, add:

```python
import config
import languages
```

- [ ] **Step 2: Add hotkey presets constant**

Find the `MLX_MODELS` list (around lines 616-621, inside `run_app`). Directly **below** that list (still inside `run_app`, same indentation), add:

```python
    # пресеты хоткея для подменю «Hotkey». None = разделитель.
    # имена должны быть понятны parse_hotkey().
    HOTKEY_PRESETS = [
        ("Right Option", "right_option"),
        ("Left Option", "left_option"),
        ("Fn", "fn"),
        ("Right Command", "right_cmd"),
        ("Left Command", "left_cmd"),
        ("Right Control", "right_ctrl"),
        ("Right Shift", "right_shift"),
        None,
        ("F13", "f13"), ("F14", "f14"), ("F15", "f15"), ("F16", "f16"),
        ("F17", "f17"), ("F18", "f18"), ("F19", "f19"),
    ]
```

- [ ] **Step 3: Replace the hardcoded language block with config-driven state**

Find this exact block (around lines 605-621, just above `MLX_MODELS`):

```python
    # выбранный язык. None = auto, иначе 'ru' / 'uk' / 'en'
    # стартовое значение берётся из args.lang ('auto' → None)
    initial_lang = None if args.lang.lower() == "auto" else args.lang.lower()
    current_lang = {"value": initial_lang}

    # эмодзи флажки для menubar (компактные)
    LANG_FLAGS = {None: "🌐", "ru": "", "uk": "🇺🇦", "en": "🇬🇧"}
    LANG_NAMES = {None: "Auto", "ru": "Russian", "uk": "Ukrainian", "en": "English"}
```

Replace it with:

```python
    # ── настройки из конфига (язык/избранное/хоткей переживают перезапуск) ──
    cfg = config.load()
    config_existed = os.path.exists(config.config_path())
    if not config_existed:
        # первый запуск: засеваем конфиг текущими CLI-флагами и сохраняем
        cfg["active_language"] = (
            None if args.lang.lower() == "auto" else args.lang.lower()
        )
        cfg["hotkey"] = args.hotkey
        config.save(cfg)
        cfg = config.load()

    favorites = {"value": list(cfg["favorite_languages"])}
    current_lang = {"value": cfg["active_language"]}  # None = auto
    current_hotkey = {"value": cfg["hotkey"]}

    def persist():
        config.save(
            {
                "favorite_languages": favorites["value"],
                "active_language": current_lang["value"],
                "hotkey": current_hotkey["value"],
            }
        )
```

(The `LANG_FLAGS`/`LANG_NAMES` dicts are intentionally removed — language display now comes from `languages.display_name`.)

- [ ] **Step 4: Resolve the startup hotkey from config with fallback**

Find this line (around line 787, below the `VoiceTypeApp` class, before the listener is created):

```python
    hotkey_obj_holder = {"key": parse_hotkey(args.hotkey)}
```

Replace it with:

```python
    def _resolve_hotkey(name):
        try:
            return parse_hotkey(name)
        except ValueError:
            print(
                f"[!] unknown hotkey {name!r}; falling back to right_option",
                file=sys.stderr,
            )
            current_hotkey["value"] = "right_option"
            return parse_hotkey("right_option")

    hotkey_obj_holder = {"key": _resolve_hotkey(current_hotkey["value"])}
```

- [ ] **Step 5: Verify the module still parses and imports**

Run: `.venv/bin/python -c "import voice_type; print('import ok')"`
Expected: prints `import ok` (importing does not start the app — `main()` is guarded by `__name__ == "__main__"`; rumps/pynput are loaded lazily inside `run_app`, so the import has no GUI side effects).

- [ ] **Step 6: Commit**

```bash
git add voice_type.py
git commit -m "feat: load language/hotkey settings from config at startup"
```

---

## Task 4: Rebuild `VoiceTypeApp` menu from state

**Files:**
- Modify: `voice_type.py` (`VoiceTypeApp` class, around lines 623-731)

- [ ] **Step 1: Replace the entire `VoiceTypeApp` class body**

Replace the whole class (from `class VoiceTypeApp(rumps.App):` through the end of `def quit_app`, around lines 623-731) with:

```python
    class VoiceTypeApp(rumps.App):
        def __init__(self):
            super().__init__("Voice Type", title="🎙", quit_button=None)
            self._build_menu()
            self._timer = rumps.Timer(self._on_tick, 0.3)
            self._timer.start()

        # ── построение меню из текущего состояния ──────────────────────────
        def _build_menu(self):
            self.menu.clear()
            self.menu.update(
                [
                    self._hotkey_menu(),
                    self._model_menu(),
                    None,
                    self._language_menu(),
                    None,
                    rumps.MenuItem(
                        "Enable hotkey"
                        if not enabled["value"]
                        else "Pause (disable hotkey)",
                        callback=self.toggle_enabled,
                    ),
                    rumps.MenuItem("Copy last text", callback=self.copy_last),
                    None,
                    rumps.MenuItem("Quit", callback=self.quit_app),
                ]
            )

        def _hotkey_menu(self):
            items = []
            for preset in HOTKEY_PRESETS:
                if preset is None:
                    items.append(None)
                    continue
                label, name = preset
                it = rumps.MenuItem(label, callback=self._make_hotkey_setter(name))
                it.state = 1 if name == current_hotkey["value"] else 0
                items.append(it)
            return ("Hotkey", items)

        def _model_menu(self):
            # поведение модели не меняется: выбор только в памяти, не персистим
            if args.engine != "mlx":
                return rumps.MenuItem(
                    f"Model: {current_model['value'].split('/')[-1]}"
                )
            entries = list(MLX_MODELS)
            known = {repo for _, repo in entries}
            if current_model["value"] not in known:
                entries.insert(
                    0,
                    (current_model["value"].split("/")[-1], current_model["value"]),
                )
            items = []
            for label, repo in entries:
                it = rumps.MenuItem(label, callback=self._make_model_setter(repo))
                it.state = 1 if repo == current_model["value"] else 0
                items.append(it)
            return ("Model", items)

        def _language_menu(self):
            items = []
            # верхний блок: Auto + избранные (+ активный), активный отмечен
            for code in languages.top_section_codes(
                favorites["value"], current_lang["value"]
            ):
                label = (
                    "🌐 " + languages.display_name(code)
                    if code is None
                    else languages.display_name(code)
                )
                it = rumps.MenuItem(
                    label, callback=self._make_active_lang_setter(code)
                )
                it.state = 1 if code == current_lang["value"] else 0
                items.append(it)
            items.append(None)
            # подменю «All languages…»: все языки, галочка = в избранном
            all_menu = rumps.MenuItem("All languages…")
            favset = set(favorites["value"])
            for code, name in languages.sorted_all():
                it = rumps.MenuItem(
                    name, callback=self._make_favorite_toggler(code)
                )
                it.state = 1 if code in favset else 0
                all_menu.add(it)
            items.append(all_menu)
            return ("Language", items)

        # ── сеттеры ────────────────────────────────────────────────────────
        def _make_active_lang_setter(self, code):
            def setter(_):
                current_lang["value"] = code
                persist()
                self._build_menu()
                print(f"[i] Language set: {languages.display_name(code)}")

            return setter

        def _make_favorite_toggler(self, code):
            def setter(_):
                favs = favorites["value"]
                if code in favs:
                    if code == current_lang["value"]:
                        # активный язык нельзя спрятать
                        notify(
                            "Voice Type",
                            f"{languages.display_name(code)} is active — keeping it",
                        )
                        return
                    favs.remove(code)
                else:
                    favs.append(code)
                persist()
                self._build_menu()

            return setter

        def _make_model_setter(self, repo):
            def setter(_):
                if repo == current_model["value"]:
                    return
                current_model["value"] = repo
                name = repo.split("/")[-1]
                print(f"[i] Model set: {name}")
                # следующая диктовка подхватит новую модель (MLX грузит лениво)
                transcriber_holder["obj"] = None
                get_transcriber()
                self._build_menu()
                notify("Voice Type", f"Model → {name}")

            return setter

        def _make_hotkey_setter(self, name):
            def setter(_):
                if name == current_hotkey["value"]:
                    return
                try:
                    new_key = parse_hotkey(name)
                except ValueError:
                    notify("Voice Type", f"Unsupported hotkey: {name}")
                    return
                # если прямо сейчас идёт запись на старой клавише — чисто стопаем
                if is_down["v"]:
                    is_down["v"] = False
                    try:
                        recorder.stop()
                    except Exception:
                        pass
                    state["value"] = "idle"
                current_hotkey["value"] = name
                hotkey_obj_holder["key"] = new_key
                persist()
                self._build_menu()
                print(f"[i] Hotkey set: {name}")
                notify("Voice Type", f"Hotkey → {name}")

            return setter

        # ── статус-иконка и действия ────────────────────────────────────────
        def _on_tick(self, _):
            now = time.time()
            if state["value"] == "recording":
                level = max(0.0, min(1.0, recorder.level * 6))
                n = max(1, int(level * 5))
                blink = "🔴" if int(now * 2) % 2 == 0 else "⭕"
                self.title = f"{blink} {'▮' * n}{'▯' * (5 - n)}"
            elif state["value"] == "transcribing":
                dots = "." * (int(now * 2) % 4)
                self.title = f"⏳ transcribing{dots}"
            elif now < done_until["ts"]:
                self.title = "✓ copied"
            else:
                self.title = "🎙" if enabled["value"] else "🚫"

        def toggle_enabled(self, _):
            enabled["value"] = not enabled["value"]
            self._build_menu()

        def copy_last(self, _):
            if last_text["value"]:
                copy_to_clipboard(last_text["value"])
                notify("Voice Type", "Last text copied")
            else:
                notify("Voice Type", "Nothing transcribed yet")

        def quit_app(self, _):
            rumps.quit_application()
```

- [ ] **Step 2: Verify the module still imports and parses**

Run: `.venv/bin/python -c "import voice_type; print('import ok')"`
Expected: prints `import ok`.

- [ ] **Step 3: Smoke-test menu construction logic in isolation**

Run this one-off check (verifies the pure ordering used by the menu, no GUI):

```bash
.venv/bin/python -c "import languages; print(languages.top_section_codes(['ru','uk','en'], None)); print(len(languages.sorted_all()))"
```
Expected: prints `[None, 'en', 'ru', 'uk']` and a count `> 90`.

- [ ] **Step 4: Commit**

```bash
git add voice_type.py
git commit -m "feat: build menu from state with language picker + hotkey submenu"
```

---

## Task 5: End-to-end manual verification + README

**Files:**
- Modify: `README.md` (Menu section)

- [ ] **Step 1: Run the full unit suite**

Run: `.venv/bin/python -m unittest discover -s tests -t . -v`
Expected: all tests PASS (12 total: 5 languages + 7 config).

- [ ] **Step 2: Launch the app and verify behavior manually**

Run (foreground, for testing): `.venv/bin/python voice_type.py`

Verify in the menubar 🎙 icon:
1. **Hotkey submenu** shows presets; current one (`right_option` on first run) is checked. Click `F19` → notification "Hotkey → f19"; hold F19 to confirm push-to-talk records.
2. **Language → All languages…** lists ~99 languages; `Russian`/`Ukrainian`/`English` are checked (default favorites). Click `German` → it gains a check and now appears in the top section of Language.
3. **Language** top section: click `German` → it becomes the active language (checkmark moves there).
4. Quit the app (menu → Quit). Relaunch `.venv/bin/python voice_type.py`. Confirm: hotkey is still `F19`, `German` still favorited and active. (Inspect `~/.config/just-voice-type/config.json` to confirm it persisted.)

If any step fails, note that rumps separators inside a submenu use `None`; if a separator renders oddly, replace the `items.append(None)` separators in `_hotkey_menu`/`_language_menu` with `rumps.separator`.

- [ ] **Step 3: Reset test changes to config**

Restore defaults so the manual test doesn't leave odd settings:

```bash
rm -f ~/.config/just-voice-type/config.json
```

- [ ] **Step 4: Update README Menu description**

In `README.md`, find the line describing the menu (it currently reads, around the features list): `Menu: Pause, Copy last text, Quit.` Replace that menu description with:

```markdown
- Menu:
  - **Hotkey** — switch the push-to-talk key from presets (Right/Left Option, Fn, Cmd, Ctrl, Shift, F13–F19); applied immediately.
  - **Model** — switch Whisper model on the fly (mlx engine).
  - **Language** — your working ("favorite") languages plus Auto at the top; pick one to make it active. "All languages…" lists the full Whisper set (~99) where you check which languages to keep as favorites.
  - **Pause / Copy last text / Quit.**

Language favorites, the active language, and the hotkey persist across restarts in `~/.config/just-voice-type/config.json`.
```

If the exact menu line differs, place this block in the same features/Menu area and remove the now-stale single-line menu description.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe language picker + hotkey switching in README"
```

---

## Self-Review

**Spec coverage:**
- "Расхардкодить язык / полный набор Whisper" → Task 1 (`languages.py`, 99 langs) + Task 4 (`_language_menu` "All languages…"). ✓
- "Пометить рабочие языки галочкой, наверх" → Task 4 (`top_section_codes`, `_make_favorite_toggler`). ✓
- "Смена хоткея из меню (пресеты, на лету)" → Task 3 (`HOTKEY_PRESETS`, `_resolve_hotkey`) + Task 4 (`_hotkey_menu`, `_make_hotkey_setter`). ✓
- "Персистентность" → Task 2 (`config.py`) + Task 3 (load/seed/persist). ✓
- Edge: active language always visible → `top_section_codes` includes active; can't un-favorite active → `_make_favorite_toggler` guard. ✓
- Edge: hotkey change while recording → `_make_hotkey_setter` stop guard. ✓
- Error handling: corrupt config, invalid codes/hotkey → `config._validate` + tests. ✓
- Non-goal: model not persisted → `_model_menu`/`_make_model_setter` unchanged in behavior. ✓

**Placeholder scan:** No TBD/TODO; every code step contains full code; commands have expected output. ✓

**Type/name consistency:** `top_section_codes`, `sorted_all`, `display_name`, `is_valid` used identically in Tasks 1 & 4. `favorites`/`current_lang`/`current_hotkey`/`persist` defined in Task 3, consumed in Task 4. `hotkey_obj_holder`/`is_down`/`recorder`/`state` referenced in Task 4 setters exist in `run_app` scope by call time (closures, late binding — same pattern as existing `_make_model_setter`). ✓
