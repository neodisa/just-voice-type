"""Модель окна настроек: снимок состояния для SwiftUI-хелпера и проверка
того, что окно просит поменять.

Чистая логика без GUI и без процесса приложения: всё, что окну нужно знать
о приложении, приходит в View; результат — словари протокола
(native/settings/PROTOCOL.md). Применение изменений — в voice_type.py.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple

import config
import i18n
import languages
import menubar_icon
import model_catalog

HOTKEYS = (
    "right_option", "left_option", "fn", "right_cmd", "left_cmd", "right_ctrl",
    "right_shift", "f13", "f14", "f15", "f16", "f17", "f18", "f19",
)
KEY_GLYPHS = {
    "right_option": "⌥", "left_option": "⌥", "right_cmd": "⌘", "left_cmd": "⌘",
    "right_ctrl": "⌃", "right_shift": "⇧",
}
SECTIONS = ("general", "recognition", "calls", "terms", "about")
LINK_IDS = ("github", "releases", "config", "logs", "call_setup", "update")
AUTHOR = {"name": "Sergey Arkhipov", "github": "neodisa"}
# плейсхолдеры, которые хелпер подставляет сам (зависят от его UI-состояния)
UI_LOCAL_PLACEHOLDERS = ("{n}", "{q}")


@dataclass
class View:
    """Всё, что окно настроек показывает о приложении."""

    version: str = "0.0.0"
    now: float = 0.0
    snapshot: menubar_icon.Snapshot = field(default_factory=menubar_icon.Snapshot)
    hotkey: str = "right_option"
    call_hotkey: str = "f13"
    live_typing: bool = True
    insert_mode: str = "paste"
    ui_language: str = "system"
    sound_theme: str = "default"
    system_language: str = "en"  # во что разрешается "system"
    login_available: bool = False
    login_enabled: bool = False
    model: str = model_catalog.MODELS[0].id
    cached_models: frozenset = frozenset()
    model_loading: bool = False
    model_progress: Optional[float] = None  # 0..1, если модель скачивается
    model_error: Optional[str] = None
    smart_mode: str = "raw"
    polish_cached: bool = True
    active_language: Optional[str] = None
    favorites: list = field(default_factory=list)
    vocabulary: list = field(default_factory=list)
    calls: list = field(default_factory=list)  # записи calls.load()
    call_state: str = "idle"
    call_started_at: Optional[float] = None
    auto_supported: bool = False
    auto_capture: bool = True
    call_stealth: bool = False
    call_detect: str = "ask"
    call_auto_stop: bool = True
    detect_supported: bool = False  # mic_users.is_supported(): macOS 14.2+
    call_device: Optional[str] = None
    input_devices: list = field(default_factory=list)
    terms: dict = field(default_factory=dict)  # replacements: услышано → как писать
    update: dict = field(default_factory=lambda: {"state": "idle"})
    logs_available: bool = True


# ── мелкие форматтеры ────────────────────────────────────────────────────
def _num(x: float) -> str:
    s = f"{x:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") if i18n.language() == "ru" else s


def _size(gb: float) -> str:
    return i18n.t("settings.size.gb", n=_num(gb))


def key_label(name: str) -> str:
    s = i18n.t(f"settings.key.{name}")
    if s != f"settings.key.{name}":
        return s
    return i18n.key_name(name)


def day_label(ts: float, now: float) -> str:
    d = _dt.datetime.fromtimestamp(ts).date()
    today = _dt.datetime.fromtimestamp(now).date()
    if d == today:
        return i18n.t("settings.date.today")
    if d == today - _dt.timedelta(days=1):
        return i18n.t("settings.date.yesterday")
    weekdays = i18n.t("settings.date.weekdays").split(",")
    months = i18n.t("settings.date.months").split(",")
    return i18n.t(
        "settings.date.format",
        weekday=weekdays[d.weekday()],
        day=d.day,
        month=months[d.month - 1],
    )


_LEADING_TS = re.compile(r"^\s*\[\d{1,2}:\d{2}(?::\d{2})?\]\s*")


def clean_preview(text) -> str:
    """Начало расшифровки без метки времени первой реплики («[00:00] »)."""
    return _LEADING_TS.sub("", str(text or "")).strip()


def system_language_name(code: str) -> str:
    return {"ru": "Русский", "en": "English"}.get(code, code)


def localized_language_name(code: str, ui_lang: str) -> str:
    """Название языка на языке интерфейса («немецкий» → «Немецкий»)."""
    try:
        from Foundation import NSLocale

        name = NSLocale.localeWithLocaleIdentifier_(ui_lang).localizedStringForLanguageCode_(code)
        if name:
            return str(name)[:1].upper() + str(name)[1:]
    except Exception:
        pass
    return languages.display_name(code)


# ── блоки снимка ─────────────────────────────────────────────────────────
def _option(value, label, glyph=None, note=None, disabled=False, separator_before=False):
    return {
        "value": value,
        "label": label,
        "glyph": glyph,
        "note": note,
        "disabled": disabled,
        "separator_before": separator_before,
    }


def _key_picker(value: str, taken: str, taken_note: str, caption: str) -> dict:
    opts = []
    if value not in HOTKEYS:
        opts.append(_option(value, value))
    for name in HOTKEYS:
        busy = name == taken
        opts.append(
            _option(
                name,
                key_label(name),
                glyph=KEY_GLYPHS.get(name),
                note=taken_note if busy else None,
                disabled=busy,
                separator_before=name == "f13",
            )
        )
    return {"value": value, "caption": caption, "disabled_reason": None, "options": opts}


def _toggle(value: bool, reason: Optional[str] = None, link: Optional[dict] = None) -> dict:
    return {"value": bool(value), "disabled_reason": reason, "link": link}


def live_typing_reason(v: View) -> Optional[str]:
    if model_catalog.is_parakeet(v.model) and v.smart_mode == "raw":
        return None
    return i18n.t("settings.live.reason")


def _general(v: View) -> dict:
    live_reason = live_typing_reason(v)
    return {
        "hotkey": _key_picker(
            v.hotkey, v.call_hotkey, i18n.t("settings.key.note.calls"),
            i18n.t("settings.general.hotkey.caption"),
        ),
        "live_typing": _toggle(
            v.live_typing and live_reason is None,
            live_reason,
            {"label": i18n.t("settings.live.link"), "section": "recognition"} if live_reason else None,
        ),
        "insert_mode": {
            "value": v.insert_mode,
            "caption": i18n.t("settings.general.insert.caption"),
            "disabled_reason": None,
            "options": [
                _option("paste", i18n.t("settings.insert.paste"), glyph="⌘V"),
                _option("ax", i18n.t("settings.insert.ax")),
            ],
        },
        "sounds": {
            "value": v.sound_theme,
            "caption": i18n.t("settings.general.sounds.caption"),
            "disabled_reason": None,
            "options": [
                _option(t, i18n.t(f"settings.sound.{t}"), separator_before=t == "macos")
                for t in config.SOUND_THEMES
            ],
        },
        "ui_language": {
            "value": v.ui_language,
            "caption": None,
            "disabled_reason": None,
            "options": [
                _option(
                    "system",
                    i18n.t("settings.uilang.system"),
                    note=i18n.t("settings.uilang.now", name=system_language_name(v.system_language)),
                ),
                _option("ru", "Русский", separator_before=True),
                _option("en", "English"),
            ],
        },
        "launch_at_login": _toggle(
            v.login_enabled and v.login_available,
            None if v.login_available else i18n.t("settings.login.reason"),
        ),
        "warning": None,
    }


def _model_entry(m_id, name, desc, size_gb, default, v: View) -> dict:
    selected = m_id == v.model
    cached = m_id in v.cached_models
    state, progress, note = ("ready" if cached else "absent"), None, None
    if not cached:
        note = i18n.t("settings.model.absent")
    if selected and v.model_error:
        state, note = "error", i18n.t("settings.model.error", error=v.model_error)
    elif selected and v.model_loading:
        if cached or v.model_progress is None:
            state, note = "loading", i18n.t("settings.model.loading")
        else:
            state, progress = "downloading", round(float(v.model_progress), 3)
            note = i18n.t(
                "settings.model.downloading",
                percent=int(progress * 100),
                size=_size(size_gb) if size_gb else "?",
            )
    return {
        "id": m_id,
        "name": name,
        "desc": desc,
        "size": _size(size_gb) if size_gb else "",
        "default": default,
        "selected": selected,
        "state": state,
        "progress": progress,
        "note": note,
    }


def _recognition(v: View, lang_name: Callable[[str, str], str]) -> dict:
    ui = i18n.language()
    models = [
        _model_entry(m.id, m.name, i18n.t(f"settings.model.{m.slug}.desc"), m.size_gb, m.default, v)
        for m in model_catalog.MODELS
    ]
    if model_catalog.get(v.model) is None:
        models.append(_model_entry(v.model, model_catalog.display_name(v.model), "", 0.0, False, v))
    chips = [{"value": None, "label": i18n.t("settings.lang.auto")}]
    for code in languages.top_section_codes(v.favorites, v.active_language):
        if code is not None:
            chips.append({"value": code, "label": lang_name(code, ui)})
    sheet = [
        {
            "code": code,
            "name": lang_name(code, ui),
            "english": english,
            "favorite": code in v.favorites,
            "locked": code == v.active_language,
        }
        for code, english in languages.WHISPER_LANGUAGES.items()
    ]
    sheet.sort(key=lambda l: l["name"].casefold())
    download = "" if v.polish_cached else " " + i18n.t(
        "settings.mode.download", size=_size(model_catalog.POLISH_SIZE_GB)
    )
    modes = []
    for mode in config.SMART_MODES:
        caption = i18n.t(f"settings.mode.{mode}.caption")
        if mode != "raw":
            caption += download
        modes.append({"value": mode, "label": i18n.t(f"settings.mode.{mode}"), "caption": caption})
    return {
        "models": models,
        "language": {"value": v.active_language, "chips": chips},
        "languages": sheet,
        "smart_mode": {"value": v.smart_mode, "disabled_reason": None, "options": modes},
        "vocabulary": {
            "items": list(v.vocabulary),
            "enabled": not model_catalog.is_parakeet(v.model),
        },
    }


def _calls(v: View, exists: Callable[[str], bool]) -> dict:
    items = []
    for c in v.calls:
        ts = float(c.get("ts") or 0.0)
        path = str(c.get("path") or "")
        items.append({
            "id": path,
            "day": day_label(ts, v.now),
            "time": _dt.datetime.fromtimestamp(ts).strftime("%H:%M"),
            "duration": menubar_icon.fmt_elapsed(float(c.get("duration_sec") or 0.0)),
            "preview": clean_preview(c.get("preview")),
            "missing": not (path and exists(path)),
        })
    auto_on = v.auto_capture and v.auto_supported
    detect_reason = None if v.detect_supported else i18n.t("settings.calls.detect.reason")
    dev_opts = [_option(d, d) for d in v.input_devices]
    if v.call_device and v.call_device not in v.input_devices:
        dev_opts.insert(0, _option(v.call_device, v.call_device, note=i18n.t("settings.device.missing")))
    return {
        "count": len(items),
        "live": {
            "state": v.call_state,
            "started_at": v.call_started_at if v.call_state == "recording" else None,
        },
        "items": items,
        "auto_supported": v.auto_supported,
        "call_hotkey": _key_picker(
            v.call_hotkey, v.hotkey, i18n.t("settings.key.note.dictation"),
            i18n.t("settings.calls.hotkey.caption"),
        ),
        "auto_capture": _toggle(
            auto_on, None if v.auto_supported else i18n.t("settings.auto.reason")
        ),
        "stealth": _toggle(v.call_stealth),
        "detect": {
            "value": v.call_detect if v.detect_supported else "off",
            "caption": i18n.t("settings.calls.detect.caption"),
            "disabled_reason": detect_reason,
            "options": [
                _option(m, i18n.t(f"settings.calls.detect.{m}")) for m in config.CALL_DETECT_MODES
            ],
        },
        "auto_stop": _toggle(v.call_auto_stop and v.detect_supported, detect_reason),
        "device": {
            "value": v.call_device,
            "caption": i18n.t("settings.device.caption"),
            "disabled_reason": i18n.t("settings.device.reason") if auto_on else None,
            "options": dev_opts,
        },
    }


def _about(v: View) -> dict:
    u = v.update or {}
    state = u.get("state", "idle")
    text = None
    if state == "checking":
        text = i18n.t("settings.update.checking")
    elif state == "uptodate":
        at = u.get("checked_at")
        hhmm = _dt.datetime.fromtimestamp(at).strftime("%H:%M") if at else "—"
        text = i18n.t("settings.update.uptodate", time=hhmm)
    elif state == "update":
        text = i18n.t("settings.update.available.caption")
    elif state == "error":
        text = i18n.t("settings.update.error")
    links = [
        {"id": "github", "label": i18n.t("settings.links.github"), "button": i18n.t("settings.about.links.open")},
        {"id": "config", "label": i18n.t("settings.links.config"), "button": i18n.t("settings.about.links.show")},
    ]
    if v.logs_available:
        links.append({"id": "logs", "label": i18n.t("settings.links.logs"), "button": i18n.t("settings.about.links.show")})
    return {
        "update": {"state": state, "text": text, "version": u.get("version") if state == "update" else None},
        "links": links,
        "author": dict(AUTHOR),
    }


def _status(v: View) -> dict:
    snap = v.snapshot
    k = menubar_icon.kind(snap)
    st = menubar_icon.status(snap)
    timer = None
    if k == "ready":
        text = i18n.t("settings.status.ready", model=model_catalog.display_name(v.model))
    elif k in ("recording", "handsfree"):
        text, timer = i18n.t("settings.status.recording"), snap.now - snap.rec_elapsed
    elif k == "call_recording":
        text, timer = i18n.t("settings.status.call"), snap.now - snap.call_elapsed
    else:
        text = st.text
    return {"dot": st.dot, "text": text, "timer_since": timer}


def _strings(v: View) -> dict:
    fill = {
        "{key}": key_label(v.call_hotkey),
        "{version}": str((v.update or {}).get("version") or ""),
    }
    out = {}
    for k, s in i18n.STRINGS[i18n.FALLBACK].items():
        if not k.startswith("settings."):
            continue
        text = i18n.t(k)
        for ph, val in fill.items():
            text = text.replace(ph, val)
        out[k[len("settings."):]] = text
    return out


def build(
    v: View,
    *,
    rev: int,
    ack: Optional[str] = None,
    errors: Optional[dict] = None,
    exists: Callable[[str], bool] = os.path.exists,
    lang_name: Callable[[str, str], str] = localized_language_name,
) -> dict:
    """Полный снимок `state` для хелпера (см. PROTOCOL.md)."""
    return {
        "type": "state",
        "rev": rev,
        "ack": ack,
        "lang": i18n.language(),
        "strings": _strings(v),
        "errors": dict(errors or {}),
        "data": {
            "version": v.version,
            "status": _status(v),
            "general": _general(v),
            "recognition": _recognition(v, lang_name),
            "calls": _calls(v, exists),
            "terms": {"items": term_items(v.terms)},
            "about": _about(v),
        },
    }


# ── проверка `set` ───────────────────────────────────────────────────────
def validate_set(v: View, key: str, value: Any) -> "Tuple[Any, Optional[str]]":
    """(нормализованное значение, None) или (None, текст ошибки)."""
    invalid = (None, i18n.t("settings.err.invalid"))
    unavailable = (None, i18n.t("settings.err.unavailable"))
    if key in ("hotkey", "call_hotkey"):
        if value not in HOTKEYS:
            return invalid
        other = v.call_hotkey if key == "hotkey" else v.hotkey
        if value == other:
            err = "settings.err.key_calls" if key == "hotkey" else "settings.err.key_dictation"
            return None, i18n.t(err)
        return value, None
    if key == "insert_mode":
        return (value, None) if value in config.INSERT_MODES else invalid
    if key == "ui_language":
        return (value, None) if value in config.UI_LANGUAGES else invalid
    if key == "smart_mode":
        return (value, None) if value in config.SMART_MODES else invalid
    if key == "sound_theme":
        return (value, None) if value in config.SOUND_THEMES else invalid
    if key == "call_detect":
        if value not in config.CALL_DETECT_MODES:
            return invalid
        if value == "ask" and not v.detect_supported:
            return unavailable
        return value, None
    if key in ("live_typing", "launch_at_login", "auto_system_audio", "call_stealth", "call_auto_stop"):
        if not isinstance(value, bool):
            return invalid
        if value and key == "live_typing" and live_typing_reason(v) is not None:
            return unavailable
        if value and key == "launch_at_login" and not v.login_available:
            return unavailable
        if value and key == "auto_system_audio" and not v.auto_supported:
            return unavailable
        if value and key == "call_auto_stop" and not v.detect_supported:
            return unavailable
        return value, None
    if key == "model":
        if isinstance(value, str) and (model_catalog.get(value) or value == v.model):
            return value, None
        return invalid
    if key == "active_language":
        if value is None or (isinstance(value, str) and languages.is_valid(value)):
            return value, None
        return invalid
    if key == "call_device":
        if isinstance(value, str) and (value in v.input_devices or value == v.call_device):
            return value, None
        return invalid
    return invalid


# ── термины и подсказки ──────────────────────────────────────────────────
def term_items(terms: dict) -> list:
    """Как термины показываются в окне: новые сверху. Индексы действий
    term_update/term_delete — позиции в этом списке."""
    return [{"heard": h, "wanted": w} for h, w in reversed(list(terms.items()))]


def _norm(heard: str, wanted: str) -> "Tuple[str, str]":
    return " ".join(str(heard or "").lower().split()), " ".join(str(wanted or "").split())


def _dup(terms: dict, heard: str, skip: Optional[str] = None) -> Optional[str]:
    for k in terms:
        if k.casefold() == heard.casefold() and k != skip:
            return k
    return None


def term_add(terms: dict, heard: str, wanted: str) -> "Tuple[dict, Optional[str]]":
    h, w = _norm(heard, wanted)
    if not h or not w:
        return terms, i18n.t("settings.err.term_empty")
    d = _dup(terms, h)
    if d is not None:
        return terms, i18n.t("settings.err.term_dup", heard=d, wanted=terms[d])
    new = dict(terms)
    new[h] = w
    return new, None


def term_update(terms: dict, index: int, heard: str, wanted: str) -> "Tuple[dict, Optional[str]]":
    items = list(terms.items())
    pos = len(items) - 1 - index if isinstance(index, int) else -1
    if not 0 <= pos < len(items):
        return terms, i18n.t("settings.err.invalid")
    h, w = _norm(heard, wanted)
    if not h or not w:
        return terms, i18n.t("settings.err.term_empty")
    old_key = items[pos][0]
    d = _dup(terms, h, skip=old_key)
    if d is not None:
        return terms, i18n.t("settings.err.term_dup", heard=d, wanted=terms[d])
    items[pos] = (h, w)
    return dict(items), None


def term_delete(terms: dict, index: int) -> "Tuple[dict, Optional[Tuple[str, str]]]":
    items = list(terms.items())
    pos = len(items) - 1 - index if isinstance(index, int) else -1
    if not 0 <= pos < len(items):
        return terms, None
    deleted = items.pop(pos)
    return dict(items), deleted


def vocab_add(vocab: list, word: str) -> "Tuple[list, Optional[str]]":
    w = " ".join(str(word or "").split())
    if not w:
        return vocab, i18n.t("settings.err.invalid")
    if any(x.casefold() == w.casefold() for x in vocab):
        return vocab, i18n.t("settings.err.vocab_dup")
    return list(vocab) + [w], None


def vocab_remove(vocab: list, index: int) -> list:
    if not isinstance(index, int) or not 0 <= index < len(vocab):
        return vocab
    return [x for i, x in enumerate(vocab) if i != index]
