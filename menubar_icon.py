"""Что показывать в строке меню: кадр иконки и строку статуса.

Чистая логика без AppKit: по снимку состояния приложения (Snapshot)
выбирает кадр (Frame: символ SF Symbols или полоски уровня, цвет,
таймер) и строку статуса для меню (Status). Рисует кадры menubar_view.

Кадры — неизменяемые и хешируемые: одинаковый кадр не перерисовывается,
поэтому полоски уровня квантуются до BAR_STEPS ступеней.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
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
    stealth: bool = False  # скрытая запись: иконка не выдаёт звонок


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


def kind(s: Snapshot) -> str:
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
    # скрытая запись: иконка ведёт себя так, будто звонка нет; строка статуса
    # в меню (status) звонок по-прежнему показывает
    k = kind(replace(s, call_state="idle") if s.stealth else s)
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
    k = kind(s)
    elapsed = s.call_elapsed if k == "call_recording" else s.rec_elapsed
    text = i18n.t(
        f"status.{k}",
        key=i18n.key_name(s.hotkey),
        time=fmt_elapsed(elapsed),
        model=s.model_name,
    )
    return Status(dot=_DOTS.get(k, "busy"), text=text)
