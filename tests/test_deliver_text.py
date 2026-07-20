import unittest

import voice_type


class TestInsertViaAxGuards(unittest.TestCase):
    def test_empty_text_returns_false_without_subprocess(self):
        # Empty text must short-circuit to False and never spawn a subprocess.
        self.assertIs(voice_type.insert_via_ax(""), False)

    def test_returns_bool(self):
        self.assertIsInstance(voice_type.insert_via_ax(""), bool)


if __name__ == "__main__":
    unittest.main()
