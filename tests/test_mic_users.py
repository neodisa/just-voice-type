import os
import sys
import unittest

import mic_users as mu
from mic_users import AudioClient as C


class FakeBackend:
    def __init__(self, clients=(), input_running=True, fail=False, supported=True):
        self._clients = list(clients)
        self._running = input_running
        self._fail = fail
        self.supported = supported
        self.walks = 0

    def input_running(self):
        if self._fail:
            raise OSError("boom")
        return self._running

    def clients(self):
        self.walks += 1
        return list(self._clients)


ZOOM = C(100, "us.zoom.xos", True, True)
ME = C(1, "com.whisperflow.local", True, False)
CHROME = C(200, "com.google.Chrome.helper", True, True)
MUSIC = C(300, "com.apple.Music", False, True)


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        mu._logged.clear()

    def test_excludes_own_pids(self):
        self.assertEqual(mu.snapshot({1}, backend=FakeBackend([ZOOM, ME])), [ZOOM])

    def test_idle_fast_path_skips_the_walk(self):
        b = FakeBackend([MUSIC], input_running=False)
        self.assertEqual(mu.snapshot(set(), backend=b), [])
        self.assertEqual(b.walks, 0)

    def test_need_output_walks_even_when_no_input_runs(self):
        b = FakeBackend([MUSIC], input_running=False)
        self.assertEqual(mu.snapshot(set(), need_output=True, backend=b), [MUSIC])

    def test_core_audio_failure_is_empty_and_logged_once(self):
        logged = []
        b = FakeBackend(fail=True)
        self.assertEqual(mu.snapshot(set(), backend=b, log=logged.append), [])
        self.assertEqual(mu.snapshot(set(), backend=b, log=logged.append), [])
        self.assertEqual(len(logged), 1)

    def test_unsupported_backend_is_empty(self):
        self.assertEqual(mu.snapshot(set(), backend=FakeBackend([ZOOM], supported=False)), [])
        self.assertFalse(mu.is_supported(FakeBackend(supported=False)))


class TestKeys(unittest.TestCase):
    def test_helper_suffixes_fold_into_the_app(self):
        self.assertEqual(mu.app_key(CHROME), "com.google.Chrome")
        self.assertEqual(mu.app_key(C(1, "com.microsoft.edgemac.helper.renderer", True, False)),
                         "com.microsoft.edgemac")
        self.assertEqual(mu.app_key(C(1, "com.tinyspeck.slackmacgap.Helper", True, False)),
                         "com.tinyspeck.slackmacgap")
        self.assertEqual(mu.app_key(ZOOM), "us.zoom.xos")

    def test_no_bundle_falls_back_to_pid(self):
        self.assertEqual(mu.app_key(C(42, "", True, False)), "pid:42")

    def test_usage_splits_mic_and_output(self):
        u = mu.usage([ZOOM, CHROME, MUSIC], name=lambda key, pid: key.upper())
        self.assertEqual(u.on_mic, frozenset({"us.zoom.xos", "com.google.Chrome"}))
        self.assertEqual(u.playing, frozenset({"us.zoom.xos", "com.google.Chrome", "com.apple.Music"}))
        self.assertEqual(u.names, {"us.zoom.xos": "US.ZOOM.XOS", "com.google.Chrome": "COM.GOOGLE.CHROME"})


class TestNames(unittest.TestCase):
    def test_running_app_by_bundle_wins(self):
        n = mu.app_name("com.google.Chrome", 200, by_bundle=lambda b: "Google Chrome",
                        by_pid=lambda p: "Google Chrome Helper")
        self.assertEqual(n, "Google Chrome")

    def test_webkit_gpu_is_safari(self):
        self.assertEqual(mu.app_name("com.apple.WebKit.GPU", 5, by_bundle=lambda b: None,
                                     by_pid=lambda p: None), "Safari")

    def test_pid_then_key_then_nothing(self):
        self.assertEqual(mu.app_name("x.y", 5, by_bundle=lambda b: None, by_pid=lambda p: "Y"), "Y")
        self.assertEqual(mu.app_name("x.y", 5, by_bundle=lambda b: None, by_pid=lambda p: None), "x.y")
        self.assertIsNone(mu.app_name("pid:5", 5, by_bundle=lambda b: "nope", by_pid=lambda p: None))

    def test_lookup_errors_are_swallowed(self):
        def boom(_):
            raise RuntimeError("AppKit")
        self.assertEqual(mu.app_name("x.y", 5, by_bundle=boom, by_pid=boom), "x.y")


@unittest.skipUnless(sys.platform == "darwin", "Core Audio only on macOS")
class TestLive(unittest.TestCase):
    def test_snapshot_returns_a_list_without_ourselves(self):
        got = mu.snapshot({os.getpid()}, need_output=True)
        self.assertIsInstance(got, list)
        self.assertNotIn(os.getpid(), [c.pid for c in got])


if __name__ == "__main__":
    unittest.main()
