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
        # окно настроек (строки уходят в SwiftUI-хелпер как есть)
        "settings.window.title": "Настройки Just Voice Type",
        "settings.nav.general": "Основное",
        "settings.nav.recognition": "Распознавание",
        "settings.nav.calls": "Звонки",
        "settings.nav.terms": "Термины",
        "settings.nav.about": "О программе",
        "settings.general.lede": "Как вы диктуете и куда попадает текст.",
        "settings.general.group.dictation": "Диктовка",
        "settings.general.hotkey": "Клавиша",
        "settings.general.hotkey.caption": "Удерживайте, пока говорите. Двойное нажатие включает запись без удержания, одиночное останавливает.",
        "settings.general.live": "Печатать по ходу речи",
        "settings.general.live.caption": "Текст появляется по предложениям, пока вы говорите.",
        "settings.general.insert": "Вставка текста",
        "settings.general.insert.caption": "Через буфер работает везде. Напрямую не трогает буфер обмена, но работает не во всех приложениях.",
        "settings.general.group.app": "Приложение",
        "settings.general.ui_language": "Язык интерфейса",
        "settings.general.login": "Запускать при входе в систему",
        "settings.recognition.lede": "Модель, язык речи и обработка текста. Всё работает на этом Mac.",
        "settings.recognition.group.model": "Модель",
        "settings.recognition.model.default": "по умолчанию",
        "settings.recognition.model.retry": "Повторить",
        "settings.recognition.group.language": "Язык речи",
        "settings.recognition.language.caption": "«Авто» определяет язык сам. Закрепите язык, если он путается.",
        "settings.recognition.language.more": "Ещё языки…",
        "settings.recognition.sheet.title": "Языки речи",
        "settings.recognition.sheet.caption": "Отмеченные языки появятся быстрыми кнопками рядом с «Авто».",
        "settings.recognition.sheet.search": "Найти язык",
        "settings.recognition.sheet.empty": "Такого языка нет в списке.",
        "settings.recognition.sheet.count": "Отмечено: {n}",
        "settings.recognition.sheet.done": "Готово",
        "settings.recognition.group.processing": "Обработка текста",
        "settings.recognition.mode": "Режим",
        "settings.recognition.vocab": "Подсказки распознаванию",
        "settings.recognition.vocab.caption": "Имена и слова, которые модель должна знать. Работают только с моделями Whisper.",
        "settings.recognition.vocab.add": "Добавить",
        "settings.recognition.vocab.placeholder": "слово",
        "settings.calls.lede": "Запись и расшифровка разговоров в Teams, Zoom, WhatsApp и любых других приложениях.",
        "settings.calls.group.recent": "Последние звонки",
        "settings.calls.group.all": "Все звонки",
        "settings.calls.show_all": "Показать все {n}",
        "settings.calls.collapse": "Свернуть",
        "settings.calls.open_folder": "Открыть папку",
        "settings.calls.search": "Найти по расшифровке",
        "settings.calls.search.empty": "Ничего не нашлось по «{q}». Поиск идёт по началу расшифровок.",
        "settings.calls.missing": "Файл расшифровки удалён или перемещён.",
        "settings.calls.copy": "Скопировать расшифровку",
        "settings.calls.copied": "Скопировано",
        "settings.calls.open": "Открыть файл",
        "settings.calls.live.recording": "Идёт запись",
        "settings.calls.live.recording.caption": "Записываем вас и собеседника. Расшифровка начнётся после остановки.",
        "settings.calls.live.stop": "Остановить",
        "settings.calls.live.transcribing": "Расшифровываю звонок…",
        "settings.calls.empty.title": "Здесь появятся ваши звонки",
        "settings.calls.empty.caption": "Нажмите {key} или выберите «Записать звонок» в меню. Расшифровка сохранится в папку и появится в этом списке.",
        "settings.calls.empty.record": "Записать звонок",
        "settings.calls.group.recording": "Запись",
        "settings.calls.unsupported.title": "Автозахват недоступен на этой версии macOS",
        "settings.calls.unsupported.caption": "Нужна macOS 14.4 или новее. Пока можно записывать собеседника через виртуальное устройство, например BlackHole.",
        "settings.calls.unsupported.howto": "Как настроить",
        "settings.calls.hotkey": "Клавиша звонка",
        "settings.calls.hotkey.caption": "Первое нажатие начинает запись, второе останавливает.",
        "settings.calls.auto": "Записывать собеседника автоматически",
        "settings.calls.auto.caption": "Системный звук без виртуального драйвера, macOS 14.4 и новее. Записывается всё, что играет на Mac.",
        "settings.calls.device": "Устройство вручную",
        "settings.calls.device.none": "Не выбрано",
        "settings.calls.consent": "Запись разговора может требовать согласия собеседника.",
        "settings.terms.lede": "Как слово распознаётся и как его писать. Склонения подхватываются сами: «в фигме» станет «в Figma».",
        "settings.terms.search": "Найти термин",
        "settings.terms.add": "Добавить",
        "settings.terms.heard": "Слышится",
        "settings.terms.wanted": "Пишется",
        "settings.terms.save": "Сохранить",
        "settings.terms.cancel": "Отмена",
        "settings.terms.delete": "Удалить",
        "settings.terms.empty.title": "Научите распознавание вашим словам",
        "settings.terms.empty.caption": "Если модель пишет «фигма» вместо Figma, добавьте пару «фигма → Figma». Склонения подхватятся сами.",
        "settings.terms.empty.add": "Добавить первый термин",
        "settings.terms.search.empty": "Термина «{q}» нет.",
        "settings.terms.search.add": "Добавить «{q}»",
        "settings.terms.note": "Нажмите на строку, чтобы исправить. Изменения работают со следующей диктовки.",
        "settings.about.lede": "Быстрый голосовой ввод текста в любое приложение: зажали клавишу, сказали, текст на месте. Ещё умеет записывать и расшифровывать звонки. Всё распознаётся на этом Mac, звук никуда не уходит.",
        "settings.about.group.updates": "Обновления",
        "settings.about.update.check": "Проверить",
        "settings.about.update.retry": "Повторить",
        "settings.about.update.whatsnew": "Что нового",
        "settings.about.update.download": "Скачать",
        "settings.about.group.links": "Ссылки",
        "settings.about.links.open": "Открыть",
        "settings.about.links.show": "Показать в Finder",
        "settings.about.group.author": "Автор",
        "settings.about.author.caption": "Придумал и делает Just Voice Type. Идеи и ошибки присылайте через GitHub.",
        "settings.about.copyright": "© 2026 Sergey Arkhipov · лицензия MIT",
        "settings.common.undo": "Отменить",
        "settings.common.esc": "Esc",
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
        "settings.window.title": "Just Voice Type Settings",
        "settings.nav.general": "General",
        "settings.nav.recognition": "Recognition",
        "settings.nav.calls": "Calls",
        "settings.nav.terms": "Terms",
        "settings.nav.about": "About",
        "settings.general.lede": "How you dictate and where the text goes.",
        "settings.general.group.dictation": "Dictation",
        "settings.general.hotkey": "Key",
        "settings.general.hotkey.caption": "Hold while you speak. Double-press records hands-free, a single press stops.",
        "settings.general.live": "Type as you speak",
        "settings.general.live.caption": "Text appears sentence by sentence while you talk.",
        "settings.general.insert": "Text insertion",
        'settings.general.insert.caption': "Clipboard works everywhere. Direct leaves the clipboard alone but doesn't work in every app.",
        "settings.general.group.app": "App",
        "settings.general.ui_language": "Interface language",
        "settings.general.login": "Open at login",
        "settings.recognition.lede": "Model, speech language and text processing. Everything runs on this Mac.",
        "settings.recognition.group.model": "Model",
        "settings.recognition.model.default": "default",
        "settings.recognition.model.retry": "Retry",
        "settings.recognition.group.language": "Speech language",
        "settings.recognition.language.caption": "“Auto” detects the language itself. Pin a language if it gets confused.",
        "settings.recognition.language.more": "More languages…",
        "settings.recognition.sheet.title": "Speech languages",
        "settings.recognition.sheet.caption": "Checked languages appear as quick buttons next to “Auto”.",
        "settings.recognition.sheet.search": "Find a language",
        "settings.recognition.sheet.empty": "No such language in the list.",
        "settings.recognition.sheet.count": "Checked: {n}",
        "settings.recognition.sheet.done": "Done",
        "settings.recognition.group.processing": "Text processing",
        "settings.recognition.mode": "Mode",
        "settings.recognition.vocab": "Recognition hints",
        "settings.recognition.vocab.caption": "Names and words the model should know. Only Whisper models use them.",
        "settings.recognition.vocab.add": "Add",
        "settings.recognition.vocab.placeholder": "word",
        "settings.calls.lede": "Record and transcribe conversations in Teams, Zoom, WhatsApp and any other app.",
        "settings.calls.group.recent": "Recent calls",
        "settings.calls.group.all": "All calls",
        "settings.calls.show_all": "Show all {n}",
        "settings.calls.collapse": "Collapse",
        "settings.calls.open_folder": "Open folder",
        "settings.calls.search": "Search transcripts",
        "settings.calls.search.empty": "Nothing found for “{q}”. Search looks at the start of transcripts.",
        "settings.calls.missing": "Transcript file was deleted or moved.",
        "settings.calls.copy": "Copy transcript",
        "settings.calls.copied": "Copied",
        "settings.calls.open": "Open file",
        "settings.calls.live.recording": "Recording",
        "settings.calls.live.recording.caption": "Recording you and the other side. Transcription starts after you stop.",
        "settings.calls.live.stop": "Stop",
        "settings.calls.live.transcribing": "Transcribing the call…",
        "settings.calls.empty.title": "Your calls will show up here",
        "settings.calls.empty.caption": "Press {key} or choose “Record call” in the menu. The transcript is saved to a folder and listed here.",
        "settings.calls.empty.record": "Record call",
        "settings.calls.group.recording": "Recording",
        'settings.calls.unsupported.title': "Automatic capture isn't available on this macOS",
        "settings.calls.unsupported.caption": "Needs macOS 14.4 or later. Until then, record the other side through a virtual device such as BlackHole.",
        "settings.calls.unsupported.howto": "How to set up",
        "settings.calls.hotkey": "Call key",
        "settings.calls.hotkey.caption": "First press starts recording, the second stops it.",
        "settings.calls.auto": "Capture the other side automatically",
        "settings.calls.auto.caption": "System audio without a virtual driver, macOS 14.4 and later. Records everything playing on the Mac.",
        "settings.calls.device": "Manual device",
        "settings.calls.device.none": "Not selected",
        'settings.calls.consent': "Recording a conversation may require the other person's consent.",
        "settings.terms.lede": "How a word is recognised and how to write it. Inflections are handled automatically.",
        "settings.terms.search": "Find a term",
        "settings.terms.add": "Add",
        "settings.terms.heard": "Heard",
        "settings.terms.wanted": "Written",
        "settings.terms.save": "Save",
        "settings.terms.cancel": "Cancel",
        "settings.terms.delete": "Delete",
        "settings.terms.empty.title": "Teach recognition your words",
        "settings.terms.empty.caption": "If the model writes “figma” instead of Figma, add the pair “figma → Figma”.",
        "settings.terms.empty.add": "Add the first term",
        "settings.terms.search.empty": "No term “{q}”.",
        "settings.terms.search.add": "Add “{q}”",
        "settings.terms.note": "Click a row to edit it. Changes apply from the next dictation.",
        "settings.about.lede": "Fast voice text input into any app: hold a key, speak, the text is there. It can also record and transcribe calls. Everything is recognised on this Mac, audio never leaves it.",
        "settings.about.group.updates": "Updates",
        "settings.about.update.check": "Check",
        "settings.about.update.retry": "Retry",
        'settings.about.update.whatsnew': "What's new",
        "settings.about.update.download": "Download",
        "settings.about.group.links": "Links",
        "settings.about.links.open": "Open",
        "settings.about.links.show": "Show in Finder",
        "settings.about.group.author": "Author",
        "settings.about.author.caption": "Created and maintained Just Voice Type. Send ideas and bugs via GitHub.",
        "settings.about.copyright": "© 2026 Sergey Arkhipov · MIT license",
        "settings.common.undo": "Undo",
        "settings.common.esc": "Esc",
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


def t(msg_id: str, /, **kw: object) -> str:
    """Строка по ключу на текущем языке; нет перевода — английская,
    нет и её — сам ключ (так пропуск видно, но ничего не падает).
    msg_id позиционный: плейсхолдер {key} передаётся как key=..."""
    s = STRINGS.get(_current, {}).get(msg_id) or STRINGS[FALLBACK].get(msg_id) or msg_id
    return s.format(**kw) if kw else s


def key_name(hotkey: str) -> str:
    """Человеческое имя клавиши: right_option → «правый ⌥», f13 → «F13»."""
    s = t(f"key.{hotkey}")
    if s != f"key.{hotkey}":
        return s
    if hotkey[:1] == "f" and hotkey[1:].isdigit():
        return hotkey.upper()
    return hotkey
