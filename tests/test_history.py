import json
import os
import tempfile
import unittest

import history


class TestHistory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_xdg
        self._tmp.cleanup()

    def test_load_missing_returns_empty(self):
        self.assertEqual(history.load(), [])

    def test_add_then_load_roundtrip_newest_first(self):
        history.add("первая", now=1.0)
        history.add("вторая", now=2.0)
        items = history.load()
        self.assertEqual([i["text"] for i in items], ["вторая", "первая"])

    def test_add_blank_is_ignored(self):
        history.add("   ")
        self.assertEqual(history.load(), [])

    def test_capped_at_max_items(self):
        for i in range(history.MAX_ITEMS + 10):
            history.add(f"текст {i}", now=float(i))
        items = history.load()
        self.assertEqual(len(items), history.MAX_ITEMS)
        # новейшая запись сохранилась, старейшие вытеснены
        self.assertEqual(items[0]["text"], f"текст {history.MAX_ITEMS + 9}")

    def test_corrupt_file_returns_empty(self):
        os.makedirs(config_dir(), exist_ok=True)
        with open(history.history_path(), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(history.load(), [])

    def test_junk_entries_dropped(self):
        os.makedirs(config_dir(), exist_ok=True)
        with open(history.history_path(), "w", encoding="utf-8") as f:
            json.dump(
                [{"text": "ok", "ts": 5.0}, {"no": "text"}, 42, {"text": ""}],
                f,
            )
        items = history.load()
        self.assertEqual([i["text"] for i in items], ["ok"])

    def test_clear(self):
        history.add("что-то")
        history.clear()
        self.assertEqual(history.load(), [])

    def test_duplicate_texts_are_kept_as_separate_entries(self):
        history.add("одно и то же", now=1.0)
        history.add("одно и то же", now=2.0)
        self.assertEqual(len(history.load()), 2)


class TestLabel(unittest.TestCase):
    def test_label_contains_index_and_text(self):
        s = history.label(3, {"text": "привет мир", "ts": 0})
        self.assertTrue(s.startswith("3."))
        self.assertIn("привет мир", s)

    def test_label_truncates_long_text(self):
        s = history.label(1, {"text": "x" * 200, "ts": 0})
        self.assertLess(len(s), 80)
        self.assertIn("…", s)

    def test_label_collapses_newlines(self):
        s = history.label(1, {"text": "стро\nка", "ts": 0})
        self.assertIn("стро ка", s)

    def test_labels_unique_for_identical_texts(self):
        a = history.label(1, {"text": "same", "ts": 0})
        b = history.label(2, {"text": "same", "ts": 0})
        self.assertNotEqual(a, b)


def config_dir():
    import config

    return config.config_dir()


if __name__ == "__main__":
    unittest.main()
