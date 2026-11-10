# UI redesign, phase 1: menubar icon, status line, i18n — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the emoji menubar title with fixed-width SF Symbols / level-bar images, add a status line at the top of the menu, and lay the RU/EN string foundation.

**Architecture:** Pure logic (`i18n.py`, `model_cache.py`, `menubar_icon.py`) is unit-tested without GUI. A thin AppKit layer (`menubar_view.py`) renders `Frame` objects to `NSImage` and puts them on rumps' `NSStatusItem`. `voice_type.py` builds a `Snapshot` every 0.1 s; the old 0.3 s work (watchdog, menu rebuild) is throttled to keep its timing.

**Tech Stack:** Python 3.13, rumps 0.4, PyObjC 12 (AppKit, Foundation), unittest.

**Spec:** `docs/superpowers/specs/2026-11-10-ui-redesign-design.md` (sections «Иконка в строке меню», «Меню» item 1, «Переводы», «Конфиг»).

**Run tests (from the worktree root):**
`/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v`
(worktrees have no own venv — always use the main-repo one)

---

## File structure

| File | Responsibility |
|---|---|
| `config.py` (modify) | new key `ui_language` |
| `i18n.py` (create) | RU/EN strings, `resolve()`, `t()`, `key_name()` |
| `model_cache.py` (create) | is a Hugging Face model already in the local cache |
| `menubar_icon.py` (create) | `Snapshot` → `Frame` (what to draw) and `Status` (menu line text + dot) |
| `menubar_view.py` (create) | AppKit: render `Frame` → `NSImage`, apply to status item, status-line dot |
| `scripts/preview_menubar_icon.py` (create) | render every icon state into one PNG for visual review |
| `voice_type.py` (modify) | wire it all in, drop emoji titles |
| `tests/test_i18n.py`, `tests/test_model_cache.py`, `tests/test_menubar_icon.py`, `tests/test_menubar_view.py` (create), `tests/test_config.py` (modify) | tests |

---

### Task 1: `ui_language` config key

**Files:**
- Modify: `config.py` (DEFAULTS, `_defaults_copy`, `_validate`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests** — append to `class TestConfig` in `tests/test_config.py`:

```python
    def test_ui_language_defaults_to_system(self):
        self.assertEqual(config.load()["ui_language"], "system")

    def test_ui_language_roundtrip(self):
        config.update(ui_language="ru")
        self.assertEqual(config.load()["ui_language"], "ru")

    def test_ui_language_junk_falls_back_to_system(self):
        with open(config.config_path(), "w", encoding="utf-8") as f:
            json.dump({"ui_language": "klingon"}, f)
        self.assertEqual(config.load()["ui_language"], "system")
```

Note: `config.update` writes into `config_dir()`; the test's `setUp` points `XDG_CONFIG_HOME` to a temp dir, and the third test needs the directory to exist — add `os.makedirs(config.config_dir(), exist_ok=True)` as its first line.

- [ ] **Step 2: Run to verify failure**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_config -v`
Expected: 3 failures/errors with `KeyError: 'ui_language'`. `test_load_missing_returns_defaults_copy` still passes.

- [ ] **Step 3: Implement** in `config.py`:

After the `"live_typing": True,` entry of `DEFAULTS` add:

```python
    # Язык интерфейса: "system" — по языку системы (см. i18n.resolve),
    # "ru" / "en" — выбран вручную в настройках.
    "ui_language": "system",
```

Below `INSERT_MODES = ("paste", "ax")` add:

```python
UI_LANGUAGES = ("system", "ru", "en")
```

In `_defaults_copy()` add `"ui_language": DEFAULTS["ui_language"],` after `live_typing`.

In `_validate()` right after the `live_typing` lines add:

```python
    ui_lang = raw.get("ui_language")
    cfg["ui_language"] = ui_lang if ui_lang in UI_LANGUAGES else DEFAULTS["ui_language"]
```

- [ ] **Step 4: Run tests**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_config -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat(config): ui_language setting (system/ru/en)"
```

---

### Task 2: `i18n.py`

**Files:**
- Create: `i18n.py`
- Test: `tests/test_i18n.py`

- [ ] **Step 1: Write the failing test** `tests/test_i18n.py`:

```python
import re
import unittest

import i18n


class TestTables(unittest.TestCase):
    def test_same_keys_in_every_language(self):
        ru, en = set(i18n.STRINGS["ru"]), set(i18n.STRINGS["en"])
        self.assertEqual(ru - en, set(), "missing in en")
        self.assertEqual(en - ru, set(), "missing in ru")

    def test_same_placeholders(self):
        ph = re.compile(r"\{(\w+)\}")
        for key, ru in i18n.STRINGS["ru"].items():
            en = i18n.STRINGS["en"][key]
            self.assertEqual(sorted(ph.findall(ru)), sorted(ph.findall(en)), key)


class TestResolve(unittest.TestCase):
    def test_explicit_setting_wins(self):
        self.assertEqual(i18n.resolve("ru", ["en-US"]), "ru")
        self.assertEqual(i18n.resolve("en", ["ru-RU"]), "en")

    def test_system_takes_first_supported(self):
        self.assertEqual(i18n.resolve("system", ["ru-RU", "en-US"]), "ru")
        self.assertEqual(i18n.resolve("system", ["en-PL", "ru-PL"]), "en")
        self.assertEqual(i18n.resolve("system", ["uk-UA", "ru-RU"]), "ru")

    def test_system_unsupported_falls_back_to_english(self):
        self.assertEqual(i18n.resolve("system", ["uk-UA"]), "en")
        self.assertEqual(i18n.resolve("system", []), "en")

    def test_underscore_locale_tags(self):
        self.assertEqual(i18n.resolve("system", ["ru_RU.UTF-8"]), "ru")


class TestTranslate(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_t_formats_in_current_language(self):
        i18n.set_language("ru")
        self.assertEqual(i18n.t("status.recording", time="0:07"), "Записываю · 0:07")
        i18n.set_language("en")
        self.assertEqual(i18n.t("status.recording", time="0:07"), "Recording · 0:07")

    def test_unknown_language_means_english(self):
        i18n.set_language("de")
        self.assertEqual(i18n.language(), "en")

    def test_unknown_key_returns_key(self):
        self.assertEqual(i18n.t("no.such.key"), "no.such.key")

    def test_falls_back_to_english_string(self):
        i18n.STRINGS["en"]["test.only_en"] = "only en"
        try:
            i18n.set_language("ru")
            self.assertEqual(i18n.t("test.only_en"), "only en")
        finally:
            del i18n.STRINGS["en"]["test.only_en"]

    def test_key_names(self):
        i18n.set_language("ru")
        self.assertEqual(i18n.key_name("right_option"), "правый ⌥")
        self.assertEqual(i18n.key_name("f13"), "F13")
        self.assertEqual(i18n.key_name("weird_key"), "weird_key")
        i18n.set_language("en")
        self.assertEqual(i18n.key_name("right_option"), "right ⌥")
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_i18n -v`
Expected: ERROR `ModuleNotFoundError: No module named 'i18n'`.

- [ ] **Step 3: Implement** `i18n.py`:

```python
"""Строки интерфейса Just Voice Type (RU/EN) и выбор языка.

Чистый модуль без GUI. Язык берётся из настройки ui_language
("system" | "ru" | "en"): "system" — первый поддерживаемый язык из
списка предпочитаемых языков macOS, иначе английский.
Новый язык = ещё одна таблица в STRINGS с теми же ключами
(тест tests/test_i18n.py следит, чтобы ключи и плейсхолдеры совпадали).
"""
from __future__ import annotations

import os
from typing import Iterable

SUPPORTED = ("ru", "en")
FALLBACK = "en"

STRINGS: "dict[str, dict[str, str]]" = {
    "ru": {
        # строка статуса сверху меню
        "status.ready": "Готов · удерживайте {key}",
        "status.recording": "Записываю · {time}",
        "status.handsfree": "Записываю · {time} · нажмите {key}, чтобы остановить",
        "status.transcribing": "Распознаю…",
        "status.inserted": "Готово",
        "status.loading_model": "Загружаю модель {model}…",
        "status.downloading_model": "Скачиваю модель {model}…",
        "status.paused": "На паузе",
        "status.call_recording": "Запись звонка · {time}",
        "status.call_transcribing": "Расшифровываю звонок…",
        "status.audio_dead": "Аудиосистема не отвечает — перезагрузите Mac",
        # названия клавиш
        "key.right_option": "правый ⌥",
        "key.left_option": "левый ⌥",
        "key.fn": "Fn",
        "key.right_cmd": "правый ⌘",
        "key.left_cmd": "левый ⌘",
        "key.right_ctrl": "правый ⌃",
        "key.right_shift": "правый ⇧",
    },
    "en": {
        "status.ready": "Ready · hold {key}",
        "status.recording": "Recording · {time}",
        "status.handsfree": "Recording · {time} · press {key} to stop",
        "status.transcribing": "Transcribing…",
        "status.inserted": "Done",
        "status.loading_model": "Loading model {model}…",
        "status.downloading_model": "Downloading model {model}…",
        "status.paused": "Paused",
        "status.call_recording": "Recording call · {time}",
        "status.call_transcribing": "Transcribing call…",
        "status.audio_dead": "Audio system not responding — restart your Mac",
        "key.right_option": "right ⌥",
        "key.left_option": "left ⌥",
        "key.fn": "Fn",
        "key.right_cmd": "right ⌘",
        "key.left_cmd": "left ⌘",
        "key.right_ctrl": "right ⌃",
        "key.right_shift": "right ⇧",
    },
}

_current = FALLBACK


def resolve(setting: str, preferred: "Iterable[str]") -> str:
    """Язык интерфейса по настройке и предпочитаемым языкам системы."""
    if setting in SUPPORTED:
        return setting
    for tag in preferred or ():
        code = str(tag).replace("_", "-").split("-")[0].split(".")[0].lower()
        if code in SUPPORTED:
            return code
    return FALLBACK


def system_languages() -> "list[str]":
    """Предпочитаемые языки macOS (["en-PL", "ru-PL", ...])."""
    try:
        from Foundation import NSLocale

        return [str(x) for x in NSLocale.preferredLanguages()]
    except Exception:
        lang = os.environ.get("LANG", "")
        return [lang] if lang else []


def set_language(code: str) -> None:
    global _current
    _current = code if code in SUPPORTED else FALLBACK


def language() -> str:
    return _current


def t(msg_id: str, /, **kw: object) -> str:
    """Строка по ключу на текущем языке; нет перевода — английская,
    нет и её — сам ключ (так пропуск видно, но ничего не падает).
    msg_id позиционный: плейсхолдер {key} передаётся как key=..."""
    s = STRINGS.get(_current, {}).get(msg_id) or STRINGS[FALLBACK].get(msg_id) or msg_id
    return s.format(**kw) if kw else s


def key_name(hotkey: str) -> str:
    """Человеческое имя клавиши: right_option → «правый ⌥», f13 → «F13»."""
    s = t(f"key.{hotkey}")
    if s != f"key.{hotkey}":
        return s
    if hotkey[:1] == "f" and hotkey[1:].isdigit():
        return hotkey.upper()
    return hotkey
```

- [ ] **Step 4: Run tests**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_i18n -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add i18n.py tests/test_i18n.py
git commit -m "feat: i18n module with RU/EN status strings"
```

---

### Task 3: `model_cache.py`

**Files:**
- Create: `model_cache.py`
- Test: `tests/test_model_cache.py`

- [ ] **Step 1: Write the failing test** `tests/test_model_cache.py`:

```python
import os
import tempfile
import unittest

import model_cache

REPO = "mlx-community/parakeet-tdt-0.6b-v3"


class TestModelCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _snapshot(self, files, incomplete=False):
        d = model_cache.repo_dir(REPO, self.cache)
        snap = os.path.join(d, "snapshots", "abc123")
        os.makedirs(snap)
        os.makedirs(os.path.join(d, "blobs"))
        for name in files:
            open(os.path.join(snap, name), "w").close()
        if incomplete:
            open(os.path.join(d, "blobs", "deadbeef.incomplete"), "w").close()

    def test_repo_dir_layout(self):
        self.assertEqual(
            model_cache.repo_dir(REPO, "/c"),
            "/c/models--mlx-community--parakeet-tdt-0.6b-v3",
        )

    def test_missing_repo_is_not_cached(self):
        self.assertFalse(model_cache.is_cached(REPO, self.cache))

    def test_weights_present_is_cached(self):
        self._snapshot(["config.json", "model.safetensors"])
        self.assertTrue(model_cache.is_cached(REPO, self.cache))

    def test_only_config_is_not_cached(self):
        self._snapshot(["config.json"])
        self.assertFalse(model_cache.is_cached(REPO, self.cache))

    def test_incomplete_download_is_not_cached(self):
        self._snapshot(["model.safetensors"], incomplete=True)
        self.assertFalse(model_cache.is_cached(REPO, self.cache))

    def test_non_hub_names_count_as_cached(self):
        # CPU-движок: «large-v3»; локальный путь к модели
        self.assertTrue(model_cache.is_cached("large-v3", self.cache))
        self.assertTrue(model_cache.is_cached(self.cache, self.cache))

    def test_hub_cache_dir_env(self):
        old = {k: os.environ.get(k) for k in ("HF_HUB_CACHE", "HF_HOME")}
        try:
            os.environ.pop("HF_HUB_CACHE", None)
            os.environ["HF_HOME"] = "/hf"
            self.assertEqual(model_cache.hub_cache_dir(), "/hf/hub")
            os.environ["HF_HUB_CACHE"] = "/direct"
            self.assertEqual(model_cache.hub_cache_dir(), "/direct")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_model_cache -v`
Expected: ERROR `No module named 'model_cache'`.

- [ ] **Step 3: Implement** `model_cache.py`:

```python
"""Есть ли модель Hugging Face в локальном кэше (без сети и без huggingface_hub).

Нужно, чтобы строка статуса различала «Загружаю модель…» (веса уже на
диске) и «Скачиваю модель…» (первая загрузка, гигабайты из сети).
"""
from __future__ import annotations

import os
from typing import Optional

WEIGHT_EXT = (".safetensors", ".npz", ".bin", ".gguf")


def hub_cache_dir() -> str:
    if os.environ.get("HF_HUB_CACHE"):
        return os.environ["HF_HUB_CACHE"]
    home = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface"
    )
    return os.path.join(home, "hub")


def repo_dir(repo: str, cache: Optional[str] = None) -> str:
    return os.path.join(cache or hub_cache_dir(), "models--" + repo.replace("/", "--"))


def is_cached(repo: str, cache: Optional[str] = None) -> bool:
    """True, если веса модели уже лежат в кэше и докачка не идёт.
    Имена не из хаба (CPU-движок «large-v3», локальный путь) — True."""
    if "/" not in repo or os.path.isabs(repo) or os.path.exists(repo):
        return True
    d = repo_dir(repo, cache)
    blobs = os.path.join(d, "blobs")
    if os.path.isdir(blobs) and any(n.endswith(".incomplete") for n in os.listdir(blobs)):
        return False
    snaps = os.path.join(d, "snapshots")
    if not os.path.isdir(snaps):
        return False
    for _root, _dirs, files in os.walk(snaps):
        if any(f.endswith(WEIGHT_EXT) for f in files):
            return True
    return False
```

- [ ] **Step 4: Run tests**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_model_cache -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add model_cache.py tests/test_model_cache.py
git commit -m "feat: detect whether a Hugging Face model is cached locally"
```

---

### Task 4: `menubar_icon.py` (pure logic)

**Files:**
- Create: `menubar_icon.py`
- Test: `tests/test_menubar_icon.py`

- [ ] **Step 1: Write the failing test** `tests/test_menubar_icon.py`:

```python
import unittest

import i18n
import menubar_icon as mi
from menubar_icon import Snapshot


class TestFmt(unittest.TestCase):
    def test_minutes_seconds(self):
        self.assertEqual(mi.fmt_elapsed(7.9), "0:07")
        self.assertEqual(mi.fmt_elapsed(724), "12:04")

    def test_hours(self):
        self.assertEqual(mi.fmt_elapsed(3723), "1:02:03")

    def test_negative_is_zero(self):
        self.assertEqual(mi.fmt_elapsed(-3), "0:00")


class TestBars(unittest.TestCase):
    def test_silence_is_lowest(self):
        self.assertEqual(mi.bar_heights(0.0), (1, 1, 1, 1, 1))

    def test_loud_follows_profile(self):
        h = mi.bar_heights(1.0)
        self.assertEqual(len(h), mi.BAR_COUNT)
        self.assertEqual(h[2], mi.BAR_STEPS)        # средняя — максимум
        self.assertLess(h[0], h[2])                 # крайние ниже
        self.assertEqual(h, tuple(reversed(h)))     # симметрично

    def test_quantized_range(self):
        for lvl in (0.01, 0.05, 0.1, 0.2, 5.0):
            for v in mi.bar_heights(lvl):
                self.assertTrue(1 <= v <= mi.BAR_STEPS)


class TestFrame(unittest.TestCase):
    def test_ready(self):
        self.assertEqual(mi.frame(Snapshot()), mi.Frame(symbol="mic"))

    def test_paused(self):
        self.assertEqual(mi.frame(Snapshot(enabled=False)).symbol, "mic.slash")

    def test_recording_is_red_bars(self):
        f = mi.frame(Snapshot(state="recording", level=0.2))
        self.assertEqual(f.symbol, "")
        self.assertEqual(f.tint, "rec")
        self.assertEqual(len(f.bars), mi.BAR_COUNT)
        self.assertEqual(f.badge, "")

    def test_handsfree_has_infinity_badge(self):
        f = mi.frame(Snapshot(state="recording", handsfree=True))
        self.assertEqual(f.badge, "infinity")

    def test_transcribing_pulses(self):
        a = mi.frame(Snapshot(state="transcribing", now=10.0))
        b = mi.frame(Snapshot(state="transcribing", now=10.5))
        self.assertEqual(a.symbol, "waveform")
        self.assertNotEqual(a.dim, b.dim)

    def test_inserted(self):
        self.assertEqual(mi.frame(Snapshot(inserted=True)).symbol, "checkmark")

    def test_call_recording_has_timer(self):
        f = mi.frame(Snapshot(call_state="recording", call_elapsed=724))
        self.assertEqual((f.symbol, f.tint, f.text), ("phone.fill", "rec", "12:04"))

    def test_call_beats_dictation(self):
        f = mi.frame(Snapshot(call_state="recording", state="recording"))
        self.assertEqual(f.symbol, "phone.fill")

    def test_model_loading(self):
        self.assertEqual(
            mi.frame(Snapshot(model_loading=True)).symbol, "arrow.down.circle"
        )

    def test_recording_beats_model_loading(self):
        f = mi.frame(Snapshot(model_loading=True, state="recording"))
        self.assertEqual(f.tint, "rec")

    def test_audio_dead_beats_everything(self):
        f = mi.frame(Snapshot(audio_dead=True, call_state="recording"))
        self.assertEqual(f.symbol, "exclamationmark.triangle")

    def test_frames_are_hashable(self):
        {mi.frame(Snapshot()): 1}


class TestStatus(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_ready_ru(self):
        i18n.set_language("ru")
        s = mi.status(Snapshot(hotkey="right_option"))
        self.assertEqual(s, mi.Status(dot="ok", text="Готов · удерживайте правый ⌥"))

    def test_recording_time(self):
        i18n.set_language("en")
        s = mi.status(Snapshot(state="recording", rec_elapsed=7))
        self.assertEqual(s, mi.Status(dot="rec", text="Recording · 0:07"))

    def test_handsfree_mentions_key(self):
        i18n.set_language("en")
        s = mi.status(Snapshot(state="recording", handsfree=True, hotkey="f13", rec_elapsed=3))
        self.assertEqual(s.text, "Recording · 0:03 · press F13 to stop")

    def test_download_vs_load(self):
        i18n.set_language("en")
        load = mi.status(Snapshot(model_loading=True, model_cached=True, model_name="m"))
        dl = mi.status(Snapshot(model_loading=True, model_cached=False, model_name="m"))
        self.assertEqual(load, mi.Status(dot="busy", text="Loading model m…"))
        self.assertEqual(dl, mi.Status(dot="busy", text="Downloading model m…"))

    def test_call_time(self):
        i18n.set_language("ru")
        s = mi.status(Snapshot(call_state="recording", call_elapsed=65))
        self.assertEqual(s, mi.Status(dot="rec", text="Запись звонка · 1:05"))

    def test_paused_and_dead(self):
        self.assertEqual(mi.status(Snapshot(enabled=False)).dot, "paused")
        self.assertEqual(mi.status(Snapshot(audio_dead=True)).dot, "error")
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_menubar_icon -v`
Expected: ERROR `No module named 'menubar_icon'`.

- [ ] **Step 3: Implement** `menubar_icon.py`:

```python
"""Что показывать в строке меню: кадр иконки и строку статуса.

Чистая логика без AppKit: по снимку состояния приложения (Snapshot)
выбирает кадр (Frame: символ SF Symbols или полоски уровня, цвет,
таймер) и строку статуса для меню (Status). Рисует кадры menubar_view.

Кадры — неизменяемые и хешируемые: одинаковый кадр не перерисовывается,
поэтому полоски уровня квантуются до BAR_STEPS ступеней.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import i18n

BAR_COUNT = 5
BAR_STEPS = 4
# средняя полоска выше крайних — читается как индикатор уровня
_BAR_PROFILE = (0.55, 0.8, 1.0, 0.8, 0.55)
# recorder.level у речи ~0.02–0.15; ×6 — как было в старом заголовке
LEVEL_GAIN = 6.0


@dataclass(frozen=True)
class Snapshot:
    now: float = 0.0
    enabled: bool = True
    state: str = "idle"  # idle | recording | transcribing | done
    handsfree: bool = False
    level: float = 0.0  # сырой recorder.level
    rec_elapsed: float = 0.0
    inserted: bool = False
    call_state: str = "idle"  # idle | recording | transcribing
    call_elapsed: float = 0.0
    model_loading: bool = False
    model_cached: bool = True
    model_name: str = ""
    audio_dead: bool = False
    hotkey: str = "right_option"


@dataclass(frozen=True)
class Frame:
    symbol: str = "mic"  # имя SF Symbol; "" — вместо символа полоски
    tint: str = "template"  # template (следует теме) | rec (красный)
    bars: Tuple[int, ...] = ()  # высоты полосок, 1..BAR_STEPS
    badge: str = ""  # маленький символ после полосок («infinity»)
    text: str = ""  # таймер звонка справа от иконки
    dim: bool = False  # тусклая фаза пульсации


@dataclass(frozen=True)
class Status:
    dot: str  # ok | rec | busy | paused | error
    text: str


def fmt_elapsed(sec: float) -> str:
    s = max(0, int(sec))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def bar_heights(level: float) -> "Tuple[int, ...]":
    x = max(0.0, min(1.0, level * LEVEL_GAIN))
    return tuple(
        max(1, min(BAR_STEPS, round(1 + x * p * (BAR_STEPS - 1)))) for p in _BAR_PROFILE
    )


def _dim_phase(now: float) -> bool:
    """Пульсация 1 Гц: полсекунды ярко, полсекунды тускло."""
    return int(now * 2) % 2 == 1


def _kind(s: Snapshot) -> str:
    if s.audio_dead:
        return "audio_dead"
    if s.call_state == "recording":
        return "call_recording"
    if s.call_state == "transcribing":
        return "call_transcribing"
    if s.state == "recording":
        return "handsfree" if s.handsfree else "recording"
    if s.state == "transcribing":
        return "transcribing"
    if s.inserted:
        return "inserted"
    if s.model_loading:
        return "loading_model" if s.model_cached else "downloading_model"
    if not s.enabled:
        return "paused"
    return "ready"


def frame(s: Snapshot) -> Frame:
    k = _kind(s)
    if k == "audio_dead":
        return Frame(symbol="exclamationmark.triangle")
    if k == "call_recording":
        return Frame(symbol="phone.fill", tint="rec", text=fmt_elapsed(s.call_elapsed))
    if k == "call_transcribing":
        return Frame(symbol="phone", dim=_dim_phase(s.now))
    if k in ("recording", "handsfree"):
        return Frame(
            symbol="",
            tint="rec",
            bars=bar_heights(s.level),
            badge="infinity" if k == "handsfree" else "",
        )
    if k == "transcribing":
        return Frame(symbol="waveform", dim=_dim_phase(s.now))
    if k == "inserted":
        return Frame(symbol="checkmark")
    if k in ("loading_model", "downloading_model"):
        return Frame(symbol="arrow.down.circle", dim=_dim_phase(s.now))
    if k == "paused":
        return Frame(symbol="mic.slash")
    return Frame(symbol="mic")


_DOTS = {
    "ready": "ok",
    "paused": "paused",
    "audio_dead": "error",
    "recording": "rec",
    "handsfree": "rec",
    "call_recording": "rec",
}


def status(s: Snapshot) -> Status:
    k = _kind(s)
    elapsed = s.call_elapsed if k == "call_recording" else s.rec_elapsed
    text = i18n.t(
        f"status.{k}",
        key=i18n.key_name(s.hotkey),
        time=fmt_elapsed(elapsed),
        model=s.model_name,
    )
    return Status(dot=_DOTS.get(k, "busy"), text=text)
```

- [ ] **Step 4: Run tests**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_menubar_icon -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add menubar_icon.py tests/test_menubar_icon.py
git commit -m "feat: pure menubar icon/status model"
```

---

### Task 5: `menubar_view.py` (AppKit rendering)

**Files:**
- Create: `menubar_view.py`
- Test: `tests/test_menubar_view.py`

- [ ] **Step 1: Write the failing test** `tests/test_menubar_view.py`:

```python
import unittest

import menubar_icon as mi

try:
    import AppKit  # noqa: F401

    import menubar_view as mv
except ImportError:  # pragma: no cover — без PyObjC
    mv = None


class FakeButton:
    def __init__(self):
        self.image = None
        self.title = None
        self.attributed = None
        self.label = None

    def setImage_(self, img):
        self.image = img

    def setImagePosition_(self, _):
        pass

    def setTitle_(self, t):
        self.title = t

    def setAttributedTitle_(self, t):
        self.attributed = t

    def setAccessibilityLabel_(self, t):
        self.label = t


class FakeStatusItem:
    def __init__(self):
        self.btn = FakeButton()
        self.length = None

    def button(self):
        return self.btn

    def setLength_(self, n):
        self.length = n


@unittest.skipIf(mv is None, "PyObjC not available")
class TestRender(unittest.TestCase):
    def test_symbol_frames_render_as_template(self):
        img = mv.render(mi.Frame(symbol="mic"))
        self.assertTrue(img.isTemplate())
        self.assertGreater(img.size().width, 0)

    def test_rec_frames_are_not_template(self):
        self.assertFalse(mv.render(mi.Frame(symbol="phone.fill", tint="rec")).isTemplate())

    def test_bars_render(self):
        img = mv.render(mi.Frame(symbol="", tint="rec", bars=(1, 2, 4, 2, 1)))
        self.assertAlmostEqual(img.size().height, mv.HEIGHT)
        badge = mv.render(
            mi.Frame(symbol="", tint="rec", bars=(1, 2, 4, 2, 1), badge="infinity")
        )
        self.assertGreater(badge.size().width, img.size().width)

    def test_unknown_symbol_falls_back_to_mic(self):
        self.assertIsNotNone(mv.render(mi.Frame(symbol="no.such.symbol.xyz")))

    def test_dim_frame_renders(self):
        self.assertIsNotNone(mv.render(mi.Frame(symbol="waveform", dim=True)))


@unittest.skipIf(mv is None, "PyObjC not available")
class TestStatusItemView(unittest.TestCase):
    def test_fixed_length_without_text(self):
        item, view = FakeStatusItem(), mv.StatusItemView()
        self.assertTrue(view.update(item, mi.Frame(symbol="mic"), "Ready"))
        self.assertEqual(item.length, mv.ICON_LENGTH)
        self.assertEqual(item.btn.title, "")
        self.assertEqual(item.btn.label, "Ready")

    def test_same_frame_is_not_reapplied(self):
        item, view = FakeStatusItem(), mv.StatusItemView()
        view.update(item, mi.Frame(symbol="mic"), "Ready")
        self.assertFalse(view.update(item, mi.Frame(symbol="mic"), "Ready"))

    def test_timer_widens_item(self):
        item, view = FakeStatusItem(), mv.StatusItemView()
        view.update(item, mi.Frame(symbol="phone.fill", tint="rec", text="12:04"), "Call")
        self.assertGreater(item.length, mv.ICON_LENGTH)
        self.assertIsNotNone(item.btn.attributed)

    def test_none_status_item_is_ignored(self):
        self.assertFalse(mv.StatusItemView().update(None, mi.Frame(), ""))


@unittest.skipIf(mv is None, "PyObjC not available")
class TestDot(unittest.TestCase):
    def test_every_dot_kind_renders(self):
        for kind in mv.DOT_RGB:
            self.assertIsNotNone(mv.dot_image(kind))
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_menubar_view -v`
Expected: tests SKIPPED or ERROR because `menubar_view` is missing (the `ImportError` branch sets `mv = None` → all skipped). Treat "all skipped" as the red state; confirm the skip reason is the missing module by running `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -c "import menubar_view"` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement** `menubar_view.py`:

```python
"""Отрисовка кадров menubar_icon в NSImage и вывод на статус-итем rumps.

Только AppKit-слой: какой кадр показать, решает menubar_icon. Ширина
статус-итема постоянная (ICON_LENGTH), чтобы соседние иконки не прыгали;
шире он становится только с таймером звонка.
"""
from __future__ import annotations

import AppKit
from AppKit import (
    NSAttributedString,
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSImageSymbolConfiguration,
    NSMakeRect,
    NSMakeSize,
)

import menubar_icon

HEIGHT = 18.0
SYMBOL_PT = 14.0
BADGE_PT = 9.0
BARS_WIDTH = 20.0
BAR_W = 2.4
ICON_LENGTH = 30.0
DIM_ALPHA = 0.45
TIMER_PT = 12.0
REC_RGB = (0xEB, 0x45, 0x37)
DOT_RGB = {
    "ok": (0x61, 0xCB, 0x7C),
    "rec": REC_RGB,
    "busy": (0xF0, 0xBA, 0x59),
    "error": (0xFB, 0x83, 0x6D),
    "paused": (0x8C, 0x8C, 0x8C),
}
DOT_SIZE = 8.0
_CACHE_MAX = 64


def _rgb(rgb, alpha: float = 1.0):
    r, g, b = rgb
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255, g / 255, b / 255, alpha)


def _symbol(name: str, pt: float, color=None):
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img is None:
        return None
    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
        pt, AppKit.NSFontWeightRegular
    )
    if color is not None:
        cfg = cfg.configurationByApplyingConfiguration_(
            NSImageSymbolConfiguration.configurationWithHierarchicalColor_(color)
        )
    return img.imageWithSymbolConfiguration_(cfg)


def _draw(size, fn):
    def handler(_rect):
        fn()
        return True

    return NSImage.imageWithSize_flipped_drawingHandler_(size, False, handler)


def _bars_image(fr: "menubar_icon.Frame"):
    color = _rgb(REC_RGB)
    badge = _symbol(fr.badge, BADGE_PT, color) if fr.badge else None
    width = BARS_WIDTH + (badge.size().width + 2.0 if badge is not None else 0.0)
    n = len(fr.bars)
    gap = (BARS_WIDTH - n * BAR_W) / max(1, n - 1)

    def paint():
        color.setFill()
        for i, step in enumerate(fr.bars):
            h = 3.0 + (HEIGHT - 6.0) * (step - 1) / (menubar_icon.BAR_STEPS - 1)
            rect = NSMakeRect(i * (BAR_W + gap), (HEIGHT - h) / 2, BAR_W, h)
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                rect, BAR_W / 2, BAR_W / 2
            ).fill()
        if badge is not None:
            bs = badge.size()
            badge.drawInRect_(NSMakeRect(BARS_WIDTH + 2.0, (HEIGHT - bs.height) / 2, bs.width, bs.height))

    return _draw(NSMakeSize(width, HEIGHT), paint)


def _with_alpha(src, alpha: float):
    def paint():
        src.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(0, 0, src.size().width, src.size().height),
            AppKit.NSZeroRect,
            AppKit.NSCompositingOperationSourceOver,
            alpha,
        )

    return _draw(src.size(), paint)


def render(fr: "menubar_icon.Frame"):
    """Кадр → NSImage. Шаблонные кадры следуют теме строки меню,
    красные (tint == "rec") рисуются как есть."""
    if fr.bars:
        img = _bars_image(fr)
    else:
        color = _rgb(REC_RGB) if fr.tint == "rec" else None
        img = _symbol(fr.symbol, SYMBOL_PT, color) or _symbol("mic", SYMBOL_PT)
    if fr.dim:
        img = _with_alpha(img, DIM_ALPHA)
    img.setTemplate_(fr.tint == "template")
    return img


class StatusItemView:
    """Кладёт кадры на кнопку NSStatusItem; одинаковый кадр — без работы."""

    def __init__(self):
        self._last = None
        self._cache: dict = {}

    def update(self, status_item, fr: "menubar_icon.Frame", label: str) -> bool:
        if status_item is None or fr == self._last:
            return False
        img = self._cache.get(fr)
        if img is None:
            if len(self._cache) >= _CACHE_MAX:
                self._cache.clear()
            img = self._cache[fr] = render(fr)
        button = status_item.button()
        button.setImage_(img)
        button.setImagePosition_(AppKit.NSImageLeft)
        if fr.text:
            attrs = {
                NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(
                    TIMER_PT, AppKit.NSFontWeightMedium
                ),
                NSForegroundColorAttributeName: _rgb(REC_RGB),
            }
            title = NSAttributedString.alloc().initWithString_attributes_(" " + fr.text, attrs)
            button.setAttributedTitle_(title)
            status_item.setLength_(ICON_LENGTH + title.size().width)
        else:
            button.setTitle_("")
            status_item.setLength_(ICON_LENGTH)
        button.setAccessibilityLabel_(label)
        self._last = fr
        return True


def dot_image(kind: str):
    color = _rgb(DOT_RGB.get(kind, DOT_RGB["paused"]))

    def paint():
        color.setFill()
        NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(1, 1, DOT_SIZE - 2, DOT_SIZE - 2)).fill()

    return _draw(NSMakeSize(DOT_SIZE, DOT_SIZE), paint)


def set_status_line(ns_menu_item, st: "menubar_icon.Status") -> None:
    """Строка статуса сверху меню: текст + цветная точка."""
    ns_menu_item.setTitle_(st.text)
    ns_menu_item.setImage_(dot_image(st.dot))
```

- [ ] **Step 4: Run tests**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_menubar_view -v`
Expected: all PASS (none skipped).

- [ ] **Step 5: Commit**

```bash
git add menubar_view.py tests/test_menubar_view.py
git commit -m "feat: render menubar frames with SF Symbols and level bars"
```

---

### Task 6: Icon preview sheet

**Files:**
- Create: `scripts/preview_menubar_icon.py`

- [ ] **Step 1: Implement** `scripts/preview_menubar_icon.py`:

```python
#!/usr/bin/env python3
"""Рисует все состояния иконки строки меню в один PNG — для глазной проверки.

  .venv/bin/python scripts/preview_menubar_icon.py [out.png]

Каждая строка: тёмная и светлая полоса меню, кадр, подпись состояния.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import AppKit  # noqa: E402
from AppKit import NSColor, NSMakeRect  # noqa: E402

import i18n  # noqa: E402
import menubar_icon as mi  # noqa: E402
import menubar_view as mv  # noqa: E402

STATES = [
    ("ready", mi.Snapshot()),
    ("paused", mi.Snapshot(enabled=False)),
    ("recording quiet", mi.Snapshot(state="recording", level=0.01)),
    ("recording loud", mi.Snapshot(state="recording", level=0.12)),
    ("hands-free", mi.Snapshot(state="recording", handsfree=True, level=0.08)),
    ("transcribing", mi.Snapshot(state="transcribing")),
    ("transcribing (dim)", mi.Snapshot(state="transcribing", now=0.5)),
    ("inserted", mi.Snapshot(inserted=True)),
    ("call", mi.Snapshot(call_state="recording", call_elapsed=724)),
    ("call transcribing", mi.Snapshot(call_state="transcribing")),
    ("model download", mi.Snapshot(model_loading=True, model_cached=False)),
    ("audio dead", mi.Snapshot(audio_dead=True)),
]
SCALE, ROW, LABEL_W, CELL = 3, 30.0, 170.0, 90.0


def main(out):
    i18n.set_language("en")
    w, h = int((LABEL_W + 2 * CELL) * SCALE), int(ROW * len(STATES) * SCALE)
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, w, h, 8, 4, True, False, AppKit.NSCalibratedRGBColorSpace, 0, 0
    )
    ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(ctx)
    tr = AppKit.NSAffineTransform.transform()
    tr.scaleBy_(SCALE)
    tr.concat()
    NSColor.whiteColor().setFill()
    AppKit.NSRectFill(NSMakeRect(0, 0, w, h))
    for i, (name, snap) in enumerate(STATES):
        y = ROW * (len(STATES) - 1 - i)
        fr = mi.frame(snap)
        for j, (bg, fg) in enumerate(((0.12, NSColor.whiteColor()), (0.93, NSColor.blackColor()))):
            x = LABEL_W + j * CELL
            NSColor.colorWithWhite_alpha_(bg, 1).setFill()
            AppKit.NSRectFill(NSMakeRect(x, y, CELL, ROW))
            img = mv.render(fr)
            if img.isTemplate():
                # шаблон рисуем цветом текста полосы меню, как это делает macOS
                tinted = img.copy()
                tinted.setTemplate_(False)
                tinted.lockFocus()
                fg.set()
                AppKit.NSRectFillUsingOperation(
                    NSMakeRect(0, 0, img.size().width, img.size().height),
                    AppKit.NSCompositingOperationSourceAtop,
                )
                tinted.unlockFocus()
                img = tinted
            s = img.size()
            img.drawInRect_(NSMakeRect(x + 8, y + (ROW - s.height) / 2, s.width, s.height))
            if fr.text:
                AppKit.NSString.stringWithString_(fr.text).drawAtPoint_withAttributes_(
                    (x + 12 + s.width, y + 8),
                    {AppKit.NSForegroundColorAttributeName: mv._rgb(mv.REC_RGB),
                     AppKit.NSFontAttributeName: AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(12, 0.23)},
                )
        label = f"{name}: {mi.status(snap).text}"
        AppKit.NSString.stringWithString_(label).drawAtPoint_withAttributes_(
            (6, y + 9), {AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(9)}
        )
    AppKit.NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None).writeToFile_atomically_(out, True)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "menubar-icon-preview.png")
```

- [ ] **Step 2: Run it and look at the PNG**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python scripts/preview_menubar_icon.py /tmp/menubar-preview.png` (use the session scratchpad instead of `/tmp`)
Expected: prints the path; open the PNG with the Read tool. Check: every row shows a glyph on both dark and light bars; recording rows are red bars; call row shows red phone + `12:04`; dim rows are visibly lighter. Fix rendering constants if something is clipped or off-centre.

- [ ] **Step 3: Commit**

```bash
git add scripts/preview_menubar_icon.py
git commit -m "chore: script to preview all menubar icon states"
```

---

### Task 7: Wire into `voice_type.py`

**Files:**
- Modify: `voice_type.py` (imports; `get_transcriber`; after `cfg = config.load()` block; `VoiceTypeApp.__init__`, `_build_menu`, `_on_tick`)

- [ ] **Step 1: Imports.** Next to the other local-module imports at the top of `voice_type.py` (`import config`, `import history`, …) add:

```python
import i18n
import menubar_icon
import model_cache
```

`menubar_view` imports AppKit; import it lazily inside `VoiceTypeApp.__init__` (see Step 4) so `import voice_type` in tests stays GUI-free.

- [ ] **Step 2: Remember whether the model is cached when loading starts.** In `get_transcriber()`, replace

```python
        transcriber_holder["loading"] = True
        transcriber_holder["obj"] = None
```

with

```python
        transcriber_holder["loading"] = True
        transcriber_holder["obj"] = None
        # для строки статуса: «Загружаю» (веса на диске) или «Скачиваю»
        transcriber_holder["cached"] = model_cache.is_cached(current_model["value"] or "")
```

and change the holder's initialisation to `transcriber_holder: dict = {"obj": None, "loading": False, "cached": True}`.

- [ ] **Step 3: Pick the UI language.** Right after the block that ends with `cfg = config.load()` (first-run seeding), add:

```python
    i18n.set_language(i18n.resolve(cfg["ui_language"], i18n.system_languages()))
```

- [ ] **Step 4: App init.** Replace `VoiceTypeApp.__init__` body with:

```python
        def __init__(self):
            super().__init__("Voice Type", title="🎙", quit_button=None)
            import menubar_view  # AppKit — только когда есть GUI

            self._view_mod = menubar_view
            self._icon_view = menubar_view.StatusItemView()
            self._status_item = None
            self._status_shown = None
            self._last_slow = 0.0
            self._build_menu()
            # 0.1 с — чтобы полоски уровня и таймеры были живыми; тяжёлая
            # часть (watchdog, перестройка меню) идёт по-прежнему раз в 0.3 с
            self._timer = rumps.Timer(self._on_tick, 0.1)
            self._timer.start()
```

- [ ] **Step 5: Status line in the menu.** In `_build_menu`, make the list passed to `self.menu.update([...])` start with the status item and a separator:

```python
                [
                    self._make_status_item(),
                    None,
                    rumps.MenuItem(
                        f"Voice Type v{__version__} — releases…",
```

(the rest of the list is unchanged). Add the method right after `_build_menu`:

```python
        def _make_status_item(self):
            """Некликабельная строка статуса сверху меню."""
            st = menubar_icon.status(self._snapshot(time.time()))
            item = rumps.MenuItem(st.text)
            item.set_callback(None)
            self._view_mod.set_status_line(item._menuitem, st)
            self._status_item = item
            self._status_shown = st
            return item
```

- [ ] **Step 6: Snapshot builder.** Add to `VoiceTypeApp` (next to `_on_tick`):

```python
        def _snapshot(self, now):
            model = current_model["value"] or ""
            return menubar_icon.Snapshot(
                now=now,
                enabled=enabled["value"],
                state=state["value"],
                handsfree=bool(gr.is_handsfree),
                level=float(recorder.level),
                rec_elapsed=(now - session["start_ts"]) if session["active"] else 0.0,
                inserted=now < done_until["ts"],
                call_state=call_state["value"],
                call_elapsed=(now - call_session["start_ts"])
                if call_state["value"] == "recording"
                else 0.0,
                model_loading=transcriber_holder["loading"],
                model_cached=transcriber_holder["cached"],
                model_name=model.split("/")[-1],
                audio_dead=recovery["gave_up"],
                hotkey=current_hotkey["value"],
            )
```

- [ ] **Step 7: New tick.** Replace the whole `_on_tick` method with:

```python
        def _on_tick(self, _):
            now = time.time()
            if now - self._last_slow >= 0.3:
                self._last_slow = now
                self._slow_tick(now)
            snap = self._snapshot(now)
            st = menubar_icon.status(snap)
            nsitem = getattr(getattr(self, "_nsapp", None), "nsstatusitem", None)
            self._icon_view.update(nsitem, menubar_icon.frame(snap), st.text)
            if self._status_item is not None and st != self._status_shown:
                self._view_mod.set_status_line(self._status_item._menuitem, st)
                self._status_shown = st

        def _slow_tick(self, now):
            # сбой watchdog не должен ломать иконку и меню: раньше исключение
            # здесь обрывало весь тик — иконка замирала до перезапуска
            try:
                self._watchdog_tick(now)
            except Exception as e:
                key = f"{type(e).__name__}: {e}"
                if key not in watchdog_errors:
                    watchdog_errors.add(key)
                    log(f"[!] watchdog: {key}", err=True)
            # перестройка меню (новая запись в истории) — только здесь,
            # в главном потоке AppKit; воркер лишь поднимает флаг
            if menu_dirty["value"]:
                menu_dirty["value"] = False
                self._build_menu()
```

This deletes all the old `self.title = …` emoji branches.

- [ ] **Step 8: Run the whole test suite**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -v`
Expected: all PASS (same count as before plus the new tests).

- [ ] **Step 9: Smoke-run from the worktree** (hotkey is dead without Accessibility — expected; we only look at the icon and menu):

```bash
/Users/sergeyarkhipov/whisper_flow/.venv/bin/python voice_type.py
```

Expected: a second menubar item appears with `arrow.down.circle` pulsing while Parakeet loads, then `mic`. The menu's first line reads "Loading model parakeet-tdt-0.6b-v3…" then "Ready · hold right ⌥" (English: system language is en-PL) with a green dot. Toggle "Pause (disable hotkey)" → `mic.slash`, status "Paused". Quit via the menu. No tracebacks in the console.

- [ ] **Step 10: Commit**

```bash
git add voice_type.py
git commit -m "feat: SF Symbols menubar icon and status line in the menu"
```

---

## Self-review notes

- Spec coverage (phase 1): icon states table → Tasks 4–5 (all ten states incl. call transcribing and audio dead); fixed width → `ICON_LENGTH`; red only while recording → `tint="rec"` only for recording/call; ~10 updates/s → 0.1 s timer with frame cache; status line → Tasks 4, 5, 7; `ui_language` + system resolution → Tasks 1–2, 7; download vs load → Task 3. Old submenus untouched (spec: they move to the window in phase 2).
- Watchdog timing preserved: `_slow_tick` still runs every ≥0.3 s, so «3 misses ≈ 0.9 s» holds.
- `transcriber_holder["cached"]` is initialised, so `_snapshot` never KeyErrors before the first load.
