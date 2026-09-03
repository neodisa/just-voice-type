import threading
import time
import types
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


class TestRecorderDeviceParams(unittest.TestCase):
    def test_defaults_preserve_existing_behavior(self):
        r = voice_type.Recorder()
        self.assertIsNone(r.device)
        self.assertFalse(r.all_channels)

    def test_device_and_all_channels_are_settable(self):
        r = voice_type.Recorder(device="Aggregate Device", all_channels=True)
        self.assertEqual(r.device, "Aggregate Device")
        self.assertTrue(r.all_channels)


class _WedgedStream:
    """Стрим, чьи abort()/close() не возвращаются никогда.

    Именно так себя ведёт «протухший» CoreAudio: Pa_AbortStream /
    Pa_CloseStream встают насмерть (смена устройства, выход из сна,
    занятый HAL-лок), и раньше это вешало весь control_loop.
    """

    def __init__(self, released):
        self._released = released
        self.aborted = False

    def abort(self):
        self.aborted = True
        self._released.wait()

    def close(self):
        self._released.wait()


class TestRecorderStopSurvivesWedgedCoreAudio(unittest.TestCase):
    def setUp(self):
        self.released = threading.Event()
        self.addCleanup(self.released.set)
        self.rec = voice_type.Recorder()
        self.np = self.rec.np

    def _load_one_second_of_speech(self):
        """Секунда «речи» (громче порога тишины) в буфере колбэка."""
        np = self.np
        tone = (np.sin(np.arange(16000) * 0.2) * 8000).astype(np.int16)
        self.rec._native_sr = 16000
        self.rec._native_channels = 1
        self.rec._recording = True
        self.rec._frames = [tone.reshape(-1, 1)]

    def test_stop_returns_audio_even_if_teardown_hangs(self):
        self._load_one_second_of_speech()
        self.rec._stream = _WedgedStream(self.released)
        t0 = time.time()
        audio = self.rec.stop()
        elapsed = time.time() - t0
        self.assertLess(elapsed, 2.0, "stop() заблокировался на закрытии стрима")
        self.assertIsNotNone(audio, "аудио сессии потерялось")
        self.assertEqual(len(audio), 16000)

    def test_stop_releases_stream_ownership_to_background(self):
        self._load_one_second_of_speech()
        stream = _WedgedStream(self.released)
        self.rec._stream = stream
        self.rec.stop()
        self.assertIsNone(self.rec._stream)
        # закрытие ушло в фон и ещё висит — это должно быть видно наружу,
        # чтобы честно сказать, что залипла аудио-подсистема
        deadline = time.time() + 2.0
        while not stream.aborted and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(stream.aborted)
        self.assertIsNotNone(self.rec.stuck_teardown(older_than=0.0))

    def test_no_stuck_teardown_when_close_is_fast(self):
        self._load_one_second_of_speech()
        self.released.set()  # abort/close возвращаются сразу
        self.rec._stream = _WedgedStream(self.released)
        self.rec.stop()
        deadline = time.time() + 2.0
        while self.rec._teardowns and time.time() < deadline:
            time.sleep(0.01)
        self.assertIsNone(self.rec.stuck_teardown(older_than=0.0))

    def test_stale_callback_cannot_write_into_next_session(self):
        np = self.np
        cb = self.rec._make_callback(self.rec._gen)
        self.rec._recording = True
        data = np.zeros((10, 1), dtype=np.int16)
        cb(data, 10, None, None)
        self.assertEqual(len(self.rec._frames), 1)
        # стрим брошен (его close() висит), стартовала новая сессия
        self.rec._gen += 1
        cb(data, 10, None, None)
        self.assertEqual(
            len(self.rec._frames), 1, "кадры брошенного стрима попали в новую сессию"
        )

    def test_stop_invalidates_callback_of_abandoned_stream(self):
        self._load_one_second_of_speech()
        gen_before = self.rec._gen
        self.rec._stream = _WedgedStream(self.released)
        self.rec.stop()
        self.assertNotEqual(self.rec._gen, gen_before)

    def test_reinit_does_not_terminate_portaudio_while_teardown_pending(self):
        # Pa_Terminate поверх висящего Pa_CloseStream — это краш процесса,
        # так что переинициализацию в этот момент делать нельзя
        calls = []
        self.rec.sd = types.SimpleNamespace(
            _terminate=lambda: calls.append("terminate"),
            _initialize=lambda: calls.append("initialize"),
        )
        self.rec._teardowns = {1: {"phase": "close", "t0": time.time(), "reported": False}}
        self.rec._native_sr = 48000
        self.rec._reinit_portaudio()
        self.assertEqual(calls, [])
        # кэш устройства всё равно сбрасываем — вдруг микрофон сменился
        self.assertIsNone(self.rec._native_sr)

    def test_reinit_terminates_portaudio_when_nothing_is_pending(self):
        calls = []
        self.rec.sd = types.SimpleNamespace(
            _terminate=lambda: calls.append("terminate"),
            _initialize=lambda: calls.append("initialize"),
        )
        self.rec._reinit_portaudio()
        self.assertEqual(calls, ["terminate", "initialize"])

class _FakeStream:
    """Свежий стрим, который открывается мгновенно."""

    samplerate = 48000
    channels = 1

    def start(self):
        pass

    def abort(self):
        pass

    def close(self):
        pass


class TestRecorderRestartStreamSurvivesWedgedCoreAudio(unittest.TestCase):
    """restart_stream() — путь авто-восстановления звонка при смене
    аудио-маршрутизации, то есть ровно та ситуация, в которой close()
    и залипает. Он не имеет права вешать control_loop."""

    def setUp(self):
        self.released = threading.Event()
        self.addCleanup(self.released.set)
        self.rec = voice_type.Recorder()
        self.terminated = []
        self.rec.sd = types.SimpleNamespace(
            InputStream=lambda **kw: _FakeStream(),
            _terminate=lambda: self.terminated.append("terminate"),
            _initialize=lambda: self.terminated.append("initialize"),
        )
        self.rec._native_sr = 48000
        self.rec._native_channels = 1
        self.rec._recording = True

    def test_restart_does_not_wait_for_a_wedged_close(self):
        self.rec._stream = _WedgedStream(self.released)
        t0 = time.time()
        ok = self.rec.restart_stream()
        elapsed = time.time() - t0
        self.assertTrue(ok)
        self.assertLess(elapsed, 4.0, "restart_stream() ждёт залипший close()")
        self.assertIsInstance(self.rec._stream, _FakeStream)

    def test_restart_mutes_the_abandoned_stream(self):
        np = self.rec.np
        self.rec._stream = _WedgedStream(self.released)
        stale_cb = self.rec._make_callback(self.rec._gen)
        self.rec.restart_stream()
        # брошенный стрим ещё жив (его close() висит) и продолжает звать
        # колбэк — в идущий звонок его кадры попадать не должны
        stale_cb(np.zeros((10, 1), dtype=np.int16), 10, None, None)
        self.assertEqual(self.rec._frames, [])

    def test_restart_skips_portaudio_reinit_while_close_is_wedged(self):
        # Pa_Terminate поверх висящего Pa_CloseStream роняет процесс
        self.rec._stream = _WedgedStream(self.released)
        self.rec.restart_stream()
        self.assertEqual(self.terminated, [])

    def test_restart_still_reinits_portaudio_when_close_is_fast(self):
        # обычный случай: закрытие проходит, и PortAudio надо честно
        # переинициализировать — иначе «протухший» контекст не лечится
        self.rec._stream = _FakeStream()
        self.rec.restart_stream()
        self.assertEqual(self.terminated, ["terminate", "initialize"])

class TestStreamTeardownAtExit(unittest.TestCase):
    """Финализация интерпретатора поверх активного Pa_CloseStream роняет
    процесс с SIGTRAP — на выходе фоновое закрытие надо дождаться, а
    залипшее — обойти жёстким выходом."""

    def setUp(self):
        self.released = threading.Event()
        self.addCleanup(self.released.set)
        self.rec = voice_type.Recorder()
        self.rec._native_sr = 16000
        self.rec._recording = True
        self.rec._frames = []

    def test_counter_drops_back_to_zero_after_a_fast_teardown(self):
        self.released.set()
        self.rec._stream = _WedgedStream(self.released)
        self.rec.stop()
        self.assertTrue(
            voice_type._drain_stream_teardowns_at_exit(timeout=2.0),
            "быстрое закрытие не дождались",
        )
        self.assertEqual(voice_type._stream_teardowns["count"], 0)

    def test_hard_exits_when_teardown_is_wedged(self):
        exits = []
        self.rec._stream = _WedgedStream(self.released)
        self.rec.stop()
        drained = voice_type._drain_stream_teardowns_at_exit(
            timeout=0.2, hard_exit=exits.append
        )
        self.assertFalse(drained)
        self.assertEqual(exits, [0])

    def test_exit_drain_is_registered_after_sounddevice_import(self):
        # atexit — LIFO: наш дренаж должен встать ПОСЛЕ sounddevice, иначе
        # его Pa_Terminate на выходе прилетит поверх живого Pa_CloseStream
        import atexit as _atexit

        voice_type._exit_drain_registered["done"] = False
        before = _atexit._ncallbacks()
        voice_type.Recorder()
        self.assertTrue(voice_type._exit_drain_registered["done"])
        self.assertEqual(_atexit._ncallbacks(), before + 1)
        # повторная регистрация не плодит обработчиков
        voice_type._register_exit_drain()
        self.assertEqual(_atexit._ncallbacks(), before + 1)

    def test_no_wait_when_nothing_is_in_flight(self):
        t0 = time.time()
        self.assertTrue(voice_type._drain_stream_teardowns_at_exit(timeout=5.0))
        self.assertLess(time.time() - t0, 1.0)

if __name__ == "__main__":
    unittest.main()
