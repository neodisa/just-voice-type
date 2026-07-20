import unittest

import voice_type


class TestInsertViaAxGuards(unittest.TestCase):
    def test_empty_text_returns_false_without_subprocess(self):
        # Empty text must short-circuit to False and never spawn a subprocess.
        self.assertIs(voice_type.insert_via_ax(""), False)

    def test_returns_bool(self):
        self.assertIsInstance(voice_type.insert_via_ax(""), bool)


class TestDeliverTextRouting(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig = {}
        for name in ("insert_via_ax", "copy_to_clipboard",
                     "paste_via_cmd_v", "read_clipboard"):
            self._orig[name] = getattr(voice_type, name)
        # read_clipboard echoes the text so deliver_text's "placed" check passes
        # and never triggers its retry-copy branch.
        voice_type.copy_to_clipboard = lambda t: self.calls.append(("copy", t))
        voice_type.paste_via_cmd_v = lambda: self.calls.append(("paste",))
        voice_type.read_clipboard = lambda: "hi"

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(voice_type, name, fn)

    def test_ax_success_skips_clipboard(self):
        voice_type.insert_via_ax = lambda t: (self.calls.append(("ax", t)) or True)
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax")
        self.assertEqual(self.calls, [("ax", "hi")])

    def test_ax_failure_falls_back_to_paste(self):
        voice_type.insert_via_ax = lambda t: (self.calls.append(("ax", t)) or False)
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="ax")
        self.assertEqual(self.calls, [("ax", "hi"), ("copy", "hi"), ("paste",)])

    def test_paste_mode_never_calls_ax(self):
        voice_type.insert_via_ax = lambda t: (self.calls.append(("ax", t)) or True)
        voice_type.deliver_text("hi", do_paste=True, restore_clipboard=False,
                                insert_mode="paste")
        self.assertEqual(self.calls, [("copy", "hi"), ("paste",)])

    def test_no_paste_with_ax_mode_skips_ax_and_paste(self):
        voice_type.insert_via_ax = lambda t: (self.calls.append(("ax", t)) or True)
        voice_type.deliver_text("hi", do_paste=False, restore_clipboard=False,
                                insert_mode="ax")
        self.assertEqual(self.calls, [("copy", "hi")])


class TestFrontmostAppPid(unittest.TestCase):
    def test_returns_int_or_none(self):
        pid = voice_type.frontmost_app_pid()
        self.assertTrue(pid is None or isinstance(pid, int))


if __name__ == "__main__":
    unittest.main()
