import unittest

import i18n
import menubar_icon as mi
from menubar_icon import Snapshot


class TestFmt(unittest.TestCase):
    def test_minutes_seconds(self):
        self.assertEqual(mi.fmt_elapsed(7.9), "0:07")
        self.assertEqual(mi.fmt_elapsed(724), "12:04")

    def test_hours(self):
        self.assertEqual(mi.fmt_elapsed(3723), "1:02:03")

    def test_negative_is_zero(self):
        self.assertEqual(mi.fmt_elapsed(-3), "0:00")


class TestBars(unittest.TestCase):
    def test_silence_is_lowest(self):
        self.assertEqual(mi.bar_heights(0.0), (1, 1, 1, 1, 1))

    def test_loud_follows_profile(self):
        h = mi.bar_heights(1.0)
        self.assertEqual(len(h), mi.BAR_COUNT)
        self.assertEqual(h[2], mi.BAR_STEPS)        # средняя — максимум
        self.assertLess(h[0], h[2])                 # крайние ниже
        self.assertEqual(h, tuple(reversed(h)))     # симметрично

    def test_quantized_range(self):
        for lvl in (0.01, 0.05, 0.1, 0.2, 5.0):
            for v in mi.bar_heights(lvl):
                self.assertTrue(1 <= v <= mi.BAR_STEPS)


class TestFrame(unittest.TestCase):
    def test_ready(self):
        self.assertEqual(mi.frame(Snapshot()), mi.Frame(symbol="mic"))

    def test_paused(self):
        self.assertEqual(mi.frame(Snapshot(enabled=False)).symbol, "mic.slash")

    def test_recording_is_red_bars(self):
        f = mi.frame(Snapshot(state="recording", level=0.2))
        self.assertEqual(f.symbol, "")
        self.assertEqual(f.tint, "rec")
        self.assertEqual(len(f.bars), mi.BAR_COUNT)
        self.assertEqual(f.badge, "")

    def test_handsfree_has_infinity_badge(self):
        f = mi.frame(Snapshot(state="recording", handsfree=True))
        self.assertEqual(f.badge, "infinity")

    def test_transcribing_pulses(self):
        a = mi.frame(Snapshot(state="transcribing", now=10.0))
        b = mi.frame(Snapshot(state="transcribing", now=10.5))
        self.assertEqual(a.symbol, "waveform")
        self.assertNotEqual(a.dim, b.dim)

    def test_inserted(self):
        self.assertEqual(mi.frame(Snapshot(inserted=True)).symbol, "checkmark")

    def test_call_recording_has_timer(self):
        f = mi.frame(Snapshot(call_state="recording", call_elapsed=724))
        self.assertEqual((f.symbol, f.tint, f.text), ("phone.fill", "rec", "12:04"))

    def test_call_beats_dictation(self):
        f = mi.frame(Snapshot(call_state="recording", state="recording"))
        self.assertEqual(f.symbol, "phone.fill")

    def test_model_loading(self):
        self.assertEqual(
            mi.frame(Snapshot(model_loading=True)).symbol, "arrow.down.circle"
        )

    def test_recording_beats_model_loading(self):
        f = mi.frame(Snapshot(model_loading=True, state="recording"))
        self.assertEqual(f.tint, "rec")

    def test_audio_dead_beats_everything(self):
        f = mi.frame(Snapshot(audio_dead=True, call_state="recording"))
        self.assertEqual(f.symbol, "exclamationmark.triangle")

    def test_frames_are_hashable(self):
        {mi.frame(Snapshot()): 1}


class TestStatus(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_ready_ru(self):
        i18n.set_language("ru")
        s = mi.status(Snapshot(hotkey="right_option"))
        self.assertEqual(s, mi.Status(dot="ok", text="Готов · удерживайте правый ⌥"))

    def test_recording_time(self):
        i18n.set_language("en")
        s = mi.status(Snapshot(state="recording", rec_elapsed=7))
        self.assertEqual(s, mi.Status(dot="rec", text="Recording · 0:07"))

    def test_handsfree_mentions_key(self):
        i18n.set_language("en")
        s = mi.status(Snapshot(state="recording", handsfree=True, hotkey="f13", rec_elapsed=3))
        self.assertEqual(s.text, "Recording · 0:03 · press F13 to stop")

    def test_download_vs_load(self):
        i18n.set_language("en")
        load = mi.status(Snapshot(model_loading=True, model_cached=True, model_name="m"))
        dl = mi.status(Snapshot(model_loading=True, model_cached=False, model_name="m"))
        self.assertEqual(load, mi.Status(dot="busy", text="Loading model m…"))
        self.assertEqual(dl, mi.Status(dot="busy", text="Downloading model m…"))

    def test_call_time(self):
        i18n.set_language("ru")
        s = mi.status(Snapshot(call_state="recording", call_elapsed=65))
        self.assertEqual(s, mi.Status(dot="rec", text="Запись звонка · 1:05"))

    def test_paused_and_dead(self):
        self.assertEqual(mi.status(Snapshot(enabled=False)).dot, "paused")
        self.assertEqual(mi.status(Snapshot(audio_dead=True)).dot, "error")
