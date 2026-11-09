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
import atexit
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

import call_health
import calls
import config
import gestures
import history
import languages
import live_typing
import mic_recovery
import polish
import streaming
import system_audio
import terms

# единственный источник правды о версии; бампается при каждом релизе
# (тег vX.Y.Z в git должен совпадать)
__version__ = "0.12.0"
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


# Сколько фоновых закрытий аудиопотока (Pa_AbortStream/Pa_CloseStream)
# сейчас в полёте на весь процесс — см. Recorder._close_stream_async и
# _drain_stream_teardowns_at_exit.
_stream_teardowns = {"count": 0}
_stream_teardowns_lock = threading.Lock()


def _drain_stream_teardowns_at_exit(timeout: float = 1.0, hard_exit=None) -> bool:
    """Дождаться фоновых закрытий аудиопотока перед выходом из процесса.

    Если дать интерпретатору финализироваться, пока фоновый поток сидит
    внутри Pa_CloseStream, процесс падает с SIGTRAP вместо тихого выхода —
    и пользователь видит «Voice Type quit unexpectedly» на обычном Quit.
    Обычное закрытие успевает за миллисекунды; залипшее не дождётся никогда,
    поэтому по таймауту выходим жёстко, минуя финализацию.

    True — всё закрылось штатно, False — пришлось выйти жёстко.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _stream_teardowns_lock:
            if _stream_teardowns["count"] == 0:
                return True
        time.sleep(0.02)
    with _stream_teardowns_lock:
        if _stream_teardowns["count"] == 0:
            return True
    sys.stdout.flush()
    sys.stderr.flush()
    (hard_exit or os._exit)(0)
    return False


_exit_drain_registered = {"done": False}


def _register_exit_drain() -> None:
    """Поставить дренаж на atexit — обязательно ПОСЛЕ импорта sounddevice.

    atexit разбирает обработчики в обратном порядке регистрации, а
    sounddevice ставит свой Pa_Terminate при импорте. Зарегистрируйся
    раньше него — и Pa_Terminate на выходе ляжет поверх ещё живого
    Pa_CloseStream в фоновом потоке, то есть SIGTRAP вместо тихого выхода.
    """
    if _exit_drain_registered["done"]:
        return
    _exit_drain_registered["done"] = True
    atexit.register(_drain_stream_teardowns_at_exit)


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
    # None = устройство по умолчанию (системный микрофон); иначе имя/индекс
    # устройства из sounddevice.query_devices() — используется Call Mode для
    # записи с Aggregate Device (свой микрофон + системный звук).
    device: "Optional[str | int]" = None
    # False = как раньше, режем канал до 1 (моно-микрофон). True = берём ВСЕ
    # каналы устройства — для Aggregate Device это даунмиксит микрофон и
    # системный звук в единую моно-дорожку в _to_mono_native.
    all_channels: bool = False

    def __post_init__(self):
        self.sd = _require("sounddevice")
        self.np = _require("numpy")
        _register_exit_drain()
        self._frames: list = []
        self._stream = None
        self._lock = threading.Lock()
        self._recording = False
        self._level: float = 0.0
        # сглаженные пиковые уровни ПО КАЖДОМУ каналу (до даунмикса) — чтобы
        # ловить отвал одного источника звонка (см. call_health.ChannelHealthMonitor)
        self._channel_levels: "list[float]" = []
        # монотонные часы (инъекция ради тестов) + метка последнего кадра из
        # callback — для детекта «зависшего» потока при смене аудио-устройства
        self._clock = time.monotonic
        self._last_frame_ts: Optional[float] = None
        # реальный sample rate микрофона (узнаём при первом старте)
        self._native_sr: Optional[int] = None
        self._native_channels: int = 1
        # аккумулятор снятых кадров в НАТИВНОМ sr (моно float [-1..1]) —
        # сюда сливаются сырые кадры при снятии чанка; отдельно от _frames,
        # чтобы не смешивать форматы (callback пишет int16, а хвост — float)
        self._carry = None
        # поколение стрима. Закрытие стрима может залипнуть в CoreAudio
        # навсегда (см. _close_stream_async), и его колбэк продолжает
        # тикать. Колбэк привязан к поколению — кадры брошенного стрима
        # не попадут в следующую диктовку.
        self._gen = 0
        # висящие abort/close: id → {phase, t0, reported}
        self._teardowns: dict = {}
        self._teardown_seq = 0
        self._teardown_lock = threading.Lock()

    def _make_callback(self, gen: int):
        """Колбэк, привязанный к поколению стрима.

        Если стрим уже брошен (его закрытие висит в CoreAudio), его кадры
        игнорируются: иначе «протухший» стрим досыпал бы чужой звук в уже
        начатую новую диктовку и портил индикатор уровня.
        """

        def _cb(indata, frames, time_info, status):
            if gen != self._gen:
                return
            self._callback(indata, frames, time_info, status)

        return _cb

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        # метка «кадры идут» — ставим всегда; пропажа кадров дольше порога
        # означает зависший/отвалившийся поток (см. seconds_since_last_frame)
        self._last_frame_ts = self._clock()
        try:
            peak = float(self.np.max(self.np.abs(indata))) / 32768.0
            self._level = self._level * 0.6 + peak * 0.4
            self._update_channel_levels(indata)
        except Exception:
            pass
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())

    def _update_channel_levels(self, indata):
        """EMA пикового уровня по каждому каналу (0..1). Число каналов берём из
        кадра; при смене раскладки просто переинициализируем аккумулятор."""
        arr = self.np.abs(indata.astype(self.np.float64))
        if arr.ndim == 2:
            peaks = arr.max(axis=0) / 32768.0
        else:
            peaks = self.np.array([arr.max() / 32768.0])
        n = len(peaks)
        if len(self._channel_levels) != n:
            self._channel_levels = [0.0] * n
        for i in range(n):
            self._channel_levels[i] = (
                self._channel_levels[i] * 0.6 + float(peaks[i]) * 0.4
            )

    @property
    def channel_levels(self) -> "list[float]":
        return list(self._channel_levels)

    def seconds_since_last_frame(self, now: "Optional[float]" = None) -> float:
        """Сколько прошло с последнего кадра из callback. inf — если кадров
        ещё не было. При живом потоке ~длина одного буфера; большое значение =
        поток встал (устройство пропало/сменилось)."""
        if self._last_frame_ts is None:
            return float("inf")
        if now is None:
            now = self._clock()
        return now - self._last_frame_ts

    def _detect_native_params(self):
        """Берём указанное (или дефолтное) входное устройство и его нативные
        параметры."""
        try:
            device = self.device if self.device is not None else self.sd.default.device[0]
            info = self.sd.query_devices(device)
            native_sr = int(info.get("default_samplerate", 48000))
            max_in = int(info.get("max_input_channels", 1))
            # all_channels=True (Call Mode): берём ВСЕ каналы устройства —
            # _to_mono_native их усреднит в одну дорожку. Иначе, как раньше,
            # режем до моно.
            channels = max_in if self.all_channels else (1 if max_in >= 1 else max_in)
            print(f"[i] device: {info['name']}, sr={native_sr}, ch={channels}")
            return native_sr, channels
        except Exception as e:
            print(f"[!] could not detect device parameters: {e}", file=sys.stderr)
            return 48000, 1

    def _close_stream_async(self, stream):
        """Закрыть стрим в отдельном потоке и не ждать его.

        Pa_AbortStream/Pa_CloseStream на CoreAudio умеют вставать намертво
        (смена аудио-устройства, выход из сна, занятый HAL-лок). Раньше это
        вешало control_loop: звук уже был снят с буфера, но stop() не
        возвращался — записанный текст терялся, и приложение больше не
        писало до перезапуска. Теперь блокирующая часть уезжает в фон:
        stop() отдаёт аудио сразу, а зависший поток висит сам по себе
        (лишний зомби-поток дешевле потерянной диктовки).
        """
        with self._teardown_lock:
            self._teardown_seq += 1
            tid = self._teardown_seq
            self._teardowns[tid] = {
                "phase": "abort", "t0": time.time(), "reported": False,
            }
        with _stream_teardowns_lock:
            _stream_teardowns["count"] += 1

        def _teardown():
            try:
                try:
                    stream.abort()
                except Exception:
                    pass
                with self._teardown_lock:
                    entry = self._teardowns.get(tid)
                    if entry is not None:
                        entry["phase"] = "close"
                        entry["t0"] = time.time()
                try:
                    stream.close()
                except Exception:
                    pass
            finally:
                with self._teardown_lock:
                    self._teardowns.pop(tid, None)
                with _stream_teardowns_lock:
                    _stream_teardowns["count"] -= 1

        threading.Thread(
            target=_teardown, daemon=True, name="audio-teardown"
        ).start()

    def _wait_teardowns(self, timeout: float) -> bool:
        """Подождать не дольше timeout, пока фоновые abort/close добьются
        своего. True — всё закрылось (значит PortAudio можно честно
        переинициализировать), False — что-то ещё висит."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._teardown_lock:
                if not self._teardowns:
                    return True
            time.sleep(0.02)
        with self._teardown_lock:
            return not self._teardowns

    def stuck_teardown(self, older_than: float = 5.0):
        """Самое долгое незакрытое abort/close старше older_than секунд —
        (phase, seconds) или None. Один и тот же случай отдаётся один раз,
        чтобы watchdog не спамил в лог."""
        now = time.time()
        with self._teardown_lock:
            for entry in self._teardowns.values():
                age = now - entry["t0"]
                if age > older_than and not entry["reported"]:
                    entry["reported"] = True
                    return entry["phase"], age
        return None

    def oldest_teardown_age(self, now: "Optional[float]" = None) -> "Optional[float]":
        """Сколько висит самое старое незакрытое abort/close (None — ничего
        не висит). В отличие от stuck_teardown не «съедает» разовый отчёт —
        это вход для решения о самоперезапуске (mic_recovery)."""
        if now is None:
            now = time.time()
        with self._teardown_lock:
            if not self._teardowns:
                return None
            return max(now - e["t0"] for e in self._teardowns.values())

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
            stream, self._stream = self._stream, None
            self._gen += 1
            self._close_stream_async(stream)
        # Pa_Terminate поверх висящего Pa_CloseStream — это краш процесса,
        # поэтому пока закрытие в полёте, ограничиваемся сбросом кэша
        # устройства.
        with self._teardown_lock:
            pending = bool(self._teardowns)
        if pending:
            log(
                "[audio] PortAudio reinit skipped — stream teardown still in "
                "flight (CoreAudio hung)",
                err=True,
            )
        else:
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
        fallback_ch = self._native_channels if self.all_channels else 1
        self._gen += 1
        gen = self._gen
        tried = []
        for sr, ch in [
            (self._native_sr, self._native_channels),
            (16000, fallback_ch),
            (44100, fallback_ch),
            (None, None),  # пусть PortAudio сам решит
        ]:
            stream = None
            try:
                kwargs = {"dtype": "int16", "callback": self._make_callback(gen)}
                if sr is not None:
                    kwargs["samplerate"] = sr
                if ch is not None:
                    kwargs["channels"] = ch
                if self.device is not None:
                    kwargs["device"] = self.device
                stream = self.sd.InputStream(**kwargs)
                stream.start()
                self._stream = stream
                actual_sr = int(stream.samplerate)
                self._native_sr = actual_sr
                if stream.channels:
                    self._native_channels = int(stream.channels)
                log(f"[i] stream opened: sr={actual_sr}, ch={self._native_channels}")
                return True
            except Exception as e:
                # стрим мог успеть открыться и упасть на start() — такой
                # брошенный audio unit как раз и «протухает» со временем
                if stream is not None:
                    self._close_stream_async(stream)
                tried.append(f"sr={sr},ch={ch}: {e}")
                continue
        log("[!] failed to open microphone: " + "; ".join(tried), err=True)
        return False

    def restart_stream(self) -> bool:
        """Переоткрыть поток на ТОМ ЖЕ устройстве, не теряя накопленный хвост
        (_carry) — авто-восстановление звонка при смене аудио-маршрутизации
        (наушники) или «протухшем» CoreAudio, без остановки записи.

        Возвращает True, если поток снова открыт. `_carry` и файл транскрипта
        не трогаем — потеряется лишь короткий фрагмент, пока поток был закрыт.
        """
        with self._lock:
            stream = self._stream
            self._stream = None
            # запись продолжается, поэтому брошенный стрим надо заглушить
            # немедленно: иначе его колбэк досыпал бы звук в звонок
            self._gen += 1
        if stream is not None:
            # закрываем в фоне: именно здесь CoreAudio и залипает — при
            # смене маршрутизации, ради которой мы и переоткрываемся
            self._close_stream_async(stream)
            # но обычному, быстрому закрытию даём чуть-чуть времени: тогда
            # _reinit_portaudio отработает полностью, а не пропустит
            # Pa_Terminate из-за ещё живого фонового потока
            self._wait_teardowns(1.5)
        self._reinit_portaudio()
        ok = self._try_open()
        if ok:
            # свежий отсчёт, чтобы детектор «стойла» не сработал повторно до
            # первого кадра нового потока
            self._last_frame_ts = self._clock()
        return ok

    def start(self):
        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._carry = None
            self._recording = True
            # базовый отсчёт «стойла»: если после старта кадры так и не пойдут
            # в течение CALL_STALL_SEC — это реальный сбой, а не то, что мы
            # спросили слишком рано
            self._last_frame_ts = self._clock()
        # Пытаемся открыть; если не вышло — переинициализируем PortAudio и
        # пробуем ещё раз (это лечит «протухший» аудио-контекст без рестарта app).
        if self._try_open():
            return
        log("[i] reinitializing PortAudio and retrying...", err=True)
        self._reinit_portaudio()
        if self._try_open():
            return
        self._recording = False
        with self._teardown_lock:
            pending = bool(self._teardowns)
        if pending:
            raise RuntimeError(
                "microphone busy: CoreAudio is still tearing down the previous "
                "stream — restart Voice Type if this repeats"
            )
        raise RuntimeError("failed to open microphone even after PortAudio reinit")

    def _to_mono_native(self, raw):
        """Сырые кадры (int16, моно/стерео) → float [-1..1] моно, нативный sr."""
        if raw.ndim == 2 and raw.shape[1] > 1:
            raw = raw.mean(axis=1)
        elif raw.ndim == 2:
            raw = raw[:, 0]
        return raw.astype(self.np.float32) / 32768.0

    def _resample_16k(self, audio_native):
        """float-моно нативный sr → float32-моно 16кГц (общий хелпер streaming)."""
        return streaming.resample_to_16k(audio_native, self._native_sr or SAMPLE_RATE)

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

    def drain_16k(self):
        """Слить весь накопленный звук как float32-моно 16кГц и очистить буфер.
        Для микса с системным звуком (CombinedCallCapture) — сырой слив без
        поиска тихой точки; резку на чанки делает объединённый поток."""
        with self._lock:
            if not self._recording:
                return self.np.empty(0, dtype=self.np.float32)
            self._drain_frames_locked()
            carry = self._carry
            self._carry = None
        if carry is None or len(carry) == 0:
            return self.np.empty(0, dtype=self.np.float32)
        return self._resample_16k(carry)

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
            # Аудио уже снято с буфера выше, так что закрытие стрима нам
            # больше не нужно синхронно — а зависнуть в CoreAudio оно может
            # навсегда. Отдаём его фоновому потоку и возвращаем текст.
            stream, self._stream = self._stream, None
            self._gen += 1  # колбэк брошенного стрима больше не пишет
            self._close_stream_async(stream)
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


# ──────────────────────────────────────────────────────────────────────────────
# Память MLX
# ──────────────────────────────────────────────────────────────────────────────
# MLX не отдаёт освобождённые Metal-буферы системе, а держит их в кэше, лимит
# которого по умолчанию — «recommended working set» устройства (на этой машине
# ~23 ГБ). Кэш заводит отдельную запись под каждый новый размер буфера и никогда
# не сжимается, поэтому за день диктовок footprint процесса уползает в десятки
# гигабайт при ~1.2 ГБ реально живых весов. Замер на одном и том же пути
# (24 чанка 3–30 с, parakeet-v3): без лимита — 5250 МБ и медиана 129 мс,
# с лимитом + чисткой на простое — 1607 МБ и медиана 128 мс. То есть память
# втрое меньше, а на скорость распознавания это не влияет.
MLX_CACHE_LIMIT_BYTES = 256 * 1024 * 1024

# probed=False — mlx.core ещё не пробовали импортировать; дальше mx или None.
_mlx_holder: dict = {"probed": False, "mx": None}


def _mlx():
    """mlx.core или None, если MLX не установлен (faster-whisper-сборка).
    Результат кэшируем — trim_mlx_cache зовут после каждой работы воркера."""
    if not _mlx_holder["probed"]:
        try:
            import mlx.core as mx  # type: ignore
        except ImportError:
            mx = None
        _mlx_holder["mx"] = mx
        _mlx_holder["probed"] = True
    return _mlx_holder["mx"]


def limit_mlx_cache(limit_bytes: int = MLX_CACHE_LIMIT_BYTES) -> None:
    """Ограничить кэш буферов MLX. Best-effort, наверх не бросает."""
    mx = _mlx()
    if mx is None:
        return
    try:
        mx.set_cache_limit(limit_bytes)
    except Exception as e:
        print(f"[!] mlx set_cache_limit failed: {e}", file=sys.stderr)


def trim_mlx_cache() -> None:
    """Вернуть кэшированные Metal-буферы системе. Зовём на простое воркера —
    между диктовками кэш не нужен, а footprint падает на гигабайты."""
    mx = _mlx()
    if mx is None:
        return
    try:
        mx.clear_cache()
    except Exception as e:
        print(f"[!] mlx clear_cache failed: {e}", file=sys.stderr)


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

    def transcribe_words(self, audio):
        """Тот же полный проход, но слова со временем начала/конца — для
        печати по ходу речи (live_typing.LiveSession)."""
        import mlx.core as mx  # type: ignore
        from parakeet_mlx.audio import get_logmel  # type: ignore

        mel = get_logmel(mx.array(audio), self._model.preprocessor_config)
        results = self._model.generate(mel)
        return live_typing.words_from_tokens(results[0].tokens if results else [], 0.0)

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


# Печатальщик для live typing: символы уходят как нажатия клавиш (unicode-
# строка в CGEvent), по символу на событие — так их принимают и Electron, и
# терминал. Источник событий «приватный», флаги обнулены: иначе зажатый
# хоткей (Right Option) примешивался бы к печатаемому — в терминале с
# «Option as Meta» это escape-последовательности вместо букв.
_TYPE_CODE = (
    "import json, sys, time\n"
    "import Quartz\n"
    "src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStatePrivate)\n"
    "def post(text):\n"
    "    for ch in text:\n"
    "        n = len(ch.encode('utf-16-le')) // 2\n"
    "        for down in (True, False):\n"
    "            e = Quartz.CGEventCreateKeyboardEvent(src, 0, down)\n"
    "            Quartz.CGEventKeyboardSetUnicodeString(e, n, ch)\n"
    "            Quartz.CGEventSetFlags(e, 0)\n"
    "            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)\n"
    "        time.sleep(0.002)\n"
    "for line in sys.stdin:\n"
    "    try:\n"
    "        post(json.loads(line))\n"
    "    except Exception as ex:\n"
    "        print(f'[typer] {ex}', file=sys.stderr, flush=True)\n"
)


class KeyTyper:
    """Долгоживущий подпроцесс, печатающий текст в активное поле.

    Отдельный процесс — по той же причине, что и paste_via_cmd_v (синтез
    событий рядом со слушателем клавиш и MLX роняет приложение), а
    долгоживущий — потому что при печати по ходу речи текст приходит
    кусками каждые полсекунды, и запускать python на каждый кусок дорого.
    Тот же подписанный python → та же TCC-личность (Accessibility).
    """

    def __init__(self, spawn=None):
        self._spawn = spawn or self._default_spawn
        self._proc = None
        self._lock = threading.Lock()

    @staticmethod
    def _default_spawn():
        return subprocess.Popen(
            [sys.executable, "-c", _TYPE_CODE],
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def type_text(self, text: str) -> bool:
        """Отправить текст на печать. False — печатальщик не запускается."""
        if not text:
            return True
        # перевод строки в чате = «отправить»: никогда не печатаем его
        line = json.dumps(text.replace("\n", " "), ensure_ascii=False) + "\n"
        with self._lock:
            for _ in range(2):  # один перезапуск, если процесс умер
                try:
                    if self._proc is None or self._proc.poll() is not None:
                        self._proc = self._spawn()
                    self._proc.stdin.write(line)
                    self._proc.stdin.flush()
                    return True
                except (OSError, ValueError):
                    self._proc = None
            return False


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
    Declined forms of a dictionary-form key are matched too (see terms.py).
    """
    return terms.apply(text, rules)


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

    # err.log однажды разросся до 145 МБ из-за ошибки в watchdog — держим
    # логи в разумных пределах (последние 2 МБ, если файл больше 20 МБ)
    mic_recovery.trim_app_logs()
    if os.environ.get(mic_recovery.ENV_KEY):
        log(f"[recovery] relaunch history: {os.environ[mic_recovery.ENV_KEY]}")

    # Запрашиваем доступ к Accessibility сразу — иначе хоткей молча не работает.
    if not ensure_accessibility(prompt=True):
        print(
            "[!] No Accessibility permission. Enable Voice Type in "
            "System Settings → Privacy & Security → Accessibility "
            "and relaunch the app.",
            file=sys.stderr,
        )

    recorder = Recorder()

    # до загрузки любых моделей: не даём MLX копить Metal-буферы гигабайтами
    limit_mlx_cache()

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
    calls_items = {"value": calls.load()}
    menu_dirty = {"value": False}
    done_until = {"ts": 0.0}  # до какого момента показывать «✓ в буфере» в menubar
    # watchdog против «вечной записи»: vk хоткея, можно ли верить Quartz-опросу
    # (калибруется при каждом реальном нажатии), счётчик тиков «не нажата»,
    # и когда запрошен stop (для детекта зависшего PortAudio)
    # start_at — когда control_loop начал открывать микрофон (None — не
    # открывает): зависшее открытие = мёртвый CoreAudio, см. mic_recovery
    watchdog = {
        "vk": None, "trusted": False, "misses": 0, "stop_at": None,
        "start_at": None,
    }
    # воркер распознаёт/доставляет текст — самоперезапуск его не прерывает
    worker_busy = {"value": False}
    # бюджет самоперезапусков исчерпан — больше не пытаемся, только сообщаем
    recovery = {"gave_up": False}
    # ошибки watchdog логируем по одному разу — иначе 3 строки в секунду
    watchdog_errors: set = set()

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
    current_call_hotkey = {"value": cfg["call_hotkey"]}
    current_call_device = {"value": cfg["call_device"]}
    current_auto_sysaudio = {"value": cfg["auto_system_audio"]}
    # модель: явный CLI-флаг → конфиг (выбор из меню) → дефолт движка.
    # По умолчанию на Apple Silicon — Parakeet: ~10× быстрее Whisper при
    # сопоставимой точности на ru/uk/en. CPU-фоллбэк остаётся на large-v3.
    default_model = (
        "mlx-community/parakeet-tdt-0.6b-v3" if args.engine == "mlx" else "large-v3"
    )
    current_model["value"] = args.model or cfg["model"] or default_model
    smart_mode = {"value": cfg["smart_mode"]}
    insert_mode = {"value": cfg["insert_mode"]}
    # печать по ходу речи (см. live_typing) и её подпроцесс-печатальщик
    live_typing_on = {"value": cfg["live_typing"]}
    typer = KeyTyper()
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
        # Меню сохраняет только свои настройки поверх файла: словарь замен,
        # vocabulary и всё, что правили руками, остаются как есть. (Раньше
        # сюда писался неполный конфиг — и смена хоткея стирала словарь.)
        config.update(
            favorite_languages=favorites["value"],
            active_language=current_lang["value"],
            hotkey=current_hotkey["value"],
            smart_mode=smart_mode["value"],
            model=current_model["value"],
            insert_mode=insert_mode["value"],
            call_hotkey=current_call_hotkey["value"],
            call_device=current_call_device["value"],
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
                    rumps.MenuItem("Добавить термин…", callback=self.add_term),
                    self._history_menu(),
                    None,
                    rumps.MenuItem(
                        "■ Stop Call Recording"
                        if call_session["active"]
                        else "Start Call Recording",
                        callback=self.toggle_call,
                    ),
                    self._call_hotkey_menu(),
                    self._auto_sysaudio_item(),
                    self._call_device_menu(),
                    self._calls_menu(),
                    None,
                    rumps.MenuItem("Quit", callback=self.quit_app),
                ]
            )

        def _auto_sysaudio_item(self):
            """Чек-пункт «Авто-захват системного звука». Активен только если
            система поддерживает process tap (macOS 14.4+ и хелпер на месте)."""
            supported = system_audio.is_supported()
            it = rumps.MenuItem(
                "Авто-захват системного звука",
                callback=self.toggle_auto_sysaudio if supported else None,
            )
            it.state = 1 if (supported and current_auto_sysaudio["value"]) else 0
            return it

        def toggle_auto_sysaudio(self, sender):
            current_auto_sysaudio["value"] = not current_auto_sysaudio["value"]
            sender.state = 1 if current_auto_sysaudio["value"] else 0
            c = config.load()
            c["auto_system_audio"] = current_auto_sysaudio["value"]
            config.save(c)
            state_txt = "включён" if current_auto_sysaudio["value"] else "выключен"
            print(f"[i] Auto system-audio: {current_auto_sysaudio['value']}")
            notify("Voice Type", f"Авто-захват системного звука {state_txt}")

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
            live_item = rumps.MenuItem(
                "Печатать по ходу речи (Parakeet, Raw)",
                callback=self._toggle_live_typing,
            )
            live_item.state = 1 if live_typing_on["value"] else 0
            items.append(live_item)
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

        def _toggle_live_typing(self, _):
            live_typing_on["value"] = not live_typing_on["value"]
            config.update(live_typing=live_typing_on["value"])
            self._build_menu()
            on = live_typing_on["value"]
            log(f"[i] Live typing: {on}")
            notify(
                "Voice Type",
                "Печать по ходу речи включена (Parakeet + Raw)"
                if on
                else "Печать по ходу речи выключена — текст вставляется в конце",
            )

        def edit_vocabulary(self, _):
            # словарь правится прямо в конфиг-файле; открываем его в редакторе
            persist()  # на случай первого запуска — гарантируем, что файл есть
            subprocess.Popen(["open", config.config_path()])
            notify(
                "Voice Type",
                "Edit the \"vocabulary\" list in config.json — applies on your next dictation",
            )

        def add_term(self, _):
            """Окно «как распознаётся = как писать» → правило в словарь
            замен; работает со следующей диктовки, склонения ловятся сами."""
            try:
                from AppKit import NSApplication

                # accessory-приложение не выходит на передний план само —
                # без этого окно ввода открывается за другими окнами
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except Exception:
                pass
            resp = rumps.Window(
                message=(
                    "Как слово распознаётся = как его писать.\n"
                    "Примеры:  фигма = Figma    хавар = ховер\n"
                    "Склонения (фигме, хавару) подхватятся сами."
                ),
                title="Добавить термин",
                default_text="",
                ok="Добавить",
                cancel="Отмена",
                dimensions=(320, 24),
            ).run()
            if not resp.clicked:
                return
            parsed = terms.parse_input(resp.text)
            if parsed is None:
                notify("Voice Type", "Не понял. Формат: как слышится = как писать")
                return
            heard, wanted = parsed
            reps = dict(config.load()["replacements"])
            reps[heard] = wanted
            config.update(replacements=reps)
            log(f"[terms] added: {heard} → {wanted}")
            notify("Voice Type", f"Термин добавлен: {heard} → {wanted}")

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
                if name == current_call_hotkey["value"]:
                    notify("Voice Type", f"{name} is already the Call Hotkey")
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

        def _call_hotkey_menu(self):
            items = []
            for preset in HOTKEY_PRESETS:
                if preset is None:
                    items.append(None)
                    continue
                label, name = preset
                it = rumps.MenuItem(label, callback=self._make_call_hotkey_setter(name))
                it.state = 1 if name == current_call_hotkey["value"] else 0
                items.append(it)
            return ("Call Hotkey", items)

        def _make_call_hotkey_setter(self, name):
            def setter(_):
                if name == current_call_hotkey["value"]:
                    return
                if name == current_hotkey["value"]:
                    notify("Voice Type", f"{name} is already the dictation Hotkey")
                    return
                try:
                    new_key = parse_hotkey(name)
                except ValueError:
                    notify("Voice Type", f"Unsupported hotkey: {name}")
                    return
                # если звонок прямо сейчас пишется — аккуратно завершаем его
                # с доставкой транскрипта, а не бросаем подвешенным на
                # старой клавише
                if call_session["active"]:
                    ctrl.put("call_stop")
                current_call_hotkey["value"] = name
                call_hotkey_obj_holder["key"] = new_key
                persist()
                self._build_menu()
                print(f"[i] Call hotkey set: {name}")
                notify("Voice Type", f"Call Hotkey → {name}")

            return setter

        def _call_device_menu(self):
            items = []
            try:
                devices = recorder.sd.query_devices()
            except Exception as e:
                log(f"[!] could not list devices: {e}")
                devices = []
            names_seen = set()
            for info in devices:
                if int(info.get("max_input_channels", 0)) <= 0:
                    continue
                name = info["name"]
                if name in names_seen:
                    continue
                names_seen.add(name)
                it = rumps.MenuItem(name, callback=self._make_call_device_setter(name))
                it.state = 1 if name == current_call_device["value"] else 0
                items.append(it)
            configured = current_call_device["value"]
            if configured and configured not in names_seen:
                warn = rumps.MenuItem(f"⚠️ {configured} (not connected)")
                warn.set_callback(None)
                items.insert(0, warn)
                items.insert(1, None)
            if not items:
                empty = rumps.MenuItem("No input devices found")
                empty.set_callback(None)
                items.append(empty)
            return ("Call Device", items)

        def _make_call_device_setter(self, name):
            def setter(_):
                current_call_device["value"] = name
                persist()
                self._build_menu()
                print(f"[i] Call device set: {name}")
                notify("Voice Type", f"Call Device → {name}")

            return setter

        def _calls_menu(self):
            items = []
            for i, item in enumerate(calls_items["value"][: calls.MENU_ITEMS], start=1):
                items.append(
                    rumps.MenuItem(
                        calls.label(i, item),
                        callback=self._make_call_copier(item["path"]),
                    )
                )
            if not items:
                empty = rumps.MenuItem("No calls recorded yet")
                empty.set_callback(None)
                items.append(empty)
            items.append(None)
            items.append(
                rumps.MenuItem("Open Calls folder…", callback=self.open_calls_folder)
            )
            items.append(
                rumps.MenuItem("Clear calls list…", callback=self.clear_calls)
            )
            return ("Calls", items)

        def _make_call_copier(self, path):
            def copier(_):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                except OSError as e:
                    notify("Voice Type", f"Could not read transcript: {e}")
                    return
                copy_to_clipboard(text)
                notify("Voice Type", "Copied call transcript — paste with Cmd+V")

            return copier

        def open_calls_folder(self, _):
            os.makedirs(calls.calls_dir(), exist_ok=True)
            subprocess.Popen(["open", calls.calls_dir()])

        def clear_calls(self, _):
            calls.clear()
            calls_items["value"] = []
            self._build_menu()
            notify("Voice Type", "Calls list cleared (files kept on disk)")

        def toggle_call(self, _):
            if call_session["active"]:
                ctrl.put("call_stop")
            elif session["active"]:
                notify("Voice Type", "Диктовка идёт — сначала остановите её")
            else:
                call_session["active"] = True
                ctrl.put("call_start")

        # ── статус-иконка и действия ────────────────────────────────────────
        def _on_tick(self, _):
            now = time.time()
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
            if call_state["value"] == "recording":
                elapsed = int(now - call_session["start_ts"])
                blink = "🔴" if int(now * 2) % 2 == 0 else "⭕"
                self.title = f"📞{blink} {elapsed // 60:02d}:{elapsed % 60:02d}"
            elif call_state["value"] == "transcribing":
                dots = "." * (int(now * 2) % 4)
                self.title = f"📞⏳{dots}"
            elif state["value"] == "recording":
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
            3) Зависшее закрытие стрима: сама диктовка уже доставлена
               (stop() больше не ждёт CoreAudio), но микрофон может не
               открыться на следующей записи — пишем в лог, что именно
               залипло.
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
            # 3) залипшее закрытие стрима в фоне
            recs = [
                r for r in (recorder, call_recorder_holder["obj"]) if r is not None
            ]
            for rec in recs:
                stuck = rec.stuck_teardown(5.0)
                if stuck is not None:
                    phase, age = stuck
                    log(
                        f"[audio] stream.{phase}() hung for {age:.0f}s in "
                        "CoreAudio — dictation was delivered, but the mic may "
                        "fail to open until the audio subsystem recovers",
                        err=True,
                    )
            # 4) самоперезапуск: зависшее открытие микрофона или давно
            #    залипшее закрытие — изнутри процесса CoreAudio уже не
            #    оживить, а свежий процесс получает чистый аудио-контекст
            if recovery["gave_up"]:
                return
            ages = [rec.oldest_teardown_age(now) for rec in recs]
            ages = [a for a in ages if a is not None]
            idle = (
                not session["active"]
                and not call_session["active"]
                and call_state["value"] == "idle"
                and state["value"] not in ("recording", "transcribing")
                and not worker_busy["value"]
                and jobs.empty()
            )
            reason = mic_recovery.relaunch_reason(
                now,
                start_since=watchdog["start_at"],
                teardown_age=max(ages) if ages else None,
                idle=idle,
            )
            # недоставленный текст важнее: ждём, пока воркер закончит
            if reason is None or worker_busy["value"]:
                return
            log(f"[recovery] {reason} — CoreAudio wedged, relaunching Voice Type", err=True)
            play_sound(SOUND_ERROR)
            notify("Voice Type", "Микрофон завис в CoreAudio — перезапускаю Voice Type")
            if not mic_recovery.relaunch(reason):
                recovery["gave_up"] = True
                log(
                    "[recovery] relaunch budget exhausted — CoreAudio stays "
                    "wedged across restarts",
                    err=True,
                )
                notify(
                    "Voice Type",
                    "Аудиосистема macOS не отвечает даже после перезапусков. "
                    "Перезагрузите Mac (или: sudo killall coreaudiod)",
                )

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
    # звонки: sid -> [(ts_sec, текст)] — реплики обеих дорожек, хронология
    # восстанавливается сортировкой при финализации (calls.assemble)
    call_lines: dict = {}

    def _wait_transcriber():
        tr = get_transcriber()
        # ждём, пока фоновый _load скачает/прогреет модель (без жёсткого
        # таймаута: первое скачивание может занять минуты)
        while tr is None and transcriber_holder["loading"]:
            time.sleep(0.1)
            tr = transcriber_holder["obj"]
        return tr

    # печать по ходу речи: sid → LiveSession (одна активная за раз)
    live_sessions: dict = {}

    def _live_typing_enabled():
        """Печатать ли эту диктовку по ходу речи. Нужны: включённый пункт
        меню, Raw (Clean/Prompt переписывают весь текст — по кускам нельзя),
        автовставка и модель со временем слов (Parakeet), уже загруженная."""
        tr = transcriber_holder["obj"]
        return bool(
            live_typing_on["value"]
            and smart_mode["value"] == "raw"
            and not args.no_paste
            and tr is not None
            and hasattr(tr, "transcribe_words")
        )

    def _handle_live_job(job):
        sid = job.get("sid")
        tr = _wait_transcriber()
        if tr is None:
            raise RuntimeError("model not loaded")
        sess = live_sessions.get(sid)
        if sess is None:
            live_sessions.clear()  # брошенные (abort) сессии не копим
            pid = target_app["pid"]

            def emit(text):
                # окно сменилось — дальше не печатаем: текст уйдёт в историю
                front = frontmost_app_pid()
                if pid is not None and front is not None and front != pid:
                    return False
                return typer.type_text(text)

            sess = live_typing.LiveSession(
                tr.transcribe_words,
                emit,
                rules=config.load()["replacements"],
            )
            live_sessions[sid] = sess
        if not job.get("final"):
            sess.feed(job.get("audio"))
            return
        state["value"] = "transcribing"
        t0 = time.time()
        full = sess.finish(
            job.get("audio"), accept=lambda t: not is_hallucination(t)
        )
        live_sessions.pop(sid, None)
        if not full:
            print("[·] Empty.")
            return
        log(f"[✓] typed live (tail {time.time() - t0:.1f}s): {full}")
        last_text["value"] = full
        history_items["value"] = history.add(full)
        menu_dirty["value"] = True
        play_sound(SOUND_DONE)
        done_until["ts"] = time.time() + 2.0
        if sess.undelivered:
            log(f"[i] live: window changed, not typed: {sess.undelivered}")
            notify(
                "Voice Type",
                "Окно сменилось — остаток не напечатан, весь текст в «Copy last text»",
            )

    def worker():
        while True:
            job = jobs.get()
            if job is None:
                return
            if job.get("live"):
                worker_busy["value"] = True
                try:
                    _handle_live_job(job)
                except Exception as e:
                    play_sound(SOUND_ERROR)
                    log(f"[!] live typing: {e}", err=True)
                    live_sessions.pop(job.get("sid"), None)
                finally:
                    worker_busy["value"] = False
                    if job.get("final"):
                        state["value"] = "idle"
                        if jobs.empty():
                            trim_mlx_cache()
                continue
            # marker-job: служебная метка в транскрипт звонка (например, о
            # пропуске записи при переоткрытии потока). Кладём её в call_lines с
            # меткой времени — тогда она встанет в хронологию и переживёт
            # финализацию — и дописываем в файл для живой durability.
            marker = job.get("marker")
            if marker is not None:
                m_sid = job.get("sid")
                m_ts = float(job.get("ts") or 0.0)
                call_lines.setdefault(m_sid, []).append((m_ts, marker))
                calls.append_chunk(job.get("path"), calls.format_line(m_ts, marker))
                continue
            audio = job.get("audio")
            sid = job.get("sid")
            final = job.get("final", True)
            mode = job.get("mode", "dictation")
            worker_busy["value"] = True
            try:
                if final:
                    if mode == "call":
                        call_state["value"] = "transcribing"
                    else:
                        state["value"] = "transcribing"
                tr = _wait_transcriber()
                if tr is None:
                    play_sound(SOUND_ERROR)
                    notify("Voice Type", "Model not loaded")
                    if mode != "call":
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
                        tag = "final" if final else "chunk"
                        if mode == "call":
                            # у звонка реплики двух дорожек приходят вперемешку —
                            # храним с меткой времени и сортируем при финализации
                            ts = float(job.get("ts") or 0.0)
                            call_lines.setdefault(sid, []).append((ts, text))
                            side = job.get("side", "?")
                            log(f"[·] ({dt:.1f}s) {tag} [{side} @{calls.format_timestamp(ts)}]: {text}")
                            calls.append_chunk(job.get("path"), calls.format_line(ts, text))
                        else:
                            session_parts.setdefault(sid, []).append(text)
                            log(f"[·] ({dt:.1f}s) {tag}: {text}")

                if not final:
                    continue  # промежуточный чанк — просто накопили, ждём дальше

                # ── финализация сессии: склейка ─────────────────────────────
                if mode == "call":
                    full = calls.assemble(call_lines.pop(sid, []))
                else:
                    parts = session_parts.pop(sid, [])
                    full = streaming.join_parts(parts)

                if mode == "call":
                    # Звонки не проходят через Smart-полиш (не имеет смысла
                    # на получасовом транскрипте) — только детерминированные
                    # замены, как и у диктовки.
                    full = apply_replacements(full, config.load()["replacements"])
                    path = job.get("path")
                    if not full:
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                        notify("Voice Type", "Пустой звонок — ничего не сохранено")
                    else:
                        saved = True
                        try:
                            calls.finalize(path, full)
                        except OSError as e:
                            saved = False
                            log(f"[!] call transcript save failed: {e}")
                            notify(
                                "Voice Type",
                                "Не удалось сохранить файл звонка (текст всё равно скопирован)",
                            )
                        copy_to_clipboard(full)
                        duration_sec = job.get("duration_sec", 0.0)
                        if saved:
                            calls_items["value"] = calls.add(path, full, duration_sec)
                            menu_dirty["value"] = True
                        play_sound(SOUND_DONE)
                        mins = int(duration_sec) // 60
                        secs = int(duration_sec) % 60
                        notify(
                            "Voice Type",
                            f"Звонок расшифрован ({mins:02d}:{secs:02d}) — скопировано в буфер",
                        )
                    continue

                # ── диктовка: опциональный Smart-полиш + детерминированные
                # замены + доставка ─────────────────────────────────────────
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
                if mode != "call":
                    session_parts.pop(sid, None)
            finally:
                worker_busy["value"] = False
                if final:
                    if mode == "call":
                        call_state["value"] = "idle"
                    else:
                        state["value"] = "idle"
                # работы больше нет — отдаём кэш Metal-буферов системе; на
                # следующий чанк это не влияет по времени (см. limit_mlx_cache)
                if jobs.empty():
                    trim_mlx_cache()

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

    def _resolve_call_hotkey(name):
        try:
            return parse_hotkey(name)
        except ValueError:
            print(
                f"[!] unknown call_hotkey {name!r}; falling back to f13",
                file=sys.stderr,
            )
            current_call_hotkey["value"] = "f13"
            persist()  # вычистить битое значение из конфига
            return parse_hotkey("f13")

    hotkey_obj_holder = {"key": _resolve_hotkey(current_hotkey["value"])}
    call_hotkey_obj_holder = {"key": _resolve_call_hotkey(current_call_hotkey["value"])}
    # распознаватель жестов (hold / double-tap / tap) и id текущей сессии.
    # gr дёргают три потока (клавиатура, pending-таймер, watchdog) — все
    # переходы под gesture_lock, чтобы состояние не разъехалось.
    gr = gestures.GestureRecognizer()
    gesture_lock = threading.Lock()
    session = {"id": 0, "active": False, "start_ts": 0.0}
    pending_timer = {"t": None}
    # авто-стоп hands-free-записи, если о ней забыли (страховка)
    MAX_SESSION_SEC = 300.0

    # ── Call Mode: отдельная запись, независимая от диктовки ────────────────
    ct = gestures.CallToggle()
    call_recorder_holder = {"obj": None}
    # per-call health-объекты (создаются на call_start): политика авто-
    # восстановления потока и детектор отвала одного аудио-источника.
    call_health_holder = {"recovery": None, "channels": None}
    call_session = {
        "id": 0, "active": False, "start_ts": 0.0, "path": None,
    }
    call_state = {"value": "idle"}  # idle | recording | transcribing
    # авто-стоп забытого звонка (страховка) — намного длиннее диктовочного,
    # звонки идут долго
    MAX_CALL_SESSION_SEC = 4 * 3600.0
    # нет кадров из callback дольше этого при активном звонке = поток встал
    # (устройство пропало/сменилось) → пробуем переоткрыть, не роняя запись
    CALL_STALL_SEC = 2.0
    # метка провала записи в транскрипте (переживает finalize, т.к. идёт через
    # session_parts воркера, а не пишется в файл напрямую)
    CALL_GAP_MARKER_TMPL = "[⚠ пропуск записи ~{n}s — переоткрытие аудио]"

    def _call_device_exists(name):
        try:
            for info in recorder.sd.query_devices():
                if info.get("name") == name and int(info.get("max_input_channels", 0)) > 0:
                    return True
        except Exception:
            pass
        return False

    # звонок с авто-захватом ещё и спавнит Swift-хелпер и ждёт его заголовок
    # (а при сброшенном разрешении — системный диалог): даём ему запас
    CALL_OPEN_GRACE_SEC = 6.0

    def _open_mic(fn, grace: float = 0.0):
        """Вызвать открытие микрофона под наблюдением watchdog: если оно
        не вернётся за mic_recovery.START_HANG_SEC (+ grace), CoreAudio
        заклинило и приложение перезапустится само (control_loop к тому
        моменту стоит)."""
        watchdog["start_at"] = time.time() + grace
        try:
            return fn()
        finally:
            watchdog["start_at"] = None

    def control_loop():
        """Все операции с PortAudio — в одном фоновом потоке.

        Колбэки клавиш только кладут команду в очередь и мгновенно
        возвращаются (иначе «протухший» CoreAudio блокирует поток event tap,
        macOS его отключает, и отпускание клавиши теряется). Этот же поток
        периодически (по таймауту 0.5с) отрезает чанк уже сказанного и шлёт
        его на транскрипцию — так длинная диктовка переводится «под капотом»,
        пока вы говорите, и в конце ждать почти нечего. Звонки (Call Mode)
        обслуживаются тем же потоком по тому же принципу, отдельным
        Recorder-инстансом на своём устройстве.
        """
        while True:
            # при печати по ходу речи звук забираем чаще — слова быстрее
            # доходят до поля (проход модели всё равно раз в STEP_SEC)
            live_now = session["active"] and session.get("live")
            try:
                cmd = ctrl.get(timeout=0.2 if live_now else 0.5)
            except queue.Empty:
                cmd = None

            if cmd == "start":
                t0 = time.time()
                try:
                    _open_mic(recorder.start)
                    session["id"] += 1
                    session["active"] = True
                    session["start_ts"] = time.time()
                    session["live"] = _live_typing_enabled()
                    target_app["pid"] = frontmost_app_pid()
                    dt = time.time() - t0
                    if dt > 0.5:
                        log(f"[rec] start took {dt:.2f}s (stale CoreAudio?)")
                except Exception as e:
                    log(f"[!] recorder.start failed ({time.time() - t0:.2f}s): {e}")
                    play_sound(SOUND_ERROR)
                    notify("Voice Type", f"Микрофон не открылся: {e}")
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
                    jobs.put({
                        "audio": rest, "sid": sid, "final": True,
                        "live": bool(session.get("live")),
                    })
                else:  # abort — выбрасываем сессию без доставки
                    session_parts.pop(sid, None)
                    state["value"] = "idle"
            elif cmd == "call_start":
                t0 = time.time()
                # выбор источника: авто-захват системы (tap+микрофон) →
                # ручной Call Device → голый микрофон. Звонок никогда не падает
                # молча: в худшем случае пишем хотя бы твой голос.
                tap_supported = system_audio.is_supported()
                kind, device, reason = system_audio.choose_source(
                    auto_enabled=current_auto_sysaudio["value"],
                    tap_supported=tap_supported,
                    tap_device="tap" if tap_supported else None,
                    manual_device=current_call_device["value"],
                )
                if kind == "manual" and not _call_device_exists(device):
                    notify(
                        "Voice Type",
                        f"Устройство «{device}» не найдено — пишу только микрофон",
                    )
                    kind, device, reason = "mic", None, "mic_only"
                try:
                    start_ts = time.time()
                    path = calls.start_transcript(start_ts)
                    if kind == "tap":
                        # система через Swift-хелпер + твой микрофон, микс
                        source = system_audio.CombinedCallCapture(
                            mic=Recorder(device=None, all_channels=False)
                        )
                    elif kind == "manual":
                        source = Recorder(device=device, all_channels=True)
                    else:  # mic
                        source = Recorder(device=None, all_channels=False)
                    _open_mic(source.start, grace=CALL_OPEN_GRACE_SEC)
                    call_recorder_holder["obj"] = source
                    call_session["id"] += 1
                    call_session["active"] = True
                    call_session["start_ts"] = start_ts
                    call_session["path"] = path
                    call_health_holder["recovery"] = call_health.RecoveryPolicy()
                    call_health_holder["channels"] = call_health.ChannelHealthMonitor()
                    call_state["value"] = "recording"
                    ct.active = True
                    menu_dirty["value"] = True
                    play_sound(SOUND_START)
                    if kind == "manual" and reason in ("tap_denied", "tap_unsupported"):
                        notify("Voice Type", "Авто-захват недоступен — пишу через выбранный Call Device")
                    elif kind == "mic":
                        notify("Voice Type", "Пишу только микрофон (авто-захват недоступен, Call Device не выбран)")
                    dt = time.time() - t0
                    if dt > 0.5:
                        log(f"[call] start took {dt:.2f}s (stale CoreAudio?)")
                except Exception as e:
                    log(f"[!] call start failed ({time.time() - t0:.2f}s): {e}")
                    notify("Voice Type", f"Не удалось начать запись звонка: {e}")
                    play_sound(SOUND_ERROR)
                    src = call_recorder_holder["obj"]
                    if src is not None:
                        try:
                            src.stop()
                        except Exception:
                            pass
                    call_recorder_holder["obj"] = None
                    call_session["active"] = False
                    call_state["value"] = "idle"
                    ct.active = False
            elif cmd == "call_stop":
                if not call_session["active"]:
                    continue  # уже остановлен — игнорируем дублирующую команду
                call_recorder = call_recorder_holder["obj"]
                sid = f"call-{call_session['id']}"
                path = call_session["path"]
                duration_sec = time.time() - call_session["start_ts"]
                call_session["active"] = False
                call_state["value"] = "transcribing"
                ct.active = False
                menu_dirty["value"] = True
                t0 = time.time()
                # у авто-захвата две дорожки: забираем «хвосты» каждой отдельно
                # (с метками времени), чтобы они встали в хронологию транскрипта
                tails = []
                if call_recorder is not None:
                    if hasattr(call_recorder, "stop_labeled"):
                        tails = call_recorder.stop_labeled()
                    else:
                        rest = call_recorder.stop()
                        if rest is not None and len(rest):
                            tails = [("mic", 0.0, rest)]
                dt = time.time() - t0
                if dt > 1.0:
                    log(f"[!] call recorder.stop took {dt:.2f}s (stale CoreAudio?)")
                # все хвосты, кроме последнего, идут как промежуточные куски;
                # последнее задание всегда final — оно и финализирует транскрипт
                for side, ts, audio in tails[:-1]:
                    jobs.put({
                        "audio": audio, "sid": sid, "mode": "call", "final": False,
                        "path": path, "ts": ts, "side": side,
                    })
                last = tails[-1] if tails else (None, 0.0, None)
                jobs.put(
                    {
                        "audio": last[2],
                        "sid": sid,
                        "mode": "call",
                        "final": True,
                        "path": path,
                        "duration_sec": duration_sec,
                        "ts": last[1],
                        "side": last[0] or "mic",
                    }
                )

            # пока идёт запись — пробуем отрезать готовый кусок в паузе
            if session["active"]:
                if time.time() - session["start_ts"] > MAX_SESSION_SEC:
                    log("[rec] hands-free session hit 5-min cap — auto-stopping")
                    ctrl.put("stop")
                    continue
                if session.get("live"):
                    # печать по ходу речи: весь новый звук сразу воркеру —
                    # он сам решает, когда прогнать модель и что напечатать
                    try:
                        fresh = recorder.drain_16k()
                    except Exception as e:
                        fresh = None
                        log(f"[!] live drain: {e}")
                    if fresh is not None and len(fresh):
                        jobs.put({
                            "audio": fresh, "sid": session["id"],
                            "final": False, "live": True,
                        })
                else:
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

            # пока идёт звонок — та же логика, отдельным Recorder-инстансом
            if call_session["active"]:
                if time.time() - call_session["start_ts"] > MAX_CALL_SESSION_SEC:
                    log("[call] hit safety cap — auto-stopping")
                    ctrl.put("call_stop")
                    continue
                call_recorder = call_recorder_holder["obj"]
                recovery = call_health_holder["recovery"]
                channels = call_health_holder["channels"]
                now_mono = time.monotonic()

                # снять готовые куски; исключение — сигнал сбоя потока.
                # У авто-захвата дорожки раздельные: каждая режется и
                # распознаётся сама по себе (правильный язык на каждой стороне)
                # и несёт метку времени для хронологии.
                failed = False
                ready = []  # [(side, ts, audio)]
                try:
                    if call_recorder is None:
                        pass
                    elif hasattr(call_recorder, "take_labeled_chunks"):
                        ready = call_recorder.take_labeled_chunks(
                            min_sec=streaming.CHUNK_SEC,
                            target_sec=streaming.CHUNK_SEC,
                            hard_max_sec=streaming.CHUNK_HARD_MAX_SEC,
                        )
                    else:
                        c = call_recorder.take_chunk(
                            min_sec=streaming.CHUNK_SEC,
                            target_sec=streaming.CHUNK_SEC,
                            hard_max_sec=streaming.CHUNK_HARD_MAX_SEC,
                        )
                        if c is not None:
                            elapsed = time.time() - call_session["start_ts"]
                            ready = [("mic", max(0.0, elapsed - len(c) / 16000.0), c)]
                except Exception as e:
                    failed = True
                    log(f"[!] call take_chunk: {e}")

                # второй сигнал сбоя: кадры перестали приходить (устройство
                # пропало/сменилось на лету — наушники, отвал агрегата)
                stalled = (
                    call_recorder is not None
                    and call_recorder.seconds_since_last_frame(now_mono) > CALL_STALL_SEC
                )

                if failed or stalled:
                    action = (
                        recovery.record_failure(now_mono)
                        if recovery is not None
                        else call_health.GIVE_UP
                    )
                    if action == call_health.RECOVER:
                        gap = max(
                            1,
                            int(round(call_recorder.seconds_since_last_frame(now_mono)))
                            if stalled and call_recorder is not None
                            else 1,
                        )
                        log(f"[call] аудиопоток встал/сбоил — переоткрываю (gap≈{gap}s)")
                        if call_recorder is not None and _open_mic(
                            call_recorder.restart_stream, grace=CALL_OPEN_GRACE_SEC
                        ):
                            # метка провала — через воркер в call_lines,
                            # чтобы пережить finalize (не пишем в файл напрямую)
                            jobs.put(
                                {
                                    "marker": CALL_GAP_MARKER_TMPL.format(n=gap),
                                    "sid": f"call-{call_session['id']}",
                                    "mode": "call",
                                    "path": call_session["path"],
                                    "ts": max(0.0, time.time() - call_session["start_ts"]),
                                }
                            )
                        # если restart не удался — на следующих тиках снова
                        # failure/stall, и политика добьёт бюджет до GIVE_UP
                    elif action == call_health.GIVE_UP:
                        log("[call] не удалось восстановить аудио — авто-стоп")
                        notify(
                            "Voice Type",
                            "Не удалось восстановить аудио звонка — запись остановлена",
                        )
                        ctrl.put("call_stop")
                    # WAIT либо только что сделали RECOVER — чанк в этот тик не отдаём
                    continue

                # поток здоров: обнулить бюджет попыток и проверить, не пропал ли
                # один из источников (твой микрофон жив, звук собеседника исчез)
                if recovery is not None:
                    recovery.reset()
                # per-channel «умер источник» — только для Recorder (у него есть
                # channel_levels); у авто-захвата дорожки и так раздельные
                if (
                    channels is not None
                    and call_recorder is not None
                    and hasattr(call_recorder, "channel_levels")
                ):
                    dead = channels.update(call_recorder.channel_levels, now_mono)
                    if dead:
                        notify(
                            "Voice Type",
                            "Похоже, один из источников звука звонка пропал "
                            "(наушники?). Запись продолжается — проверьте маршрутизацию",
                        )

                for side, ts, audio in ready:
                    if audio is None or streaming.is_silent(audio):
                        continue
                    jobs.put(
                        {
                            "audio": audio,
                            "sid": f"call-{call_session['id']}",
                            "mode": "call",
                            "final": False,
                            "path": call_session["path"],
                            "ts": ts,
                            "side": side,
                        }
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
                session["active"] = True
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
                if call_session["active"]:
                    return  # звонок пишется — диктовку не стартуем поверх
                with gesture_lock:
                    _apply_actions(gr.on_press(time.time()), key)
            elif key == call_hotkey_obj_holder["key"]:
                if session["active"]:
                    return  # диктовка идёт — звонок не стартуем поверх неё
                action = ct.on_press(time.time())
                if action == "call_start":
                    call_session["active"] = True
                if action is not None:
                    ctrl.put(action)
        except Exception as e:
            log(f"[!] on_press: {e}")

    def on_release(key):
        try:
            if not enabled["value"]:
                return
            if key == hotkey_obj_holder["key"]:
                _handle_release(time.time())
            elif key == call_hotkey_obj_holder["key"]:
                ct.on_release(time.time())
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

    # Гарантированный запрос доступа к микрофону в контексте приложения. Делаем
    # ПОСЛЕ старта run loop (в фоновом потоке с задержкой) — иначе системный
    # диалог не может отобразиться и запрос мгновенно отклоняется. Нужно, чтобы
    # приложение снова оказалось в System Settings → Microphone и получило грант
    # (PortAudio сам промпт не поднимает).
    def _bootstrap_mic():
        import time as _t

        _t.sleep(2.5)
        try:
            import AVFoundation as _AVF  # type: ignore

            st = _AVF.AVCaptureDevice.authorizationStatusForMediaType_("soun")
            log(f"[mic] authorization status: {int(st)} (3=authorized)")
            if int(st) != 3:
                _AVF.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    "soun", lambda g: log(f"[mic] access {'granted' if g else 'denied'}")
                )
        except Exception as _e:
            log(f"[mic] permission bootstrap failed: {_e}")

    threading.Thread(target=_bootstrap_mic, daemon=True).start()

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
