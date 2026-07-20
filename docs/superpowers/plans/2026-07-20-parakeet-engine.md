# Parakeet ASR Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NVIDIA Parakeet-TDT-0.6b-v3 as an optional, faster transcription engine selectable from the Model menu, alongside Whisper (which stays the default).

**Architecture:** A new `ParakeetTranscriber` class implements the existing transcriber interface (`transcribe(audio, language, initial_prompt) -> str`, `warm_up()`, `.model`/`.last_language`). A pure `transcriber_class_for(model_id, engine)` routing function picks the class by model id. The ffmpeg-free WAV loader is extracted to a shared module function so both Whisper and Parakeet use it. Audio is fed to Parakeet via `get_logmel(...) -> model.generate(...)`, avoiding parakeet-mlx's ffmpeg-based file path.

**Tech Stack:** Python 3, `parakeet-mlx` (MLX on Apple Silicon), stdlib `wave`/`unittest`. New dependency: `parakeet-mlx`.

**Test command (from project root):** `.venv/bin/python -m unittest discover -s tests -t . -v`

**Spec:** `docs/superpowers/specs/2026-07-20-parakeet-engine-design.md`

---

## File Structure

- Modify: `voice_type.py`
  - Extract module-level `load_wav_16k(path)` (from `MLXTranscriber._load_audio`).
  - Add `ParakeetTranscriber` class.
  - Add module-level `transcriber_class_for(model_id, engine)`.
  - Wire routing into `get_transcriber._load()`.
  - Add Parakeet entry to `MLX_MODELS`.
- Create: `tests/test_transcriber.py` — unit tests for `load_wav_16k`, `transcriber_class_for`, and the Parakeet interface.
- Modify: `requirements.txt` — add `parakeet-mlx`.
- Modify: `README.md` — document the new engine and trade-offs.

---

### Task 1: Extract `load_wav_16k(path)` shared loader

**Files:**
- Modify: `voice_type.py` (`MLXTranscriber._load_audio`, ~400-436, and its caller ~459)
- Test: `tests/test_transcriber.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_transcriber.py`:

```python
import tempfile
import unittest
import wave

import numpy as np

import voice_type


def _write_wav(path, samples_bytes, sr, sampwidth=2, channels=1):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sr)
        wf.writeframes(samples_bytes)


class TestLoadWav16k(unittest.TestCase):
    def test_reads_16bit_16k_mono(self):
        sr = 16000
        data = (np.sin(np.linspace(0, 10, sr)) * 30000).astype(np.int16)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        _write_wav(path, data.tobytes(), sr)
        a = voice_type.load_wav_16k(path)
        self.assertEqual(a.dtype, np.float32)
        self.assertAlmostEqual(len(a), sr, delta=2)
        self.assertLessEqual(float(np.max(np.abs(a))), 1.0)

    def test_resamples_non_16k_up_to_16k(self):
        sr = 8000
        data = (np.ones(sr) * 10000).astype(np.int16)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        _write_wav(path, data.tobytes(), sr)
        a = voice_type.load_wav_16k(path)
        self.assertAlmostEqual(len(a), 16000, delta=4)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_transcriber -v`
Expected: FAIL — `AttributeError: module 'voice_type' has no attribute 'load_wav_16k'`

- [ ] **Step 3: Add the module-level function**

In `voice_type.py`, in the "Транскрипция" section just above `class MLXTranscriber` (~line 384), add:

```python
def load_wav_16k(wav_path: str):
    """Read a WAV into a float32 mono 16 kHz numpy array WITHOUT ffmpeg.

    Recording is already 16 kHz, but resample linearly if the source differs.
    Keeps the app fully offline/self-contained (no ffmpeg in the .app PATH).
    """
    import wave as _wave

    import numpy as _np

    with _wave.open(wav_path, "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())

    if sw == 2:
        a = _np.frombuffer(raw, dtype=_np.int16).astype(_np.float32) / 32768.0
    elif sw == 4:
        a = _np.frombuffer(raw, dtype=_np.int32).astype(_np.float32) / 2147483648.0
    else:  # 8-bit unsigned
        a = _np.frombuffer(raw, dtype=_np.uint8).astype(_np.float32) / 128.0 - 1.0

    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)

    if sr != 16000 and len(a) > 1:
        new_len = int(round(len(a) * 16000 / sr))
        a = _np.interp(
            _np.linspace(0, len(a), new_len, endpoint=False),
            _np.arange(len(a)),
            a,
        )
    return a.astype(_np.float32)
```

- [ ] **Step 4: Replace `MLXTranscriber._load_audio` with a call to it**

Delete the `_load_audio` staticmethod from `MLXTranscriber` (the whole `@staticmethod def _load_audio(wav_path): ...` block). In `MLXTranscriber.transcribe`, change:

```python
        if isinstance(audio, str):
            audio = self._load_audio(audio)
```
to:
```python
        if isinstance(audio, str):
            audio = load_wav_16k(audio)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_transcriber -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `.venv/bin/python -m unittest discover -s tests -t . -v`
Expected: all PASS (skips allowed for missing optional deps)

- [ ] **Step 7: Commit**

```bash
git add voice_type.py tests/test_transcriber.py
git commit -m "refactor: extract load_wav_16k shared WAV loader

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Add `ParakeetTranscriber` class

**Files:**
- Modify: `voice_type.py` (after `FasterWhisperTranscriber`, ~line 524)
- Test: `tests/test_transcriber.py`

- [ ] **Step 1: Write the failing interface test**

Append to `tests/test_transcriber.py` (before the `if __name__` block):

```python
class TestParakeetInterface(unittest.TestCase):
    def test_class_exists_with_matching_interface(self):
        import inspect

        cls = voice_type.ParakeetTranscriber
        params = list(inspect.signature(cls.transcribe).parameters)
        self.assertIn("language", params)
        self.assertIn("initial_prompt", params)
        self.assertTrue(hasattr(cls, "warm_up"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_transcriber.TestParakeetInterface -v`
Expected: FAIL — `AttributeError: module 'voice_type' has no attribute 'ParakeetTranscriber'`

- [ ] **Step 3: Add the class**

In `voice_type.py`, immediately after the `FasterWhisperTranscriber` class (before the `# Вставка` section divider, ~line 524), add:

```python
class ParakeetTranscriber:
    """NVIDIA Parakeet-TDT-0.6b-v3 via parakeet-mlx — fast, multilingual
    (auto-detects; supports ru/uk/en among 25 European languages)."""

    def __init__(self, model: str, language: Optional[str]):
        try:
            from parakeet_mlx import from_pretrained  # type: ignore
        except ImportError as e:
            print("\n[!] pip install parakeet-mlx\n", file=sys.stderr)
            raise SystemExit(1) from e
        self._model = from_pretrained(model)
        self.model = model
        self.language = language
        self.last_language: Optional[str] = None

    def transcribe(
        self,
        audio,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> str:
        """audio: float32 mono 16 kHz numpy array or path to WAV.

        `language` and `initial_prompt` are accepted for interface parity but
        IGNORED: Parakeet auto-detects the language and supports neither a
        language force nor prompt biasing. We feed a precomputed log-mel to
        `generate()` so we never hit parakeet-mlx's ffmpeg-based file path.
        """
        import mlx.core as mx  # type: ignore
        from parakeet_mlx.audio import get_logmel  # type: ignore

        if isinstance(audio, str):
            audio = load_wav_16k(audio)
        mel = get_logmel(mx.array(audio), self._model.preprocessor_config)
        results = self._model.generate(mel)
        text = (results[0].text if results else "") or ""
        # Parakeet returns no language code; best-effort for the polisher.
        self.last_language = language if language is not None else self.language
        return text.strip()

    def warm_up(self) -> None:
        """Run 0.5s of silence through the model to load weights + compile
        Metal kernels off the first real dictation. Best-effort, never raises."""
        import numpy as np

        try:
            self.transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))
        except Exception as e:
            print(f"[!] parakeet warm-up failed: {e}", file=sys.stderr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_transcriber.TestParakeetInterface -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add voice_type.py tests/test_transcriber.py
git commit -m "feat: add ParakeetTranscriber (parakeet-mlx, ffmpeg-free)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Add `transcriber_class_for` routing and wire it into loading

**Files:**
- Modify: `voice_type.py` (add function after `ParakeetTranscriber`; edit `get_transcriber._load()` ~726-733)
- Test: `tests/test_transcriber.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_transcriber.py` (before the `if __name__` block):

```python
class TestTranscriberClassFor(unittest.TestCase):
    def test_parakeet_id_routes_to_parakeet(self):
        cls = voice_type.transcriber_class_for(
            "mlx-community/parakeet-tdt-0.6b-v3", "mlx")
        self.assertIs(cls, voice_type.ParakeetTranscriber)

    def test_whisper_mlx_routes_to_mlx(self):
        cls = voice_type.transcriber_class_for(
            "mlx-community/whisper-large-v3-mlx", "mlx")
        self.assertIs(cls, voice_type.MLXTranscriber)

    def test_faster_engine_routes_to_faster(self):
        cls = voice_type.transcriber_class_for("large-v3", "faster")
        self.assertIs(cls, voice_type.FasterWhisperTranscriber)

    def test_parakeet_id_wins_even_on_faster_engine(self):
        cls = voice_type.transcriber_class_for(
            "mlx-community/parakeet-tdt-0.6b-v3", "faster")
        self.assertIs(cls, voice_type.ParakeetTranscriber)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_transcriber.TestTranscriberClassFor -v`
Expected: FAIL — `AttributeError: module 'voice_type' has no attribute 'transcriber_class_for'`

- [ ] **Step 3: Add the routing function**

In `voice_type.py`, immediately after the `ParakeetTranscriber` class (before the `# Вставка` divider), add:

```python
def transcriber_class_for(model_id: str, engine: str):
    """Pick the transcriber class by model id. A model id containing
    "parakeet" always routes to ParakeetTranscriber regardless of engine;
    otherwise the mlx/faster engine flag decides the Whisper backend."""
    if "parakeet" in model_id:
        return ParakeetTranscriber
    return MLXTranscriber if engine == "mlx" else FasterWhisperTranscriber
```

- [ ] **Step 4: Wire it into `get_transcriber._load()`**

In `get_transcriber._load()` (~726), replace:

```python
            try:
                # инициируем с None — язык подставляется на каждый запрос
                if args.engine == "mlx":
                    obj = MLXTranscriber(target, None)
                else:
                    obj = FasterWhisperTranscriber(target, None)
```
with:
```python
            try:
                # инициируем с None — язык подставляется на каждый запрос;
                # класс выбираем по id модели (parakeet → ParakeetTranscriber)
                cls = transcriber_class_for(target, args.engine)
                obj = cls(target, None)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_transcriber.TestTranscriberClassFor -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -t . -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add voice_type.py tests/test_transcriber.py
git commit -m "feat: route transcriber class by model id (parakeet vs whisper)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Add the menu entry and dependency

**Files:**
- Modify: `voice_type.py` (`MLX_MODELS`, ~821-826)
- Modify: `requirements.txt`

- [ ] **Step 1: Add the Model menu entry**

In `voice_type.py`, in the `MLX_MODELS` list (~821), add the Parakeet entry as the second item (right after Large v3):

```python
    MLX_MODELS = [
        ("🎯 Large v3 — most accurate (default)", "mlx-community/whisper-large-v3-mlx"),
        ("⚡ Parakeet v3 — fastest (RU/UK/EN)", "mlx-community/parakeet-tdt-0.6b-v3"),
        ("⚡ Turbo — faster decode, weaker RU/UK", "mlx-community/whisper-large-v3-turbo"),
        ("Medium — balanced", "mlx-community/whisper-medium-mlx"),
        ("Small — fastest", "mlx-community/whisper-small-mlx"),
    ]
```

- [ ] **Step 2: Add the dependency**

In `requirements.txt`, add after the `mlx-lm` line:

```
parakeet-mlx>=0.3.0
```

- [ ] **Step 3: Verify the module still imports and the suite passes**

Run: `.venv/bin/python -c "import voice_type" && .venv/bin/python -m unittest discover -s tests -t . -v`
Expected: import succeeds without error; all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add voice_type.py requirements.txt
git commit -m "feat: expose Parakeet v3 in the Model menu; add parakeet-mlx dep

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Install locally and run the manual A/B (the point of this change)

**Files:** none (local validation)

- [ ] **Step 1: Install the new dependency**

Run: `.venv/bin/pip install parakeet-mlx`
Expected: installs cleanly on Apple Silicon.

- [ ] **Step 2: Launch and select Parakeet**

Run: `.venv/bin/python voice_type.py`
In the 🎙 menu → Model → pick "⚡ Parakeet v3 — fastest (RU/UK/EN)".
Expected: first selection downloads ~600 MB from HuggingFace and warms up in the
background; log prints `Model ready: parakeet-tdt-0.6b-v3 (warm-up …s)`.

- [ ] **Step 3: A/B the same phrases**

Dictate the same 3-4 phrases (Russian, Ukrainian, English, and a mixed one) once
on Parakeet and once on `large-v3`. Record for each:
- release→paste latency (feel/stopwatch),
- accuracy (errors, especially RU/UK morphology and any domain terms).

- [ ] **Step 4: Record the outcome in the spec**

Append a short "Local A/B results" section to
`docs/superpowers/specs/2026-07-20-parakeet-engine-design.md` with the numbers and
a recommendation on whether Parakeet should become the default. Commit it.

---

### Task 6: Document the engine and trade-offs in README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the models table and add a trade-offs note**

In `README.md`, add a Parakeet row to the "Alternative models" table:

```
| ⚡ `parakeet-tdt-0.6b-v3` | ~10× faster than Whisper (FastConformer-TDT). Multilingual incl. RU/UK/EN, auto-detects language. No vocabulary bias / no forced language. (~600 MB) |
```

And add a short note near the vocabulary/Smart section:

```
> **Parakeet note:** Parakeet auto-detects the language and doesn't take an
> `initial_prompt`, so the vocabulary list doesn't bias it the way it biases
> Whisper. The LLM correction pass (Clean/Prompt) still applies your vocabulary.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document Parakeet engine and its trade-offs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- Line numbers are approximate (`~`) and shift as edits land — anchor on the quoted
  code, not the number.
- Heavy deps (`mlx`, `parakeet_mlx`, `rumps`) are imported lazily inside classes, so
  `import voice_type` and all unit tests run without them installed. Do NOT move these
  imports to module top level.
- Tasks 1-4 and 6 are pure code/docs and fully unit-testable. Task 5 is manual local
  validation on Apple Silicon — it needs the model download and real microphone input,
  so it is not automated.
