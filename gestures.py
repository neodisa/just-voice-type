"""Hotkey gesture recognizer for Just Voice Type.

Turns raw press/release/timeout events on the single hotkey into recording
intents, distinguishing three gestures:

  • hold (press, keep holding, release)      → push-to-talk
  • double-tap (two quick taps)              → hands-free toggle ON
  • single tap while hands-free              → toggle OFF

Pure and deterministic (time is passed in, never read), so it is fully
unit-testable without real timers or a keyboard.

States:
  idle       — not recording
  ptt        — recording, user is holding the key (push-to-talk)
  pending    — key released after a short tap; still recording while we wait
               DOUBLE_TAP_WINDOW for a possible second tap. If it comes →
               hands-free; if it times out → finalize as a short dictation.
  handsfree  — recording, key is free; next tap stops it.

Actions returned to the caller:
  START      — begin a new recording session
  FINALIZE   — stop recording and transcribe what was captured
  ARM_TIMER  — (re)start the pending timer for DOUBLE_TAP_WINDOW seconds
  DISARM_TIMER — cancel the pending timer (second tap arrived)
"""
from __future__ import annotations

START = "START"
FINALIZE = "FINALIZE"
ARM_TIMER = "ARM_TIMER"
DISARM_TIMER = "DISARM_TIMER"

# зажатие короче этого — «тап» (кандидат в double-tap), иначе push-to-talk hold
HOLD_MIN = 0.35
# максимальный интервал между отпусканием первого тапа и вторым нажатием
DOUBLE_TAP_WINDOW = 0.5


class GestureRecognizer:
    def __init__(self, hold_min: float = HOLD_MIN, window: float = DOUBLE_TAP_WINDOW):
        self.hold_min = hold_min
        self.window = window
        self.mode = "idle"
        self._press_time = 0.0

    def on_press(self, now: float) -> "list[str]":
        if self.mode == "handsfree":
            # одиночный тап завершает hands-free
            self.mode = "idle"
            return [FINALIZE]
        if self.mode == "pending":
            # второй тап быстрого double-tap — запись не прерывалась
            self.mode = "handsfree"
            return [DISARM_TIMER]
        if self.mode == "ptt":
            # повторный press без release (автоповтор модификатора) — игнор
            return []
        # idle → начинаем запись, пока считаем это push-to-talk
        self.mode = "ptt"
        self._press_time = now
        return [START]

    def on_release(self, now: float) -> "list[str]":
        if self.mode != "ptt":
            # в handsfree/pending/idle отпускание клавиши ничего не значит
            return []
        if now - self._press_time >= self.hold_min:
            # держали достаточно долго → обычный push-to-talk стоп
            self.mode = "idle"
            return [FINALIZE]
        # быстрый тап: не прерываем запись, ждём возможный второй тап
        self.mode = "pending"
        return [ARM_TIMER]

    def on_timeout(self, now: float) -> "list[str]":
        # pending-таймер истёк без второго тапа → одиночная короткая диктовка
        if self.mode == "pending":
            self.mode = "idle"
            return [FINALIZE]
        return []

    @property
    def is_recording(self) -> bool:
        return self.mode in ("ptt", "pending", "handsfree")

    @property
    def is_handsfree(self) -> bool:
        return self.mode == "handsfree"
