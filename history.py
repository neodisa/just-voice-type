"""Persistent dictation history for Just Voice Type.

Stored as JSON at ~/.config/just-voice-type/history.json (honors
$XDG_CONFIG_HOME via the config module). Newest first. Pure I/O +
formatting helpers, no GUI deps — unit-testable.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import Any, Optional

import config

HISTORY_FILE_NAME = "history.json"
# сколько записей храним на диске / показываем в меню
MAX_ITEMS = 50
MENU_ITEMS = 15
LABEL_LEN = 60


def history_path() -> str:
    return os.path.join(config.config_dir(), HISTORY_FILE_NAME)


def load() -> "list[dict[str, Any]]":
    try:
        with open(history_path(), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as e:
        print(f"[!] history load failed ({e}); starting empty", file=sys.stderr)
        return []
    if not isinstance(raw, list):
        return []
    items = []
    for it in raw:
        if isinstance(it, dict) and isinstance(it.get("text"), str) and it["text"].strip():
            try:
                ts = float(it.get("ts") or 0.0)
            except (TypeError, ValueError):
                ts = 0.0
            items.append({"text": it["text"], "ts": ts})
    return items[:MAX_ITEMS]


def save(items: "list[dict[str, Any]]") -> None:
    d = config.config_dir()
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".history-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items[:MAX_ITEMS], f, ensure_ascii=False, indent=2)
        os.replace(tmp, history_path())
    except OSError as e:
        print(f"[!] history save failed: {e}", file=sys.stderr)


def add(text: str, now: Optional[float] = None) -> "list[dict[str, Any]]":
    """Добавить диктовку в начало истории; вернуть обновлённый список."""
    if not text or not text.strip():
        return load()
    items = load()
    items.insert(0, {"text": text, "ts": now if now is not None else time.time()})
    items = items[:MAX_ITEMS]
    save(items)
    return items


def clear() -> None:
    save([])


def label(index: int, item: "dict[str, Any]", max_len: int = LABEL_LEN) -> str:
    """Подпись пункта меню: номер + время + усечённый текст.

    Номер обязателен: rumps использует title как ключ меню, одинаковые
    диктовки без номера конфликтовали бы.
    """
    t = " ".join(item["text"].split())
    if len(t) > max_len:
        t = t[: max_len - 1] + "…"
    ts = item.get("ts") or 0
    when = time.strftime("%H:%M", time.localtime(ts)) if ts else "--:--"
    return f"{index}.  {when}  {t}"
