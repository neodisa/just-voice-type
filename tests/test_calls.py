import os
import tempfile
import unittest

import calls


class TestCallsMeta(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        self._old_home = os.environ.get("HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name
        os.environ["HOME"] = self._tmp.name

    def tearDown(self):
        for var, old in (("XDG_CONFIG_HOME", self._old_xdg), ("HOME", self._old_home)):
            if old is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = old
        self._tmp.cleanup()

    def test_load_missing_returns_empty(self):
        self.assertEqual(calls.load(), [])

    def test_add_then_load_roundtrip_newest_first(self):
        calls.add("/tmp/a.txt", "первый звонок", 60.0, now=1.0)
        calls.add("/tmp/b.txt", "второй звонок", 120.0, now=2.0)
        items = calls.load()
        self.assertEqual([i["path"] for i in items], ["/tmp/b.txt", "/tmp/a.txt"])

    def test_add_blank_text_is_ignored(self):
        calls.add("/tmp/a.txt", "   ", 60.0)
        self.assertEqual(calls.load(), [])

    def test_capped_at_max_items(self):
        for i in range(calls.MAX_ITEMS + 5):
            calls.add(f"/tmp/{i}.txt", f"звонок {i}", 60.0, now=float(i))
        items = calls.load()
        self.assertEqual(len(items), calls.MAX_ITEMS)

    def test_clear_empties_list(self):
        calls.add("/tmp/a.txt", "текст", 60.0)
        calls.clear()
        self.assertEqual(calls.load(), [])

    def test_label_includes_duration_and_preview(self):
        items = calls.add("/tmp/a.txt", "обсудили план на неделю", 125.0, now=0.0)
        text = calls.label(1, items[0])
        self.assertIn("2 мин", text)
        self.assertIn("обсудили план на неделю", text)


class TestTranscriptFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def test_start_transcript_creates_empty_file(self):
        path = calls.start_transcript(0.0)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "")

    def test_transcript_path_dedupes_on_collision(self):
        os.makedirs(calls.calls_dir(), exist_ok=True)
        first = calls.transcript_path(0.0)
        with open(first, "w", encoding="utf-8"):
            pass
        second = calls.transcript_path(0.0)
        self.assertNotEqual(first, second)
        self.assertTrue(second.endswith("-2.txt"))

    def test_append_chunk_appends_not_overwrites(self):
        path = calls.start_transcript(0.0)
        calls.append_chunk(path, "первая часть")
        calls.append_chunk(path, "вторая часть")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("первая часть", content)
        self.assertIn("вторая часть", content)

    def test_append_chunk_ignores_blank_text(self):
        path = calls.start_transcript(0.0)
        calls.append_chunk(path, "   ")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "")

    def test_finalize_overwrites_with_final_text(self):
        path = calls.start_transcript(0.0)
        calls.append_chunk(path, "черновой кусок")
        calls.finalize(path, "итоговый чистый текст")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "итоговый чистый текст")


if __name__ == "__main__":
    unittest.main()
