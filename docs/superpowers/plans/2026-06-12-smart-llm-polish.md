# Smart LLM Polish Modes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local on-device LLM pass after Whisper that cleans dictation and restructures it into a clear AI prompt, controlled by a Raw/Clean/Prompt menu picker.

**Architecture:** New isolated, GUI-free `polish.py` module wrapping `mlx_lm` (Qwen2.5-3B-Instruct-4bit), dependency-injectable for hermetic tests. `config.py` gains `smart_mode` + `vocabulary`. `voice_type.py` wires a single `Polisher` into the transcription worker between `transcribe` and `deliver_text`, feeds `vocabulary` to Whisper's `initial_prompt`, and adds a `Smart` menu picker. Polish never blocks paste — any error returns the raw Whisper text.

**Tech Stack:** Python 3.10+, `mlx-lm` v0.31+, `unittest`, rumps (menubar).

---

## File Structure

| File | Responsibility |
|---|---|
| `polish.py` | **New.** Pure prompt-building + output-cleaning helpers, `Polisher` class wrapping mlx_lm with DI for tests. No GUI deps. |
| `config.py` | Add `smart_mode` (raw/clean/prompt) + `vocabulary` (list[str]) to DEFAULTS/validation. |
| `voice_type.py` | Wire `Polisher` into worker, `vocabulary`→Whisper `initial_prompt`, `Smart` menu, persist new fields. |
| `requirements.txt` | `+ mlx-lm`. |
| `tests/test_polish.py` | **New.** Unit tests for `polish.py` (hermetic, mocked model). |
| `tests/test_config.py` | Extend for `smart_mode` + `vocabulary`. |
| `README.md` | Document Smart modes + vocabulary (last). |

---

## Task 1: Config — `smart_mode` + `vocabulary`

**Files:**
- Modify: `config.py` (DEFAULTS, `_defaults_copy`, `_validate`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py` inside `class TestConfig`:

```python
    def test_defaults_include_smart_mode_and_vocabulary(self):
        cfg = config.load()
        self.assertEqual(cfg["smart_mode"], "prompt")
        self.assertEqual(cfg["vocabulary"], [])

    def test_smart_mode_roundtrip(self):
        config.save({"smart_mode": "clean", "vocabulary": ["Anthropic", "Qwen"]})
        cfg = config.load()
        self.assertEqual(cfg["smart_mode"], "clean")
        self.assertEqual(cfg["vocabulary"], ["Anthropic", "Qwen"])

    def test_invalid_smart_mode_falls_back_to_prompt(self):
        config.save({"smart_mode": "nonsense"})
        self.assertEqual(config.load()["smart_mode"], "prompt")

    def test_vocabulary_drops_non_strings_and_blanks(self):
        config.save({"vocabulary": ["ok", "", "  ", 42, None, "Claude"]})
        self.assertEqual(config.load()["vocabulary"], ["ok", "Claude"])

    def test_defaults_copy_isolates_vocabulary_list(self):
        cfg = config.load()
        cfg["vocabulary"].append("mutated")
        self.assertEqual(config.DEFAULTS["vocabulary"], [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_config -v`
Expected: FAIL — `KeyError: 'smart_mode'` / assertion errors.

- [ ] **Step 3: Implement config changes**

In `config.py`, update `DEFAULTS`:

```python
DEFAULTS = {
    "favorite_languages": ["ru", "uk", "en"],
    "active_language": None,
    "hotkey": "right_option",
    "smart_mode": "prompt",
    "vocabulary": [],
}

SMART_MODES = ("raw", "clean", "prompt")
```

Update `_defaults_copy()` to include the new keys:

```python
def _defaults_copy() -> "dict[str, Any]":
    return {
        "favorite_languages": list(DEFAULTS["favorite_languages"]),
        "active_language": DEFAULTS["active_language"],
        "hotkey": DEFAULTS["hotkey"],
        "smart_mode": DEFAULTS["smart_mode"],
        "vocabulary": list(DEFAULTS["vocabulary"]),
    }
```

In `_validate()`, before `return cfg`, add:

```python
    mode = raw.get("smart_mode")
    if isinstance(mode, str) and mode in SMART_MODES:
        cfg["smart_mode"] = mode
    else:
        cfg["smart_mode"] = DEFAULTS["smart_mode"]

    vocab = raw.get("vocabulary")
    if isinstance(vocab, list):
        cfg["vocabulary"] = [
            v.strip() for v in vocab if isinstance(v, str) and v.strip()
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_config -v`
Expected: PASS (all, including the 5 new ones).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat(config): add smart_mode and vocabulary settings"
```

---

## Task 2: `polish.py` — pure helpers

**Files:**
- Create: `polish.py`
- Test: `tests/test_polish.py`

Pure, model-free functions: prompt building, output cleaning, token budget.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_polish.py`:

```python
import unittest

import polish


class TestBuildMessages(unittest.TestCase):
    def test_clean_mode_system_forbids_translation_and_answering(self):
        msgs = polish.build_messages("ну привет", "clean", language="ru")
        self.assertEqual(msgs[0]["role"], "system")
        sys_l = msgs[0]["content"].lower()
        self.assertIn("ru", sys_l)
        self.assertIn("clean", sys_l)
        self.assertEqual(msgs[-1]["role"], "user")
        self.assertIn("ну привет", msgs[-1]["content"])

    def test_prompt_mode_mentions_instruction(self):
        msgs = polish.build_messages("сделай скрипт", "prompt")
        self.assertIn("instruction", msgs[0]["content"].lower())

    def test_vocabulary_embedded_when_present(self):
        msgs = polish.build_messages("x", "prompt", vocabulary=["Anthropic", "Qwen"])
        self.assertIn("Anthropic", msgs[0]["content"])
        self.assertIn("Qwen", msgs[0]["content"])

    def test_no_vocabulary_section_when_empty(self):
        msgs = polish.build_messages("x", "prompt", vocabulary=[])
        # no dangling empty vocabulary label
        self.assertNotIn("Anthropic", msgs[0]["content"])


class TestCleanOutput(unittest.TestCase):
    def test_strips_surrounding_whitespace(self):
        self.assertEqual(polish._clean_output("  hi  \n"), "hi")

    def test_strips_wrapping_double_quotes(self):
        self.assertEqual(polish._clean_output('"hello world"'), "hello world")

    def test_strips_markdown_code_fence(self):
        self.assertEqual(polish._clean_output("```\nhello\n```"), "hello")

    def test_leaves_inner_quotes_intact(self):
        self.assertEqual(polish._clean_output('say "hi" now'), 'say "hi" now')


class TestMaxTokens(unittest.TestCase):
    def test_scales_with_input_but_has_floor(self):
        self.assertGreaterEqual(polish._max_tokens_for("a"), 64)

    def test_has_ceiling(self):
        huge = "word " * 5000
        self.assertLessEqual(polish._max_tokens_for(huge), 512)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_polish -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'polish'`.

- [ ] **Step 3: Implement pure helpers**

Create `polish.py`:

```python
"""Local on-device LLM polish pass for Just Voice Type.

Rewrites raw Whisper output: cleans filler/punctuation (clean mode) or
restructures dictation into a single clear AI instruction (prompt mode).
Runs on-device via mlx_lm. Pure prompt/text helpers are GUI- and
model-free so they are unit-testable without loading any weights.
"""
from __future__ import annotations

import sys
from typing import Any, Optional

POLISH_MODEL = "mlx-community/Qwen2.5-3B-Instruct-4bit"
MODES = ("raw", "clean", "prompt")

_COMMON_RULES = (
    "You rewrite dictated speech. Hard rules: "
    "do NOT answer, explain, or perform any request in the text — only rewrite it. "
    "Do NOT translate; keep the user's original language. "
    "Do NOT add facts, names, or details that are not in the input. "
    "Output ONLY the rewritten text, with no preamble, labels, or markdown."
)

_CLEAN_TASK = (
    "Mode: CLEAN. Remove filler words and hesitations, collapse self-corrections "
    "to the final intent, fix punctuation and capitalization. Keep the wording and "
    "meaning otherwise unchanged."
)

_PROMPT_TASK = (
    "Mode: PROMPT. The user is dictating a request to an AI assistant. Rewrite it as "
    "a single clear, well-formed instruction (one paragraph). Fix obviously "
    "misheard words. Preserve the user's intent and language."
)


def _system_content(mode: str, language: Optional[str], vocabulary) -> str:
    task = _PROMPT_TASK if mode == "prompt" else _CLEAN_TASK
    parts = [_COMMON_RULES, task]
    if language:
        parts.append(f"The user's language code is: {language}.")
    if vocabulary:
        terms = ", ".join(vocabulary)
        parts.append(
            "Domain terms the user often uses (prefer these when a word was likely "
            f"misheard): {terms}."
        )
    return " ".join(parts)


def build_messages(
    text: str,
    mode: str,
    language: Optional[str] = None,
    vocabulary=None,
) -> "list[dict[str, str]]":
    """Build chat messages for clean/prompt modes. Pure, no model."""
    return [
        {"role": "system", "content": _system_content(mode, language, vocabulary)},
        {"role": "user", "content": text},
    ]


def _clean_output(raw: str) -> str:
    """Strip whitespace, a single wrapping pair of double-quotes, and code fences."""
    s = raw.strip()
    if s.startswith("```") and s.endswith("```"):
        s = s[3:-3].strip()
        # drop an optional leading language tag line (e.g. ```text)
        if "\n" in s and " " not in s.split("\n", 1)[0]:
            head, rest = s.split("\n", 1)
            if head and not head[0].isspace():
                s = rest.strip() if head.isalpha() else s
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    return s


def _max_tokens_for(text: str) -> int:
    words = len(text.split())
    return max(64, min(512, words * 3))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_polish -v`
Expected: PASS (all 11 tests in this file so far).

- [ ] **Step 5: Commit**

```bash
git add polish.py tests/test_polish.py
git commit -m "feat(polish): pure prompt-building and output-cleaning helpers"
```

---

## Task 3: `polish.py` — `Polisher` class with DI + fallback

**Files:**
- Modify: `polish.py` (add `Polisher`)
- Test: `tests/test_polish.py`

`Polisher` wraps mlx_lm with injectable `load_fn`/`generate_fn` so tests never load real weights. `raw`/empty bypass the model entirely; any model error returns the input unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_polish.py`:

```python
class _FakeTokenizer:
    def apply_chat_template(self, messages, add_generation_prompt=True):
        # echo a deterministic prompt string built from messages
        return "PROMPT::" + messages[-1]["content"]


class TestPolisher(unittest.TestCase):
    def _polisher(self, gen):
        return polish.Polisher(
            model="fake",
            load_fn=lambda m: ("FAKE_MODEL", _FakeTokenizer()),
            generate_fn=gen,
        )

    def test_raw_mode_returns_input_without_loading(self):
        calls = {"load": 0, "gen": 0}

        def load_fn(m):
            calls["load"] += 1
            return ("M", _FakeTokenizer())

        def gen_fn(*a, **k):
            calls["gen"] += 1
            return "should not run"

        p = polish.Polisher(model="fake", load_fn=load_fn, generate_fn=gen_fn)
        self.assertEqual(p.polish("verbatim text", "raw"), "verbatim text")
        self.assertEqual(calls["load"], 0)
        self.assertEqual(calls["gen"], 0)
        self.assertFalse(p.is_loaded())

    def test_empty_text_returns_input_without_loading(self):
        p = self._polisher(lambda *a, **k: "x")
        self.assertEqual(p.polish("   ", "prompt"), "   ")
        self.assertFalse(p.is_loaded())

    def test_clean_mode_calls_model_and_cleans_output(self):
        p = self._polisher(lambda *a, **k: '  "cleaned text"  ')
        out = p.polish("ну эээ привет", "clean", language="ru")
        self.assertEqual(out, "cleaned text")
        self.assertTrue(p.is_loaded())

    def test_prompt_passed_through_chat_template(self):
        seen = {}

        def gen_fn(model, tokenizer, prompt=None, **k):
            seen["prompt"] = prompt
            return "ok"

        p = self._polisher(gen_fn)
        p.polish("сделай скрипт", "prompt")
        self.assertTrue(seen["prompt"].startswith("PROMPT::"))
        self.assertIn("сделай скрипт", seen["prompt"])

    def test_model_error_falls_back_to_raw_text(self):
        def boom(*a, **k):
            raise RuntimeError("mlx blew up")

        p = self._polisher(boom)
        self.assertEqual(p.polish("original", "prompt"), "original")

    def test_empty_generation_falls_back_to_raw_text(self):
        p = self._polisher(lambda *a, **k: "   ")
        self.assertEqual(p.polish("original", "clean"), "original")

    def test_model_loaded_only_once(self):
        calls = {"load": 0}

        def load_fn(m):
            calls["load"] += 1
            return ("M", _FakeTokenizer())

        p = polish.Polisher(
            model="fake", load_fn=load_fn, generate_fn=lambda *a, **k: "out"
        )
        p.polish("a", "clean")
        p.polish("b", "clean")
        self.assertEqual(calls["load"], 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_polish -v`
Expected: FAIL — `AttributeError: module 'polish' has no attribute 'Polisher'`.

- [ ] **Step 3: Implement `Polisher`**

Append to `polish.py`:

```python
class Polisher:
    """On-device LLM polisher. Lazy-loads weights on first clean/prompt call.

    `load_fn` / `generate_fn` are injectable for tests; in production they
    default to `mlx_lm.load` / `mlx_lm.generate`.
    """

    def __init__(self, model: str = POLISH_MODEL, load_fn=None, generate_fn=None):
        self.model_id = model
        self._load_fn = load_fn
        self._generate_fn = generate_fn
        self._model: Any = None
        self._tokenizer: Any = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        load_fn = self._load_fn
        if load_fn is None:
            from mlx_lm import load as load_fn  # type: ignore
        self._model, self._tokenizer = load_fn(self.model_id)

    def polish(
        self,
        text: str,
        mode: str,
        language: Optional[str] = None,
        vocabulary=None,
    ) -> str:
        if mode == "raw" or not text or not text.strip():
            return text
        if mode not in ("clean", "prompt"):
            return text
        try:
            self._ensure_loaded()
            generate_fn = self._generate_fn
            if generate_fn is None:
                from mlx_lm import generate as generate_fn  # type: ignore
            messages = build_messages(text, mode, language, vocabulary)
            prompt = self._tokenizer.apply_chat_template(
                messages, add_generation_prompt=True
            )
            out = generate_fn(
                self._model,
                self._tokenizer,
                prompt=prompt,
                max_tokens=_max_tokens_for(text),
                temperature=0.1,
            )
            cleaned = _clean_output(out or "")
            return cleaned or text
        except Exception as e:  # never block paste
            print(f"[!] polish failed ({e}); using raw text", file=sys.stderr)
            return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_polish -v`
Expected: PASS (all tests in `tests/test_polish.py`).

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (config + languages + polish).

- [ ] **Step 6: Commit**

```bash
git add polish.py tests/test_polish.py
git commit -m "feat(polish): Polisher class with lazy load, DI, and raw-text fallback"
```

---

## Task 4: requirements + Whisper `initial_prompt` plumbing

**Files:**
- Modify: `requirements.txt`
- Modify: `voice_type.py` (`MLXTranscriber.transcribe`, `FasterWhisperTranscriber.transcribe`)

Add the `initial_prompt` parameter to both transcribers so the vocabulary can bias recognition. Pure plumbing — verified by syntax check (mlx not available in CI).

- [ ] **Step 1: Add dependency**

In `requirements.txt`, add after `mlx-whisper>=0.4.0`:

```
mlx-lm>=0.31.0
```

- [ ] **Step 2: Add `initial_prompt` to `MLXTranscriber.transcribe`**

In `voice_type.py`, change the signature and kwargs (around [voice_type.py:374](../../../voice_type.py)):

```python
    def transcribe(
        self,
        wav_path: str,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> str:
        # язык можно переопределить на каждый запрос
        lang = language if language is not None else self.language
        kwargs = dict(
            path_or_hf_repo=self.model,
            word_timestamps=False,
        )
        if lang:
            kwargs["language"] = lang
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        audio = self._load_audio(wav_path)
        result = self._transcribe(audio, **kwargs)
```

(leave the rest of the method unchanged)

- [ ] **Step 3: Add `initial_prompt` to `FasterWhisperTranscriber.transcribe`**

In `voice_type.py`, around [voice_type.py:403](../../../voice_type.py):

```python
    def transcribe(
        self,
        wav_path: str,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> str:
        lang = language if language is not None else self.language
        segments, info = self._model.transcribe(
            wav_path,
            language=lang,  # None = auto-detect
            vad_filter=True,
            beam_size=5,
            initial_prompt=initial_prompt or None,
        )
```

(leave the rest of the method unchanged)

- [ ] **Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open('voice_type.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt voice_type.py
git commit -m "feat: add mlx-lm dep and initial_prompt support to transcribers"
```

---

## Task 5: Wire config holders + persist in `voice_type.py`

**Files:**
- Modify: `voice_type.py` (imports, holders, `persist`)

- [ ] **Step 1: Import polish**

In `voice_type.py`, near the top with the other local imports (`import config`, `import languages`), add:

```python
import polish
```

- [ ] **Step 2: Add holders**

After `current_hotkey = {"value": cfg["hotkey"]}` ([voice_type.py:622](../../../voice_type.py)), add:

```python
    smart_mode = {"value": cfg["smart_mode"]}
    vocabulary = {"value": list(cfg["vocabulary"])}
    polisher = polish.Polisher()
```

- [ ] **Step 3: Persist the new fields**

Update `persist()` ([voice_type.py:624](../../../voice_type.py)) to include them:

```python
    def persist():
        config.save(
            {
                "favorite_languages": favorites["value"],
                "active_language": current_lang["value"],
                "hotkey": current_hotkey["value"],
                "smart_mode": smart_mode["value"],
                "vocabulary": vocabulary["value"],
            }
        )
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open('voice_type.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add voice_type.py
git commit -m "feat: load/persist smart_mode and vocabulary, init Polisher"
```

---

## Task 6: Polish in the worker + vocabulary → Whisper

**Files:**
- Modify: `voice_type.py` (worker, [voice_type.py:866](../../../voice_type.py))

Insert the polish call between transcription and delivery, and feed the vocabulary into Whisper as `initial_prompt`.

- [ ] **Step 1: Pass vocabulary to the transcriber**

In `worker()`, replace the transcribe call ([voice_type.py:866](../../../voice_type.py)):

```python
                t0 = time.time()
                vocab_prompt = ", ".join(vocabulary["value"]) or None
                # передаём текущий выбранный язык (None = auto) и словарь-bias
                text = tr.transcribe(
                    wav_path,
                    language=current_lang["value"],
                    initial_prompt=vocab_prompt,
                )
                dt = time.time() - t0
```

- [ ] **Step 2: Insert the polish pass after the hallucination filter**

Immediately after the `is_hallucination` block (after [voice_type.py:870](../../../voice_type.py), the line `text = ""`), and before `if text:`, add:

```python
                if text and smart_mode["value"] != "raw":
                    if not polisher.is_loaded():
                        notify("Voice Type", "Загружаю LLM… (первый раз)")
                    t1 = time.time()
                    text = polish_text_safe(
                        polisher,
                        text,
                        smart_mode["value"],
                        current_lang["value"],
                        vocabulary["value"],
                    )
                    print(f"[i] polished ({smart_mode['value']}, {time.time() - t1:.1f}s)")
```

- [ ] **Step 3: Add the top-level safety wrapper**

`Polisher.polish` already catches its own errors, but the worker must never die if anything around it throws. Add this module-level helper near the other top-level helpers in `voice_type.py` (e.g. just before `def run_app(args):`, around [voice_type.py:549](../../../voice_type.py)):

```python
def polish_text_safe(polisher, text, mode, language, vocabulary):
    """Polish wrapper that can never raise — returns raw text on any failure."""
    try:
        return polisher.polish(text, mode, language=language, vocabulary=vocabulary)
    except Exception as e:
        print(f"[!] polish_text_safe: {e}", file=sys.stderr)
        return text
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open('voice_type.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add voice_type.py
git commit -m "feat: run LLM polish pass in worker, feed vocabulary to Whisper"
```

---

## Task 7: `Smart` menu picker + Edit vocabulary

**Files:**
- Modify: `voice_type.py` (`SMART_PRESETS`, `_smart_menu`, `_make_smart_setter`, `edit_vocabulary`, `_build_menu`)

- [ ] **Step 1: Add the presets constant**

In `voice_type.py`, after `HOTKEY_PRESETS = [...]` ([voice_type.py:655](../../../voice_type.py)), add:

```python
    # пресеты для подменю «Smart» (режим LLM-прохода)
    SMART_PRESETS = [
        ("Raw — verbatim Whisper", "raw"),
        ("Clean — fix filler & punctuation", "clean"),
        ("Prompt — restructure for AI", "prompt"),
    ]
```

- [ ] **Step 2: Add `_smart_menu` and its setter**

In `class VoiceTypeApp`, after `_model_menu` ([voice_type.py:716](../../../voice_type.py)), add:

```python
        def _smart_menu(self):
            items = []
            for label, mode in SMART_PRESETS:
                it = rumps.MenuItem(label, callback=self._make_smart_setter(mode))
                it.state = 1 if mode == smart_mode["value"] else 0
                items.append(it)
            items.append(None)
            items.append(
                rumps.MenuItem("Edit vocabulary…", callback=self.edit_vocabulary)
            )
            return ("Smart", items)
```

After `_make_model_setter` ([voice_type.py:789](../../../voice_type.py)), add:

```python
        def _make_smart_setter(self, mode):
            def setter(_):
                if mode == smart_mode["value"]:
                    return
                smart_mode["value"] = mode
                persist()
                self._build_menu()
                print(f"[i] Smart mode set: {mode}")
                notify("Voice Type", f"Smart → {mode}")

            return setter

        def edit_vocabulary(self, _):
            # словарь правится прямо в конфиг-файле; открываем его в редакторе
            persist()  # на случай первого запуска — гарантируем, что файл есть
            subprocess.Popen(["open", config.config_path()])
            notify(
                "Voice Type",
                "Edit \"vocabulary\" in config.json, then re-pick a Smart mode",
            )
```

- [ ] **Step 3: Add `Smart` to the built menu**

In `_build_menu()` ([voice_type.py:665](../../../voice_type.py)), add `self._smart_menu()` to the `self.menu.update([...])` list, right after `self._model_menu()`:

```python
            self.menu.update(
                [
                    self._hotkey_menu(),
                    self._model_menu(),
                    self._smart_menu(),
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
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open('voice_type.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Manual smoke test**

Run: `python voice_type.py` (on the Mac, in the venv with deps installed).
Verify:
- Menubar shows a `Smart` submenu with Raw / Clean / Prompt + `Edit vocabulary…`; `Prompt` is checked by default.
- Dictate a rambly request in Prompt mode → first time shows "Загружаю LLM…", then pasted text is a clean single instruction.
- Switch to Raw → dictation pastes verbatim Whisper output instantly.
- `Edit vocabulary…` opens `~/.config/just-voice-type/config.json`.

- [ ] **Step 6: Commit**

```bash
git add voice_type.py
git commit -m "feat: Smart menu picker (raw/clean/prompt) + Edit vocabulary"
```

---

## Task 8: Document in README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Smart-modes section**

In `README.md`, under the Features list, add a bullet:

```markdown
- 🧠 **Smart modes** — pick **Raw** (verbatim), **Clean** (strip filler & fix punctuation), or **Prompt** (restructure your dictation into a clear instruction for an AI) from the **Smart** menu. Runs a small on-device LLM (`Qwen2.5-3B-Instruct-4bit` via `mlx_lm`) — no cloud. Add domain terms via **Edit vocabulary…** so misheard names/jargon get fixed and bias Whisper itself.
```

Add a short subsection after the model section explaining: default mode is `Prompt`; the LLM (~2 GB) downloads on first Clean/Prompt dictation; polish never blocks paste (falls back to raw Whisper on error); `vocabulary` lives in `config.json` and feeds both Whisper's `initial_prompt` and the LLM.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document Smart modes and vocabulary"
```

---

## Self-Review Notes

- **Spec coverage:** local mlx_lm pass (T2–T3), 3-mode picker (T7), Raw/Clean/Prompt semantics (T2 prompts), misheard-word two layers — Whisper `initial_prompt` (T4/T6) + LLM vocab (T2/T3), persistence (T1/T5), never-block-paste (T3 fallback + T6 `polish_text_safe`), config vocabulary edit (T7), tests (T1–T3), requirements (T4), README (T8). All covered.
- **No placeholders:** every code step is concrete.
- **Type consistency:** `Polisher(model, load_fn, generate_fn)`, `.polish(text, mode, language=, vocabulary=)`, `.is_loaded()`, `build_messages`, `_clean_output`, `_max_tokens_for`, `polish_text_safe` — names used identically across tasks.
- **Note:** menubar status stays `transcribing` during polish (no `_on_tick` change) — YAGNI; the spec's "extend processing" is satisfied since polish runs inside the existing `transcribing` window.
```
