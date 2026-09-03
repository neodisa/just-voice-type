"""Automatic system-audio capture for Call Mode (macOS 14.4+).

Captures the whole system output (+ the mic) via a Core Audio process tap.
The tap is read by a small bundled Swift helper (`WhisperFlowSysCap`) that
streams mono float32 PCM to stdout; this module manages that helper as a
subprocess and exposes a `Recorder`-shaped surface to the control loop.

This file holds the pieces that are pure Python and unit-testable
(capability probe, source selection, header/PCM parsing). The subprocess
reader (`SystemAudioCapture`) lives here too but its native behaviour is
validated on hardware, not in CI. No PyObjC/CoreAudio calls happen here —
all native work is inside the Swift helper.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
from typing import Optional, Tuple

HELPER_NAME = "WhisperFlowSysCap"


def _macos_at_least(major: int, minor: int, ver: "Optional[str]" = None) -> bool:
    if ver is None:
        try:
            ver = platform.mac_ver()[0]
        except Exception:
            return False
    try:
        parts = [int(x) for x in ver.split(".")[:2]]
    except (ValueError, AttributeError):
        return False
    while len(parts) < 2:
        parts.append(0)
    return (parts[0], parts[1]) >= (major, minor)


def helper_path() -> str:
    """Путь к бинарю-хелперу: сперва рядом с работающим интерпретатором
    (в бандле это Contents/MacOS/WhisperFlowSysCap), затем dev-сборка
    ./native/WhisperFlowSysCap рядом с этим модулем."""
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    cand = os.path.join(exe_dir, HELPER_NAME)
    if os.path.isfile(cand):
        return cand
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "native", HELPER_NAME)


def _helper_exists(path: "Optional[str]" = None) -> bool:
    p = path or helper_path()
    return os.path.isfile(p) and os.access(p, os.X_OK)


def is_supported(helper: "Optional[str]" = None) -> bool:
    """True, только если ОС ≥ 14.4 и хелпер-бинарь на месте. Не бросает."""
    if sys.platform != "darwin" or not _macos_at_least(14, 4):
        return False
    return _helper_exists(helper)


def choose_source(
    auto_enabled: bool,
    tap_supported: bool,
    tap_device: "Optional[str]",
    manual_device: "Optional[str]",
) -> "Tuple[str, Optional[str], str]":
    """Выбор источника записи звонка. Возвращает (kind, device, reason).

    Три яруса, чтобы намеренный авто-звонок никогда не падал молча:
      tap → ручной Call Device → голый микрофон.
    """
    if auto_enabled and tap_supported and tap_device:
        return ("tap", tap_device, "tap_ok")
    if manual_device:
        reason = (
            "manual_fallback"
            if not auto_enabled
            else ("tap_unsupported" if not tap_supported else "tap_denied")
        )
        return ("manual", manual_device, reason)
    return ("mic", None, "mic_only")


def parse_header(line: bytes) -> "Optional[Tuple[int, int]]":
    """Разобрать первую строку хелпера: {"sample_rate":48000,"channels":1}."""
    try:
        obj = json.loads(line.decode("utf-8").strip())
        return int(obj["sample_rate"]), int(obj["channels"])
    except Exception:
        return None


def decode_pcm(raw: bytes):
    """Сырые байты little-endian float32 → np.float32 (неполный хвост отбрасываем)."""
    import numpy as np

    n = len(raw) - (len(raw) % 4)
    if n <= 0:
        return np.empty(0, dtype=np.float32)
    return np.frombuffer(raw[:n], dtype="<f4").astype(np.float32)


_SR16 = 16000


def mix_streams(a, b):
    """Сложить два моно-потока, дотянув более короткий нулями до длины более
    длинного, и клипнуть в [-1,1].

    Почему так, а не «по минимальной длине с остатком»: при выравнивании по
    min() слабая сторона (например, не отдающий кадры системный хелпер или
    микрофон с провалами) ЗАДЕРЖИВАЕТ вторую — звонок выходил пустым или
    рваным. Здесь ни один сэмпл не задерживается и не выбрасывается: если одна
    сторона молчит, вторая просто идёт как есть. Цена — при расхождении темпа
    источников в дорожку добавляются короткие паузы (миллисекунды), что для
    транскрипции безвредно.
    """
    import numpy as np

    la, lb = len(a), len(b)
    n = max(la, lb)
    if n == 0:
        return np.empty(0, dtype=np.float32)
    out = np.zeros(n, dtype=np.float32)
    if la:
        out[:la] += a
    if lb:
        out[:lb] += b
    return np.clip(out, -1.0, 1.0).astype(np.float32)


def _concat(a, b):
    import numpy as np

    if a is None or len(a) == 0:
        return b
    if b is None or len(b) == 0:
        return a
    return np.concatenate([a, b])


class SystemAudioCapture:
    """Управляет Swift-хелпером как субпроцессом и отдаёт звук чанками —
    интерфейс совместим с тем, что control_loop зовёт у Recorder
    (`take_chunk` / `stop` / `seconds_since_last_frame` / `is_recording`).

    Хелпер печатает строку-заголовок, затем сырой mono float32 PCM в stdout;
    фоновый поток копит его в `_carry` (в нативном sr, обычно 48к), а
    take_chunk отдаёт префикс, ресемплированный в 16к.
    """

    def __init__(self, argv: "Optional[list]" = None) -> None:
        self._argv = list(argv) if argv else [helper_path()]
        self._proc: "Optional[subprocess.Popen]" = None
        self._thread: "Optional[threading.Thread]" = None
        self._lock = threading.Lock()
        self._carry = None  # np.float32 mono @ sample_rate
        self.sample_rate: "Optional[int]" = None
        self._clock = time.monotonic
        self._last_frame_ts: "Optional[float]" = None
        self._started_ts: "Optional[float]" = None
        self._stopped = False

    def start(self) -> None:
        # дефолтная буферизация → stdout это BufferedReader (есть read1);
        # bufsize=0 дал бы сырой поток без read1
        self._proc = subprocess.Popen(
            self._argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        header = self._proc.stdout.readline()
        parsed = parse_header(header)
        self.sample_rate = parsed[0] if parsed else 48000
        self._last_frame_ts = self._clock()
        self._started_ts = self._last_frame_ts
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        # stderr хелпера — в наш лог: без этого сбои захвата (какой агрегат
        # выбран, дошли ли первые кадры) не видны при разборе звонка
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in iter(proc.stderr.readline, b""):
                txt = line.decode("utf-8", "replace").strip()
                if txt:
                    print(f"[syscap] {txt}", file=sys.stderr, flush=True)
        except (ValueError, OSError):
            pass

    def _reader(self) -> None:
        import numpy as np

        leftover = b""
        stream = self._proc.stdout if self._proc is not None else None
        if stream is None:
            return
        while not self._stopped:
            try:
                raw = stream.read1(65536)
            except (ValueError, OSError):
                break
            if not raw:
                break
            buf = leftover + raw
            n = len(buf) - (len(buf) % 4)
            leftover = buf[n:]
            if n <= 0:
                continue
            samples = np.frombuffer(buf[:n], dtype="<f4").astype(np.float32)
            with self._lock:
                if self._carry is None or len(self._carry) == 0:
                    self._carry = samples
                else:
                    self._carry = np.concatenate([self._carry, samples])
                self._last_frame_ts = self._clock()

    def take_chunk(self, min_sec: float, target_sec: float, hard_max_sec: float):
        import streaming

        sr = self.sample_rate or 48000
        with self._lock:
            carry = self._carry
            if carry is None or len(carry) / sr < min_sec:
                return None
            split = streaming.find_split_point(carry, sr, target_sec=target_sec)
            hard = int(hard_max_sec * sr)
            if split > hard:
                split = hard
            split = max(1, min(split, len(carry)))
            prefix = carry[:split]
            self._carry = carry[split:]
        return streaming.resample_to_16k(prefix, sr)

    def stop(self):
        import streaming

        self._stopped = True
        if self._proc is not None:
            try:
                self._proc.terminate()  # SIGTERM → хелпер снимает tap/aggregate
            except Exception:
                pass
            try:
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._proc is not None:
            for s in (self._proc.stdout, self._proc.stderr):
                try:
                    if s is not None:
                        s.close()
                except Exception:
                    pass
        sr = self.sample_rate or 48000
        with self._lock:
            carry = self._carry
            self._carry = None
        self._proc = None
        if carry is None or len(carry) == 0:
            return None
        return streaming.resample_to_16k(carry, sr)

    # сколько времени после спавна не считаем отсутствие кадров зависанием:
    # процесс + постановка tap занимают ~1-2с, иначе получаем ложные рестарты
    STARTUP_GRACE_SEC = 6.0

    def drain_16k(self):
        """Слить весь накопленный звук как 16к-моно и очистить буфер (для микса)."""
        import numpy as np
        import streaming

        sr = self.sample_rate or 48000
        with self._lock:
            carry = self._carry
            self._carry = None
        if carry is None or len(carry) == 0:
            return np.empty(0, dtype=np.float32)
        return streaming.resample_to_16k(carry, sr)

    def seconds_since_last_frame(self, now: "Optional[float]" = None) -> float:
        if self._last_frame_ts is None:
            return float("inf")
        if now is None:
            now = self._clock()
        # грейс на старте: пока идёт постановка tap, кадров ещё нет — это не
        # зависание, иначе control_loop уходит в цикл ложных переоткрытий
        if self._started_ts is not None and (now - self._started_ts) < self.STARTUP_GRACE_SEC:
            return 0.0
        return now - self._last_frame_ts

    @property
    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


class CombinedCallCapture:
    """Источник записи звонка «система + микрофон» (Plan B).

    Системный звук берётся из надёжного system-only Swift-хелпера
    (`SystemAudioCapture`), микрофон — из обычного `Recorder`. Оба потока —
    16к-моно; на каждом тике сливаем накопленное из обоих, складываем по
    совпадающей длине (`mix_aligned`, стороны держатся выровненными), а
    объединённый поток режем на чанки той же логикой, что и Recorder.

    Экспонирует интерфейс, который зовёт control_loop у Recorder:
    take_chunk / stop / seconds_since_last_frame / is_recording / restart_stream.
    """

    def __init__(self, system=None, mic=None) -> None:
        self._system = system if system is not None else SystemAudioCapture()
        self._mic = mic  # Recorder (или None → только система)
        self._carry = None
        self._clock = time.monotonic
        # сколько сэмплов 16к уже отдано с каждой дорожки — из этого получаем
        # метку времени реплики (позиция в звонке), без дрейфа настенных часов
        self._consumed = {"system": 0, "mic": 0}

    def _sides(self):
        yield "system", self._system
        if self._mic is not None:
            yield "mic", self._mic

    def take_labeled_chunks(self, min_sec: float, target_sec: float, hard_max_sec: float):
        """Снять готовые куски С КАЖДОЙ дорожки отдельно.

        Возвращает список (side, ts_sec, audio16k). Дорожки не смешиваются:
        каждая режется по своим паузам и распознаётся отдельно — это даёт
        (а) правильный язык на каждой стороне (чужая речь больше не «утаскивает»
        распознавание твоей), (б) метку времени для восстановления хронологии.
        """
        out = []
        for side, src in self._sides():
            try:
                chunk = src.take_chunk(
                    min_sec=min_sec, target_sec=target_sec, hard_max_sec=hard_max_sec
                )
            except Exception:
                chunk = None
            if chunk is None or len(chunk) == 0:
                continue
            ts = self._consumed[side] / float(_SR16)
            self._consumed[side] += len(chunk)
            out.append((side, ts, chunk))
        return out

    def stop_labeled(self):
        """Остановить обе дорожки и вернуть их «хвосты» как (side, ts, audio)."""
        out = []
        for side, src in self._sides():
            try:
                tail = src.stop()
            except Exception:
                tail = None
            if tail is None or len(tail) == 0:
                continue
            ts = self._consumed[side] / float(_SR16)
            self._consumed[side] += len(tail)
            out.append((side, ts, tail))
        return out

    def start(self) -> None:
        self._system.start()
        if self._mic is not None:
            self._mic.start()

    def _pull(self) -> None:
        """Слить накопленное с обеих сторон и подмешать в объединённый поток.
        Ничего не задерживаем и не выбрасываем (см. mix_streams)."""
        import numpy as np

        empty = np.empty(0, dtype=np.float32)
        sys_new = self._system.drain_16k()
        mic_new = self._mic.drain_16k() if self._mic is not None else empty
        mixed = mix_streams(
            sys_new if sys_new is not None else empty,
            mic_new if mic_new is not None else empty,
        )
        if len(mixed):
            self._carry = _concat(self._carry, mixed)

    def take_chunk(self, min_sec: float, target_sec: float, hard_max_sec: float):
        import streaming

        self._pull()
        carry = self._carry
        if carry is None or len(carry) / _SR16 < min_sec:
            return None
        split = streaming.find_split_point(carry, _SR16, target_sec=target_sec)
        hard = int(hard_max_sec * _SR16)
        if split > hard:
            split = hard
        split = max(1, min(split, len(carry)))
        prefix = carry[:split]
        self._carry = carry[split:]
        return prefix

    def stop(self):
        import numpy as np

        self._pull()
        empty = np.empty(0, dtype=np.float32)
        sys_tail = self._system.stop()
        mic_tail = self._mic.stop() if self._mic is not None else None
        tail = mix_streams(
            sys_tail if sys_tail is not None else empty,
            mic_tail if mic_tail is not None else empty,
        )
        if len(tail):
            self._carry = _concat(self._carry, tail)
        carry = self._carry
        self._carry = None
        if carry is None or len(carry) == 0:
            return None
        return carry

    def seconds_since_last_frame(self, now: "Optional[float]" = None) -> float:
        """Здоровье по САМОЙ ЖИВОЙ стороне (min): пока хоть один источник даёт
        кадры, запись идёт и переоткрывать нечего. С max() медленный старт
        хелпера (~2с на постановку tap) выглядел как зависание и вызывал
        бесконечные ложные «переоткрытия»."""
        vals = [self._system.seconds_since_last_frame(now)]
        if self._mic is not None:
            vals.append(self._mic.seconds_since_last_frame(now))
        return min(vals)

    @property
    def is_recording(self) -> bool:
        if not self._system.is_recording:
            return False
        if self._mic is not None and not self._mic.is_recording:
            return False
        return True

    def restart_stream(self) -> bool:
        """Восстановление: пере-спавним системный хелпер (хрупкую часть)."""
        try:
            self._system.stop()
        except Exception:
            pass
        try:
            self._system = SystemAudioCapture()
            self._system.start()
            return True
        except Exception:
            return False
