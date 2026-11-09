"""Печать по ходу речи: какие слова и когда уходят в поле.

Печатаем по предложениям: предложение уходит в поле, когда его конец
(точка/вопрос/восклицание) подтверждён — так каждое предложение
распознаётся со всем своим контекстом, и на стыках не бывает «. и» / «, Но».
"""
import types
import unittest

import numpy as np

import live_typing
from live_typing import Agreement, LiveSession, Word

SR = 16000


def tok(text, start, end):
    return types.SimpleNamespace(text=text, start=start, end=end)


class TestWordsFromTokens(unittest.TestCase):
    def test_groups_subword_tokens_into_words_with_offset(self):
        tokens = [tok(" По", 0.0, 0.2), tok("смотри", 0.2, 0.5), tok(" в", 0.6, 0.7),
                  tok(" фиг", 0.8, 1.0), tok("ме", 1.0, 1.2)]
        words = live_typing.words_from_tokens(tokens, offset=10.0)
        self.assertEqual([w.text for w in words], ["Посмотри", "в", "фигме"])
        self.assertAlmostEqual(words[0].start, 10.0)
        self.assertAlmostEqual(words[2].end, 11.2)

    def test_first_token_without_space_still_starts_a_word(self):
        words = live_typing.words_from_tokens([tok("Да", 0.0, 0.3), tok(".", 0.3, 0.4)], 0.0)
        self.assertEqual([w.text for w in words], ["Да."])


def W(text, start, end):
    return Word(text, start, end)


# «Работает. И оно пишет» — конец предложения на первом слове
SENT = [W("Работает.", 0.0, 0.5), W("И", 0.6, 0.7), W("оно", 0.8, 1.0), W("пишет", 1.1, 1.4)]


def texts(words):
    return [w.text for w in words]


class TestAgreementCommitsWholeSentences(unittest.TestCase):
    def test_first_pass_commits_nothing(self):
        self.assertEqual(Agreement().update(SENT, audio_end=3.0), [])

    def test_agreed_words_mid_sentence_are_not_typed(self):
        a = Agreement()
        hyp = [W("Ну", 0.0, 0.2), W("да,", 0.3, 0.5), W("реально", 0.6, 1.0)]
        a.update(hyp, audio_end=3.0)
        self.assertEqual(a.update(hyp, audio_end=3.5), [])

    def test_sentence_confirmed_by_the_next_agreed_word(self):
        a = Agreement()
        a.update(SENT, audio_end=3.0)
        self.assertEqual(texts(a.update(SENT, audio_end=3.5)), ["Работает."])

    def test_period_that_turned_into_a_comma_is_not_a_boundary(self):
        a = Agreement()
        a.update(SENT, audio_end=3.0)
        flipped = [W("работает,", 0.0, 0.5)] + [W("и", 0.6, 0.7)] + SENT[2:]
        self.assertEqual(a.update(flipped, audio_end=3.5), [], "фраза продолжается")

    def test_sentence_confirmed_by_a_pause(self):
        a = Agreement()
        hyp = [W("Готово.", 0.0, 0.5)]
        a.update(hyp, audio_end=1.8)
        self.assertEqual(texts(a.update(hyp, audio_end=2.0)), ["Готово."])

    def test_unconfirmed_sentence_end_waits(self):
        a = Agreement()
        hyp = [W("Готово.", 0.0, 0.5)]
        a.update(hyp, audio_end=0.9)
        self.assertEqual(a.update(hyp, audio_end=1.0), [], "ни паузы, ни продолжения")

    def test_freshest_text_of_the_sentence_is_typed(self):
        a = Agreement()
        old = [W("Посмотри", 0.0, 0.4), W("фильме.", 0.5, 0.9), W("Там", 1.0, 1.2)]
        new = [W("Посмотри", 0.0, 0.4), W("фигме.", 0.5, 0.9), W("Там", 1.0, 1.2)]
        a.update(old, audio_end=3.0)
        # слово внутри ещё не напечатанного предложения поменялось — сверка
        # «двух проходов» сбрасывается, печатаем только когда устоится
        self.assertEqual(a.update(new, audio_end=3.5), [])
        self.assertEqual(texts(a.update(new, audio_end=4.0)), ["Посмотри", "фигме."])

    def test_long_sentence_without_period_is_cut_at_a_comma(self):
        a = Agreement()
        hyp = [W("раз", 0.0, 0.5), W("два,", 1.0, 1.5), W("три", 4.0, 4.5),
               W("четыре,", 6.0, 6.5), W("пять", 8.5, 9.0), W("шесть", 9.5, 10.0)]
        a.update(hyp, audio_end=11.0)
        self.assertEqual(
            texts(a.update(hyp, audio_end=11.5)), ["раз", "два,", "три", "четыре,"]
        )

    def test_next_sentence_after_a_commit(self):
        a = Agreement()
        a.update(SENT, audio_end=3.0)
        a.update(SENT, audio_end=3.5)  # «Работает.» напечатано
        nxt = SENT[1:] + [W("сразу.", 1.5, 1.9), W("Да", 2.0, 2.2)]
        a.update(nxt, audio_end=4.0)
        self.assertEqual(texts(a.update(nxt, audio_end=4.5)), ["И", "оно", "пишет", "сразу."])

    def test_jittered_timestamps_do_not_retype_the_sentence_end(self):
        a = Agreement()
        a.update(SENT, audio_end=3.0)
        a.update(SENT, audio_end=3.5)  # «Работает.» напечатано (конец 0.5)
        # следующий проход услышал «Работает.» чуть позже конца коммита
        shifted = [W("Работает.", 0.1, 0.6)] + SENT[1:] + [W("сразу.", 1.5, 1.9), W("Да", 2.0, 2.2)]
        a.update(shifted, audio_end=4.0)
        got = a.update(shifted, audio_end=4.5)
        self.assertEqual(texts(got), ["И", "оно", "пишет", "сразу."])

    def test_finish_returns_everything_not_yet_committed(self):
        a = Agreement()
        a.update(SENT, audio_end=3.0)
        a.update(SENT, audio_end=3.5)
        self.assertEqual(texts(a.finish(SENT)), ["И", "оно", "пишет"])


class _ScriptedModel:
    """Идеальный распознаватель: отдаёт слова сценария, уже прозвучавшие
    к концу переданного куска (с учётом сдвига окна сессии)."""

    def __init__(self, script):
        self.script = script
        self.session = None
        self.calls = 0

    def __call__(self, audio):
        self.calls += 1
        start = self.session.window_start
        end = start + len(audio) / SR
        return [
            Word(t, s - start, e - start) for t, s, e in self.script if e <= end and s >= start
        ]


SCRIPT = [
    ("Посмотри", 0.0, 0.5), ("в", 0.55, 0.6), ("фигме", 0.65, 1.1), ("макет.", 1.15, 1.6),
    ("Там", 1.8, 2.0), ("клод", 2.1, 2.4), ("код", 2.45, 2.8), ("работает.", 2.9, 3.5),
]
FULL = "Посмотри в Figma макет. Там Claude Code работает."
RULES = {"фигма": "Figma", "клод код": "Claude Code"}


def speech(sec):
    return np.full(int(sec * SR), 0.1, dtype=np.float32)


class TestLiveSession(unittest.TestCase):
    def _session(self, emit=None, script=SCRIPT):
        model = _ScriptedModel(script)
        out = []

        def default_emit(text):
            out.append(text)
            return True

        s = LiveSession(model, emit or default_emit, rules=RULES)
        model.session = s
        return s, model, out

    def test_types_sentence_by_sentence(self):
        s, _, out = self._session()
        for _ in range(8):  # 4 с: первое предложение подтверждено, второе ещё нет
            s.feed(speech(0.5))
        self.assertEqual(out, ["Посмотри в Figma макет."])
        s.finish(np.empty(0, dtype=np.float32))
        self.assertEqual("".join(out), FULL)
        self.assertEqual(s.text, FULL)

    def test_next_sentence_is_capitalized_after_a_typed_period(self):
        script = [("Готово.", 0.0, 0.5), ("и", 0.7, 0.9), ("дальше.", 1.0, 1.5)]
        s, _, out = self._session(script=script)
        for _ in range(6):
            s.feed(speech(0.5))
        s.finish(np.empty(0, dtype=np.float32))
        self.assertEqual("".join(out), "Готово. И дальше.")

    def test_silence_is_not_sent_to_the_model(self):
        s, model, out = self._session()
        for _ in range(4):
            s.feed(np.zeros(SR // 2, dtype=np.float32))
        self.assertEqual(model.calls, 0)
        self.assertEqual(out, [])

    def test_lone_hallucination_is_not_typed(self):
        model = _ScriptedModel([("Yeah.", 0.1, 0.4)])
        out = []
        s = LiveSession(model, lambda t: out.append(t) or True, rules={})
        model.session = s
        s.feed(speech(0.45))
        text = s.finish(np.empty(0, dtype=np.float32), accept=lambda t: t != "Yeah.")
        self.assertEqual(out, [])
        self.assertEqual(text, "")

    def test_focus_loss_stops_typing_and_keeps_the_rest(self):
        state = {"typed": 0}
        out = []

        def emit(text):
            if state["typed"] >= 1:
                return False  # окно сменилось
            state["typed"] += 1
            out.append(text)
            return True

        s, _, _ = self._session(emit)
        for _ in range(8):
            s.feed(speech(0.5))
        s.finish(np.empty(0, dtype=np.float32))
        self.assertEqual(out, ["Посмотри в Figma макет."])
        self.assertEqual(s.undelivered, "Там Claude Code работает.")
        self.assertEqual(s.text, FULL)


if __name__ == "__main__":
    unittest.main()
