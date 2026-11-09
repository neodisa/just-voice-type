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
        self.assertEqual(cfg["smart_mode"], "raw")
        self.assertEqual(cfg["vocabulary"], [])

    def test_smart_mode_roundtrip(self):
        config.save({"smart_mode": "clean", "vocabulary": ["Anthropic", "Qwen"]})
        cfg = config.load()
        self.assertEqual(cfg["smart_mode"], "clean")
        self.assertEqual(cfg["vocabulary"], ["Anthropic", "Qwen"])

    def test_invalid_smart_mode_falls_back_to_default(self):
        config.save({"smart_mode": "nonsense"})
        self.assertEqual(config.load()["smart_mode"], "raw")

    def test_vocabulary_drops_non_strings_and_blanks(self):
        config.save({"vocabulary": ["ok", "", "  ", 42, None, "Claude"]})
        self.assertEqual(config.load()["vocabulary"], ["ok", "Claude"])

    def test_model_defaults_to_none(self):
        self.assertIsNone(config.load()["model"])

    def test_model_roundtrip(self):
        config.save({"model": "mlx-community/whisper-large-v3-mlx"})
        self.assertEqual(
            config.load()["model"], "mlx-community/whisper-large-v3-mlx"
        )

    def test_model_junk_becomes_none(self):
        config.save({"model": 42})
        self.assertIsNone(config.load()["model"])
        config.save({"model": "   "})
        self.assertIsNone(config.load()["model"])

    def test_defaults_copy_isolates_vocabulary_list(self):
        cfg = config.load()
        cfg["vocabulary"].append("mutated")
        self.assertEqual(config.DEFAULTS["vocabulary"], [])


class TestInsertMode(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old
        self._tmp.cleanup()

    def test_default_is_paste(self):
        self.assertEqual(config.load()["insert_mode"], "paste")

    def test_valid_ax_roundtrips(self):
        config.save({"insert_mode": "ax"})
        self.assertEqual(config.load()["insert_mode"], "ax")

    def test_invalid_falls_back_to_paste(self):
        config.save({"insert_mode": "nonsense"})
        self.assertEqual(config.load()["insert_mode"], "paste")


class TestReplacements(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old
        self._tmp.cleanup()

    def test_default_is_empty_dict(self):
        self.assertEqual(config.load()["replacements"], {})

    def test_valid_map_roundtrips(self):
        config.save({"replacements": {"апруф": "апрув"}})
        self.assertEqual(config.load()["replacements"], {"апруф": "апрув"})

    def test_non_dict_becomes_empty(self):
        config.save({"replacements": ["not", "a", "dict"]})
        self.assertEqual(config.load()["replacements"], {})

    def test_non_string_entries_dropped(self):
        config.save({"replacements": {"ok": "fine", "bad": 5, 7: "x", "": "y", "z": ""}})
        self.assertEqual(config.load()["replacements"], {"ok": "fine"})

    def test_whitespace_padded_entries_are_stripped(self):
        config.save({"replacements": {"  approve ": "  апрув "}})
        self.assertEqual(config.load()["replacements"], {"approve": "апрув"})


class TestCallSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old
        self._tmp.cleanup()

    def test_default_call_hotkey_is_f13(self):
        self.assertEqual(config.load()["call_hotkey"], "f13")

    def test_default_call_device_is_none(self):
        self.assertIsNone(config.load()["call_device"])

    def test_call_hotkey_roundtrip(self):
        config.save({"call_hotkey": "f14"})
        self.assertEqual(config.load()["call_hotkey"], "f14")

    def test_invalid_call_hotkey_falls_back_to_default(self):
        config.save({"call_hotkey": ""})
        self.assertEqual(config.load()["call_hotkey"], "f13")

    def test_call_device_roundtrip(self):
        config.save({"call_device": "Aggregate Device"})
        self.assertEqual(config.load()["call_device"], "Aggregate Device")

    def test_call_device_junk_becomes_none(self):
        config.save({"call_device": 42})
        self.assertIsNone(config.load()["call_device"])
        config.save({"call_device": "   "})
        self.assertIsNone(config.load()["call_device"])

    def test_no_collision_when_hotkeys_differ(self):
        config.save({"hotkey": "right_option", "call_hotkey": "f13"})
        cfg = config.load()
        self.assertEqual(cfg["hotkey"], "right_option")
        self.assertEqual(cfg["call_hotkey"], "f13")

    def test_call_hotkey_colliding_with_hotkey_falls_back(self):
        config.save({"hotkey": "f13", "call_hotkey": "f13"})
        cfg = config.load()
        self.assertNotEqual(cfg["call_hotkey"], cfg["hotkey"])
        self.assertEqual(cfg["call_hotkey"], "f14")

    def test_call_hotkey_collision_when_default_is_dictation_hotkey(self):
        # dictation hotkey happens to be f13 — the call default — so
        # call_hotkey (left unset, defaults to f13) must fall back further
        config.save({"hotkey": "f13"})
        self.assertEqual(config.load()["call_hotkey"], "f14")


if __name__ == "__main__":
    unittest.main()


class TestUpdatePreservesFileOwnedKeys(unittest.TestCase):
    """Меню сохраняет только свои настройки. Раньше persist() писал конфиг
    без "replacements" — и любая смена хоткея/языка/модели стирала словарь."""

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

    def test_update_keeps_replacements_and_other_keys(self):
        config.save({
            "hotkey": "f19",
            "replacements": {"фигма": "Figma"},
            "vocabulary": ["Figma"],
            "auto_system_audio": False,
        })
        config.update(hotkey="right_option", model="m")
        cfg = config.load()
        self.assertEqual(cfg["hotkey"], "right_option")
        self.assertEqual(cfg["model"], "m")
        self.assertEqual(cfg["replacements"], {"фигма": "Figma"})
        self.assertEqual(cfg["vocabulary"], ["Figma"])
        self.assertFalse(cfg["auto_system_audio"])

    def test_update_returns_saved_config(self):
        cfg = config.update(smart_mode="clean")
        self.assertEqual(cfg["smart_mode"], "clean")
        self.assertEqual(config.load()["smart_mode"], "clean")


class TestLiveTyping(unittest.TestCase):
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

    def test_live_typing_on_by_default(self):
        self.assertTrue(config.load()["live_typing"])

    def test_live_typing_roundtrip(self):
        config.save({"live_typing": False})
        self.assertFalse(config.load()["live_typing"])

    def test_junk_falls_back_to_default(self):
        config.save({"live_typing": "yes"})
        self.assertTrue(config.load()["live_typing"])
