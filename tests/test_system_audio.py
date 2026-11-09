import os
import sys
import tempfile
import unittest

import numpy as np

import system_audio


class TestMacOSAtLeast(unittest.TestCase):
    def test_newer_is_supported(self):
        self.assertTrue(system_audio._macos_at_least(14, 4, ver="14.4"))
        self.assertTrue(system_audio._macos_at_least(14, 4, ver="26.5.1"))
        self.assertTrue(system_audio._macos_at_least(14, 4, ver="15.0"))

    def test_older_is_not(self):
        self.assertFalse(system_audio._macos_at_least(14, 4, ver="14.3"))
        self.assertFalse(system_audio._macos_at_least(14, 4, ver="13.6.1"))
        self.assertFalse(system_audio._macos_at_least(14, 4, ver="10.15.7"))

    def test_garbage_version_is_false(self):
        self.assertFalse(system_audio._macos_at_least(14, 4, ver=""))
        self.assertFalse(system_audio._macos_at_least(14, 4, ver="not-a-version"))


class TestChooseSource(unittest.TestCase):
    def test_tap_wins_when_auto_and_supported_and_created(self):
        self.assertEqual(
            system_audio.choose_source(True, True, "tap", "My Aggregate"),
            ("tap", "tap", "tap_ok"),
        )

    def test_manual_when_auto_off(self):
        self.assertEqual(
            system_audio.choose_source(False, True, None, "My Aggregate"),
            ("manual", "My Aggregate", "manual_fallback"),
        )

    def test_manual_when_tap_unsupported(self):
        self.assertEqual(
            system_audio.choose_source(True, False, None, "My Aggregate"),
            ("manual", "My Aggregate", "tap_unsupported"),
        )

    def test_manual_when_tap_creation_failed(self):
        self.assertEqual(
            system_audio.choose_source(True, True, None, "My Aggregate"),
            ("manual", "My Aggregate", "tap_denied"),
        )

    def test_mic_only_when_nothing_else(self):
        self.assertEqual(
            system_audio.choose_source(True, True, None, None),
            ("mic", None, "mic_only"),
        )

    def test_mic_only_when_auto_off_and_no_manual(self):
        self.assertEqual(
            system_audio.choose_source(False, False, None, None),
            ("mic", None, "mic_only"),
        )


class TestParseHeader(unittest.TestCase):
    def test_parses_sr_and_channels(self):
        self.assertEqual(
            system_audio.parse_header(b'{"sample_rate":48000,"channels":1}\n'),
            (48000, 1),
        )

    def test_bad_header_returns_none(self):
        self.assertIsNone(system_audio.parse_header(b"garbage\n"))
        self.assertIsNone(system_audio.parse_header(b""))


class TestDecodePCM(unittest.TestCase):
    def test_bytes_to_float32(self):
        a = np.array([0.0, 0.5, -0.5], dtype="<f4")
        np.testing.assert_array_equal(system_audio.decode_pcm(a.tobytes()), a)

    def test_partial_frame_ignored(self):
        buf = np.float32(0.25).tobytes() + b"\x00"  # 5 bytes -> 1 sample
        out = system_audio.decode_pcm(buf)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(float(out[0]), 0.25, places=6)

    def test_empty(self):
        self.assertEqual(len(system_audio.decode_pcm(b"")), 0)


class TestIsSupported(unittest.TestCase):
    def test_returns_bool_never_raises(self):
        self.assertIsInstance(system_audio.is_supported(), bool)

    def test_false_when_helper_missing(self):
        self.assertFalse(system_audio.is_supported(helper="/nope/does/not/exist"))

    def test_true_path_needs_mac_and_helper(self):
        # существующий исполняемый файл + darwin>=14.4 → True; иначе False,
        # но в любом случае без исключений
        with tempfile.NamedTemporaryFile(suffix="-helper") as f:
            os.chmod(f.name, 0o755)
            self.assertIsInstance(system_audio.is_supported(helper=f.name), bool)


class TestSystemAudioCaptureReader(unittest.TestCase):
    """Использует фейковый хелпер (чистый Python), поэтому реальный звук не нужен."""

    def _fake_helper(self, d, samples=48000, value=0.5):
        p = os.path.join(d, "fake_helper.py")
        with open(p, "w") as f:
            f.write(
                "import sys, struct, time\n"
                'sys.stdout.buffer.write(b\'{"sample_rate":48000,"channels":1}\\n\')\n'
                f"sys.stdout.buffer.write(struct.pack('<{samples}f', *([{value}]*{samples})))\n"
                "sys.stdout.buffer.flush()\n"
                "time.sleep(30)\n"
            )
        return p

    def test_reads_header_and_returns_nonsilent_chunk(self):
        import time as _t

        with tempfile.TemporaryDirectory() as d:
            cap = system_audio.SystemAudioCapture(
                argv=[sys.executable, self._fake_helper(d)]
            )
            cap.start()
            try:
                _t.sleep(0.6)
                self.assertEqual(cap.sample_rate, 48000)
                chunk = cap.take_chunk(min_sec=0.5, target_sec=0.6, hard_max_sec=1.0)
                self.assertIsNotNone(chunk)
                self.assertGreater(float(np.max(np.abs(chunk))), 0.4)
            finally:
                cap.stop()

    def test_stop_is_idempotent_and_kills_process(self):
        with tempfile.TemporaryDirectory() as d:
            cap = system_audio.SystemAudioCapture(
                argv=[sys.executable, self._fake_helper(d)]
            )
            cap.start()
            cap.stop()
            cap.stop()  # второй раз — без исключений
            self.assertFalse(cap.is_recording)


class TestMixStreams(unittest.TestCase):
    def test_equal_length_sums(self):
        a = np.full(10, 0.3, dtype=np.float32)
        b = np.full(10, 0.2, dtype=np.float32)
        out = system_audio.mix_streams(a, b)
        self.assertEqual(len(out), 10)
        self.assertAlmostEqual(float(out[0]), 0.5, places=5)

    def test_pads_shorter_side_keeping_all_audio(self):
        # система длиннее микрофона — НИЧЕГО не выбрасываем и не задерживаем
        a = np.full(10, 0.3, dtype=np.float32)
        b = np.full(4, 0.2, dtype=np.float32)
        out = system_audio.mix_streams(a, b)
        self.assertEqual(len(out), 10)
        self.assertAlmostEqual(float(out[0]), 0.5, places=5)   # обе стороны
        self.assertAlmostEqual(float(out[9]), 0.3, places=5)   # только система

    def test_one_side_empty_passes_other_through(self):
        # мёртвая системная сторона НЕ должна блокировать микрофон
        a = np.empty(0, dtype=np.float32)
        b = np.full(5, 0.4, dtype=np.float32)
        out = system_audio.mix_streams(a, b)
        self.assertEqual(len(out), 5)
        self.assertAlmostEqual(float(out[0]), 0.4, places=5)

    def test_clips_to_unit_range(self):
        a = np.full(5, 0.8, dtype=np.float32)
        b = np.full(5, 0.8, dtype=np.float32)
        self.assertLessEqual(float(np.max(system_audio.mix_streams(a, b))), 1.0)

    def test_both_empty(self):
        out = system_audio.mix_streams(
            np.empty(0, dtype=np.float32), np.empty(0, dtype=np.float32)
        )
        self.assertEqual(len(out), 0)


class _FakeSource:
    """Отдаёт заранее заданные блоки 16к через drain_16k()/take_chunk()."""

    def __init__(self, blocks):
        self._blocks = list(blocks)
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def drain_16k(self):
        if self._blocks:
            return self._blocks.pop(0)
        return np.empty(0, dtype=np.float32)

    def take_chunk(self, min_sec, target_sec, hard_max_sec):
        if self._blocks:
            return self._blocks.pop(0)
        return None

    def stop(self):
        self.stopped = True
        return None

    def seconds_since_last_frame(self, now=None):
        return 0.0

    @property
    def is_recording(self):
        return not self.stopped


class TestCombinedCallCapture(unittest.TestCase):
    def test_mixes_both_sides_into_chunk(self):
        sys_src = _FakeSource([np.full(16000, 0.3, dtype=np.float32)])
        mic_src = _FakeSource([np.full(16000, 0.2, dtype=np.float32)])
        cap = system_audio.CombinedCallCapture(system=sys_src, mic=mic_src)
        cap.start()
        self.assertTrue(sys_src.started and mic_src.started)
        chunk = cap.take_chunk(min_sec=0.5, target_sec=0.6, hard_max_sec=1.0)
        self.assertIsNotNone(chunk)
        self.assertAlmostEqual(float(np.max(np.abs(chunk))), 0.5, places=4)

    def test_none_until_enough_accumulated(self):
        sys_src = _FakeSource([np.full(1600, 0.3, dtype=np.float32)])  # 0.1s
        mic_src = _FakeSource([np.full(1600, 0.2, dtype=np.float32)])
        cap = system_audio.CombinedCallCapture(system=sys_src, mic=mic_src)
        cap.start()
        self.assertIsNone(cap.take_chunk(min_sec=0.5, target_sec=0.6, hard_max_sec=1.0))

    def test_stop_stops_both(self):
        sys_src = _FakeSource([])
        mic_src = _FakeSource([])
        cap = system_audio.CombinedCallCapture(system=sys_src, mic=mic_src)
        cap.start()
        cap.stop()
        self.assertTrue(sys_src.stopped and mic_src.stopped)
        self.assertFalse(cap.is_recording)

    def test_dead_system_does_not_block_mic(self):
        """Регресс: раньше mix по min() блокировал микрофон, если системная
        сторона молчала — звонок выходил пустым."""
        sys_src = _FakeSource([])  # система не отдаёт НИЧЕГО
        mic_src = _FakeSource([np.full(16000, 0.4, dtype=np.float32)])
        cap = system_audio.CombinedCallCapture(system=sys_src, mic=mic_src)
        cap.start()
        chunk = cap.take_chunk(min_sec=0.5, target_sec=0.6, hard_max_sec=1.0)
        self.assertIsNotNone(chunk)
        self.assertGreater(float(np.max(np.abs(chunk))), 0.3)

    def test_dead_mic_does_not_block_system(self):
        sys_src = _FakeSource([np.full(16000, 0.35, dtype=np.float32)])
        mic_src = _FakeSource([])
        cap = system_audio.CombinedCallCapture(system=sys_src, mic=mic_src)
        cap.start()
        chunk = cap.take_chunk(min_sec=0.5, target_sec=0.6, hard_max_sec=1.0)
        self.assertIsNotNone(chunk)
        self.assertGreater(float(np.max(np.abs(chunk))), 0.3)

    def test_no_audio_is_dropped_on_uneven_sides(self):
        """Длинная системная сторона + короткий микрофон: суммарная длина
        объединённого потока = длине более длинной стороны (ничего не теряем)."""
        sys_src = _FakeSource([np.full(16000, 0.3, dtype=np.float32)])
        mic_src = _FakeSource([np.full(4000, 0.2, dtype=np.float32)])
        cap = system_audio.CombinedCallCapture(system=sys_src, mic=mic_src)
        cap.start()
        got = []
        while True:
            c = cap.take_chunk(min_sec=0.1, target_sec=0.3, hard_max_sec=0.5)
            if c is None:
                break
            got.append(c)
        total = sum(len(c) for c in got)
        tail = cap.stop()
        if tail is not None:
            total += len(tail)
        self.assertEqual(total, 16000)

    def test_labeled_chunks_carry_side_and_timestamp(self):
        """Каждая дорожка режется и распознаётся отдельно; метка времени —
        позиция куска в этой дорожке (по потреблённым сэмплам, без дрейфа)."""
        sys_src = _FakeSource([np.full(16000, 0.3, dtype=np.float32)])   # 1s
        mic_src = _FakeSource([np.full(32000, 0.4, dtype=np.float32)])   # 2s
        cap = system_audio.CombinedCallCapture(system=sys_src, mic=mic_src)
        cap.start()
        got = cap.take_labeled_chunks(min_sec=0.5, target_sec=1.0, hard_max_sec=2.0)
        sides = {side: (ts, len(a)) for side, ts, a in got}
        self.assertEqual(set(sides), {"system", "mic"})
        self.assertEqual(sides["system"], (0.0, 16000))
        self.assertEqual(sides["mic"], (0.0, 32000))

    def test_timestamps_advance_with_consumed_audio(self):
        sys_src = _FakeSource([
            np.full(16000, 0.3, dtype=np.float32),
            np.full(16000, 0.3, dtype=np.float32),
        ])
        cap = system_audio.CombinedCallCapture(system=sys_src, mic=None)
        cap.start()
        first = cap.take_labeled_chunks(min_sec=0.5, target_sec=1.0, hard_max_sec=2.0)
        second = cap.take_labeled_chunks(min_sec=0.5, target_sec=1.0, hard_max_sec=2.0)
        self.assertEqual(first[0][1], 0.0)
        self.assertEqual(second[0][1], 1.0)  # второй кусок начинается на 1с

    def test_labeled_chunks_empty_when_nothing_ready(self):
        cap = system_audio.CombinedCallCapture(
            system=_FakeSource([]), mic=_FakeSource([])
        )
        cap.start()
        self.assertEqual(
            cap.take_labeled_chunks(min_sec=0.5, target_sec=1.0, hard_max_sec=2.0), []
        )

    def test_labeled_tails_on_stop(self):
        class _TailSource(_FakeSource):
            def stop(self):
                self.stopped = True
                return np.full(8000, 0.25, dtype=np.float32)

        sys_src = _TailSource([])
        cap = system_audio.CombinedCallCapture(system=sys_src, mic=None)
        cap.start()
        tails = cap.stop_labeled()
        self.assertEqual(len(tails), 1)
        side, ts, audio = tails[0]
        self.assertEqual(side, "system")
        self.assertEqual(len(audio), 8000)

    def test_health_uses_the_live_side(self):
        """Если хотя бы одна сторона отдаёт кадры, источник считается живым —
        иначе медленный старт хелпера вызывал ложные «переоткрытия»."""

        class _Stalled(_FakeSource):
            def seconds_since_last_frame(self, now=None):
                return 99.0

        cap = system_audio.CombinedCallCapture(
            system=_Stalled([]), mic=_FakeSource([])
        )
        cap.start()
        self.assertLess(cap.seconds_since_last_frame(), 1.0)


if __name__ == "__main__":
    unittest.main()
