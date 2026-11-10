"""Процесс окна настроек (SwiftUI-хелпер JustVoiceTypeSettings) и обмен
с ним строками JSON по stdin/stdout. Протокол: native/settings/PROTOCOL.md.

Поток чтения только кладёт сообщения в очередь; разбирает их главный
поток приложения (poll() из тика таймера), как и всё, что трогает AppKit.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from typing import Callable, List, Optional

HELPER_NAME = "JustVoiceTypeSettings"
INCOMING = ("ready", "set", "action", "closed")


def helper_path() -> Optional[str]:
    """Сперва рядом с интерпретатором (в бандле — Contents/MacOS), затем
    dev-сборка ./native/JustVoiceTypeSettings. None — хелпер не собран."""
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(exe_dir, HELPER_NAME), os.path.join(here, "native", HELPER_NAME)):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def parse_line(line) -> Optional[dict]:
    """Строка от хелпера → сообщение или None, если строка битая/чужая."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    line = line.strip()
    if not line:
        return None
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("type") not in INCOMING:
        return None
    if msg["type"] == "set" and not isinstance(msg.get("key"), str):
        return None
    if msg["type"] == "action":
        if not isinstance(msg.get("name"), str):
            return None
        if not isinstance(msg.get("args", {}), dict):
            return None
        msg.setdefault("args", {})
    if "req" in msg and not isinstance(msg["req"], str):
        msg["req"] = str(msg["req"])
    return msg


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


class SettingsBridge:
    """Один процесс окна на приложение. open() поднимает уже открытое окно."""

    def __init__(
        self,
        command: Callable[[], Optional[List[str]]] = lambda: [helper_path()] if helper_path() else None,
        log: Callable[[str], None] = print,
    ):
        self._command = command
        self._log = log
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._inbox: "queue.Queue[dict]" = queue.Queue()
        self.pending_section: Optional[str] = None

    def available(self) -> bool:
        return bool(self._command())

    def is_open(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def open(self, section: Optional[str] = None) -> bool:
        if self.is_open():
            if section:
                self.send({"type": "focus", "section": section})
            else:
                self.send({"type": "focus", "section": None})
            return True
        cmd = self._command()
        if not cmd:
            return False
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0
            )
        except OSError as e:
            self._log(f"[settings] could not start helper: {e}")
            return False
        self._proc = proc
        self.pending_section = section
        threading.Thread(target=self._reader, args=(proc,), daemon=True).start()
        return True

    def _reader(self, proc: subprocess.Popen) -> None:
        for raw in proc.stdout:
            msg = parse_line(raw)
            if msg is None:
                self._log(f"[settings] ignored line from helper: {raw[:200]!r}")
                continue
            self._inbox.put(msg)
        proc.wait()
        self._inbox.put({"type": "closed", "_exit": proc.returncode})

    def send(self, msg: dict) -> bool:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return False
            try:
                proc.stdin.write(encode(msg))
                proc.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError):
                return False

    def poll(self) -> "list[dict]":
        """Все пришедшие сообщения (зовётся из главного потока)."""
        out = []
        while True:
            try:
                msg = self._inbox.get_nowait()
            except queue.Empty:
                return out
            if msg["type"] == "closed":
                with self._lock:
                    self._proc = None
                if any(m["type"] == "closed" for m in out):
                    continue
            out.append(msg)

    def close(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.stdin.write(encode({"type": "quit"}))
            proc.stdin.close()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
