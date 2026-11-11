import json
import threading
import unittest

import offer_prompt


class FakeStdin:
    def __init__(self, closed):
        self.data = b""
        self._closed = closed

    def write(self, b):
        self.data += b

    def flush(self):
        pass

    def close(self):
        self._closed.set()


class FakeStdout:
    """Отдаёт строки, затем (hold=True) ждёт закрытия stdin — как живой хелпер."""

    def __init__(self, lines, hold, closed):
        self._lines = [l.encode() if isinstance(l, str) else l for l in lines]
        self._hold = hold
        self._closed = closed

    def __iter__(self):
        yield from self._lines
        if self._hold:
            self._closed.wait(5)


class FakeProc:
    def __init__(self, lines=(), hold=False):
        self.closed = threading.Event()
        self.stdin = FakeStdin(self.closed)
        self.stdout = FakeStdout(lines, hold, self.closed)
        self.killed = False
        self.waited = threading.Event()

    def wait(self, timeout=None):
        self.waited.set()
        return 0

    def poll(self):
        return 0 if self.closed.is_set() or self.waited.is_set() else None

    def kill(self):
        self.killed = True
        self.closed.set()


PAYLOAD = {"title": "Zoom использует микрофон", "body": "Записать звонок?", "record": "Записать",
           "dismiss": "Не сейчас", "hint": "или", "key": "F13"}


class Base(unittest.TestCase):
    def setUp(self):
        self.procs, self.argv, self.answers = [], [], []
        self.answered = threading.Event()

    def prompt(self, *procs, helper="/x/JustVoiceTypeSettings"):
        queue = list(procs)

        def popen(argv, **kw):
            self.argv.append(argv)
            p = queue.pop(0)
            self.procs.append(p)
            return p

        return offer_prompt.OfferPrompt(helper=lambda: helper, log=lambda *a: None, popen=popen)

    def on_answer(self, key, answer):
        self.answers.append((key, answer))
        self.answered.set()


class TestShow(Base):
    def test_writes_the_payload_and_reports_the_answer(self):
        p = self.prompt(FakeProc(['{"type":"offer_answer","answer":"record"}\n']))
        self.assertTrue(p.show("us.zoom.xos", PAYLOAD, self.on_answer))
        self.assertTrue(self.answered.wait(2))
        self.assertEqual(self.answers, [("us.zoom.xos", "record")])
        self.assertEqual(self.argv, [["/x/JustVoiceTypeSettings", "--offer"]])
        sent = json.loads(self.procs[0].stdin.data.decode())
        self.assertEqual(sent["type"], "offer")
        self.assertEqual(sent["title"], "Zoom использует микрофон")

    def test_dismiss_is_reported_too(self):
        p = self.prompt(FakeProc(['{"type":"offer_answer","answer":"dismiss"}\n']))
        p.show("us.zoom.xos", PAYLOAD, self.on_answer)
        self.assertTrue(self.answered.wait(2))
        self.assertEqual(self.answers, [("us.zoom.xos", "dismiss")])

    def test_no_helper_means_no_panel(self):
        p = self.prompt(helper=None)
        self.assertFalse(p.show("k", PAYLOAD, self.on_answer))
        self.assertEqual(self.argv, [])

    def test_popen_failure_means_no_panel(self):
        def popen(argv, **kw):
            raise OSError("no exec")

        p = offer_prompt.OfferPrompt(helper=lambda: "/x/h", log=lambda *a: None, popen=popen)
        self.assertFalse(p.show("k", PAYLOAD, self.on_answer))
        self.assertIsNone(p.showing)

    def test_exit_without_an_answer_reports_nothing(self):
        proc = FakeProc(["garbage\n", '{"type":"other"}\n'])
        p = self.prompt(proc)
        p.show("k", PAYLOAD, self.on_answer)
        self.assertTrue(proc.waited.wait(2))
        self.assertEqual(self.answers, [])


class TestWithdraw(Base):
    def test_withdraw_closes_the_panel_of_that_app(self):
        proc = FakeProc(hold=True)
        p = self.prompt(proc)
        p.show("us.zoom.xos", PAYLOAD, self.on_answer)
        self.assertEqual(p.showing, "us.zoom.xos")
        p.withdraw("com.google.Chrome")
        self.assertFalse(proc.closed.is_set())
        p.withdraw("us.zoom.xos")
        self.assertTrue(proc.closed.is_set())
        self.assertIsNone(p.showing)
        self.assertEqual(self.answers, [])

    def test_withdraw_without_a_key_closes_any_panel(self):
        proc = FakeProc(hold=True)
        p = self.prompt(proc)
        p.show("k", PAYLOAD, self.on_answer)
        p.withdraw()
        self.assertTrue(proc.closed.is_set())

    def test_a_new_offer_replaces_the_old_panel(self):
        first, second = FakeProc(hold=True), FakeProc(hold=True)
        p = self.prompt(first, second)
        p.show("us.zoom.xos", PAYLOAD, self.on_answer)
        p.show("com.google.Chrome", PAYLOAD, self.on_answer)
        self.assertTrue(first.closed.is_set())
        self.assertEqual(p.showing, "com.google.Chrome")
        p.withdraw()

    def test_withdraw_when_nothing_shows_is_harmless(self):
        self.prompt().withdraw("x")


if __name__ == "__main__":
    unittest.main()
