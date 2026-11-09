"""Печать по ходу речи: какие слова и когда уходят в поле."""
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


class TestAgreement(unittest.TestCase):
    def test_first_pass_commits_nothing(self):
        a = Agreement()
        self.assertEqual(a.update([W("раз", 0, 0.3), W("два", 0.4, 0.7)], audio_end=2.0), [])

    def test_commits_common_prefix_of_two_passes(self):
        a = Agreement()
        a.update([W("раз", 0, 0.3), W("два", 0.4, 0.7)], audio_end=2.0)
        got = a.update([W("раз", 0, 0.3), W("три", 0.4, 0.7)], audio_end=2.5)
        self.assertEqual([w.text for w in got], ["раз"])

    def test_does_not_commit_words_at_the_audio_edge(self):
        a = Agreement()
        hyp = [W("раз", 0, 0.3), W("два", 0.4, 0.95)]
        a.update(hyp, audio_end=1.0)
        got = a.update(hyp, audio_end=1.0)
        self.assertEqual([w.text for w in got], ["раз"], "«два» ещё может измениться")

    def test_jittered_timestamps_do_not_retype_a_word(self):
        a = Agreement()
        a.update([W("там", 1.0, 1.4), W("кнопка", 1.5, 2.0)], audio_end=3.0)
        a.update([W("там", 1.0, 1.4), W("кнопка", 1.5, 2.0)], audio_end=3.5)
        # следующий проход сдвинул границы «кнопка» чуть позже конца коммита
        got = a.update(
            [W("кнопка", 1.55, 2.05), W("синяя", 2.1, 2.5)], audio_end=4.0
        )
        self.assertEqual(got, [])
        got = a.update(
            [W("кнопка", 1.6, 2.1), W("синяя", 2.1, 2.5)], audio_end=4.5
        )
        self.assertEqual([w.text for w in got], ["синяя"])

    def test_comparison_ignores_case_and_punctuation(self):
        a = Agreement()
        a.update([W("макет", 0, 0.5), W("там", 0.6, 0.8)], audio_end=3.0)
        got = a.update([W("макет,", 0, 0.5), W("там", 0.6, 0.8)], audio_end=3.5)
        self.assertEqual([w.text for w in got], ["макет,", "там"], "печатаем свежую версию")

    def test_finish_returns_everything_not_yet_committed(self):
        a = Agreement()
        a.update([W("раз", 0, 0.3)], audio_end=2.0)
        a.update([W("раз", 0, 0.3)], audio_end=2.5)
        rest = a.finish([W("раз", 0, 0.3), W("два", 0.4, 0.7), W("три.", 0.8, 1.0)])
        self.assertEqual([w.text for w in rest], ["два", "три."])


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
    ("Посмотри", 0.0, 0.5), ("в", 0.55, 0.6), ("фигме", 0.65, 1.1),
    ("макет,", 1.15, 1.6), ("там", 1.8, 2.0), ("клод", 2.1, 2.4),
    ("код", 2.45, 2.8), ("работает.", 2.9, 3.5),
]
RULES = {"фигма": "Figma", "клод код": "Claude Code"}


def speech(sec):
    return np.full(int(sec * SR), 0.1, dtype=np.float32)


class TestLiveSession(unittest.TestCase):
    def _session(self, emit=None):
        model = _ScriptedModel(SCRIPT)
        out = []

        def default_emit(text):
            out.append(text)
            return True

        s = LiveSession(model, emit or default_emit, rules=RULES)
        model.session = s
        return s, model, out

    def test_types_incrementally_and_ends_with_the_full_text(self):
        s, _, out = self._session()
        for _ in range(8):  # 4 с речи кусками по 0.5 с
            s.feed(speech(0.5))
        typed_before_finish = "".join(out)
        s.finish(np.empty(0, dtype=np.float32))
        self.assertTrue(typed_before_finish, "ничего не напечатано, пока говорили")
        self.assertEqual("".join(out), "Посмотри в Figma макет, там Claude Code работает.")
        self.assertEqual(s.text, "Посмотри в Figma макет, там Claude Code работает.")

    def test_multiword_term_is_not_split_across_pieces(self):
        s, _, out = self._session()
        for _ in range(8):
            s.feed(speech(0.5))
        s.finish(np.empty(0, dtype=np.float32))
        self.assertFalse(any(piece.rstrip().endswith("клод") for piece in out))

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

    def test_accept_check_does_not_block_a_normal_tail(self):
        s, _, out = self._session()
        for _ in range(8):
            s.feed(speech(0.5))
        s.finish(np.empty(0, dtype=np.float32), accept=lambda t: t != "Yeah.")
        self.assertEqual("".join(out), "Посмотри в Figma макет, там Claude Code работает.")

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
        self.assertEqual(len(out), 1)
        self.assertTrue(s.undelivered)
        self.assertEqual(
            " ".join([out[0].strip(), s.undelivered]),
            "Посмотри в Figma макет, там Claude Code работает.",
        )


if __name__ == "__main__":
    unittest.main()
