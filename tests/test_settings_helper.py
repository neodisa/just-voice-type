"""Собранный SwiftUI-хелпер разбирает настоящий снимок из settings_model
(режим --protocol-selftest, без окна). Пропускается, если хелпер не собран:
./scripts/build_settings.sh."""
import json
import os
import subprocess
import unittest

import i18n
import menubar_icon
import settings_model as sm

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "native", "JustVoiceTypeSettings")


@unittest.skipUnless(os.access(HELPER, os.X_OK), "settings helper not built")
class TestHelperDecodesPythonSnapshot(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def selftest(self, msg):
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        p = subprocess.run([HELPER, "--protocol-selftest"], input=line.encode(), capture_output=True, timeout=20)
        return p.returncode, [json.loads(l) for l in p.stdout.decode().splitlines() if l.strip()]

    def test_full_snapshot_in_both_languages(self):
        for lang in ("ru", "en"):
            i18n.set_language(lang)
            v = sm.View(
                version="0.14.0", now=1_762_790_000.0,
                snapshot=menubar_icon.Snapshot(now=1_762_790_000.0, call_state="recording", call_elapsed=12),
                calls=[{"ts": 1_762_780_000.0, "duration_sec": 60, "path": "/x.txt", "preview": "[00:00] p"}],
                call_state="recording", call_started_at=1_762_789_988.0,
                terms={"фигма": "Figma"}, vocabulary=["Figma"], favorites=["ru", "en"],
                input_devices=["BlackHole 2ch"], call_device="Gone", auto_capture=False,
                model="mlx-community/whisper-medium-mlx", model_loading=True, model_progress=0.3,
                update={"state": "update", "version": "0.15.0"},
            )
            msg = sm.build(v, rev=7, ack="r3", errors={"term": "x"})
            code, out = self.selftest(msg)
            self.assertEqual(code, 0, lang)
            self.assertEqual(out[0], {"type": "ready"})
            self.assertEqual(out[1]["name"], "check_updates")

    def test_garbage_is_rejected(self):
        p = subprocess.run([HELPER, "--protocol-selftest"], input=b'{"type":"state"}\n', capture_output=True, timeout=20)
        self.assertEqual(p.returncode, 2)
