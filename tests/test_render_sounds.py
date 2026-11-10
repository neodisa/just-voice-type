import importlib.util
import os
import unittest

import numpy as np

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "render_sounds.py")
_spec = importlib.util.spec_from_file_location("render_sounds", _PATH)
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


class LoudnessTest(unittest.TestCase):
    def test_full_scale_997hz_sine_is_minus_3_lufs(self):
        # BS.1770 reference: a full-scale 997 Hz sine reads −3.01 LUFS
        t = np.arange(rs.SR) / rs.SR
        x = np.sin(2 * np.pi * 997 * t)
        self.assertAlmostEqual(rs.loudness(x), -3.01, delta=0.1)

    def test_stereo_is_measured_as_its_mix(self):
        t = np.arange(rs.SR) / rs.SR
        x = 0.5 * np.sin(2 * np.pi * 997 * t)
        self.assertAlmostEqual(rs.loudness(np.stack([x, x], axis=1)), rs.loudness(x), places=6)


class TrimTailTest(unittest.TestCase):
    def test_cuts_silence_keeps_20ms_and_fades_to_zero(self):
        loud = np.full((4800, 2), 0.5)
        x = np.concatenate([loud, np.zeros((48000, 2))])
        y = rs.trim_tail(x)
        self.assertEqual(len(y), 4800 + int(rs.TAIL_KEEP_SEC * rs.SR))
        self.assertEqual(y[0, 0], 0.5)
        self.assertAlmostEqual(float(y[-1, 0]), 0.0, places=6)

    def test_silence_trims_to_nothing(self):
        self.assertEqual(len(rs.trim_tail(np.zeros((1000, 2)))), 0)


if __name__ == "__main__":
    unittest.main()
