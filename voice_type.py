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
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from typing import Optional

import config
import languages

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2

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


def play_sound(path: str) -> None:
    if not os.path.exists(path):
        return
    subprocess.Popen(
        ["afplay", "-v", "0.5", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


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
                print(f"[i] stream opened: sr={actual_sr}, ch={self._native_channels}")
                return True
            except Exception as e:
                tried.append(f"sr={sr},ch={ch}: {e}")
                continue
        print("[!] failed to open microphone: " + "; ".join(tried), file=sys.stderr)
        return False

    def start(self):
        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._recording = True
        # Пытаемся открыть; если не вышло — переинициализируем PortAudio и
        # пробуем ещё раз (это лечит «протухший» аудио-контекст без рестарта app).
        if self._try_open():
            return
        print("[i] reinitializing PortAudio and retrying...", file=sys.stderr)
        self._reinit_portaudio()
        if self._try_open():
            return
        self._recording = False
        raise RuntimeError("failed to open microphone even after PortAudio reinit")

    def stop(self) -> Optional[str]:
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if not self._frames:
            return None
        audio = self.np.concatenate(self._frames, axis=0)

        # если устройство дало стерео — миксуем в моно
        if audio.ndim == 2 and audio.shape[1] > 1:
            audio = audio.mean(axis=1).astype(self.np.int16)
        elif audio.ndim == 2:
            audio = audio[:, 0]

        # нативный sr (как реально пишет устройство)
        src_sr = self._native_sr or SAMPLE_RATE
        duration = len(audio) / src_sr
        if duration < 0.3:
            print("[·] Too short (<0.3s)")
            return None

        # простой ресемплинг до SAMPLE_RATE (16000) — линейная интерполяция
        if src_sr != SAMPLE_RATE:
            new_len = int(round(len(audio) * SAMPLE_RATE / src_sr))
            if new_len > 1:
                old_idx = self.np.linspace(0, len(audio) - 1, new_len)
                audio = self.np.interp(
                    old_idx, self.np.arange(len(audio)), audio
                ).astype(self.np.int16)

        # ── защита от «Thank you»-галлюцинации Whisper ────────────────────
        # Если в записи фактически только тишина — не отправляем на модель.
        # Используем RMS (среднеквадратичное значение) и пиковое значение.
        try:
            audio_f = audio.astype(self.np.float32) / 32768.0
            rms = float(self.np.sqrt(self.np.mean(audio_f * audio_f)))
            peak = float(self.np.max(self.np.abs(audio_f)))
        except Exception:
            rms = 0.0
            peak = 0.0

        print(
            f"[a] длительность={duration:.2f}s, RMS={rms:.4f}, peak={peak:.4f}"
        )

        # Эмпирические пороги: если и RMS<0.003 и peak<0.02 — это тишина
        # (даже самый тихий шёпот даёт RMS ~0.005, peak ~0.05).
        if rms < 0.003 and peak < 0.02:
            print("[·] Silence — skipping (guard against 'Thank you' hallucination)")
            return None

        path = os.path.join(
            tempfile.gettempdir(), f"voice_type_{int(time.time() * 1000)}.wav"
        )
        with wave.open(path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio.tobytes())
        return path

    @property
    def level(self) -> float:
        return self._level

    @property
    def is_recording(self) -> bool:
        return self._recording


# ──────────────────────────────────────────────────────────────────────────────
# Транскрипция
# ──────────────────────────────────────────────────────────────────────────────


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

    @staticmethod
    def _load_audio(wav_path: str):
        """Читаем WAV в float32-моно 16кГц БЕЗ ffmpeg.

        mlx_whisper.transcribe умеет принимать numpy-массив напрямую; так мы не
        зависим от внешнего ffmpeg (которого нет в PATH у .app) и остаёмся
        полностью офлайн/самодостаточными. Запись уже идёт в 16кГц, но на всякий
        случай ресемплим линейно, если sr отличается.
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

    def transcribe(self, wav_path: str, language: Optional[str] = None) -> str:
        # язык можно переопределить на каждый запрос
        lang = language if language is not None else self.language
        kwargs = dict(
            path_or_hf_repo=self.model,
            word_timestamps=False,
        )
        if lang:
            kwargs["language"] = lang
        audio = self._load_audio(wav_path)
        result = self._transcribe(audio, **kwargs)
        # печатаем определённый язык в лог (полезно для дебага)
        detected = result.get("language")
        if detected and not lang:
            print(f"[i] language detected: {detected}")
        return (result.get("text") or "").strip()


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

    def transcribe(self, wav_path: str, language: Optional[str] = None) -> str:
        lang = language if language is not None else self.language
        segments, info = self._model.transcribe(
            wav_path,
            language=lang,  # None = auto-detect
            vad_filter=True,
            beam_size=5,
        )
        if info and not lang:
            print(f"[i] language detected: {info.language}")
        return " ".join(seg.text.strip() for seg in segments).strip()


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


def deliver_text(text: str, do_paste: bool, restore_clipboard: bool) -> None:
    """
    1) Кладём текст в буфер обмена и гарантируем, что он там остаётся.
       Можно в любой момент вставить Cmd+V вручную в любое поле.
    2) Опционально эмулируем Cmd+V, чтобы вставилось автоматически в активное окно.
    3) Если restore_clipboard=True (по умолчанию выключено),
       через 0.4с возвращаем прежнее содержимое буфера.
    """
    if not text:
        return
    previous = read_clipboard() if restore_clipboard else None
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
    if restore_clipboard and previous is not None:
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

    # текущая выбранная модель (меняется из меню на лету)
    current_model = {"value": args.model}

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
                # инициируем с None — язык подставляется на каждый запрос.
                # Для MLX веса грузятся лениво (на первом transcribe), так что
                # конструктор почти мгновенный; для faster — модель грузится тут.
                if args.engine == "mlx":
                    obj = MLXTranscriber(target, None)
                else:
                    obj = FasterWhisperTranscriber(target, None)
                # за время загрузки выбор мог снова поменяться — не перетираем
                if current_model["value"] == target:
                    transcriber_holder["obj"] = obj
                print(f"[+] Model ready: {target.split('/')[-1]}")
            except Exception as e:
                print(f"[!] Model load error: {e}", file=sys.stderr)
            finally:
                transcriber_holder["loading"] = False

        threading.Thread(target=_load, daemon=True).start()
        return None

    jobs: "queue.Queue[str]" = queue.Queue()
    enabled = {"value": True}
    state = {"value": "idle"}  # idle | recording | transcribing | done
    last_text = {"value": ""}
    done_until = {"ts": 0.0}  # до какого момента показывать «✓ в буфере» в menubar

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

    # модели для подменю «Model» (только для движка mlx).
    # порядок = от быстрой/рекомендованной к более медленной/точной.
    MLX_MODELS = [
        ("⚡ Turbo — fast (recommended)", "mlx-community/whisper-large-v3-turbo"),
        ("🎯 Large v3 — most accurate", "mlx-community/whisper-large-v3-mlx"),
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

    def worker():
        while True:
            wav_path = jobs.get()
            if wav_path is None:
                return
            try:
                state["value"] = "transcribing"
                tr = get_transcriber()
                for _ in range(600):
                    if tr is not None:
                        break
                    time.sleep(0.1)
                    tr = transcriber_holder["obj"]
                if tr is None:
                    play_sound(SOUND_ERROR)
                    notify("Voice Type", "Model not loaded")
                    continue
                t0 = time.time()
                # передаём текущий выбранный язык (None = auto)
                text = tr.transcribe(wav_path, language=current_lang["value"])
                dt = time.time() - t0
                if text and is_hallucination(text):
                    print(f"[·] ({dt:.1f}s) Whisper hallucination, skipping: {text!r}")
                    text = ""
                if text:
                    print(f"[✓] ({dt:.1f}s) copied: {text}")
                    last_text["value"] = text
                    play_sound(SOUND_DONE)  # сигнал: распознано и в буфере
                    deliver_text(
                        text,
                        do_paste=not args.no_paste,
                        # по умолчанию буфер НЕ восстанавливается:
                        # распознанный текст остаётся доступен для Cmd+V вручную
                        restore_clipboard=args.restore_clipboard,
                    )
                    # показываем «✓ в буфере» в menubar 2 секунды
                    done_until["ts"] = time.time() + 2.0
                    if args.notify:
                        preview = text if len(text) < 120 else text[:117] + "…"
                        notify("Voice Type", preview)
                else:
                    print("[·] Empty.")
            except Exception as e:
                play_sound(SOUND_ERROR)
                print(f"[!] {e}", file=sys.stderr)
            finally:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
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
    is_down = {"v": False}

    def on_press(key):
        try:
            if not enabled["value"]:
                return
            if key == hotkey_obj_holder["key"] and not is_down["v"]:
                is_down["v"] = True
                state["value"] = "recording"
                play_sound(SOUND_START)
                recorder.start()
        except Exception as e:
            print(f"[!] on_press: {e}", file=sys.stderr)

    def on_release(key):
        try:
            if not enabled["value"]:
                return
            if key == hotkey_obj_holder["key"] and is_down["v"]:
                is_down["v"] = False
                play_sound(SOUND_STOP)
                wav = recorder.stop()
                if wav:
                    jobs.put(wav)
                else:
                    state["value"] = "idle"
                    print("[·] Too short.")
        except Exception as e:
            print(f"[!] on_release: {e}", file=sys.stderr)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()

    get_transcriber()

    print(
        f"[+] Voice Type started. Hotkey: {current_hotkey['value']}. "
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

    if args.model is None:
        args.model = (
            "mlx-community/whisper-large-v3-mlx" if args.engine == "mlx" else "large-v3"
        )

    run_app(args)


if __name__ == "__main__":
    main()
