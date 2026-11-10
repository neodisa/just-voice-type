import os
import plistlib
import tempfile
import unittest

import login_item as li


class TestLoginItem(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.app = os.path.join(self.home, "Applications", "Just Voice Type.app")
        os.makedirs(os.path.join(self.app, "Contents"))
        with open(os.path.join(self.app, "Contents", "Info.plist"), "wb") as f:
            plistlib.dump({"CFBundleIdentifier": "com.justvoicetype.app"}, f)

    def tearDown(self):
        self._tmp.cleanup()

    def test_bundle_path_from_executable(self):
        exe = "/Applications/Just Voice Type.app/Contents/MacOS/JustVoiceType-python"
        self.assertEqual(li.app_bundle_path(exe), "/Applications/Just Voice Type.app")
        self.assertIsNone(li.app_bundle_path("/usr/local/bin/python3"))

    def test_render(self):
        d = plistlib.loads(li.render_plist(self.app, "com.x"))
        self.assertEqual(d["ProgramArguments"], ["/usr/bin/open", "-a", self.app])
        self.assertTrue(d["RunAtLoad"])
        self.assertEqual(d["AssociatedBundleIdentifiers"], ["com.x"])
        self.assertEqual(d["Label"], li.LABEL)

    def test_enable_disable(self):
        self.assertFalse(li.is_enabled(self.app, self.home))
        self.assertIsNone(li.enable(self.app, self.home))
        self.assertTrue(li.is_enabled(self.app, self.home))
        with open(li.plist_path(self.home), "rb") as f:
            self.assertEqual(plistlib.load(f)["AssociatedBundleIdentifiers"], ["com.justvoicetype.app"])
        self.assertFalse(li.is_enabled("/other/App.app", self.home))
        calls = []
        self.assertIsNone(li.disable(self.home, run=lambda *a, **k: calls.append(a)))
        self.assertFalse(li.is_enabled(self.app, self.home))
        self.assertEqual(calls[0][0][:2], ["launchctl", "bootout"])
        self.assertIsNone(li.disable(self.home, run=lambda *a, **k: None))  # повторно — не ошибка

    def test_none_app(self):
        self.assertFalse(li.is_enabled(None, self.home))
