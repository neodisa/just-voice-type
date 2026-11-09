"""Печать по ходу речи (live typing) для Just Voice Type.

Встроенный потоковый режим parakeet-mlx (локальное внимание) на русской речи
выдаёт кашу, поэтому делаем по-другому: каждые ~0.4 с заново распознаём
«окно» последних секунд ПОЛНЫМ проходом модели (так же точно, как обычная
диктовка) и сверяем с прошлым проходом (LocalAgreement-2).

Печатаем ПРЕДЛОЖЕНИЯМИ. Напечатанное в чужом поле уже не исправить, а
модель, дослушав фразу, нередко меняет знак или слово в ней («работает.» →
«работает, и оно…»). Поэтому предложение уходит в поле, только когда его
конец подтверждён: точка (?, !) на одном и том же слове в двух проходах и
дальше либо следующее подтверждённое слово, либо пауза. Текст берём из
самого свежего прохода. Очень длинную фразу без точки печатаем до последней
подтверждённой запятой, чтобы не ждать слишком долго.

Тут только логика без модели и клавиатуры: распознавание и «печать»
передаются функциями, поэтому всё проверяется тестами.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

import streaming
import terms

# сколько нового звука копим между проходами модели
STEP_SEC = 0.4
# слова, кончающиеся ближе этого к краю звука, ещё не подтверждаем
HOLD_SEC = 0.3
# окно распознавания длиннее этого — подрезаем слева по подтверждённому
WINDOW_MAX_SEC = 15.0
# сколько уже напечатанного звука оставляем в окне как контекст
TRIM_KEEP_SEC = 1.0
# сколько слов хвоста сверяем, чтобы не напечатать слово второй раз
DEDUPE_MAX = 4
# пауза после точки, которой хватает, чтобы считать предложение законченным
PAUSE_SEC = 0.8
# фраза без точки дольше этого — печатаем до последней подтверждённой запятой
LONG_SENTENCE_SEC = 8.0
# …а если и запятой нет так долго — печатаем, оставив пару последних слов
HARD_CUT_SEC = 16.0

_TERMINAL = re.compile(r"[.!?…]['\"»)\]]*$")
_CLAUSE = re.compile(r"[,;:—]['\"»)\]]*$")
_ANY_PUNCT = re.compile(r"[^\w]$")


@dataclass
class Word:
    text: str
    start: float
    end: float

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2


def norm(s: str) -> str:
    return re.sub(r"[^\w]", "", s.lower())


def words_from_tokens(tokens, offset: float = 0.0) -> "list[Word]":
    """Токены модели (кусочки слов; начало слова — с пробела) → слова с
    временем начала/конца в секундах (+offset)."""
    words: "list[Word]" = []
    for t in tokens:
        text = t.text
        if text.startswith(" ") or not words:
            words.append(Word(text.strip(), t.start + offset, t.end + offset))
        else:
            words[-1].text += text
            words[-1].end = t.end + offset
    return [w for w in words if w.text]


class Agreement:
    """Решает, какие слова гипотезы уже можно печатать."""

    def __init__(self) -> None:
        self.committed_end = 0.0
        self._prev: "list[Word]" = []
        self._typed: "list[Word]" = []

    def _fresh(self, hyp: "list[Word]") -> "list[Word]":
        # всё, что по времени уже напечатано, отбрасываем (по середине
        # слова: границы между проходами чуть «плавают»)…
        cand = [w for w in hyp if w.mid > self.committed_end]
        # …и ведущие слова, которые повторяют хвост напечатанного и начались
        # до его конца — это то же слово, услышанное с другим таймингом
        if cand and self._typed and cand[0].start < self.committed_end:
            for j in range(min(DEDUPE_MAX, len(cand), len(self._typed)), 0, -1):
                if [norm(w.text) for w in cand[:j]] == [
                    norm(w.text) for w in self._typed[-j:]
                ]:
                    return cand[j:]
        return cand

    def _commit(self, words: "list[Word]") -> "list[Word]":
        if words:
            self.committed_end = words[-1].end
            self._typed.extend(words)
        return words

    def update(self, hyp: "list[Word]", audio_end: float) -> "list[Word]":
        """Очередная гипотеза окна → законченные предложения, которые пора
        печатать (пусто, если ни одно ещё не подтверждено)."""
        cand = self._fresh(hyp)
        prev = self._prev
        # подтверждённый префикс: те же слова, что в прошлом проходе, и не у
        # самого края звука
        k = 0
        limit = audio_end - HOLD_SEC
        while (
            k < min(len(cand), len(prev))
            and norm(cand[k].text) == norm(prev[k].text)
            and cand[k].end < limit
        ):
            k += 1
        cut = self._cut(cand, prev, k, audio_end)
        if cut is None:
            self._prev = cand
            return []
        self._prev = cand[cut + 1:]
        return self._commit(cand[: cut + 1])

    @staticmethod
    def _cut(cand, prev, k, audio_end) -> "Optional[int]":
        """Индекс последнего слова, по которое можно печатать, или None."""

        def both(pattern, i):
            return pattern.search(cand[i].text) and pattern.search(prev[i].text)

        cut = None
        for i in range(k):
            if not both(_TERMINAL, i):
                continue
            nxt = cand[i + 1].start if i + 1 < len(cand) else audio_end
            if i + 1 < k or nxt - cand[i].end >= PAUSE_SEC:
                cut = i
        if cut is not None or k == 0:
            return cut
        span = cand[k - 1].end - cand[0].start
        if span >= LONG_SENTENCE_SEC:
            # i ≤ k-2: следующее слово тоже подтверждено — запятая устоялась
            for i in range(k - 2, -1, -1):
                if both(_CLAUSE, i):
                    return i
        if span >= HARD_CUT_SEC and k >= 3:
            return k - 3
        return None

    def finish(self, hyp: "list[Word]") -> "list[Word]":
        """Финальная гипотеза (клавишу отпустили) → всё, что ещё не напечатано."""
        self._prev = []
        return self._commit(self._fresh(hyp))

    def trim_start(self, window_start: float, audio_end: float) -> float:
        if audio_end - window_start <= WINDOW_MAX_SEC:
            return window_start
        return max(window_start, self.committed_end - TRIM_KEEP_SEC)


def _multiword_prefixes(rules: "dict[str, str]") -> "set[tuple]":
    """Начала фраз-терминов («клод» из «клод код»): такие слова придерживаем,
    пока не станет ясно, не начало ли это фразы."""
    out = set()
    for key in rules:
        ws = [norm(w) for w in key.split()]
        for i in range(1, len(ws)):
            out.add(tuple(ws[:i]))
    return out


class LiveSession:
    """Одна диктовка в режиме печати по ходу речи.

    transcribe_words(audio16k) -> [Word] (время — от начала куска);
    emit(text) -> bool: напечатать текст; False — печатать больше нельзя
    (сменилось окно), остаток копится в `undelivered`.
    """

    def __init__(
        self,
        transcribe_words: Callable,
        emit: Callable[[str], bool],
        rules: "Optional[dict[str, str]]" = None,
        sr: int = 16000,
        step_sec: float = STEP_SEC,
    ) -> None:
        self._transcribe = transcribe_words
        self._emit = emit
        self._rules = dict(rules or {})
        self._prefixes = _multiword_prefixes(self._rules)
        self._sr = sr
        self._step = step_sec
        self._audio = np.empty(0, dtype=np.float32)
        self._since_pass = 0.0
        self.window_start = 0.0
        self._agree = Agreement()
        self._held: "list[Word]" = []
        self._typed: "list[str]" = []
        self._undelivered: "list[str]" = []
        self._diverted = False

    @property
    def audio_end(self) -> float:
        return len(self._audio) / self._sr

    @property
    def typed_text(self) -> str:
        return " ".join(self._typed)

    @property
    def undelivered(self) -> str:
        return " ".join(self._undelivered)

    @property
    def text(self) -> str:
        """Весь текст диктовки — напечатанный и не доставленный."""
        return " ".join(self._typed + self._undelivered)

    def feed(self, chunk) -> None:
        if chunk is None or len(chunk) == 0:
            return
        self._audio = np.concatenate([self._audio, chunk.astype(np.float32)])
        self._since_pass += len(chunk) / self._sr
        if self._since_pass >= self._step:
            self._since_pass = 0.0
            self._pass(final=False)

    def finish(self, tail=None, accept: "Optional[Callable[[str], bool]]" = None) -> str:
        """Клавишу отпустили: допечатать хвост. accept(text) — фильтр для
        диктовки, из которой ещё ничего не напечатано (галлюцинации модели
        на шуме вроде «Yeah.» не печатаем)."""
        if tail is not None and len(tail):
            self._audio = np.concatenate([self._audio, tail.astype(np.float32)])
        self._accept = accept
        self._pass(final=True)
        return self.text

    _accept: "Optional[Callable[[str], bool]]" = None

    def _pass(self, final: bool) -> None:
        seg = self._audio[int(round(self.window_start * self._sr)):]
        if len(seg) == 0 or streaming.is_silent(seg):
            hyp: "list[Word]" = []
        else:
            hyp = [
                Word(w.text, w.start + self.window_start, w.end + self.window_start)
                for w in self._transcribe(seg)
            ]
        if final:
            words = self._agree.finish(hyp)
        else:
            words = self._agree.update(hyp, self.audio_end)
            self.window_start = self._agree.trim_start(self.window_start, self.audio_end)
        self._output(words, final)

    def _hold_count(self) -> int:
        if not self._prefixes:
            return 0
        longest = max(len(p) for p in self._prefixes)
        for n in range(min(longest, len(self._held)), 0, -1):
            if tuple(norm(w.text) for w in self._held[-n:]) in self._prefixes:
                return n
        return 0

    def _output(self, words: "list[Word]", final: bool) -> None:
        self._held.extend(words)
        # фразу-термин («клод код») может разорвать только аварийный рез
        # длинной фразы без знаков — тогда придерживаем её начало
        open_end = self._held and not _ANY_PUNCT.search(self._held[-1].text)
        hold = self._hold_count() if (open_end and not final) else 0
        n = len(self._held) - hold
        if n <= 0:
            return
        batch, self._held = self._held[:n], self._held[n:]
        text = terms.apply(" ".join(w.text for w in batch), self._rules)
        if (
            final
            and text
            and self._accept is not None
            and not self._typed
            and not self._undelivered
            and not self._accept(text)
        ):
            return
        if text:
            self._deliver(text)

    def _deliver(self, text: str) -> None:
        # после напечатанной точки — новое предложение с заглавной, даже если
        # модель в более позднем проходе начала его со строчной
        done = self._typed + self._undelivered
        if done and _TERMINAL.search(done[-1]) and text[:1].islower():
            text = text[:1].upper() + text[1:]
        if self._diverted:
            self._undelivered.append(text)
            return
        piece = text if not self._typed else " " + text
        try:
            ok = bool(self._emit(piece))
        except Exception:
            ok = False
        if ok:
            self._typed.append(text)
        else:
            self._diverted = True
            self._undelivered.append(text)
