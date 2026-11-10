import os
import tempfile
import unittest

import notifier


class FakeWorkspace:
    def __init__(self):
        self.selected = []
        self.opened = []

    def activateFileViewerSelectingURLs_(self, urls):
        self.selected.append([u.path() for u in urls])

    def openURL_(self, url):
        self.opened.append(url.path())
        return True


class RevealTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = os.path.join(self.tmp.name, "call.md")
        with open(self.file, "w") as f:
            f.write("x")
        self.ws = FakeWorkspace()

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_file_is_selected_in_finder(self):
        self.assertTrue(notifier.reveal_in_finder(self.file, workspace=self.ws))
        self.assertEqual(self.ws.selected, [[self.file]])

    def test_missing_file_opens_its_folder(self):
        gone = os.path.join(self.tmp.name, "gone.md")
        self.assertTrue(notifier.reveal_in_finder(gone, workspace=self.ws))
        self.assertEqual(self.ws.opened, [self.tmp.name])

    def test_nothing_to_show(self):
        self.assertFalse(notifier.reveal_in_finder("/nope/nope/x.md", workspace=self.ws))
        self.assertFalse(notifier.reveal_in_finder("", workspace=self.ws))


class ClickTest(unittest.TestCase):
    def setUp(self):
        self.revealed = []

    def test_default_click_reveals_the_path(self):
        notifier.handle_click({"reveal": "/a/b.md"}, notifier.DEFAULT_ACTION, self.revealed.append)
        self.assertEqual(self.revealed, ["/a/b.md"])

    def test_dismiss_does_nothing(self):
        notifier.handle_click({"reveal": "/a/b.md"}, "com.apple.UNNotificationDismissActionIdentifier", self.revealed.append)
        self.assertEqual(self.revealed, [])

    def test_click_without_path_does_nothing(self):
        notifier.handle_click({}, notifier.DEFAULT_ACTION, self.revealed.append)
        notifier.handle_click(None, notifier.DEFAULT_ACTION, self.revealed.append)
        self.assertEqual(self.revealed, [])


class FakeCenter:
    def __init__(self, error=None):
        self.requests = []
        self.error = error

    def addNotificationRequest_withCompletionHandler_(self, request, handler):
        self.requests.append(request)
        handler(self.error)


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.fallen_back = []
        self.n = notifier.Notifier(log=lambda *a: None, fallback=lambda t, m: self.fallen_back.append((t, m)))

    def test_without_a_center_falls_back_to_osascript(self):
        self.n.notify("Voice Type", "hi", reveal="/a.md")
        self.assertEqual(self.fallen_back, [("Voice Type", "hi")])

    def test_start_outside_an_app_bundle_keeps_the_fallback(self):
        self.n.start(bundle_id=lambda: None)
        self.assertFalse(self.n.native)
        self.n.notify("Voice Type", "hi")
        self.assertEqual(len(self.fallen_back), 1)

    def test_start_under_pythons_own_bundle_keeps_the_fallback(self):
        # dev run from the venv: mainBundle is Python.app, not Voice Type.app
        self.n.start(bundle_id=lambda: "org.python.python")
        self.assertFalse(self.n.native)

    def test_native_request_carries_title_body_and_path(self):
        center = FakeCenter()
        self.n.use_center(center)
        self.n.notify("Voice Type", "Call transcribed", reveal="/calls/a.md")
        self.assertEqual(self.fallen_back, [])
        content = center.requests[0].content()
        self.assertEqual((content.title(), content.body()), ("Voice Type", "Call transcribed"))
        self.assertEqual(content.userInfo()["reveal"], "/calls/a.md")

    def test_native_request_without_path_has_no_user_info(self):
        center = FakeCenter()
        self.n.use_center(center)
        self.n.notify("Voice Type", "hi")
        self.assertNotIn("reveal", center.requests[0].content().userInfo() or {})

    def test_refused_request_falls_back(self):
        self.n.use_center(FakeCenter(error="not authorized"))
        self.n.notify("Voice Type", "hi")
        self.assertEqual(self.fallen_back, [("Voice Type", "hi")])


if __name__ == "__main__":
    unittest.main()
