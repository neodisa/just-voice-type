#!/usr/bin/env python3
"""
voice_type.py — Just Voice Type: local push-to-talk dictation for macOS (Apple Silicon).

UI:
  • Menubar icon (rumps): 🎙 idle, 🔴 REC (blinks + volume bars),
    ⏳ transcribing, 🚫 paused.
  • macOS beeps on record start/stop.
  • macOS notification with recognized text (--notify).
  • Menu: Pause, Copy last text, Quit.

Run:
    python3 voice_type.py
    python3 voice_type.py --hotkey f19 --model mlx-community/whisper-medium-mlx

macOS permissions (System Settings → Privacy & Security):
  Accessibility / Input Monitoring / Microphone → Terminal (or your launcher).
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

import config
import gestures
import history
import languages
import polish
import streaming

# единственный источник правды о версии; бампается при каждом релизе
# (тег vX.Y.Z в git должен совпадать)
__version__ = "0.9.0"
RELEASES_URL = "https://github.com/neodisa/just-voice-type/releases"

SAMPLE_RATE = 16_000

SOUND_START = "/System/Library/Sounds/Tink.aiff"
SOUND_STOP = "/System/Library/Sounds/Pop.aiff"
SOUND_ERROR = "/System/Library/Sounds/Basso.aiff"
SOUND_DONE = "/System/Library/Sounds/Ping.aiff"  # распознано и в буфере (простой одиночный сигнал)

# известные галлюцинации Whisper на тишине/шуме
# (модель обучена на YouTube — часто выдаёт фразы из концовок видео)
HALLUCINATIONS = {
    "thank you.",
    "thanks for watching.",
    "thanks for watching!",
    "thank you for watching.",
    "thank you for watching!",
    "thank you.",
    "thanks.",
    "you",
    ".",
    "субтитры подогнал «А.С.»",
    "субтитры сделал dimatorzok",
    "продолжение следует...",
    "редактор субтитров а.семкин корректор а.егорова",
    "продолжение в следующей серии",
}


def is_hallucination(text: str) -> bool:
    t = text.strip().lower().rstrip(".!?")
    if not t:
        return True
    # точное совпадение с известной галлюцинацией
    for h in HALLUCINATIONS:
        if t == h.lower().rstrip(".!?"):
            return True
    # совсем короткий текст из 1-2 символов — почти всегда мусор
    if len(t) <= 2:
        return True
    return False


def _require(pkg: str, pip_name: Optional[str] = None):
    try:
        return __import__(pkg)
    except ImportError as e:
        name = pip_name or pkg
        print(f"\n[!] pip install {name}\n", file=sys.stderr)
        raise SystemExit(1) from e


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────────────────────


def log(msg: str, err: bool = False) -> None:
    """Лог с таймстампом (при запуске из .app stdout/stderr уходят в
    ~/Library/Logs/WhisperFlow/whisper_flow{,.err}.log)."""
    stream = sys.stderr if err else sys.stdout
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=stream, flush=True)


def play_sound(path: str) -> None:
    if not os.path.exists(path):
        return
    subprocess.Popen(
        ["afplay", "-v", "0.5", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def frontmost_app_pid():
    """PID of the current frontmost application, or None. AppKit is already
    loaded in-process by rumps, so this is a safe, instant read."""
    try:
        from AppKit import NSWorkspace  # type: ignore

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else None
    except Exception:
        return None


def notify(title: str, message: str) -> None:
    safe = message.replace('"', '\\"').replace("\n", " ")
    safe_title = title.replace('"', '\\"')
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{safe}" with title "{safe_title}"',
        ],
        check=False,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Запись
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class Recorder:
    sample_rate: int = SAMPLE_RATE

    def __post_init__(self):
        self.sd = _require("sounddevice")
        self.np = _require("numpy")
        self._frames: list = []
        self._stream = None
        self._lock = threading.Lock()
        self._recording = False
        self._level: float = 0.0
        # реальный sample rate микрофона (узнаём при первом старте)
        self._native_sr: Optional[int] = None
        self._native_channels: int = 1
        # аккумулятор снятых кадров в НАТИВНОМ sr (моно float [-1..1]) —
        # сюда сливаются сырые кадры при снятии чанка; отдельно от _frames,
        # чтобы не смешивать форматы (callback пишет int16, а хвост — float)
        self._carry = None

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        try:
            peak = float(self.np.max(self.np.abs(indata))) / 32768.0
            self._level = self._level * 0.6 + peak * 0.4
        except Exception:
            pass
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())

    def _detect_native_params(self):
        """Берём дефолтное входное устройство и его нативные параметры."""
        try:
            default_in_idx = self.sd.default.device[0]
            info = self.sd.query_devices(default_in_idx)
            native_sr = int(info.get("default_samplerate", 48000))
            # ограничим до моно если устройство умеет, иначе берём что есть
            max_in = int(info.get("max_input_channels", 1))
            channels = 1 if max_in >= 1 else max_in
            print(f"[i] device: {info['name']}, sr={native_sr}, ch={channels}")
            return native_sr, channels
        except Exception as e:
            print(f"[!] could not detect device parameters: {e}", file=sys.stderr)
            return 48000, 1

    def _reinit_portaudio(self):
        """Перезапуск PortAudio внутри процесса.

        CoreAudio-бэкенд PortAudio со временем «протухает» (смена аудио-устройств,
        сон системы, много открытий потока) и InputStream перестаёт открываться
        (ошибки -9986 / AUHAL -10851). Раньше спасал только перезапуск всего
        приложения. Тут делаем то же самое точечно: terminate + initialize
        сбрасывает контекст PortAudio, а сброс кэша устройства заставляет заново
        определить текущий дефолтный микрофон.
        """
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        try:
            self.sd._terminate()
        except Exception:
            pass
        try:
            self.sd._initialize()
        except Exception as e:
            print(f"[!] reinit PortAudio: {e}", file=sys.stderr)
        self._native_sr = None
        self._native_channels = 1

    def _try_open(self) -> bool:
        if self._native_sr is None:
            self._native_sr, self._native_channels = self._detect_native_params()
        # стратегия открытия: сначала native sr, потом 16000, потом без указания
        tried = []
        for sr, ch in [
            (self._native_sr, self._native_channels),
            (16000, 1),
            (44100, 1),
            (None, None),  # пусть PortAudio сам решит
        ]:
            try:
                kwargs = {"dtype": "int16", "callback": self._callback}
                if sr is not None:
                    kwargs["samplerate"] = sr
                if ch is not None:
                    kwargs["channels"] = ch
                self._stream = self.sd.InputStream(**kwargs)
                self._stream.start()
                actual_sr = int(self._stream.samplerate)
                self._native_sr = actual_sr
                if self._stream.channels:
                    self._native_channels = int(self._stream.channels)
                log(f"[i] stream opened: sr={actual_sr}, ch={self._native_channels}")
                return True
            except Exception as e:
                tried.append(f"sr={sr},ch={ch}: {e}")
                continue
        log("[!] failed to open microphone: " + "; ".join(tried), err=True)
        return False

    def start(self):
        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._carry = None
            self._recording = True
        # Пытаемся открыть; если не вышло — переинициализируем PortAudio и
        # пробуем ещё раз (это лечит «протухший» аудио-контекст без рестарта app).
        if self._try_open():
            return
        log("[i] reinitializing PortAudio and retrying...", err=True)
        self._reinit_portaudio()
        if self._try_open():
            return
        self._recording = False
        raise RuntimeError("failed to open microphone even after PortAudio reinit")

    def _to_mono_native(self, raw):
        """Сырые кадры (int16, моно/стерео) → float [-1..1] моно, нативный sr."""
        if raw.ndim == 2 and raw.shape[1] > 1:
            raw = raw.mean(axis=1)
        elif raw.ndim == 2:
            raw = raw[:, 0]
        return raw.astype(self.np.float32) / 32768.0

    def _resample_16k(self, audio_native):
        """float-моно нативный sr → float32-моно 16кГц (линейная интерполяция)."""
        src_sr = self._native_sr or SAMPLE_RATE
        if src_sr == SAMPLE_RATE or len(audio_native) <= 1:
            return audio_native.astype(self.np.float32)
        new_len = int(round(len(audio_native) * SAMPLE_RATE / src_sr))
        if new_len <= 1:
            return audio_native.astype(self.np.float32)
        old_idx = self.np.linspace(0, len(audio_native) - 1, new_len)
        return self.np.interp(
            old_idx, self.np.arange(len(audio_native)), audio_native
        ).astype(self.np.float32)

    def _drain_frames_locked(self):
        """Слить сырые кадры из callback в _carry (нативный моно float).
        Вызывать под self._lock."""
        if self._frames:
            raw = self.np.concatenate(self._frames, axis=0)
            self._frames = []
            mono = self._to_mono_native(raw)
            if self._carry is None or len(self._carry) == 0:
                self._carry = mono
            else:
                self._carry = self.np.concatenate([self._carry, mono], axis=0)

    def take_chunk(
        self,
        min_sec: float,
        target_sec: float,
        hard_max_sec: float,
    ):
        """Если накоплено >= min_sec — отрезать префикс до тихой точки и вернуть
        его как float32-моно 16кГц; хвост остаётся в буфере. Иначе None.

        Позволяет транскрибировать длинную диктовку по кускам, пока она идёт.
        """
        import streaming

        src_sr = self._native_sr or SAMPLE_RATE
        with self._lock:
            if not self._recording:
                return None
            self._drain_frames_locked()
            carry = self._carry
            if carry is None or len(carry) / src_sr < min_sec:
                return None
            split = streaming.find_split_point(carry, src_sr, target_sec=target_sec)
            hard = int(hard_max_sec * src_sr)
            if split > hard:  # паузы всё нет — режем принудительно
                split = hard
            split = max(1, min(split, len(carry)))
            prefix_native = carry[:split]
            self._carry = carry[split:]
        return self._resample_16k(prefix_native)

    def stop(self):
        """Останавливает запись и возвращает остаток как float32-моно 16кГц
        (или None, если он слишком короткий/тихий)."""
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            self._drain_frames_locked()
            carry = self._carry
            self._carry = None
        if self._stream is not None:
            # abort() отбрасывает буферы и возвращается быстрее stop();
            # на «протухшем» CoreAudio-потоке stop() может зависнуть надолго
            try:
                self._stream.abort()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if carry is None or len(carry) == 0:
            return None

        src_sr = self._native_sr or SAMPLE_RATE
        duration = len(carry) / src_sr
        if duration < 0.3:
            print("[·] Too short (<0.3s)")
            return None

        audio_f = self._resample_16k(carry)

        # ── защита от «Thank you»-галлюцинации Whisper ────────────────────
        # Если в остатке фактически только тишина — не отправляем на модель.
        try:
            rms = float(self.np.sqrt(self.np.mean(audio_f * audio_f)))
            peak = float(self.np.max(self.np.abs(audio_f)))
        except Exception:
            rms = 0.0
            peak = 0.0

        log(f"[a] длительность={duration:.2f}s, RMS={rms:.4f}, peak={peak:.4f}")

        if rms < 0.003 and peak < 0.02:
            print("[·] Silence — skipping (guard against 'Thank you' hallucination)")
            return None

        return audio_f

    @property
    def level(self) -> float:
        return self._level

    @property
    def is_recording(self) -> bool:
        return self._recording


# ──────────────────────────────────────────────────────────────────────────────
# Транскрипция
# ──────────────────────────────────────────────────────────────────────────────


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


class MLXTranscriber:
    def __init__(self, model: str, language: Optional[str]):
        try:
            from mlx_whisper import transcribe  # type: ignore
        except ImportError as e:
            print("\n[!] pip install mlx-whisper\n", file=sys.stderr)
            raise SystemExit(1) from e
        self._transcribe = transcribe
        self.model = model
        # None = автоопределение
        self.language = language
        # язык последней транскрипции (детект Whisper) — нужен полировщику,
        # чтобы LLM не переводила текст, когда выбран режим Auto
        self.last_language: Optional[str] = None

    def transcribe(
        self,
        audio,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> str:
        """audio: float32-моно 16кГц numpy-массив или путь к WAV-файлу."""
        # язык можно переопределить на каждый запрос
        lang = language if language is not None else self.language
        kwargs = dict(
            path_or_hf_repo=self.model,
            word_timestamps=False,
            # НЕ подаём предыдущий текст как контекст: именно это на длинных
            # монологах с паузами срывает Whisper в петлю «только ли только ли…»
            condition_on_previous_text=False,
        )
        if lang:
            kwargs["language"] = lang
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        if isinstance(audio, str):
            audio = load_wav_16k(audio)
        result = self._transcribe(audio, **kwargs)
        # печатаем определённый язык в лог (полезно для дебага)
        detected = result.get("language")
        if detected and not lang:
            print(f"[i] language detected: {detected}")
        self.last_language = lang or detected
        return (result.get("text") or "").strip()

    def warm_up(self) -> None:
        """Прогоняем 0.5с тишины через модель: mlx_whisper грузит веса лениво,
        и без прогрева первая диктовка платит загрузку + компиляцию
        Metal-кернелов (ощущается как «зависло»). Best-effort, не кидает."""
        import numpy as np

        try:
            self.transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32), language="en")
        except Exception as e:
            print(f"[!] whisper warm-up failed: {e}", file=sys.stderr)


class FasterWhisperTranscriber:
    def __init__(self, model: str, language: Optional[str]):
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as e:
            print("\n[!] pip install faster-whisper\n", file=sys.stderr)
            raise SystemExit(1) from e
        self._model = WhisperModel(model, device="cpu", compute_type="int8")
        self.model = model
        self.language = language
        self.last_language: Optional[str] = None

    def transcribe(
        self,
        audio,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> str:
        """audio: float32-моно 16кГц numpy-массив или путь к WAV-файлу."""
        lang = language if language is not None else self.language
        segments, info = self._model.transcribe(
            audio,
            language=lang,  # None = auto-detect
            vad_filter=True,
            # greedy: для диктовки ~2x быстрее beam search при неотличимом
            # качестве на коротких фразах
            beam_size=1,
            # см. MLXTranscriber: гасит петли-повторы на длинных монологах
            condition_on_previous_text=False,
            initial_prompt=initial_prompt or None,
        )
        if info and not lang:
            print(f"[i] language detected: {info.language}")
        self.last_language = lang or (info.language if info else None)
        return " ".join(seg.text.strip() for seg in segments).strip()

    def warm_up(self) -> None:
        """Прогрев декодера на 0.5с тишины (веса уже загружены в __init__)."""
        import numpy as np

        try:
            self.transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32), language="en")
        except Exception as e:
            print(f"[!] whisper warm-up failed: {e}", file=sys.stderr)


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

        `language` and `initial_prompt` are accepted for interface parity.
        Parakeet auto-detects the language and supports no prompt biasing, so
        neither affects transcription; `language` is still recorded in
        `last_language` as a best-effort hint for the polisher. We feed a
        precomputed log-mel to `generate()` so we never hit parakeet-mlx's
        ffmpeg-based file path.
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
            self.transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32), language="en")
        except Exception as e:
            print(f"[!] parakeet warm-up failed: {e}", file=sys.stderr)


def transcriber_class_for(model_id: str, engine: str) -> type:
    """Pick the transcriber class by model id. A model id containing
    "parakeet" (case-insensitive) always routes to ParakeetTranscriber
    regardless of engine; otherwise the mlx/faster engine flag decides the
    Whisper backend."""
    if "parakeet" in model_id.lower():
        return ParakeetTranscriber
    return MLXTranscriber if engine == "mlx" else FasterWhisperTranscriber


# ──────────────────────────────────────────────────────────────────────────────
# Вставка
# ──────────────────────────────────────────────────────────────────────────────


def copy_to_clipboard(text: str) -> None:
    p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    p.communicate(text.encode("utf-8"))


def read_clipboard() -> str:
    try:
        return subprocess.check_output(["pbpaste"]).decode("utf-8", errors="ignore")
    except Exception:
        return ""


_PASTE_CODE = (
    "import Quartz\n"
    "d = Quartz.CGEventCreateKeyboardEvent(None, 9, True)\n"   # 'v' down
    "Quartz.CGEventSetFlags(d, Quartz.kCGEventFlagMaskCommand)\n"
    "Quartz.CGEventPost(Quartz.kCGHIDEventTap, d)\n"
    "u = Quartz.CGEventCreateKeyboardEvent(None, 9, False)\n"  # 'v' up
    "Quartz.CGEventSetFlags(u, Quartz.kCGEventFlagMaskCommand)\n"
    "Quartz.CGEventPost(Quartz.kCGHIDEventTap, u)\n"
)


def paste_via_cmd_v() -> None:
    """Эмулируем Cmd+V в ОТДЕЛЬНОМ подпроцессе через Quartz CGEvent.

    Почему так:
      • pynput.Controller в этом же процессе (рядом с активным слушателем и
        MLX/Metal) роняет приложение;
      • osascript→System Events в фоновом (launchd) процессе молча отклоняется,
        т.к. macOS не показывает запрос Automation фоновым процессам.
    Подпроцесс изолирован (не уронит app), а CGEvent требует только
    Accessibility — то же право, что и у хоткея. Automation не нужен.
    Подпроцесс — та же подписанная копия python, поэтому TCC-личность совпадает.
    """
    subprocess.run(
        [sys.executable, "-c", _PASTE_CODE],
        check=False,
    )


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
    passed as argv, text on stdin. Any failure/timeout -> "paste_fallback".
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


def deliver_text(
    text: str,
    do_paste: bool,
    restore_clipboard: bool,
    insert_mode: str = "paste",
    target_pid: "Optional[int]" = None,
) -> None:
    """
    0) В режиме insert_mode="ax" сначала пробуем прямую AX-вставку в поле
       (в исходное приложение по target_pid, если фокус ушёл). Успех — выходим,
       буфер не трогаем; history_only — уведомляем и выходим; paste_fallback —
       идём по пути 1–3 ниже.
    1) Кладём текст в буфер обмена и гарантируем, что он там остаётся.
       Можно в любой момент вставить Cmd+V вручную в любое поле.
    2) Опционально эмулируем Cmd+V, чтобы вставилось автоматически в активное окно.
    3) Восстанавливаем прежний буфер через 0.4с, если restore_clipboard=True ИЛИ
       insert_mode="ax" (в AX-режиме диктовка никогда не затирает буфер надолго).
    """
    if not text:
        return
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
    # In AX mode the paste fallback must not clobber the clipboard, so restore
    # regardless of the restore_clipboard flag. Plain paste mode is unchanged.
    restore = restore_clipboard or (insert_mode == "ax")
    previous = read_clipboard() if restore else None
    copy_to_clipboard(text)
    # подтверждаем что положилось
    placed = read_clipboard()
    if placed.strip() != text.strip():
        # некоторые приложения держат буфер — пробуем ещё раз через секунду
        time.sleep(0.1)
        copy_to_clipboard(text)
    if do_paste:
        time.sleep(0.05)
        paste_via_cmd_v()
    if restore and previous is not None:
        def _restore():
            time.sleep(0.4)
            copy_to_clipboard(previous)

        threading.Thread(target=_restore, daemon=True).start()


# ──────────────────────────────────────────────────────────────────────────────
# Хоткеи
# ──────────────────────────────────────────────────────────────────────────────


def parse_hotkey(name: str):
    keyboard = _require("pynput.keyboard", "pynput").keyboard  # type: ignore
    name = name.lower().strip()
    aliases = {
        "right_option": keyboard.Key.alt_r,
        "ralt": keyboard.Key.alt_r,
        "right_alt": keyboard.Key.alt_r,
        "left_option": keyboard.Key.alt_l,
        "lalt": keyboard.Key.alt_l,
        "left_alt": keyboard.Key.alt_l,
        "fn": getattr(keyboard.Key, "fn", None),
        "right_shift": keyboard.Key.shift_r,
        "left_shift": keyboard.Key.shift_l,
        "right_ctrl": keyboard.Key.ctrl_r,
        "left_ctrl": keyboard.Key.ctrl_l,
        "right_cmd": keyboard.Key.cmd_r,
        "left_cmd": keyboard.Key.cmd_l,
    }
    if name in aliases and aliases[name] is not None:
        return aliases[name]
    if name.startswith("f") and name[1:].isdigit():
        key = getattr(keyboard.Key, name, None)
        if key is not None:
            return key
    raise ValueError(f"Unknown hotkey: {name}")


def _hotkey_vk(key) -> Optional[int]:
    """Виртуальный keycode pynput-клавиши (Key.alt_r → 61) или None."""
    vk = getattr(key, "vk", None)
    if vk is None:
        vk = getattr(getattr(key, "value", None), "vk", None)
    return vk if isinstance(vk, int) else None


def _key_is_down(vk: int) -> Optional[bool]:
    """Физически ли клавиша нажата прямо сейчас (опрос HID через Quartz).

    Это независимый от event tap источник правды: даже если событие
    отпускания потерялось (secure input, отключённый tap), здесь видно
    реальное состояние. None = проверить не удалось.
    """
    try:
        from Quartz import (
            CGEventSourceKeyState,
            kCGEventSourceStateHIDSystemState,
        )

        return bool(CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, vk))
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Главное приложение: rumps menubar
# ──────────────────────────────────────────────────────────────────────────────


def ensure_accessibility(prompt: bool = True) -> bool:
    """Проверить (и при необходимости запросить) доступ к Accessibility.

    Хоткей через pynput использует Quartz event tap, которому нужен доступ
    в System Settings → Privacy & Security → Accessibility. При prompt=True
    macOS покажет диалог и добавит приложение в список — останется включить
    галочку. Возвращает True, если доступ уже выдан.
    """
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        opts = {kAXTrustedCheckOptionPrompt: bool(prompt)}
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception as e:  # pragma: no cover
        print(f"[!] Accessibility check failed: {e}", file=sys.stderr)
        return True  # не блокируем запуск


def apply_replacements(text: str, rules: "dict") -> str:
    """Replace user-defined terms in `text`: whole-word, case-insensitive,
    single pass. `rules` maps heard-form -> wanted-form. Output is the literal
    wanted value; a rule's output is never re-scanned by another rule.
    """
    if not text or not rules:
        return text
    # Longest keys first so multi-word phrases win over their prefixes.
    keys = [k for k in sorted(rules.keys(), key=len, reverse=True) if k]
    if not keys:
        return text
    lookup = {k.lower(): v for k, v in rules.items() if k}
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: lookup[m.group(0).lower()], text)


def polish_text_safe(polisher, text, mode, language, vocabulary):
    """Polish wrapper that can never raise — returns raw text on any failure."""
    try:
        return polisher.polish(text, mode, language=language, vocabulary=vocabulary)
    except Exception as e:
        print(f"[!] polish_text_safe: {e}", file=sys.stderr)
        return text


def run_app(args):
    rumps = _require("rumps")
    keyboard = _require("pynput.keyboard", "pynput").keyboard  # type: ignore

    # Запрашиваем доступ к Accessibility сразу — иначе хоткей молча не работает.
    if not ensure_accessibility(prompt=True):
        print(
            "[!] No Accessibility permission. Enable Voice Type in "
            "System Settings → Privacy & Security → Accessibility "
            "and relaunch the app.",
            file=sys.stderr,
        )

    recorder = Recorder()

    transcriber_holder: dict = {"obj": None, "loading": False}

    # текущая выбранная модель (меняется из меню, переживает перезапуск);
    # значение подставляется ниже после чтения конфига
    current_model = {"value": None}

    def get_transcriber():
        obj = transcriber_holder["obj"]
        # если модель совпадает с выбранной — отдаём как есть
        if obj is not None and getattr(obj, "model", None) == current_model["value"]:
            return obj
        # иначе нужна (пере)загрузка под текущую модель
        if transcriber_holder["loading"]:
            return None
        transcriber_holder["loading"] = True
        transcriber_holder["obj"] = None

        def _load():
            target = current_model["value"]
            try:
                # инициируем с None — язык подставляется на каждый запрос;
                # класс выбираем по id модели (parakeet → ParakeetTranscriber)
                cls = transcriber_class_for(target, args.engine)
                obj = cls(target, None)
                # Прогреваем ДО публикации: скачивание весов, загрузка и
                # компиляция Metal-кернелов происходят здесь, в фоне. Воркер
                # ждёт, пока loading=True, так что диктовка во время прогрева
                # просто дождётся готовой (уже быстрой) модели.
                t0 = time.time()
                obj.warm_up()
                # за время загрузки выбор мог снова поменяться — не перетираем
                if current_model["value"] == target:
                    transcriber_holder["obj"] = obj
                print(
                    f"[+] Model ready: {target.split('/')[-1]} "
                    f"(warm-up {time.time() - t0:.1f}s)"
                )
            except Exception as e:
                print(f"[!] Model load error: {e}", file=sys.stderr)
            finally:
                transcriber_holder["loading"] = False

        threading.Thread(target=_load, daemon=True).start()
        return None

    # очередь диктовок: float32-моно 16кГц numpy-массивы (None = стоп)
    jobs: "queue.Queue" = queue.Queue()
    # команды управления записью: "start" | "stop" | "abort" (стоп без текста)
    ctrl: "queue.Queue" = queue.Queue()
    enabled = {"value": True}
    state = {"value": "idle"}  # idle | recording | transcribing | done
    last_text = {"value": ""}
    # история диктовок: список в памяти + persist на диск; меню перестраивается
    # только из главного потока (AppKit) — воркер лишь поднимает флаг
    history_items = {"value": history.load()}
    menu_dirty = {"value": False}
    done_until = {"ts": 0.0}  # до какого момента показывать «✓ в буфере» в menubar
    # watchdog против «вечной записи»: vk хоткея, можно ли верить Quartz-опросу
    # (калибруется при каждом реальном нажатии), счётчик тиков «не нажата»,
    # и когда запрошен stop (для детекта зависшего PortAudio)
    watchdog = {"vk": None, "trusted": False, "misses": 0, "stop_at": None}

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
    # модель: явный CLI-флаг → конфиг (выбор из меню) → дефолт движка.
    # По умолчанию на Apple Silicon — Parakeet: ~10× быстрее Whisper при
    # сопоставимой точности на ru/uk/en. CPU-фоллбэк остаётся на large-v3.
    default_model = (
        "mlx-community/parakeet-tdt-0.6b-v3" if args.engine == "mlx" else "large-v3"
    )
    current_model["value"] = args.model or cfg["model"] or default_model
    smart_mode = {"value": cfg["smart_mode"]}
    insert_mode = {"value": cfg["insert_mode"]}
    # PID приложения, активного на старте диктовки (для «прилипания» AX-вставки).
    target_app = {"pid": None}
    vocabulary = {"value": list(cfg["vocabulary"])}
    polisher = polish.Polisher()

    def warm_polisher_async():
        """Фоновый прогрев LLM: без него первая clean/prompt-диктовка платит
        загрузку весов + компиляцию кернелов (несколько секунд)."""
        if smart_mode["value"] != "raw" and not polisher.is_loaded():
            threading.Thread(target=polisher.warm_up, daemon=True).start()

    def persist():
        # vocabulary is owned by the user via the config file (Edit vocabulary…),
        # not by the menu. Re-read it from disk so menu-driven saves never clobber
        # manual edits the user made in the file.
        on_disk = config.load()
        config.save(
            {
                "favorite_languages": favorites["value"],
                "active_language": current_lang["value"],
                "hotkey": current_hotkey["value"],
                "smart_mode": smart_mode["value"],
                "vocabulary": on_disk["vocabulary"],
                "model": current_model["value"],
                "insert_mode": insert_mode["value"],
            }
        )

    # модели для подменю «Model» (только для движка mlx).
    MLX_MODELS = [
        ("⚡ Parakeet v3 — fastest, default (RU/UK/EN)", "mlx-community/parakeet-tdt-0.6b-v3"),
        ("🎯 Large v3 — most accurate", "mlx-community/whisper-large-v3-mlx"),
        ("⚡ Turbo — faster decode, weaker RU/UK", "mlx-community/whisper-large-v3-turbo"),
        ("Medium — balanced", "mlx-community/whisper-medium-mlx"),
        ("Small — fastest", "mlx-community/whisper-small-mlx"),
    ]

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

    # пресеты для подменю «Smart» (режим LLM-прохода)
    SMART_PRESETS = [
        ("Raw — verbatim Whisper", "raw"),
        ("Clean — fix filler & punctuation", "clean"),
        ("Prompt — restructure for AI", "prompt"),
    ]

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
                    rumps.MenuItem(
                        f"Voice Type v{__version__} — releases…",
                        callback=self.open_releases,
                    ),
                    None,
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
                    self._history_menu(),
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
            items.append(
                rumps.MenuItem("Edit replacements…", callback=self.edit_replacements)
            )
            items.append(None)  # separator: delivery toggle is not a polish preset
            ax_item = rumps.MenuItem(
                "Insert via Accessibility (no clipboard)",
                callback=self._toggle_insert_mode,
            )
            ax_item.state = 1 if insert_mode["value"] == "ax" else 0
            items.append(ax_item)
            return ("Smart", items)

        def _history_menu(self):
            items = []
            for i, item in enumerate(
                history_items["value"][: history.MENU_ITEMS], start=1
            ):
                items.append(
                    rumps.MenuItem(
                        history.label(i, item),
                        callback=self._make_history_copier(item["text"]),
                    )
                )
            if not items:
                empty = rumps.MenuItem("No dictations yet")
                empty.set_callback(None)
                items.append(empty)
            items.append(None)
            items.append(
                rumps.MenuItem("Clear history…", callback=self.clear_history)
            )
            return ("History", items)

        def _make_history_copier(self, text):
            def copier(_):
                copy_to_clipboard(text)
                notify("Voice Type", "Copied from history — paste with Cmd+V")

            return copier

        def clear_history(self, _):
            history.clear()
            history_items["value"] = []
            self._build_menu()
            notify("Voice Type", "History cleared")

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
                persist()  # выбор модели переживает перезапуск
                name = repo.split("/")[-1]
                print(f"[i] Model set: {name}")
                # следующая диктовка подхватит новую модель (MLX грузит лениво)
                transcriber_holder["obj"] = None
                get_transcriber()
                self._build_menu()
                notify("Voice Type", f"Model → {name}")

            return setter

        def _make_smart_setter(self, mode):
            def setter(_):
                if mode == smart_mode["value"]:
                    return
                smart_mode["value"] = mode
                persist()
                self._build_menu()
                warm_polisher_async()
                print(f"[i] Smart mode set: {mode}")
                notify("Voice Type", f"Smart → {mode}")

            return setter

        def _toggle_insert_mode(self, _):
            insert_mode["value"] = "ax" if insert_mode["value"] == "paste" else "paste"
            persist()
            self._build_menu()
            print(f"[i] Insert mode: {insert_mode['value']}")

        def edit_vocabulary(self, _):
            # словарь правится прямо в конфиг-файле; открываем его в редакторе
            persist()  # на случай первого запуска — гарантируем, что файл есть
            subprocess.Popen(["open", config.config_path()])
            notify(
                "Voice Type",
                "Edit the \"vocabulary\" list in config.json — applies on your next dictation",
            )

        def edit_replacements(self, _):
            # словарь замен правится прямо в конфиг-файле; открываем его
            persist()  # на случай первого запуска — гарантируем, что файл есть
            subprocess.Popen(["open", config.config_path()])
            notify(
                "Voice Type",
                'Edit the "replacements" map in config.json — applies on your next dictation',
            )

        def _make_hotkey_setter(self, name):
            def setter(_):
                if name == current_hotkey["value"]:
                    return
                try:
                    new_key = parse_hotkey(name)
                except ValueError:
                    notify("Voice Type", f"Unsupported hotkey: {name}")
                    return
                # если прямо сейчас идёт запись на старой клавише — чисто
                # стопаем без транскрипции (через управляющий поток)
                with gesture_lock:
                    if gr.is_recording:
                        _cancel_pending_timer()
                        gr.mode = "idle"
                        ctrl.put("abort")
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
            self._watchdog_tick(now)
            # перестройка меню (новая запись в истории) — только здесь,
            # в главном потоке AppKit; воркер лишь поднимает флаг
            if menu_dirty["value"]:
                menu_dirty["value"] = False
                self._build_menu()
            if state["value"] == "recording":
                level = max(0.0, min(1.0, recorder.level * 6))
                n = max(1, int(level * 5))
                blink = "🔴" if int(now * 2) % 2 == 0 else "⭕"
                bars = f"{'▮' * n}{'▯' * (5 - n)}"
                # в hands-free клавиша свободна — помечаем ∞, чтобы было видно,
                # что запись идёт сама и её надо остановить тапом
                self.title = f"{blink}∞ {bars}" if gr.is_handsfree else f"{blink} {bars}"
            elif state["value"] == "transcribing":
                dots = "." * (int(now * 2) % 4)
                self.title = f"⏳ transcribing{dots}"
            elif now < done_until["ts"]:
                self.title = "✓ copied"
            else:
                self.title = "🎙" if enabled["value"] else "🚫"

        def _watchdog_tick(self, now):
            """Страховка от «вечной записи».

            1) Потерянное отпускание в push-to-talk: событие release может не
               дойти (secure input, отключённый event tap) — сверяем с
               физическим состоянием клавиши через Quartz и останавливаем
               сами. В hands-free клавиша отпущена легально — не трогаем.
            2) Зависший stop: если после запроса остановки PortAudio молчит
               дольше 5с — честно сообщаем в лог и чиним UI.
            """
            # 1) только в режиме удержания (ptt)
            if gr.mode == "ptt" and watchdog["trusted"]:
                if _key_is_down(watchdog["vk"]) is False:
                    watchdog["misses"] += 1
                    if watchdog["misses"] >= 3:  # ~0.9с подряд «не нажата»
                        log(
                            "[watchdog] hotkey released but no release event "
                            "arrived (lost by event tap?) — stopping recording"
                        )
                        _handle_release(now)
                else:
                    watchdog["misses"] = 0
            # 2) зависший recorder.stop
            if watchdog["stop_at"] is not None and now - watchdog["stop_at"] > 5.0:
                log(
                    "[watchdog] recorder.stop still running 5s after request — "
                    "PortAudio hung; restart the app if the mic stops responding"
                )
                watchdog["stop_at"] = None
                play_sound(SOUND_ERROR)
                state["value"] = "idle"

        def toggle_enabled(self, _):
            enabled["value"] = not enabled["value"]
            self._build_menu()

        def open_releases(self, _):
            # быстрый способ проверить, последняя ли версия установлена
            subprocess.Popen(["open", RELEASES_URL])

        def copy_last(self, _):
            if last_text["value"]:
                copy_to_clipboard(last_text["value"])
                notify("Voice Type", "Last text copied")
            else:
                notify("Voice Type", "Nothing transcribed yet")

        def quit_app(self, _):
            rumps.quit_application()

    # накопленные транскрипты чанков по сессиям: sid → [str, ...]
    session_parts: dict = {}

    def _wait_transcriber():
        tr = get_transcriber()
        # ждём, пока фоновый _load скачает/прогреет модель (без жёсткого
        # таймаута: первое скачивание может занять минуты)
        while tr is None and transcriber_holder["loading"]:
            time.sleep(0.1)
            tr = transcriber_holder["obj"]
        return tr

    def worker():
        while True:
            job = jobs.get()
            if job is None:
                return
            audio = job.get("audio")
            sid = job.get("sid")
            final = job.get("final", True)
            try:
                if final:
                    state["value"] = "transcribing"
                tr = _wait_transcriber()
                if tr is None:
                    play_sound(SOUND_ERROR)
                    notify("Voice Type", "Model not loaded")
                    session_parts.pop(sid, None)
                    continue

                # ── транскрипция куска (если он есть) ──────────────────────
                if audio is not None:
                    t0 = time.time()
                    vocabulary["value"] = config.load()["vocabulary"]
                    vocab_prompt = ", ".join(vocabulary["value"]) or None
                    text = tr.transcribe(
                        audio,
                        language=current_lang["value"],
                        initial_prompt=vocab_prompt,
                    )
                    dt = time.time() - t0
                    if text and is_hallucination(text):
                        print(f"[·] ({dt:.1f}s) hallucination, skipping: {text!r}")
                        text = ""
                    if text:
                        session_parts.setdefault(sid, []).append(text)
                        tag = "final" if final else "chunk"
                        log(f"[·] ({dt:.1f}s) {tag}: {text}")

                if not final:
                    continue  # промежуточный чанк — просто накопили, ждём дальше

                # ── финализация сессии: склейка + polish + доставка ───────
                parts = session_parts.pop(sid, [])
                full = streaming.join_parts(parts)
                if full and smart_mode["value"] != "raw":
                    if not polisher.is_loaded():
                        notify("Voice Type", "Загружаю LLM… (первый раз)")
                    t1 = time.time()
                    # при Auto берём язык, который определил Whisper, — без
                    # него маленькая LLM может перевести текст на английский
                    polish_lang = current_lang["value"] or tr.last_language
                    full = polish_text_safe(
                        polisher,
                        full,
                        smart_mode["value"],
                        polish_lang,
                        vocabulary["value"],
                    )
                    print(f"[i] polished ({smart_mode['value']}, {time.time() - t1:.1f}s)")

                # Детерминированные пользовательские замены (heard -> wanted),
                # перечитываем с диска ради мгновенного эффекта без рестарта.
                full = apply_replacements(full, config.load()["replacements"])

                if full:
                    log(f"[✓] copied: {full}")
                    last_text["value"] = full
                    history_items["value"] = history.add(full)
                    menu_dirty["value"] = True
                    play_sound(SOUND_DONE)
                    deliver_text(
                        full,
                        do_paste=not args.no_paste,
                        restore_clipboard=args.restore_clipboard,
                        insert_mode=insert_mode["value"],
                        target_pid=target_app["pid"],
                    )
                    done_until["ts"] = time.time() + 2.0
                    if args.notify:
                        preview = full if len(full) < 120 else full[:117] + "…"
                        notify("Voice Type", preview)
                else:
                    print("[·] Empty.")
            except Exception as e:
                play_sound(SOUND_ERROR)
                print(f"[!] {e}", file=sys.stderr)
                session_parts.pop(sid, None)
            finally:
                if final:
                    state["value"] = "idle"

    threading.Thread(target=worker, daemon=True).start()

    def _resolve_hotkey(name):
        try:
            return parse_hotkey(name)
        except ValueError:
            print(
                f"[!] unknown hotkey {name!r}; falling back to right_option",
                file=sys.stderr,
            )
            current_hotkey["value"] = "right_option"
            persist()  # вычистить битое значение из конфига
            return parse_hotkey("right_option")

    hotkey_obj_holder = {"key": _resolve_hotkey(current_hotkey["value"])}
    # распознаватель жестов (hold / double-tap / tap) и id текущей сессии.
    # gr дёргают три потока (клавиатура, pending-таймер, watchdog) — все
    # переходы под gesture_lock, чтобы состояние не разъехалось.
    gr = gestures.GestureRecognizer()
    gesture_lock = threading.Lock()
    session = {"id": 0, "active": False, "start_ts": 0.0}
    pending_timer = {"t": None}
    # авто-стоп hands-free-записи, если о ней забыли (страховка)
    MAX_SESSION_SEC = 300.0

    def control_loop():
        """Все операции с PortAudio — в одном фоновом потоке.

        Колбэки клавиш только кладут команду в очередь и мгновенно
        возвращаются (иначе «протухший» CoreAudio блокирует поток event tap,
        macOS его отключает, и отпускание клавиши теряется). Этот же поток
        периодически (по таймауту 0.5с) отрезает чанк уже сказанного и шлёт
        его на транскрипцию — так длинная диктовка переводится «под капотом»,
        пока вы говорите, и в конце ждать почти нечего.
        """
        while True:
            try:
                cmd = ctrl.get(timeout=0.5)
            except queue.Empty:
                cmd = None

            if cmd == "start":
                t0 = time.time()
                try:
                    recorder.start()
                    session["id"] += 1
                    session["active"] = True
                    session["start_ts"] = time.time()
                    target_app["pid"] = frontmost_app_pid()
                    dt = time.time() - t0
                    if dt > 0.5:
                        log(f"[rec] start took {dt:.2f}s (stale CoreAudio?)")
                except Exception as e:
                    log(f"[!] recorder.start failed ({time.time() - t0:.2f}s): {e}")
                    play_sound(SOUND_ERROR)
                    session["active"] = False
                    state["value"] = "idle"
            elif cmd in ("stop", "abort"):
                sid = session["id"]
                session["active"] = False
                t0 = time.time()
                rest = recorder.stop()
                dt = time.time() - t0
                watchdog["stop_at"] = None
                if dt > 1.0:
                    log(f"[!] recorder.stop took {dt:.2f}s (stale CoreAudio?)")
                if cmd == "stop":
                    # финальное задание всегда (даже если rest пуст) — worker
                    # склеит уже накопленные чанки и доставит текст
                    jobs.put({"audio": rest, "sid": sid, "final": True})
                else:  # abort — выбрасываем сессию без доставки
                    session_parts.pop(sid, None)
                    state["value"] = "idle"

            # пока идёт запись — пробуем отрезать готовый кусок в паузе
            if session["active"]:
                if time.time() - session["start_ts"] > MAX_SESSION_SEC:
                    log("[rec] hands-free session hit 5-min cap — auto-stopping")
                    ctrl.put("stop")
                    continue
                try:
                    chunk = recorder.take_chunk(
                        min_sec=streaming.CHUNK_SEC,
                        target_sec=streaming.CHUNK_SEC,
                        hard_max_sec=streaming.CHUNK_HARD_MAX_SEC,
                    )
                except Exception as e:
                    chunk = None
                    log(f"[!] take_chunk: {e}")
                if chunk is not None and not streaming.is_silent(chunk):
                    jobs.put(
                        {"audio": chunk, "sid": session["id"], "final": False}
                    )

    def _cancel_pending_timer():
        if pending_timer["t"] is not None:
            pending_timer["t"].cancel()
            pending_timer["t"] = None

    def _arm_pending_timer():
        _cancel_pending_timer()

        def _fire():
            with gesture_lock:
                _apply_actions(gr.on_timeout(time.time()), None)

        t = threading.Timer(gr.window, _fire)
        t.daemon = True
        pending_timer["t"] = t
        t.start()

    def _apply_actions(actions, key):
        for a in actions:
            if a == gestures.START:
                state["value"] = "recording"
                # калибровка watchdog: сразу после реального нажатия Quartz
                # обязан видеть клавишу нажатой — иначе опросу верить нельзя
                # (например, fn) и watchdog для этой клавиши отключается
                vk = _hotkey_vk(key) if key is not None else None
                watchdog["vk"] = vk
                watchdog["trusted"] = vk is not None and _key_is_down(vk) is True
                watchdog["misses"] = 0
                play_sound(SOUND_START)
                ctrl.put("start")
            elif a == gestures.FINALIZE:
                watchdog["stop_at"] = time.time()
                play_sound(SOUND_STOP)
                ctrl.put("stop")
            elif a == gestures.ARM_TIMER:
                _arm_pending_timer()
            elif a == gestures.DISARM_TIMER:
                _cancel_pending_timer()
                notify("Voice Type", "Hands-free — tap the key again to stop")

    def _handle_release(now):
        """Обработать отпускание хоткея (реальное или от watchdog)."""
        with gesture_lock:
            _apply_actions(gr.on_release(now), None)

    def on_press(key):
        try:
            if not enabled["value"]:
                return
            if key == hotkey_obj_holder["key"]:
                with gesture_lock:
                    _apply_actions(gr.on_press(time.time()), key)
        except Exception as e:
            log(f"[!] on_press: {e}")

    def on_release(key):
        try:
            if not enabled["value"]:
                return
            if key == hotkey_obj_holder["key"]:
                _handle_release(time.time())
        except Exception as e:
            log(f"[!] on_release: {e}")

    threading.Thread(target=control_loop, daemon=True).start()
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()

    get_transcriber()
    warm_polisher_async()

    print(
        f"[+] Voice Type v{__version__} started. Hotkey: {current_hotkey['value']}. "
        f"Model: {current_model['value']}"
    )
    print("[+] Look for the 🎙 icon in the menubar (top-right).")

    # Работаем как menubar-утилита (accessory): без иконки в Dock и без меню
    # приложения в строке меню. Иначе при запуске из .app процесс Python.app
    # регистрируется как обычное foreground-приложение, и статус-иконка
    # конфликтует с меню приложения (особенно на дисплеях с вырезом).
    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
        )

        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception as e:  # pragma: no cover - только на не-macOS / без pyobjc
        print(f"[!] Failed to enable accessory mode: {e}", file=sys.stderr)

    VoiceTypeApp().run()


def main():
    ap = argparse.ArgumentParser(
        description="Just Voice Type — local push-to-talk dictation with menubar UI."
    )
    ap.add_argument("--engine", choices=("mlx", "faster"), default="mlx")
    ap.add_argument("--model", default=None)
    ap.add_argument(
        "--lang",
        default="auto",
        help="Начальный язык: ru / uk / en / auto. Можно менять налету в menubar.",
    )
    ap.add_argument("--hotkey", default="right_option")
    ap.add_argument(
        "--no-paste",
        action="store_true",
        help="Не эмулировать Cmd+V — только класть в буфер обмена.",
    )
    ap.add_argument(
        "--restore-clipboard",
        action="store_true",
        help="Восстанавливать прежнее содержимое буфера через 0.4с после вставки. "
        "По умолчанию ВЫКЛЮЧЕНО — распознанный текст остаётся в буфере, и вы можете "
        "вставить его Cmd+V в любое окно когда угодно.",
    )
    # обратная совместимость со старым флагом:
    ap.add_argument("--no-restore-clipboard", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument(
        "--notify",
        action="store_true",
        help="Показывать macOS-уведомление с распознанным текстом.",
    )
    args = ap.parse_args()

    # args.model остаётся None, если флаг не передан: run_app подставит
    # модель из конфига (выбор в меню) или дефолтную large-v3
    run_app(args)


if __name__ == "__main__":
    main()
