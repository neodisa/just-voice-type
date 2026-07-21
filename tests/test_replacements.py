import unittest

import voice_type


class TestApplyReplacements(unittest.TestCase):
    def test_no_rules_returns_unchanged(self):
        self.assertEqual(voice_type.apply_replacements("hello world", {}), "hello world")

    def test_empty_text_unchanged(self):
        self.assertEqual(voice_type.apply_replacements("", {"a": "b"}), "")

    def test_whole_word_replaced(self):
        self.assertEqual(
            voice_type.apply_replacements("надо апрув сделать", {"апрув": "approve"}),
            "надо approve сделать",
        )

    def test_substring_inside_word_not_touched(self):
        self.assertEqual(
            voice_type.apply_replacements("improve it", {"prove": "XXX"}),
            "improve it",
        )

    def test_case_insensitive_literal_output(self):
        self.assertEqual(
            voice_type.apply_replacements("Апрув и апрув", {"апрув": "апрув!"}),
            "апрув! и апрув!",
        )

    def test_multiword_phrase(self):
        self.assertEqual(
            voice_type.apply_replacements("open a pull request now",
                                          {"pull request": "пул-реквест"}),
            "open a пул-реквест now",
        )

    def test_longest_key_wins(self):
        out = voice_type.apply_replacements(
            "make a pull request",
            {"pull": "П", "pull request": "ПР"},
        )
        self.assertEqual(out, "make a ПР")

    def test_single_pass_no_cascade(self):
        out = voice_type.apply_replacements("b", {"b": "a", "a": "z"})
        self.assertEqual(out, "a")

    def test_cyrillic_word_boundary(self):
        self.assertEqual(
            voice_type.apply_replacements("это задиплоить надо", {"задиплоить": "задеплоить"}),
            "это задеплоить надо",
        )


if __name__ == "__main__":
    unittest.main()
