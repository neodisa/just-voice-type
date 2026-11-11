"""Плашка «{app} использует микрофон — записать звонок?».

Показывает её SwiftUI-хелпер в режиме --offer (native/settings/OfferPanel.swift):
своя плашка вместо системного уведомления, потому что уведомления Voice Type
macOS может молча не показывать (authorizationStatus: Denied — баннеров нет,
запись только в Центре уведомлений), а предложение записать звонок важно
увидеть. Плашка висит, пока вы не ответите или программа звонка не отпустит
микрофон (withdraw).

Обмен: одна строка JSON в stdin хелпера (готовые строки интерфейса), одна
строка ответа из stdout ({"type":"offer_answer","answer":"record"|"dismiss"}).
Закрытый stdin — плашка уходит без ответа.
"""
from __future__ import annotations

import json
import subprocess
import threading
from typing import Callable, Optional

import settings_bridge

ANSWERS = ("record", "dismiss")
# хелпер не ушёл за столько секунд после закрытия stdin — добиваем
EXIT_GRACE_SEC = 2.0


def parse_answer(line) -> Optional[str]:
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    if isinstance(msg, dict) and msg.get("type") == "offer_answer" and msg.get("answer") in ANSWERS:
        return msg["answer"]
    return None


class OfferPrompt:
    """Одна плашка за раз; новое предложение заменяет старое."""

    def __init__(
        self,
        helper: Callable[[], Optional[str]] = settings_bridge.helper_path,
        log: Callable[[str], object] = print,
        popen: Callable = subprocess.Popen,
    ) -> None:
        self._helper = helper
        self._log = log
        self._popen = popen
        self._lock = threading.Lock()
        self._proc = None
        self._key: Optional[str] = None

    @property
    def showing(self) -> Optional[str]:
        with self._lock:
            return self._key

    def show(self, key: str, payload: dict, on_answer: Callable[[str, str], object]) -> bool:
        """True — плашка показана. False — хелпера нет или он не запустился
        (вызывающий тогда шлёт обычное уведомление)."""
        self.withdraw()
        path = self._helper()
        if not path:
            return False
        try:
            proc = self._popen(
                [path, "--offer"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self._log(f"[offer] helper did not start: {e}")
            return False
        try:
            line = json.dumps({"type": "offer", **payload}, ensure_ascii=False) + "\n"
            proc.stdin.write(line.encode("utf-8"))
            proc.stdin.flush()
        except Exception as e:
            self._log(f"[offer] helper did not take the offer: {e}")
            self._close(proc)
            return False
        with self._lock:
            self._proc, self._key = proc, key
        threading.Thread(
            target=self._read, args=(proc, key, on_answer), name="offer", daemon=True
        ).start()
        return True

    def _read(self, proc, key: str, on_answer) -> None:
        answer = None
        try:
            for line in proc.stdout:
                answer = parse_answer(line)
                if answer:
                    break
        except Exception as e:
            self._log(f"[offer] read failed: {e}")
        try:
            proc.wait(timeout=EXIT_GRACE_SEC)
        except Exception:
            self._kill(proc)
        with self._lock:
            if self._proc is proc:
                self._proc, self._key = None, None
        if answer:
            try:
                on_answer(key, answer)
            except Exception as e:
                self._log(f"[offer] answer handler failed: {e}")

    def withdraw(self, key: Optional[str] = None) -> None:
        """Убрать плашку (только для этой программы, если key задан)."""
        with self._lock:
            proc = self._proc
            if proc is None or (key is not None and self._key != key):
                return
            self._proc, self._key = None, None
        self._close(proc)

    def _close(self, proc) -> None:
        try:
            proc.stdin.close()  # EOF → хелпер убирает плашку и выходит
        except Exception:
            pass
        timer = threading.Timer(EXIT_GRACE_SEC, self._kill, (proc,))
        timer.daemon = True
        timer.start()

    @staticmethod
    def _kill(proc) -> None:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
