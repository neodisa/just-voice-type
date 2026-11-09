import os
import tempfile
import unittest
import wave

import numpy as np

import voice_type


def _write_wav(path, samples_bytes, sr, sampwidth=2, channels=1):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sr)
        wf.writeframes(samples_bytes)


class TestLoadWav16k(unittest.TestCase):
    def test_reads_16bit_16k_mono(self):
        sr = 16000
        data = (np.sin(np.linspace(0, 10, sr)) * 30000).astype(np.int16)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        self.addCleanup(os.unlink, path)
        _write_wav(path, data.tobytes(), sr)
        a = voice_type.load_wav_16k(path)
        self.assertEqual(a.dtype, np.float32)
        self.assertAlmostEqual(len(a), sr, delta=2)
        self.assertLessEqual(float(np.max(np.abs(a))), 1.0)

    def test_resamples_non_16k_up_to_16k(self):
        sr = 8000
        data = (np.ones(sr) * 10000).astype(np.int16)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        self.addCleanup(os.unlink, path)
        _write_wav(path, data.tobytes(), sr)
        a = voice_type.load_wav_16k(path)
        self.assertAlmostEqual(len(a), 16000, delta=4)

    def test_downmixes_stereo_to_mono(self):
        sr = 16000
        frames = sr
        mono = (np.sin(np.linspace(0, 10, frames)) * 20000).astype(np.int16)
        stereo = np.repeat(mono, 2)  # interleaved L=R
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        self.addCleanup(os.unlink, path)
        _write_wav(path, stereo.tobytes(), sr, sampwidth=2, channels=2)
        a = voice_type.load_wav_16k(path)
        self.assertEqual(a.dtype, np.float32)
        self.assertAlmostEqual(len(a), frames, delta=2)


class TestParakeetInterface(unittest.TestCase):
    def test_interface_matches_mlx_transcriber(self):
        import inspect

        self.assertEqual(
            inspect.signature(voice_type.ParakeetTranscriber.__init__),
            inspect.signature(voice_type.MLXTranscriber.__init__),
        )
        self.assertEqual(
            inspect.signature(voice_type.ParakeetTranscriber.transcribe),
            inspect.signature(voice_type.MLXTranscriber.transcribe),
        )
        self.assertTrue(hasattr(voice_type.ParakeetTranscriber, "warm_up"))


class TestTranscriberClassFor(unittest.TestCase):
    def test_parakeet_id_routes_to_parakeet(self):
        cls = voice_type.transcriber_class_for(
            "mlx-community/parakeet-tdt-0.6b-v3", "mlx")
        self.assertIs(cls, voice_type.ParakeetTranscriber)

    def test_whisper_mlx_routes_to_mlx(self):
        cls = voice_type.transcriber_class_for(
            "mlx-community/whisper-large-v3-mlx", "mlx")
        self.assertIs(cls, voice_type.MLXTranscriber)

    def test_faster_engine_routes_to_faster(self):
        cls = voice_type.transcriber_class_for("large-v3", "faster")
        self.assertIs(cls, voice_type.FasterWhisperTranscriber)

    def test_parakeet_id_wins_even_on_faster_engine(self):
        cls = voice_type.transcriber_class_for(
            "mlx-community/parakeet-tdt-0.6b-v3", "faster")
        self.assertIs(cls, voice_type.ParakeetTranscriber)

    def test_parakeet_match_is_case_insensitive(self):
        cls = voice_type.transcriber_class_for(
            "mlx-community/Parakeet-TDT-0.6b-v3", "mlx")
        self.assertIs(cls, voice_type.ParakeetTranscriber)


if __name__ == "__main__":
    unittest.main()


class _FakeMX:
    """Заглушка mlx.core: запоминает вызовы управления кэшем буферов."""

    def __init__(self, raises=False):
        self.raises = raises
        self.cache_limits = []
        self.clears = 0

    def set_cache_limit(self, n):
        if self.raises:
            raise RuntimeError("boom")
        self.cache_limits.append(n)
        return 0

    def clear_cache(self):
        if self.raises:
            raise RuntimeError("boom")
        self.clears += 1


class TestMLXCache(unittest.TestCase):
    def _install(self, mx):
        old = dict(voice_type._mlx_holder)
        self.addCleanup(voice_type._mlx_holder.update, old)
        voice_type._mlx_holder.update({"probed": True, "mx": mx})

    def test_limit_sets_cache_limit(self):
        mx = _FakeMX()
        self._install(mx)
        voice_type.limit_mlx_cache()
        self.assertEqual(mx.cache_limits, [voice_type.MLX_CACHE_LIMIT_BYTES])

    def test_trim_clears_cache(self):
        mx = _FakeMX()
        self._install(mx)
        voice_type.trim_mlx_cache()
        self.assertEqual(mx.clears, 1)

    def test_no_mlx_is_a_noop(self):
        self._install(None)
        voice_type.limit_mlx_cache()
        voice_type.trim_mlx_cache()  # не должно бросать

    def test_mlx_errors_are_swallowed(self):
        self._install(_FakeMX(raises=True))
        voice_type.limit_mlx_cache()
        voice_type.trim_mlx_cache()  # best-effort, наверх не пробрасываем


class TestParakeetWordTimestamps(unittest.TestCase):
    """Для печати по ходу речи нужны слова со временем — их даёт тот же
    полный проход модели, что и обычная диктовка."""

    def test_transcribe_words_groups_tokens(self):
        import types

        tr = voice_type.ParakeetTranscriber.__new__(voice_type.ParakeetTranscriber)
        tok = lambda text, s, e: types.SimpleNamespace(text=text, start=s, end=e)
        result = types.SimpleNamespace(
            tokens=[tok(" При", 0.0, 0.2), tok("вет", 0.2, 0.4), tok(" мир", 0.5, 0.8)]
        )
        tr._model = types.SimpleNamespace(
            preprocessor_config=None, generate=lambda mel: [result]
        )
        import unittest.mock as um

        with um.patch("parakeet_mlx.audio.get_logmel", lambda a, cfg: a):
            words = tr.transcribe_words(__import__("numpy").zeros(1600, dtype="float32"))
        self.assertEqual([w.text for w in words], ["Привет", "мир"])
        self.assertAlmostEqual(words[1].end, 0.8)

    def test_whisper_transcribers_do_not_claim_word_timestamps(self):
        self.assertFalse(hasattr(voice_type.MLXTranscriber, "transcribe_words"))
