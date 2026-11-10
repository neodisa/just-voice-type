import os
import tempfile
import unittest

import sounds


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        os.makedirs(os.path.join(self.dir, "mech"))
        with open(os.path.join(self.dir, "mech", "done.wav"), "wb") as f:
            f.write(b"RIFF")

    def tearDown(self):
        self.tmp.cleanup()

    def test_cuelume_theme_uses_rendered_file_at_full_volume(self):
        path, vol = sounds.resolve("done", "mech", sounds_dir=self.dir)
        self.assertEqual(path, os.path.join(self.dir, "mech", "done.wav"))
        self.assertEqual(vol, sounds.FILE_VOLUME)

    def test_macos_theme_uses_system_sounds_at_half_volume(self):
        self.assertEqual(
            sounds.resolve("dictation_start", "macos", sounds_dir=self.dir),
            ("/System/Library/Sounds/Tink.aiff", sounds.MACOS_VOLUME),
        )
        self.assertEqual(sounds.resolve("error", "macos")[0], "/System/Library/Sounds/Basso.aiff")

    def test_off_resolves_to_nothing(self):
        self.assertIsNone(sounds.resolve("done", "off", sounds_dir=self.dir))

    def test_missing_rendered_file_falls_back_to_macos(self):
        # a broken checkout must never silence an error
        self.assertEqual(
            sounds.resolve("error", "bubble", sounds_dir=self.dir),
            ("/System/Library/Sounds/Basso.aiff", sounds.MACOS_VOLUME),
        )

    def test_unknown_theme_plays_default(self):
        os.makedirs(os.path.join(self.dir, "default"))
        with open(os.path.join(self.dir, "default", "done.wav"), "wb") as f:
            f.write(b"RIFF")
        path, _ = sounds.resolve("done", "nope", sounds_dir=self.dir)
        self.assertEqual(path, os.path.join(self.dir, "default", "done.wav"))

    def test_unknown_event_resolves_to_nothing(self):
        self.assertIsNone(sounds.resolve("nope", "macos"))

    def test_every_event_has_a_cue_and_a_macos_sound(self):
        for event in sounds.EVENTS:
            self.assertIn(event, sounds.CUES)
            self.assertIsNotNone(sounds.resolve(event, "macos"))


class PlayTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def run_(self, argv, **kw):
        self.calls.append(argv)

    def test_plays_through_afplay_with_volume(self):
        sounds.play("error", "macos", run=self.run_)
        self.assertEqual(self.calls, [["afplay", "-v", "0.5", "/System/Library/Sounds/Basso.aiff"]])

    def test_quiet_calls_skips_only_call_events(self):
        for event in sounds.EVENTS:
            sounds.play(event, "macos", quiet_calls=True, run=self.run_)
        played = {argv[-1] for argv in self.calls}
        self.assertEqual(len(self.calls), len(sounds.EVENTS) - len(sounds.CALL_EVENTS))
        self.assertNotIn(None, played)

    def test_off_plays_nothing(self):
        sounds.play("error", "off", run=self.run_)
        self.assertEqual(self.calls, [])


class ShippedFilesTest(unittest.TestCase):
    def test_every_cuelume_theme_ships_every_event(self):
        for theme in sounds.CUELUME_THEMES:
            for event in sounds.EVENTS:
                p = os.path.join(sounds.SOUNDS_DIR, theme, f"{event}.wav")
                self.assertTrue(os.path.isfile(p), p)

    def test_cuelume_license_ships_with_the_files(self):
        self.assertTrue(os.path.isfile(os.path.join(sounds.SOUNDS_DIR, "LICENSE-cuelume.txt")))


if __name__ == "__main__":
    unittest.main()
