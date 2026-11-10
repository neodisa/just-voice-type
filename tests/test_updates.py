import threading
import unittest

import updates


class TestVersions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updates.parse_version("v0.14.0"), (0, 14, 0))
        self.assertEqual(updates.parse_version("1.2.3-beta"), (1, 2, 3))
        self.assertEqual(updates.parse_version("garbage"), ())

    def test_newer(self):
        self.assertTrue(updates.is_newer("v0.15.0", "0.14.0"))
        self.assertTrue(updates.is_newer("0.14.1", "0.14"))
        self.assertFalse(updates.is_newer("v0.14.0", "0.14.0"))
        self.assertFalse(updates.is_newer("v0.13.9", "0.14.0"))
        self.assertFalse(updates.is_newer("", "0.14.0"))

    def test_interpret(self):
        r = updates.interpret({"tag_name": "v0.15.0", "html_url": "https://x"}, "0.14.0", 5.0)
        self.assertEqual(r, {"state": "update", "version": "0.15.0", "url": "https://x", "checked_at": 5.0})
        self.assertEqual(updates.interpret({"tag_name": "v0.14.0"}, "0.14.0", 5.0),
                         {"state": "uptodate", "checked_at": 5.0})


class TestChecker(unittest.TestCase):
    def run_checker(self, fetch):
        done = threading.Event()
        c = updates.Checker("0.14.0", fetch=fetch)
        self.assertTrue(c.start(done.set))
        self.assertTrue(done.wait(5))
        return c.state

    def test_update_found(self):
        self.assertEqual(self.run_checker(lambda v: {"tag_name": "v0.15.0"})["state"], "update")

    def test_network_error(self):
        def boom(v):
            raise OSError("offline")
        self.assertEqual(self.run_checker(boom), {"state": "error"})

    def test_no_double_start(self):
        gate = threading.Event()
        c = updates.Checker("0.14.0", fetch=lambda v: (gate.wait(5), {"tag_name": "v0.14.0"})[1])
        self.assertTrue(c.start())
        self.assertEqual(c.state, {"state": "checking"})
        self.assertFalse(c.start())
        gate.set()
