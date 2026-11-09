"""Словарь терминов Just Voice Type: «услышано → как писать».

Parakeet не принимает подсказок словаря, поэтому термины чинятся после
распознавания — детерминированно, без модели и без задержки.

Правило задаёт одну форму слова, а склонения подхватываются сами:
  • «фигма = Figma»  → «в фигме», «фигму», «фигмой» → «Figma»
    (бренд латиницей не склоняется — все формы схлопываются в него);
  • «хавар = ховер»  → «хавару» → «ховеру», «хаваром» → «ховером»
    (кириллица → окончание переносится).

Формы порождаются только от «словарной» формы — слова на согласную или
на -а длиной от 4 букв. Если ключ уже сам словоформа («пройде»), он
заменяется только точно: иначе можно задеть настоящие слова
(«пройду», «пройди»). Фразы из нескольких слов — только точно.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

MIN_EXPAND_LEN = 4

# падежные окончания (рус. + самые частые укр.) для основы на согласную…
_CONSONANT_ENDINGS = (
    "а", "у", "е", "ом", "ем", "ы", "и", "ов", "ам", "ами", "ах",
    "і", "ові", "ою",
)
# …и для слов на -а (окончание -а заменяется)
_A_ENDINGS = ("ы", "и", "е", "у", "ой", "ою", "ам", "ами", "ах", "і")

_CYR_WORD = re.compile(r"^[а-яёіїєґ]+$")
_LATIN = re.compile(r"[A-Za-z]")
_VOWELS = set("аеёиоуыэюяіїє")
_SEPARATOR = re.compile(r"\s*(?:->|→|=)\s*")


def _base_class(word: str) -> Optional[str]:
    """'cons' — кириллическое слово на согласную, 'a' — на -а; None —
    от этого слова формы не порождаем."""
    w = word.lower()
    if len(w) < MIN_EXPAND_LEN or not _CYR_WORD.match(w):
        return None
    last = w[-1]
    if last == "а":
        return "a"
    if last in _VOWELS or last in "ьй":
        return None
    return "cons"


def _forms(heard: str, wanted: str) -> "dict[str, str]":
    """Все формы одного правила: {услышанная форма: что вставить}."""
    out = {heard: wanted}
    cls = _base_class(heard)
    if cls is None:
        return out
    latin = bool(_LATIN.search(wanted))
    if not latin and _base_class(wanted) != cls:
        # «попапа → попап»: непонятно, как переносить окончание — только точно
        return out
    if cls == "cons":
        stem, endings, wanted_stem = heard, _CONSONANT_ENDINGS, wanted
    else:
        stem, endings, wanted_stem = heard[:-1], _A_ENDINGS, wanted[:-1]
    for ending in endings:
        out.setdefault(stem + ending, wanted if latin else wanted_stem + ending)
    return out


def build_table(rules: "dict[str, str]") -> "dict[str, str]":
    """Плоская таблица замен с формами. Явное правило всегда важнее
    порождённой формы другого правила."""
    explicit = {
        " ".join(k.lower().split()): v
        for k, v in rules.items()
        if isinstance(k, str) and k.strip() and isinstance(v, str)
    }
    table: "dict[str, str]" = {}
    for heard, wanted in explicit.items():
        for form, out in _forms(heard, wanted).items():
            if form not in explicit:
                table.setdefault(form, out)
    table.update(explicit)
    return table


def apply(text: str, rules: "dict[str, str]") -> str:
    """Заменить термины в тексте: целые слова/фразы, без учёта регистра,
    один проход (результат правила другими правилами не сканируется),
    длинное совпадение важнее короткого."""
    if not text or not rules:
        return text
    table = build_table(rules)
    if not table:
        return text
    keys = sorted(table, key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b", re.IGNORECASE
    )
    return pattern.sub(lambda m: table[m.group(0).lower()], text)


def parse_input(raw: str) -> Optional[Tuple[str, str]]:
    """«хавар = ховер» (или ->, →) → ("хавар", "ховер"). Услышанная часть
    приводится к нижнему регистру, нужная — как написана. None — не разобрать."""
    if not raw or not raw.strip():
        return None
    parts = _SEPARATOR.split(raw.strip())
    if len(parts) != 2:
        return None
    heard = " ".join(parts[0].lower().split())
    wanted = " ".join(parts[1].split())
    if not heard or not wanted:
        return None
    return heard, wanted
