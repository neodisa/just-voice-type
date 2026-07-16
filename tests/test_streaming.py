import unittest

import numpy as np

import streaming


class TestFindSplitPoint(unittest.TestCase):
    def test_returns_len_when_shorter_than_target(self):
        audio = np.ones(1000, dtype=np.float32)
        self.assertEqual(streaming.find_split_point(audio, 16000, target_sec=1.0), 1000)

    def test_splits_at_the_silent_gap(self):
        sr = 16000
        # 25с речи-как-шума, но с чёткой тишиной ровно на 20-й секунде
        loud = (np.random.RandomState(0).randn(25 * sr) * 0.3).astype(np.float32)
        gap_start = 20 * sr
        gap = int(0.4 * sr)
        loud[gap_start : gap_start + gap] = 0.0
        split = streaming.find_split_point(loud, sr, target_sec=20.0, search_sec=3.0)
        # разрез должен попасть внутрь тихого промежутка
        self.assertGreaterEqual(split, gap_start)
        self.assertLessEqual(split, gap_start + gap)

    def test_split_within_bounds(self):
        sr = 16000
        audio = (np.random.RandomState(1).randn(24 * sr) * 0.3).astype(np.float32)
        split = streaming.find_split_point(audio, sr, target_sec=20.0)
        self.assertGreater(split, 0)
        self.assertLess(split, len(audio))


class TestIsSilent(unittest.TestCase):
    def test_zeros_are_silent(self):
        self.assertTrue(streaming.is_silent(np.zeros(16000, dtype=np.float32)))

    def test_empty_is_silent(self):
        self.assertTrue(streaming.is_silent(np.array([], dtype=np.float32)))

    def test_loud_is_not_silent(self):
        a = (np.random.RandomState(2).randn(16000) * 0.3).astype(np.float32)
        self.assertFalse(streaming.is_silent(a))


class TestJoinParts(unittest.TestCase):
    def test_joins_with_single_spaces(self):
        self.assertEqual(streaming.join_parts(["привет", "как дела"]), "привет как дела")

    def test_drops_empty_and_whitespace(self):
        self.assertEqual(streaming.join_parts(["a", "", "  ", "b"]), "a b")

    def test_collapses_internal_whitespace(self):
        self.assertEqual(streaming.join_parts(["a  b", "c\nd"]), "a b c d")

    def test_empty_list(self):
        self.assertEqual(streaming.join_parts([]), "")


if __name__ == "__main__":
    unittest.main()
