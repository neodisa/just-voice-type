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


if __name__ == "__main__":
    unittest.main()
