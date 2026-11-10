"""Звуки приложения: событие → файл в выбранном стиле.

Стили default/mech/bubble/press — звуки cuelume (MIT, © 2026 Daniel Belyi),
один раз отрендеренные в sounds/<стиль>/<событие>.wav скриптом
scripts/render_sounds.py. Стиль macos — системные Tink/Pop/Ping/Basso, как
было до 0.14. Играем через afplay, не блокируя поток.
"""

import os
import subprocess
import time
from typing import Callable, Optional, Tuple

SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")

EVENTS = (
    "dictation_start",
    "dictation_stop",
    "done",
    "error",
    "call_start",
    "call_stop",
    "call_ready",
)
CALL_EVENTS = frozenset({"call_start", "call_stop", "call_ready"})

# событие → (cue cuelume, emphasis); по этой таблице отрендерены файлы
CUES = {
    "dictation_start": ("open", "subtle"),
    "dictation_stop": ("close", "subtle"),
    "done": ("success", "subtle"),
    "error": ("error", "normal"),
    "call_start": ("loading", "normal"),
    "call_stop": ("close", "normal"),
    "call_ready": ("ready", "normal"),
}

CUELUME_THEMES = ("default", "mech", "bubble", "press")
THEMES = CUELUME_THEMES + ("macos", "off")
DEFAULT_THEME = "default"

_MACOS = {
    "dictation_start": "Tink",
    "dictation_stop": "Pop",
    "done": "Ping",
    "error": "Basso",
    "call_start": "Tink",
    "call_stop": "Pop",
    "call_ready": "Ping",
}
MACOS_VOLUME = 0.5
# файлы cuelume уже выровнены по громкости под системные звуки на 0.5
FILE_VOLUME = 1.0


def _macos(event: str) -> Tuple[str, float]:
    return f"/System/Library/Sounds/{_MACOS[event]}.aiff", MACOS_VOLUME


def resolve(
    event: str,
    theme: str,
    *,
    sounds_dir: str = SOUNDS_DIR,
    exists: Callable[[str], bool] = os.path.isfile,
) -> Optional[Tuple[str, float]]:
    """(путь, громкость afplay) или None — молчать."""
    if event not in EVENTS or theme == "off":
        return None
    if theme == "macos":
        return _macos(event)
    if theme not in CUELUME_THEMES:
        theme = DEFAULT_THEME
    path = os.path.join(sounds_dir, theme, f"{event}.wav")
    if exists(path):
        return path, FILE_VOLUME
    # битая установка не должна глушить ошибки
    return _macos(event)


def play(
    event: str,
    theme: str,
    *,
    quiet_calls: bool = False,
    run: Callable = subprocess.Popen,
) -> None:
    """Сыграть звук события. quiet_calls — скрытая запись: звонок молчит."""
    if quiet_calls and event in CALL_EVENTS:
        return
    found = resolve(event, theme)
    if found is None:
        return
    path, volume = found
    run(
        ["afplay", "-v", f"{volume:g}", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# Live typing доставляет текст через 0.1–0.2 с после отпускания клавиши, и
# «готово» сливалось со «стопом» в один длинный звук. Начало диктовки — один
# звук, конец тоже: если текст пришёл быстрее этого окна, хватает «стопа».
# После заметного ожидания (Whisper, Clean/Prompt) «готово» всё же звучит.
DONE_AFTER_STOP_SEC = 1.0


class Cues:
    """play() с памятью о последнем «стопе» диктовки."""

    def __init__(self, *, play: Callable = play, clock: Callable[[], float] = time.monotonic):
        self._play = play
        self._clock = clock
        self._stop_at: Optional[float] = None

    def __call__(self, event: str, theme: str, *, quiet_calls: bool = False) -> None:
        now = self._clock()
        if event == "dictation_stop":
            self._stop_at = now
        elif event == "done" and self._stop_at is not None:
            quick = now - self._stop_at < DONE_AFTER_STOP_SEC
            self._stop_at = None
            if quick:
                return
        self._play(event, theme, quiet_calls=quiet_calls)
