"""Persistent call-recording transcripts for Just Voice Type.

Two things live here: the transcript **files** (one per call, under
~/Documents/JustVoiceType/Calls/ — visible and Finder-browsable, unlike the
dotfile config dir, since this is what the user goes and grabs manually) and
a lightweight **metadata list** (~/.config/just-voice-type/calls.json,
honors $XDG_CONFIG_HOME via the config module) holding {ts, duration_sec,
path, preview} — never the full text, so it stays small regardless of call
length. Pure I/O + formatting helpers, no GUI deps — unit-testable.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import Any, Optional

import config

CALLS_SUBDIR = "Calls"
CALLS_FILE_NAME = "calls.json"
MAX_ITEMS = 30
MENU_ITEMS = 10
LABEL_LEN = 60


def calls_dir() -> str:
    base = os.path.expanduser("~/Documents")
    return os.path.join(base, "JustVoiceType", CALLS_SUBDIR)


def calls_meta_path() -> str:
    return os.path.join(config.config_dir(), CALLS_FILE_NAME)


def transcript_path(ts: float) -> str:
    """Файл транскрипта для звонка с меткой времени `ts`; при коллизии имени
    (два звонка в одну и ту же минуту) добавляет -2, -3, … суффикс."""
    d = calls_dir()
    stamp = time.strftime("call-%Y-%m-%d_%H-%M", time.localtime(ts))
    base = os.path.join(d, f"{stamp}.txt")
    if not os.path.exists(base):
        return base
    n = 2
    while True:
        candidate = os.path.join(d, f"{stamp}-{n}.txt")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def start_transcript(ts: float) -> str:
    """Создать пустой файл транскрипта звонка на диске; вернуть его путь."""
    os.makedirs(calls_dir(), exist_ok=True)
    path = transcript_path(ts)
    with open(path, "w", encoding="utf-8"):
        pass
    return path


def format_timestamp(sec: "Optional[float]") -> str:
    """Смещение от начала звонка → MM:SS (или H:MM:SS для длинных звонков)."""
    try:
        s = int(sec or 0)
    except (TypeError, ValueError):
        s = 0
    if s < 0:
        s = 0
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{ss:02d}"
    return f"{m:02d}:{ss:02d}"


def format_line(sec: "Optional[float]", text: str) -> str:
    """Одна реплика транскрипта: «[MM:SS] текст» (пробелы схлопнуты)."""
    clean = " ".join((text or "").split())
    return f"[{format_timestamp(sec)}] {clean}"


def assemble(entries: "list[tuple[float, str]]") -> str:
    """Собрать транскрипт из реплик (ts, текст): отсортировать по времени
    (стабильно — при равном ts порядок поступления сохраняется), выбросить
    пустые, отформатировать построчно.

    Реплики двух дорожек звонка (микрофон и системный звук) распознаются
    отдельно и приходят вперемешку, поэтому хронологию восстанавливаем здесь.
    """
    items = [(ts, txt) for ts, txt in entries if txt and txt.strip()]
    items.sort(key=lambda it: it[0])
    return "\n".join(format_line(ts, txt) for ts, txt in items)


def append_chunk(path: str, text: str) -> None:
    """Дописать один распознанный кусок в файл транскрипта — устойчивость
    к падению приложения посреди долгого звонка: на диске всегда лежит
    «всё расшифрованное на данный момент», а не только финальный текст."""
    if not text or not text.strip():
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text.strip() + " ")
    except OSError as e:
        print(f"[!] call transcript append failed: {e}", file=sys.stderr)


def finalize(path: str, full_text: str) -> None:
    """Перезаписать файл транскрипта финальным (склеенным) текстом — куски
    на диске могли разрезать слово криво на границе чанка."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(full_text)


def load() -> "list[dict[str, Any]]":
    try:
        with open(calls_meta_path(), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as e:
        print(f"[!] calls load failed ({e}); starting empty", file=sys.stderr)
        return []
    if not isinstance(raw, list):
        return []
    items = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        path = it.get("path")
        preview = it.get("preview")
        if not isinstance(path, str) or not path or not isinstance(preview, str):
            continue
        try:
            ts = float(it.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        try:
            duration_sec = float(it.get("duration_sec") or 0.0)
        except (TypeError, ValueError):
            duration_sec = 0.0
        items.append(
            {"ts": ts, "duration_sec": duration_sec, "path": path, "preview": preview}
        )
    return items[:MAX_ITEMS]


def save(items: "list[dict[str, Any]]") -> None:
    d = config.config_dir()
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".calls-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items[:MAX_ITEMS], f, ensure_ascii=False, indent=2)
        os.replace(tmp, calls_meta_path())
    except OSError as e:
        print(f"[!] calls save failed: {e}", file=sys.stderr)


def add(
    path: str, full_text: str, duration_sec: float, now: "Optional[float]" = None
) -> "list[dict[str, Any]]":
    """Добавить звонок в начало списка метаданных; вернуть обновлённый список."""
    text = " ".join((full_text or "").split())
    if not text:
        return load()
    preview = text if len(text) <= LABEL_LEN else text[: LABEL_LEN - 1] + "…"
    items = load()
    items.insert(
        0,
        {
            "ts": now if now is not None else time.time(),
            "duration_sec": duration_sec,
            "path": path,
            "preview": preview,
        },
    )
    items = items[:MAX_ITEMS]
    save(items)
    return items


def clear() -> None:
    save([])


def label(index: int, item: "dict[str, Any]", max_len: int = LABEL_LEN) -> str:
    """Подпись пункта меню: номер + время + длительность + усечённое превью."""
    preview = item.get("preview", "")
    if len(preview) > max_len:
        preview = preview[: max_len - 1] + "…"
    ts = item.get("ts") or 0
    when = time.strftime("%H:%M", time.localtime(ts)) if ts else "--:--"
    dur = int(item.get("duration_sec") or 0)
    mins = dur // 60
    return f"{index}.  {when} ({mins} мин)  {preview}"
