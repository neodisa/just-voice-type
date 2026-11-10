import re
import unittest

import i18n


class TestTables(unittest.TestCase):
    def test_same_keys_in_every_language(self):
        ru, en = set(i18n.STRINGS["ru"]), set(i18n.STRINGS["en"])
        self.assertEqual(ru - en, set(), "missing in en")
        self.assertEqual(en - ru, set(), "missing in ru")

    def test_same_placeholders(self):
        ph = re.compile(r"\{(\w+)\}")
        for key, ru in i18n.STRINGS["ru"].items():
            en = i18n.STRINGS["en"][key]
            self.assertEqual(sorted(ph.findall(ru)), sorted(ph.findall(en)), key)


class TestResolve(unittest.TestCase):
    def test_explicit_setting_wins(self):
        self.assertEqual(i18n.resolve("ru", ["en-US"]), "ru")
        self.assertEqual(i18n.resolve("en", ["ru-RU"]), "en")

    def test_system_takes_first_supported(self):
        self.assertEqual(i18n.resolve("system", ["ru-RU", "en-US"]), "ru")
        self.assertEqual(i18n.resolve("system", ["en-PL", "ru-PL"]), "en")
        self.assertEqual(i18n.resolve("system", ["uk-UA", "ru-RU"]), "ru")

    def test_system_unsupported_falls_back_to_english(self):
        self.assertEqual(i18n.resolve("system", ["uk-UA"]), "en")
        self.assertEqual(i18n.resolve("system", []), "en")

    def test_underscore_locale_tags(self):
        self.assertEqual(i18n.resolve("system", ["ru_RU.UTF-8"]), "ru")


class TestTranslate(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_t_formats_in_current_language(self):
        i18n.set_language("ru")
        self.assertEqual(i18n.t("status.recording", time="0:07"), "Записываю · 0:07")
        i18n.set_language("en")
        self.assertEqual(i18n.t("status.recording", time="0:07"), "Recording · 0:07")

    def test_unknown_language_means_english(self):
        i18n.set_language("de")
        self.assertEqual(i18n.language(), "en")

    def test_unknown_key_returns_key(self):
        self.assertEqual(i18n.t("no.such.key"), "no.such.key")

    def test_falls_back_to_english_string(self):
        i18n.STRINGS["en"]["test.only_en"] = "only en"
        try:
            i18n.set_language("ru")
            self.assertEqual(i18n.t("test.only_en"), "only en")
        finally:
            del i18n.STRINGS["en"]["test.only_en"]

    def test_key_names(self):
        i18n.set_language("ru")
        self.assertEqual(i18n.key_name("right_option"), "правый ⌥")
        self.assertEqual(i18n.key_name("f13"), "F13")
        self.assertEqual(i18n.key_name("weird_key"), "weird_key")
        i18n.set_language("en")
        self.assertEqual(i18n.key_name("right_option"), "right ⌥")
