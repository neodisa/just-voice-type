# Parakeet ASR engine (fast dictation) — design

**Date:** 2026-07-20
**Status:** Approved, pre-implementation

## Problem

Whisper `large-v3` (our default) is autoregressive: it decodes token by token, so
the felt latency of a dictation is the transcription of the final chunk after the
key is released. On long or fast speech this "frozen" tail is the main pain point.

We want a faster path that still supports the languages we care about (Russian,
Ukrainian, English).

## Chosen approach

Add **NVIDIA Parakeet-TDT-0.6b-v3** as a second, optional engine alongside Whisper,
via the Python **`parakeet-mlx`** package (senstella/parakeet-mlx, MLX on Apple
Silicon). Parakeet is a FastConformer-TDT model — near-parallel decoding, ~10×
faster than Whisper, ~600M params (~600 MB). Verified: v3 supports 25 European
languages **including `ru` and `uk`**, auto-detects language (no prompt).

Whisper stays the default. Parakeet is opt-in from the Model menu. Low risk: the
transcriber layer is already a pluggable backend.

## Non-goals (YAGNI)

- Not replacing Whisper as default (decided after local A/B testing, separate step).
- Not using Parakeet's built-in `transcribe_stream` — our pause-sliced streaming
  stays as is; built-in streaming is a possible future optimization.
- No Swift/FluidAudio/CoreML path — we stay in the existing Python app.

## Components

### 1. `ParakeetTranscriber` (new class in `voice_type.py`)

Implements the same interface as `MLXTranscriber` / `FasterWhisperTranscriber`:
`transcribe(audio, language=None, initial_prompt=None) -> str`, `warm_up()`,
attributes `.model`, `.language`, `.last_language`.

- `__init__(model, language)`: `from parakeet_mlx import from_pretrained`;
  `self._model = from_pretrained(model)`. On `ImportError`, print
  `pip install parakeet-mlx` and `raise SystemExit(1)` — same pattern as the
  other backends. `language` is stored but only used to seed `last_language`.
- `transcribe`:
  - If `audio` is a `str` path → `load_wav_16k(audio)` (see §2).
  - `mel = get_logmel(mx.array(audio), self._model.preprocessor_config)`
    (`from parakeet_mlx.audio import get_logmel`, `import mlx.core as mx`).
    This is the ffmpeg-free path — `parakeet_mlx`'s own `transcribe(path)` and
    `load_audio` shell out to ffmpeg, which the `.app` does not have. `generate`
    on a precomputed mel avoids that entirely.
  - `res = self._model.generate(mel)` → return `res[0].text.strip()` (or `""`
    if empty).
  - `language` and `initial_prompt` are **ignored** — Parakeet supports neither a
    language force nor prompt biasing. Documented in the docstring.
  - `last_language = language or self.language` (Parakeet returns no code); `None`
    is acceptable to the polisher.
- `warm_up`: run 0.5s of silence through `transcribe`, best-effort, never raises —
  same as Whisper (loads weights + compiles Metal kernels off the first dictation).
- Sample rate: app records at `SAMPLE_RATE = 16_000`, which matches Parakeet's
  `preprocessor_config.sample_rate`. `load_wav_16k` already targets 16 kHz.

### 2. Refactor: extract `load_wav_16k(path)`

`MLXTranscriber._load_audio` (ffmpeg-free WAV → float32 mono 16 kHz numpy) becomes
a module-level function `load_wav_16k(path)`. `MLXTranscriber` and
`ParakeetTranscriber` both call it. Behavior unchanged; removes duplication.

### 3. Class selection + menu

- `get_transcriber._load()` (voice_type.py ~726): pick the class by model id —
  `if "parakeet" in target: ParakeetTranscriber(target, None)` else the current
  mlx/faster branch. Live switching and persisted model choice already work.
- `MLX_MODELS` (voice_type.py ~821): add
  `("⚡ Parakeet v3 — fastest (RU/UK/EN)", "mlx-community/parakeet-tdt-0.6b-v3")`.
- Default model unchanged: `mlx-community/whisper-large-v3-mlx`.

### 4. Dependencies

`requirements.txt`: add `parakeet-mlx`. Model (~600 MB) downloads from HuggingFace
in the background on first selection and warms up, like the other models.

## Data flow (unchanged except the engine)

record → (streaming: pause-sliced chunks) → `get_transcriber().transcribe(numpy)`
→ join parts → polish (optional) → paste. Only the transcriber implementation
changes; the queue/worker/streaming code is untouched.

## Error handling

- Missing package → clear install message + `SystemExit(1)`.
- `generate` returns empty / raises → `transcribe` returns `""`; existing
  worker treats empty as "nothing transcribed".
- Warm-up failure is logged, non-fatal.

## Known trade-offs (to document in README)

- `vocabulary` loses its Whisper `initial_prompt` bias for Parakeet; the LLM
  correction half in `polish.py` still applies.
- In Auto mode the polisher gets no detected language code from Parakeet; the
  default `raw` mode is unaffected.

## Testing

- **Unit tests** (`tests/`, pure logic, no model download):
  - class selection by model id ("parakeet" → `ParakeetTranscriber`).
  - `load_wav_16k` across 8/16/32-bit and non-16 kHz sample rates (mirrors any
    existing audio-loader coverage).
- **Manual local A/B (the point of this change):** same RU/UK/EN recordings
  through Parakeet vs `large-v3`; measure (a) release→paste latency and (b)
  accuracy. Decide afterwards whether Parakeet becomes the default.

## Ship

After local validation: update README (new engine, trade-offs), then a GitHub
update (commit/PR).
