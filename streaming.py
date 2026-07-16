"""Streaming-transcription helpers for Just Voice Type.

While the user is still speaking, we periodically slice off the accumulated
audio and transcribe it in the background, so that by the time they stop only
a short tail remains. Slicing at a quiet point (a pause between phrases)
avoids cutting a word in half.

Pure NumPy helpers — no audio device, no model — so they are unit-testable.
"""
from __future__ import annotations

import numpy as np

# после какого объёма накопленного аудио отрезаем чанк
CHUNK_SEC = 20.0
# в каком окне вокруг цели ищем самую тихую точку для реза
SPLIT_SEARCH_SEC = 3.0
# жёсткий предел: если паузы всё нет, режем не дальше этой длины
CHUNK_HARD_MAX_SEC = 30.0


def find_split_point(
    audio: np.ndarray,
    sr: int,
    target_sec: float = CHUNK_SEC,
    search_sec: float = SPLIT_SEARCH_SEC,
) -> int:
    """Индекс сэмпла, по которому резать чанк — самая тихая точка около цели.

    Ищем минимум скользящей энергии в окне [target-search, target+search],
    чтобы разрез попал в паузу между словами. Возвращает индекс в пределах
    (0, len(audio)); если аудио короче цели — возвращает len(audio).
    """
    n = len(audio)
    target = int(target_sec * sr)
    if n <= target:
        return n
    lo = max(1, target - int(search_sec * sr))
    hi = min(n, target + int(search_sec * sr))
    if hi - lo < 2:
        return min(target, n)

    win = max(1, int(0.05 * sr))  # окно энергии ~50 мс
    seg = audio[lo:hi].astype(np.float64)
    energy = seg * seg
    # скользящая сумма энергии окном win через cumsum
    csum = np.cumsum(energy)
    if len(csum) <= win:
        return (lo + hi) // 2
    window_energy = csum[win:] - csum[:-win]
    # индекс минимума энергии → центр самого тихого окна
    quiet = int(np.argmin(window_energy))
    return lo + quiet + win // 2


def is_silent(audio: np.ndarray, rms_thresh: float = 0.003, peak_thresh: float = 0.02) -> bool:
    """Тот же порог тишины, что и в записи — чтобы не гонять тихие чанки
    через модель (защита от 'Thank you'-галлюцинаций)."""
    if audio is None or len(audio) == 0:
        return True
    a = audio.astype(np.float64)
    rms = float(np.sqrt(np.mean(a * a)))
    peak = float(np.max(np.abs(a)))
    return rms < rms_thresh and peak < peak_thresh


def join_parts(parts: "list[str]") -> str:
    """Склеить транскрипты чанков в один текст: непустые части через пробел,
    лишние пробелы схлопнуть."""
    joined = " ".join(p.strip() for p in parts if p and p.strip())
    return " ".join(joined.split())
