"""Persistent settings for Just Voice Type.

Stored as JSON at ~/.config/just-voice-type/config.json (honors
$XDG_CONFIG_HOME). Pure I/O + validation, no GUI deps — unit-testable.
Depends only on the `languages` module.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any

import languages

APP_DIR_NAME = "just-voice-type"
CONFIG_FILE_NAME = "config.json"

DEFAULTS = {
    "favorite_languages": ["ru", "uk", "en"],
    "active_language": None,
    "hotkey": "right_option",
    # Default Raw keeps verbatim Whisper output (backward-compatible, no model
    # download). Users opt into Clean/Prompt via the Smart menu.
    "smart_mode": "raw",
    "vocabulary": [],
    # Whisper-модель, выбранная в меню Model. None = дефолт приложения.
    "model": None,
    # Способ вставки текста: "paste" (буфер+Cmd+V) или "ax" (Accessibility API).
    "insert_mode": "paste",
    # Словарь замен «как распозналось» -> «как надо», применяется к финальному
    # тексту (см. apply_replacements). Пусто = ничего не заменяем.
    "replacements": {},
}

SMART_MODES = ("raw", "clean", "prompt")
INSERT_MODES = ("paste", "ax")


def _defaults_copy() -> "dict[str, Any]":
    return {
        "favorite_languages": list(DEFAULTS["favorite_languages"]),
        "active_language": DEFAULTS["active_language"],
        "hotkey": DEFAULTS["hotkey"],
        "smart_mode": DEFAULTS["smart_mode"],
        "vocabulary": list(DEFAULTS["vocabulary"]),
        "model": DEFAULTS["model"],
        "insert_mode": DEFAULTS["insert_mode"],
        "replacements": dict(DEFAULTS["replacements"]),
    }


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), CONFIG_FILE_NAME)


def _validate(raw: Any) -> "dict[str, Any]":
    cfg = _defaults_copy()
    if not isinstance(raw, dict):
        return cfg

    favs = raw.get("favorite_languages")
    if isinstance(favs, list):
        seen = []
        for c in favs:
            if isinstance(c, str) and languages.is_valid(c) and c not in seen:
                seen.append(c)
        cfg["favorite_languages"] = seen

    active = raw.get("active_language")
    if active is None or (isinstance(active, str) and languages.is_valid(active)):
        cfg["active_language"] = active
    else:
        cfg["active_language"] = None

    hk = raw.get("hotkey")
    if isinstance(hk, str) and hk.strip():
        cfg["hotkey"] = hk.strip()

    mode = raw.get("smart_mode")
    if isinstance(mode, str) and mode in SMART_MODES:
        cfg["smart_mode"] = mode
    else:
        cfg["smart_mode"] = DEFAULTS["smart_mode"]

    vocab = raw.get("vocabulary")
    if isinstance(vocab, list):
        cfg["vocabulary"] = [
            v.strip() for v in vocab if isinstance(v, str) and v.strip()
        ]

    model = raw.get("model")
    if isinstance(model, str) and model.strip():
        cfg["model"] = model.strip()

    imode = raw.get("insert_mode")
    if isinstance(imode, str) and imode in INSERT_MODES:
        cfg["insert_mode"] = imode
    else:
        cfg["insert_mode"] = DEFAULTS["insert_mode"]

    reps = raw.get("replacements")
    if isinstance(reps, dict):
        cfg["replacements"] = {
            k.strip(): v.strip()
            for k, v in reps.items()
            if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
        }
    else:
        cfg["replacements"] = {}

    return cfg


def load() -> "dict[str, Any]":
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return _defaults_copy()
    except (json.JSONDecodeError, OSError) as e:
        print(f"[!] config load failed ({e}); using defaults", file=sys.stderr)
        return _defaults_copy()
    return _validate(raw)


def save(cfg: "dict[str, Any]") -> None:
    clean = _validate(cfg)
    d = config_dir()
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".config-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_path())
    except OSError as e:
        print(f"[!] config save failed: {e}", file=sys.stderr)
