import unittest

import voice_type


class TestInsertViaAxGuards(unittest.TestCase):
    def test_empty_text_returns_paste_fallback_without_subprocess(self):
        # Empty text short-circuits to a status string, never spawning a subprocess.
        self.assertEqual(voice_type.insert_via_ax(""), "paste_fallback")

    def test_returns_status_string(self):
        self.assertIn(voice_type.insert_via_ax(""),
                      ("ok", "paste_fallback", "history_only"))


class TestDeliverTextRouting(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig = {}
        for name in ("insert_via_ax", "copy_to_clipboard",
                     "paste_via_cmd_v", "read_clipboard", "notify"):
            self._orig[name] = getattr(voice_type, name)
        voice_type.copy_to_clipboard = lambda t: self.calls.append(("copy", t))
        voice_type.paste_via_cmd_v = lambda: self.calls.append(("paste",))
        voice_type.read_clipboard = lambda: (self.calls.append(("read",)) or "hi")
        voice_type.notify = lambda title, msg: self.calls.append(("notify", title, msg))

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(voice_type, name, fn)

    def _stub_ax(self, status):
        voice_type.insert_via_ax = lambda t, pid=None: (
            self.calls.append(("ax", t, pid)) or status)

    def test_ok_touches_nothing_else(self):
        self._stub_ax("ok")
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax", target_pid=123)
        self.assertEqual(self.calls, [("ax", "hi", 123)])

    def test_history_only_notifies_and_skips_clipboard(self):
        self._stub_ax("history_only")
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax", target_pid=123)
        ops = [c[0] for c in self.calls]
        self.assertEqual(ops, ["ax", "notify"])
        self.assertNotIn("copy", ops)
        self.assertNotIn("paste", ops)

    def test_paste_fallback_in_ax_mode_forces_restore(self):
        self._stub_ax("paste_fallback")
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax", target_pid=123)
        ops = [c[0] for c in self.calls]
        self.assertEqual(ops.count("read"), 2)
        self.assertIn(("copy", "hi"), self.calls)
        self.assertIn(("paste",), self.calls)

    def test_paste_mode_unchanged_no_ax_no_forced_restore(self):
        self._stub_ax("ok")  # must never be called in paste mode
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="paste", target_pid=123)
        ops = [c[0] for c in self.calls]
        self.assertNotIn("ax", ops)
        self.assertEqual(ops.count("read"), 1)
        self.assertIn(("copy", "hi"), self.calls)
        self.assertIn(("paste",), self.calls)


class TestFrontmostAppPid(unittest.TestCase):
    def test_returns_int_or_none(self):
        pid = voice_type.frontmost_app_pid()
        self.assertTrue(pid is None or isinstance(pid, int))


if __name__ == "__main__":
    unittest.main()
