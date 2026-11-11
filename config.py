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
    # Хоткей для режима звонков (Call Mode) — toggle, независимый от
    # основного хоткея диктовки.
    "call_hotkey": "f13",
    # Устройство записи для звонков (имя из sounddevice.query_devices(),
    # обычно Aggregate Device: микрофон + виртуальный loopback). None = не
    # настроено — тогда Call Mode пишет через авто-захват или голый микрофон.
    "call_device": None,
    # Авто-захват системного звука в Call Mode через Core Audio process tap
    # (macOS 14.4+, Swift-хелпер). True = пытаться автоматически; иначе ручной
    # Call Device. См. system_audio.choose_source.
    "auto_system_audio": True,
    # Печать по ходу речи: слова появляются в поле, пока вы говорите (только
    # Parakeet и режим Raw). False — текст вставляется целиком в конце.
    "live_typing": True,
    # Язык интерфейса: "system" — по языку системы (см. i18n.resolve),
    # "ru" / "en" — выбран вручную в настройках.
    "ui_language": "system",
    # Стиль звуков: стили cuelume (default/mech/bubble/press), "macos" —
    # системные Tink/Pop/Ping/Basso, "off" — тишина. См. sounds.py.
    "sound_theme": "default",
    # Скрытая запись звонков: иконка в строке меню не показывает звонок,
    # звуки звонка и уведомление о расшифровке молчат. Статус — только в меню.
    "call_stealth": False,
    # Определение звонков по микрофону (call_detect.py): "ask" — когда другая
    # программа держит микрофон, предложить запись уведомлением; "off" — нет.
    "call_detect": "ask",
    # Останавливать запись, когда программа звонка отпустила микрофон и
    # замолчала (call_detect.STOP_AFTER_SEC).
    "call_auto_stop": True,
}

SMART_MODES = ("raw", "clean", "prompt")
INSERT_MODES = ("paste", "ax")
UI_LANGUAGES = ("system", "ru", "en")
# совпадает с sounds.THEMES (тест следит), здесь — чтобы config не тянул sounds
SOUND_THEMES = ("default", "mech", "bubble", "press", "macos", "off")
# совпадает с call_detect.MODES (тест следит)
CALL_DETECT_MODES = ("ask", "off")


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
        "call_hotkey": DEFAULTS["call_hotkey"],
        "call_device": DEFAULTS["call_device"],
        "auto_system_audio": DEFAULTS["auto_system_audio"],
        "live_typing": DEFAULTS["live_typing"],
        "ui_language": DEFAULTS["ui_language"],
        "sound_theme": DEFAULTS["sound_theme"],
        "call_stealth": DEFAULTS["call_stealth"],
        "call_detect": DEFAULTS["call_detect"],
        "call_auto_stop": DEFAULTS["call_auto_stop"],
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

    call_hk = raw.get("call_hotkey")
    if isinstance(call_hk, str) and call_hk.strip():
        cfg["call_hotkey"] = call_hk.strip()

    call_dev = raw.get("call_device")
    if isinstance(call_dev, str) and call_dev.strip():
        cfg["call_device"] = call_dev.strip()

    asa = raw.get("auto_system_audio")
    if isinstance(asa, bool):
        cfg["auto_system_audio"] = asa
    else:
        cfg["auto_system_audio"] = DEFAULTS["auto_system_audio"]

    live = raw.get("live_typing")
    cfg["live_typing"] = live if isinstance(live, bool) else DEFAULTS["live_typing"]

    ui_lang = raw.get("ui_language")
    cfg["ui_language"] = ui_lang if ui_lang in UI_LANGUAGES else DEFAULTS["ui_language"]

    theme = raw.get("sound_theme")
    cfg["sound_theme"] = theme if theme in SOUND_THEMES else DEFAULTS["sound_theme"]

    stealth = raw.get("call_stealth")
    cfg["call_stealth"] = stealth if isinstance(stealth, bool) else DEFAULTS["call_stealth"]

    detect = raw.get("call_detect")
    cfg["call_detect"] = detect if detect in CALL_DETECT_MODES else DEFAULTS["call_detect"]

    auto_stop = raw.get("call_auto_stop")
    cfg["call_auto_stop"] = auto_stop if isinstance(auto_stop, bool) else DEFAULTS["call_auto_stop"]

    # звонок и диктовка не могут висеть на одной и той же клавише
    if cfg["call_hotkey"] == cfg["hotkey"]:
        cfg["call_hotkey"] = (
            "f14" if DEFAULTS["call_hotkey"] == cfg["hotkey"] else DEFAULTS["call_hotkey"]
        )

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


def update(**changes: Any) -> "dict[str, Any]":
    """Перечитать конфиг с диска, поменять только переданные ключи и
    сохранить. Всё остальное (словарь замен, vocabulary, правки руками в
    файле) остаётся как было. Возвращает сохранённый конфиг."""
    cfg = load()
    cfg.update(changes)
    save(cfg)
    return _validate(cfg)


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
