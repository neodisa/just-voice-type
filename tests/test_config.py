import json
import os
import tempfile
import unittest

import config


class TestConfig(unittest.TestCase):
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

    def test_load_missing_returns_defaults_copy(self):
        cfg = config.load()
        self.assertEqual(cfg, config.DEFAULTS)
        cfg["hotkey"] = "mutated"
        self.assertNotEqual(config.DEFAULTS["hotkey"], "mutated")

    def test_save_then_load_roundtrip(self):
        config.save(
            {"favorite_languages": ["en", "de"], "active_language": "de", "hotkey": "f19"}
        )
        cfg = config.load()
        self.assertEqual(cfg["favorite_languages"], ["en", "de"])
        self.assertEqual(cfg["active_language"], "de")
        self.assertEqual(cfg["hotkey"], "f19")

    def test_save_creates_valid_json_file(self):
        config.save(config.DEFAULTS)
        with open(config.config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["hotkey"], "right_option")

    def test_corrupt_file_falls_back_to_defaults(self):
        os.makedirs(config.config_dir(), exist_ok=True)
        with open(config.config_path(), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(config.load(), config.DEFAULTS)

    def test_validate_drops_invalid_languages_and_dedups(self):
        config.save(
            {"favorite_languages": ["ru", "zzz", "ru", "en"], "active_language": "ru", "hotkey": "fn"}
        )
        cfg = config.load()
        self.assertEqual(cfg["favorite_languages"], ["ru", "en"])

    def test_invalid_active_becomes_none(self):
        config.save({"favorite_languages": [], "active_language": "zzz", "hotkey": "fn"})
        self.assertIsNone(config.load()["active_language"])

    def test_invalid_hotkey_becomes_default(self):
        config.save({"favorite_languages": [], "active_language": None, "hotkey": ""})
        self.assertEqual(config.load()["hotkey"], "right_option")

    def test_defaults_include_smart_mode_and_vocabulary(self):
        cfg = config.load()
        self.assertEqual(cfg["smart_mode"], "prompt")
        self.assertEqual(cfg["vocabulary"], [])

    def test_smart_mode_roundtrip(self):
        config.save({"smart_mode": "clean", "vocabulary": ["Anthropic", "Qwen"]})
        cfg = config.load()
        self.assertEqual(cfg["smart_mode"], "clean")
        self.assertEqual(cfg["vocabulary"], ["Anthropic", "Qwen"])

    def test_invalid_smart_mode_falls_back_to_prompt(self):
        config.save({"smart_mode": "nonsense"})
        self.assertEqual(config.load()["smart_mode"], "prompt")

    def test_vocabulary_drops_non_strings_and_blanks(self):
        config.save({"vocabulary": ["ok", "", "  ", 42, None, "Claude"]})
        self.assertEqual(config.load()["vocabulary"], ["ok", "Claude"])

    def test_defaults_copy_isolates_vocabulary_list(self):
        cfg = config.load()
        cfg["vocabulary"].append("mutated")
        self.assertEqual(config.DEFAULTS["vocabulary"], [])


if __name__ == "__main__":
    unittest.main()
