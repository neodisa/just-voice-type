import unittest

import voice_type


class TestHotkeyVk(unittest.TestCase):
    def test_vk_from_named_modifier(self):
        try:
            key = voice_type.parse_hotkey("right_option")
        except SystemExit:
            self.skipTest("pynput not installed")
        vk = voice_type._hotkey_vk(key)
        self.assertIsInstance(vk, int)

    def test_vk_none_for_object_without_keycode(self):
        self.assertIsNone(voice_type._hotkey_vk(object()))

    def test_vk_direct_attribute(self):
        class FakeKey:
            vk = 61

        self.assertEqual(voice_type._hotkey_vk(FakeKey()), 61)

    def test_vk_nested_value_attribute(self):
        # pynput Key.alt_r хранит keycode в key.value.vk
        class FakeKeyCode:
            vk = 61

        class FakeKey:
            value = FakeKeyCode()

        self.assertEqual(voice_type._hotkey_vk(FakeKey()), 61)


class TestKeyIsDown(unittest.TestCase):
    def test_returns_bool_or_none_never_raises(self):
        # на macOS с Quartz вернёт bool; в другом окружении — None
        result = voice_type._key_is_down(61)
        self.assertIn(type(result), (bool, type(None)))


class TestVersion(unittest.TestCase):
    def test_version_is_semver(self):
        import re

        self.assertRegex(voice_type.__version__, r"^\d+\.\d+\.\d+$")

    def test_releases_url_points_to_repo(self):
        self.assertTrue(
            voice_type.RELEASES_URL.startswith("https://github.com/")
        )


class TestHallucinationFilter(unittest.TestCase):
    def test_known_hallucination(self):
        self.assertTrue(voice_type.is_hallucination("Thank you."))

    def test_normal_text_passes(self):
        self.assertFalse(voice_type.is_hallucination("Привет, как дела?"))


if __name__ == "__main__":
    unittest.main()
