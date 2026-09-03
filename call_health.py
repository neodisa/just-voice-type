"""Pure decision helpers for keeping a Call Mode recording alive across audio
routing changes (headphones plugged/unplugged, CoreAudio hiccups).

No audio device or GUI deps — plain state machines driven by a caller-supplied
monotonic clock — so they are fully unit-testable. The control loop owns the
real `Recorder` and calls into these to decide *whether* to reopen the stream
and *whether* to warn the user; the actual I/O stays in voice_type.py.
"""
from __future__ import annotations

from typing import Sequence

# ── RecoveryPolicy actions ──────────────────────────────────────────────────
RECOVER = "RECOVER"  # попробовать переоткрыть поток прямо сейчас
WAIT = "WAIT"  # сбой ещё держится, но не долбим устройство — ждём backoff
GIVE_UP = "GIVE_UP"  # бюджет попыток исчерпан — звонок пора авто-останавливать


class RecoveryPolicy:
    """Решает, что делать при сигнале сбоя аудиопотока.

    Разрешаем до `max_attempts` попыток восстановления в скользящем окне
    `window_sec`, с минимальным интервалом `backoff_sec` между попытками.
    Успешное возобновление кадров (`reset`) обнуляет бюджет.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_sec: float = 60.0,
        backoff_sec: float = 1.0,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self.backoff_sec = backoff_sec
        self._attempts: "list[float]" = []  # метки времени попыток в окне

    def record_failure(self, now: float) -> str:
        """Зарегистрировать сигнал сбоя в момент `now`; вернуть действие."""
        # выкидываем попытки, выпавшие из окна — старые сбои не должны
        # засчитываться в бюджет бесконечно
        cutoff = now - self.window_sec
        self._attempts = [t for t in self._attempts if t > cutoff]

        if len(self._attempts) >= self.max_attempts:
            return GIVE_UP

        if self._attempts and (now - self._attempts[-1]) < self.backoff_sec:
            return WAIT

        self._attempts.append(now)
        return RECOVER

    def reset(self) -> None:
        """Кадры снова пошли — считаем поток здоровым, бюджет полон."""
        self._attempts = []


class ChannelHealthMonitor:
    """Ловит отвал одного источника звонка (например, системный звук
    собеседника пропал после смены наушников), пока другой источник (твой
    микрофон) продолжает писать.

    Кормится покадровыми уровнями (peak, 0..1) по каждому каналу ДО даунмикса.
    Сигналит про канал, только если он: (1) когда-то был активен, (2) молчит
    дольше `silence_sec`, и (3) при этом ЖИВ хотя бы один другой канал —
    иначе «все молчат» неотличимо от честной паузы в разговоре. Один сигнал на
    канал за время жизни монитора (без спама уведомлениями).
    """

    def __init__(self, active_thresh: float = 0.02, silence_sec: float = 8.0) -> None:
        self.active_thresh = active_thresh
        self.silence_sec = silence_sec
        self._ever_active: "dict[int, bool]" = {}
        self._last_active_ts: "dict[int, float]" = {}
        self._warned: "set[int]" = set()

    def update(self, levels: "Sequence[float]", now: float) -> "list[int]":
        """Скормить текущие per-channel уровни; вернуть индексы каналов,
        которые ИМЕННО СЕЙЧАС перешли в состояние «мёртв»."""
        active_now = [lvl >= self.active_thresh for lvl in levels]
        for i, is_active in enumerate(active_now):
            if is_active:
                self._ever_active[i] = True
                self._last_active_ts[i] = now

        newly_dead: "list[int]" = []
        for i, is_active in enumerate(active_now):
            if is_active or i in self._warned or not self._ever_active.get(i):
                continue
            # нужен хотя бы один ДРУГОЙ живой канал (не считаем сам i)
            others_alive = any(a for j, a in enumerate(active_now) if j != i)
            if not others_alive:
                continue
            silent_for = now - self._last_active_ts.get(i, now)
            if silent_for >= self.silence_sec:
                self._warned.add(i)
                newly_dead.append(i)
        return newly_dead
