"""KeyTyper — долгоживущий процесс-печатальщик для печати по ходу речи."""
import json
import unittest

import voice_type


class _FakeStdin:
    def __init__(self, broken=False):
        self.lines = []
        self.broken = broken

    def write(self, s):
        if self.broken:
            raise BrokenPipeError()
        self.lines.append(s)

    def flush(self):
        pass

    def close(self):
        pass


class _FakeProc:
    def __init__(self, broken=False):
        self.stdin = _FakeStdin(broken)
        self.alive = True

    def poll(self):
        return None if self.alive else 0


class TestKeyTyper(unittest.TestCase):
    def test_sends_text_as_one_json_line(self):
        procs = []

        def spawn():
            procs.append(_FakeProc())
            return procs[-1]

        typer = voice_type.KeyTyper(spawn=spawn)
        self.assertTrue(typer.type_text("Привет, мир"))
        self.assertEqual(len(procs), 1, "процесс запускается один раз и живёт")
        self.assertTrue(typer.type_text(" и ещё"))
        self.assertEqual(len(procs), 1)
        sent = [json.loads(line) for line in procs[0].stdin.lines]
        self.assertEqual(sent, ["Привет, мир", " и ещё"])
        self.assertTrue(all(line.endswith("\n") for line in procs[0].stdin.lines))

    def test_respawns_once_after_broken_pipe(self):
        procs = [_FakeProc(broken=True), _FakeProc()]
        it = iter(procs)
        typer = voice_type.KeyTyper(spawn=lambda: next(it))
        self.assertTrue(typer.type_text("текст"))
        self.assertEqual(json.loads(procs[1].stdin.lines[0]), "текст")

    def test_reports_failure_when_helper_cannot_start(self):
        def spawn():
            raise OSError("no python")

        self.assertFalse(voice_type.KeyTyper(spawn=spawn).type_text("x"))

    def test_empty_text_is_a_noop(self):
        procs = []
        typer = voice_type.KeyTyper(spawn=lambda: procs.append(_FakeProc()) or procs[-1])
        self.assertTrue(typer.type_text(""))
        self.assertEqual(procs, [])


if __name__ == "__main__":
    unittest.main()
