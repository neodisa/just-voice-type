"""Звонок по микрофону: когда предложить запись и когда её остановить.

Чистая логика без Core Audio. Каждые POLL_SEC приложение передаёт, какие
программы (ключи mic_users.app_key) держат микрофон и какие играют звук,
и получает события:
- Ask(key): программа держит микрофон ASK_AFTER_SEC, звонок не пишется —
  предложить запись (один раз за «сеанс микрофона» этой программы);
- Withdraw(key): программа отпустила микрофон — убрать предложение;
- Stop(key, quiet_for): все программы, связанные с записью, уже
  STOP_AFTER_SEC не держат микрофон и не играют звук — остановить запись.

Запись связывается с программами, которые были в микрофоне при её старте
или держали его ASK_AFTER_SEC во время записи. Без связанных программ
(встреча вживую) запись останавливается только вручную. Условие «не играет
звук» бережёт слушателя с выключенным микрофоном: собеседников слышно —
значит, звонок идёт.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

POLL_SEC = 2.0
# короче — Siri, системная диктовка, голосовые; звонок держит микрофон дольше
ASK_AFTER_SEC = 8.0
# пауза после звонка: короткий обрыв или переподключение не режет запись
STOP_AFTER_SEC = 20.0
MODES = ("ask", "off")


@dataclass(frozen=True)
class Ask:
    key: str


@dataclass(frozen=True)
class Withdraw:
    key: str


@dataclass(frozen=True)
class Stop:
    key: str
    quiet_for: float


class Detector:
    def __init__(self) -> None:
        self.mic_since: dict = {}
        self.asked: Set[str] = set()
        self.linked: Set[str] = set()
        self.quiet_since: Optional[float] = None
        self._recording = False

    def poll(
        self,
        now: float,
        on_mic: Iterable[str],
        playing: Iterable[str],
        *,
        recording: bool,
        busy: bool,
        ask: bool,
        auto_stop: bool,
    ) -> list:
        on_mic, playing = set(on_mic), set(playing)
        events: List[object] = []
        for key in sorted(self.mic_since):
            if key not in on_mic:
                del self.mic_since[key]
                if key in self.asked:
                    self.asked.discard(key)
                    events.append(Withdraw(key))
        for key in on_mic:
            self.mic_since.setdefault(key, now)

        if recording != self._recording:
            # начало записи связывает её со всеми, кто сейчас в микрофоне,
            # конец — отвязывает. asked живёт дольше записи: остановили
            # вручную посреди звонка — тот же звонок второй раз не предлагаем
            self.linked = set(on_mic) if recording else set()
            self.quiet_since = None
            self._recording = recording

        held = {k for k in on_mic if now - self.mic_since[k] >= ASK_AFTER_SEC}
        if recording:
            self.linked |= held
            events += self._stop_check(now, on_mic | playing, auto_stop)
        elif ask and not busy:
            for key in sorted(held - self.asked):
                self.asked.add(key)
                events.append(Ask(key))
        return events

    def _stop_check(self, now: float, active: Set[str], auto_stop: bool) -> list:
        if not self.linked:
            return []  # запись без программы звонка — только вручную
        if self.linked & active:
            self.quiet_since = None
            return []
        if self.quiet_since is None:
            self.quiet_since = now
        quiet = now - self.quiet_since
        if not auto_stop or quiet < STOP_AFTER_SEC:
            return []
        key = sorted(self.linked)[0]
        self.linked = set()  # один Stop на запись
        self.quiet_since = None
        return [Stop(key, quiet)]
