import unittest

import languages


class TestLanguages(unittest.TestCase):
    def test_dict_has_expected_entries(self):
        self.assertGreater(len(languages.WHISPER_LANGUAGES), 90)
        for code in ("ru", "en", "uk"):
            self.assertIn(code, languages.WHISPER_LANGUAGES)
        for name in languages.WHISPER_LANGUAGES.values():
            self.assertIsInstance(name, str)
            self.assertTrue(name)

    def test_is_valid(self):
        self.assertTrue(languages.is_valid("ru"))
        self.assertFalse(languages.is_valid("zzz"))

    def test_display_name(self):
        self.assertEqual(languages.display_name(None), "Auto")
        self.assertEqual(languages.display_name("ru"), "Russian")
        self.assertEqual(languages.display_name("zzz"), "zzz")

    def test_sorted_all_is_sorted_by_name(self):
        names = [name for _, name in languages.sorted_all()]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertEqual(len(names), len(languages.WHISPER_LANGUAGES))

    def test_top_section_codes(self):
        self.assertEqual(
            languages.top_section_codes(["ru", "en"], "uk"),
            [None, "en", "ru", "uk"],
        )
        self.assertEqual(
            languages.top_section_codes(["ru", "en"], "ru"),
            [None, "en", "ru"],
        )
        self.assertEqual(
            languages.top_section_codes(["ru", "en"], None),
            [None, "en", "ru"],
        )
        self.assertEqual(
            languages.top_section_codes(["ru", "zzz"], None),
            [None, "ru"],
        )


if __name__ == "__main__":
    unittest.main()
