"""Whisper-supported languages (code -> display name) + pure menu helpers.

Pure data and functions, no third-party deps — unit-testable without a GUI.
The code list mirrors openai-whisper's tokenizer LANGUAGES set.
"""
from __future__ import annotations

from typing import Optional

WHISPER_LANGUAGES: dict[str, str] = {
    "en": "English", "zh": "Chinese", "de": "German", "es": "Spanish",
    "ru": "Russian", "ko": "Korean", "fr": "French", "ja": "Japanese",
    "pt": "Portuguese", "tr": "Turkish", "pl": "Polish", "ca": "Catalan",
    "nl": "Dutch", "ar": "Arabic", "sv": "Swedish", "it": "Italian",
    "id": "Indonesian", "hi": "Hindi", "fi": "Finnish", "vi": "Vietnamese",
    "he": "Hebrew", "uk": "Ukrainian", "el": "Greek", "ms": "Malay",
    "cs": "Czech", "ro": "Romanian", "da": "Danish", "hu": "Hungarian",
    "ta": "Tamil", "no": "Norwegian", "th": "Thai", "ur": "Urdu",
    "hr": "Croatian", "bg": "Bulgarian", "lt": "Lithuanian", "la": "Latin",
    "mi": "Maori", "ml": "Malayalam", "cy": "Welsh", "sk": "Slovak",
    "te": "Telugu", "fa": "Persian", "lv": "Latvian", "bn": "Bengali",
    "sr": "Serbian", "az": "Azerbaijani", "sl": "Slovenian", "kn": "Kannada",
    "et": "Estonian", "mk": "Macedonian", "br": "Breton", "eu": "Basque",
    "is": "Icelandic", "hy": "Armenian", "ne": "Nepali", "mn": "Mongolian",
    "bs": "Bosnian", "kk": "Kazakh", "sq": "Albanian", "sw": "Swahili",
    "gl": "Galician", "mr": "Marathi", "pa": "Punjabi", "si": "Sinhala",
    "km": "Khmer", "sn": "Shona", "yo": "Yoruba", "so": "Somali",
    "af": "Afrikaans", "oc": "Occitan", "ka": "Georgian", "be": "Belarusian",
    "tg": "Tajik", "sd": "Sindhi", "gu": "Gujarati", "am": "Amharic",
    "yi": "Yiddish", "lo": "Lao", "uz": "Uzbek", "fo": "Faroese",
    "ht": "Haitian Creole", "ps": "Pashto", "tk": "Turkmen", "nn": "Nynorsk",
    "mt": "Maltese", "sa": "Sanskrit", "lb": "Luxembourgish", "my": "Myanmar",
    "bo": "Tibetan", "tl": "Tagalog", "mg": "Malagasy", "as": "Assamese",
    "tt": "Tatar", "haw": "Hawaiian", "ln": "Lingala", "ha": "Hausa",
    "ba": "Bashkir", "jw": "Javanese", "su": "Sundanese", "yue": "Cantonese",
}

AUTO_LABEL = "Auto"


def is_valid(code: str) -> bool:
    return code in WHISPER_LANGUAGES


def display_name(code: Optional[str]) -> str:
    if code is None:
        return AUTO_LABEL
    return WHISPER_LANGUAGES.get(code, code)


def sorted_all() -> "list[tuple[str, str]]":
    """All languages as (code, name) pairs sorted by display name."""
    return sorted(WHISPER_LANGUAGES.items(), key=lambda kv: kv[1].lower())


def top_section_codes(favorites, active):
    """Ordered codes for the top of the Language menu.

    Returns [None] (Auto) followed by favorite languages plus the active
    language (if it is a real language), de-duplicated and sorted by display
    name. Invalid codes are dropped.
    """
    codes = {c for c in favorites if is_valid(c)}
    if active is not None and is_valid(active):
        codes.add(active)
    ordered = sorted(codes, key=lambda c: display_name(c).lower())
    return [None] + ordered
