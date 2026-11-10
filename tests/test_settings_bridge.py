import os
import sys
import tempfile
import textwrap
import time
import unittest

import settings_bridge as sb

FAKE_HELPER = textwrap.dedent('''
    import json, sys
    print(json.dumps({"type": "ready"}), flush=True)
    print("not json", flush=True)
    for line in sys.stdin:
        msg = json.loads(line)
        if msg["type"] == "quit":
            break
        if msg["type"] == "state":
            print(json.dumps({"type": "action", "req": 1, "name": "echo", "args": {"rev": msg["rev"]}}), flush=True)
        if msg["type"] == "focus":
            print(json.dumps({"type": "set", "req": "f", "key": "section", "value": msg["section"]}), flush=True)
    print(json.dumps({"type": "closed"}), flush=True)
''')


def wait_for(bridge, n, timeout=5.0):
    got, end = [], time.time() + timeout
    while len(got) < n and time.time() < end:
        got += bridge.poll()
        time.sleep(0.02)
    return got


class TestParse(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(sb.parse_line(b'{"type":"ready"}\n'), {"type": "ready"})
        self.assertEqual(
            sb.parse_line('{"type":"action","req":"1","name":"x"}'),
            {"type": "action", "req": "1", "name": "x", "args": {}},
        )
        self.assertEqual(sb.parse_line('{"type":"set","req":5,"key":"hotkey","value":"f14"}')["req"], "5")

    def test_invalid(self):
        for line in ("", "garbage", "[1]", '{"type":"hack"}', '{"type":"set","value":1}',
                     '{"type":"action","name":"x","args":[1]}', '{"type":"action"}'):
            self.assertIsNone(sb.parse_line(line), line)

    def test_encode_is_one_line_utf8(self):
        b = sb.encode({"type": "toast", "text": "Привет\nмир"})
        self.assertTrue(b.endswith(b"\n"))
        self.assertEqual(b.count(b"\n"), 1)
        self.assertIn("Привет".encode(), b)


class TestProcess(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.script = os.path.join(self._tmp.name, "helper.py")
        with open(self.script, "w") as f:
            f.write(FAKE_HELPER)
        self.logs = []
        self.bridge = sb.SettingsBridge(command=lambda: [sys.executable, self.script], log=self.logs.append)

    def tearDown(self):
        self.bridge.close()
        self._tmp.cleanup()

    def test_roundtrip_and_close(self):
        self.assertTrue(self.bridge.open(section="terms"))
        self.assertEqual(self.bridge.pending_section, "terms")
        self.assertEqual(wait_for(self.bridge, 1), [{"type": "ready"}])
        self.assertTrue(any("not json" in l for l in self.logs))
        self.bridge.send({"type": "state", "rev": 3})
        msgs = wait_for(self.bridge, 1)
        self.assertEqual(msgs[0]["args"], {"rev": 3})
        self.assertEqual(msgs[0]["req"], "1")
        # повторный open не плодит процессы, а шлёт focus
        self.assertTrue(self.bridge.open(section="calls"))
        self.assertEqual(wait_for(self.bridge, 1)[0]["value"], "calls")
        self.bridge.send({"type": "quit"})
        msgs = wait_for(self.bridge, 1)
        self.assertEqual([m["type"] for m in msgs], ["closed"])
        self.assertFalse(self.bridge.is_open())
        self.assertFalse(self.bridge.send({"type": "state", "rev": 4}))

    def test_missing_helper(self):
        b = sb.SettingsBridge(command=lambda: None)
        self.assertFalse(b.available())
        self.assertFalse(b.open())
