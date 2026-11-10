"""Строки интерфейса Just Voice Type (RU/EN) и выбор языка.

Чистый модуль без GUI. Язык берётся из настройки ui_language
("system" | "ru" | "en"): "system" — первый поддерживаемый язык из
списка предпочитаемых языков macOS, иначе английский.
Новый язык = ещё одна таблица в STRINGS с теми же ключами
(тест tests/test_i18n.py следит, чтобы ключи и плейсхолдеры совпадали).
"""
from __future__ import annotations

import os
from typing import Iterable

SUPPORTED = ("ru", "en")
FALLBACK = "en"

STRINGS: "dict[str, dict[str, str]]" = {
    "ru": {
        # строка статуса сверху меню
        "status.ready": "Готов · удерживайте {key}",
        "status.recording": "Записываю · {time}",
        "status.handsfree": "Записываю · {time} · нажмите {key}, чтобы остановить",
        "status.transcribing": "Распознаю…",
        "status.inserted": "Готово",
        "status.loading_model": "Загружаю модель {model}…",
        "status.downloading_model": "Скачиваю модель {model}…",
        "status.paused": "На паузе",
        "status.call_recording": "Запись звонка · {time}",
        "status.call_transcribing": "Расшифровываю звонок…",
        "status.audio_dead": "Аудиосистема не отвечает — перезагрузите Mac",
        # названия клавиш
        "key.right_option": "правый ⌥",
        "key.left_option": "левый ⌥",
        "key.fn": "Fn",
        "key.right_cmd": "правый ⌘",
        "key.left_cmd": "левый ⌘",
        "key.right_ctrl": "правый ⌃",
        "key.right_shift": "правый ⇧",
    },
    "en": {
        "status.ready": "Ready · hold {key}",
        "status.recording": "Recording · {time}",
        "status.handsfree": "Recording · {time} · press {key} to stop",
        "status.transcribing": "Transcribing…",
        "status.inserted": "Done",
        "status.loading_model": "Loading model {model}…",
        "status.downloading_model": "Downloading model {model}…",
        "status.paused": "Paused",
        "status.call_recording": "Recording call · {time}",
        "status.call_transcribing": "Transcribing call…",
        "status.audio_dead": "Audio system not responding — restart your Mac",
        "key.right_option": "right ⌥",
        "key.left_option": "left ⌥",
        "key.fn": "Fn",
        "key.right_cmd": "right ⌘",
        "key.left_cmd": "left ⌘",
        "key.right_ctrl": "right ⌃",
        "key.right_shift": "right ⇧",
    },
}

_current = FALLBACK


def resolve(setting: str, preferred: "Iterable[str]") -> str:
    """Язык интерфейса по настройке и предпочитаемым языкам системы."""
    if setting in SUPPORTED:
        return setting
    for tag in preferred or ():
        code = str(tag).replace("_", "-").split("-")[0].split(".")[0].lower()
        if code in SUPPORTED:
            return code
    return FALLBACK


def system_languages() -> "list[str]":
    """Предпочитаемые языки macOS (["en-PL", "ru-PL", ...])."""
    try:
        from Foundation import NSLocale

        return [str(x) for x in NSLocale.preferredLanguages()]
    except Exception:
        lang = os.environ.get("LANG", "")
        return [lang] if lang else []


def set_language(code: str) -> None:
    global _current
    _current = code if code in SUPPORTED else FALLBACK


def language() -> str:
    return _current


def t(key: str, **kw: object) -> str:
    """Строка по ключу на текущем языке; нет перевода — английская,
    нет и её — сам ключ (так пропуск видно, но ничего не падает)."""
    s = STRINGS.get(_current, {}).get(key) or STRINGS[FALLBACK].get(key) or key
    return s.format(**kw) if kw else s


def key_name(hotkey: str) -> str:
    """Человеческое имя клавиши: right_option → «правый ⌥», f13 → «F13»."""
    s = t(f"key.{hotkey}")
    if s != f"key.{hotkey}":
        return s
    if hotkey[:1] == "f" and hotkey[1:].isdigit():
        return hotkey.upper()
    return hotkey
