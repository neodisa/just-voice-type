"""Ручная проверка новой версии приложения по последнему релизу на GitHub."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from typing import Callable, Optional, Tuple

API_URL = "https://api.github.com/repos/neodisa/just-voice-type/releases/latest"
RELEASES_URL = "https://github.com/neodisa/just-voice-type/releases"


def parse_version(s: str) -> "Tuple[int, ...]":
    parts = []
    for chunk in str(s or "").strip().lstrip("vV").split("."):
        m = re.match(r"\d+", chunk)
        if not m:
            break
        parts.append(int(m.group()))
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b)) if a else False


def interpret(payload: dict, current: str, now: float) -> dict:
    tag = str(payload.get("tag_name") or "")
    if is_newer(tag, current):
        return {
            "state": "update",
            "version": tag.lstrip("vV"),
            "url": str(payload.get("html_url") or RELEASES_URL),
            "checked_at": now,
        }
    return {"state": "uptodate", "checked_at": now}


def fetch_latest(version: str, timeout: float = 5.0, opener: Callable = urllib.request.urlopen) -> dict:
    req = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"JustVoiceType/{version}"},
    )
    with opener(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Checker:
    """Фоновая проверка; state читается из главного потока."""

    def __init__(self, version: str, fetch: Callable[[str], dict] = fetch_latest):
        self.version = version
        self._fetch = fetch
        self.state: dict = {"state": "idle"}
        self._lock = threading.Lock()

    def start(self, on_done: Optional[Callable[[], None]] = None) -> bool:
        with self._lock:
            if self.state.get("state") == "checking":
                return False
            self.state = {"state": "checking"}

        def run():
            try:
                result = interpret(self._fetch(self.version), self.version, time.time())
            except Exception:
                result = {"state": "error"}
            with self._lock:
                self.state = result
            if on_done:
                on_done()

        threading.Thread(target=run, daemon=True).start()
        return True
