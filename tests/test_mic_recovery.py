"""Самовосстановление после зависшего CoreAudio.

Сценарий из логов: после диктовки stream.abort() навсегда встаёт в
CoreAudio (фоновый поток), а следующий recorder.start() в control_loop
блокируется на открытии микрофона — приложение больше не пишет до ручного
перезапуска. Здесь проверяется логика, которая замечает это и
перезапускает процесс сама.
"""
import os
import sys
import tempfile
import time
import unittest

import mic_recovery
import system_audio
import voice_type


class TestRelaunchReason(unittest.TestCase):
    NOW = 1000.0

    def test_nothing_wrong_means_no_relaunch(self):
        self.assertIsNone(
            mic_recovery.relaunch_reason(
                self.NOW, start_since=None, teardown_age=None, idle=True
            )
        )

    def test_start_hung_past_threshold_triggers_relaunch(self):
        since = self.NOW - mic_recovery.START_HANG_SEC - 0.1
        self.assertEqual(
            mic_recovery.relaunch_reason(
                self.NOW, start_since=since, teardown_age=None, idle=False
            ),
            "start_hung",
        )

    def test_slow_but_normal_start_is_tolerated(self):
        since = self.NOW - 1.0
        self.assertIsNone(
            mic_recovery.relaunch_reason(
                self.NOW, start_since=since, teardown_age=None, idle=False
            )
        )

    def test_long_stuck_teardown_while_idle_triggers_relaunch(self):
        self.assertEqual(
            mic_recovery.relaunch_reason(
                self.NOW,
                start_since=None,
                teardown_age=mic_recovery.TEARDOWN_HANG_SEC + 0.1,
                idle=True,
            ),
            "teardown_hung",
        )

    def test_stuck_teardown_never_interrupts_active_work(self):
        # диктовка/звонок/доставка текста идут — не рвём их перезапуском
        self.assertIsNone(
            mic_recovery.relaunch_reason(
                self.NOW,
                start_since=None,
                teardown_age=mic_recovery.TEARDOWN_HANG_SEC + 60,
                idle=False,
            )
        )

    def test_short_teardown_is_tolerated(self):
        self.assertIsNone(
            mic_recovery.relaunch_reason(
                self.NOW, start_since=None, teardown_age=2.0, idle=True
            )
        )


class TestRelaunchBudget(unittest.TestCase):
    def test_first_relaunch_is_allowed_and_recorded(self):
        ok, value = mic_recovery.budget_allows("", now=500.0)
        self.assertTrue(ok)
        self.assertEqual(value, "500.0")

    def test_budget_exhausted_within_window(self):
        prev = ",".join(str(100.0 + i) for i in range(mic_recovery.BUDGET_MAX))
        ok, _ = mic_recovery.budget_allows(prev, now=200.0)
        self.assertFalse(ok, "CoreAudio висит системно — не надо крутить перезапуски")

    def test_old_relaunches_fall_out_of_window(self):
        old = 100.0
        prev = ",".join(str(old) for _ in range(mic_recovery.BUDGET_MAX))
        now = old + mic_recovery.BUDGET_WINDOW_SEC + 1
        ok, value = mic_recovery.budget_allows(prev, now=now)
        self.assertTrue(ok)
        self.assertEqual(value, str(now))

    def test_garbage_in_env_is_ignored(self):
        ok, value = mic_recovery.budget_allows("abc,,12x", now=10.0)
        self.assertTrue(ok)
        self.assertEqual(value, "10.0")


class TestRelaunch(unittest.TestCase):
    def test_execs_same_interpreter_with_original_argv_and_budget_in_env(self):
        calls = []
        env = {"PATH": "/usr/bin", mic_recovery.ENV_KEY: ""}
        done = mic_recovery.relaunch(
            "start_hung",
            env=env,
            now=777.0,
            execv=lambda exe, argv, e: calls.append((exe, argv, e)),
            diagnose=lambda reason: None,
        )
        self.assertTrue(done)
        exe, argv, new_env = calls[0]
        self.assertEqual(exe, sys.executable)
        self.assertEqual(list(argv), list(sys.orig_argv))
        self.assertEqual(new_env[mic_recovery.ENV_KEY], "777.0")
        self.assertEqual(new_env["PATH"], "/usr/bin")

    def test_no_exec_when_budget_exhausted(self):
        calls = []
        prev = ",".join(["700.0"] * mic_recovery.BUDGET_MAX)
        done = mic_recovery.relaunch(
            "start_hung",
            env={mic_recovery.ENV_KEY: prev},
            now=777.0,
            execv=lambda *a: calls.append(a),
            diagnose=lambda reason: None,
        )
        self.assertFalse(done)
        self.assertEqual(calls, [])

    def test_diagnostics_run_before_exec(self):
        order = []
        mic_recovery.relaunch(
            "teardown_hung",
            env={},
            now=1.0,
            execv=lambda *a: order.append("exec"),
            diagnose=lambda reason: order.append(("diag", reason)),
        )
        self.assertEqual(order, [("diag", "teardown_hung"), "exec"])

    def test_failing_diagnostics_do_not_block_relaunch(self):
        calls = []

        def boom(reason):
            raise RuntimeError("sample not available")

        done = mic_recovery.relaunch(
            "start_hung",
            env={},
            now=1.0,
            execv=lambda *a: calls.append(a),
            diagnose=boom,
        )
        self.assertTrue(done)
        self.assertEqual(len(calls), 1)


class TestDumpThreads(unittest.TestCase):
    def test_writes_python_stacks_of_all_threads(self):
        with tempfile.TemporaryFile("w+") as f:
            mic_recovery.dump_threads(f)
            f.seek(0)
            text = f.read()
        self.assertIn("test_writes_python_stacks_of_all_threads", text)


class TestTrimLog(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(os.unlink, self.path)

    def test_huge_log_is_cut_down_to_its_tail(self):
        with open(self.path, "wb") as f:
            f.write(b"a" * 900 + b"TAIL-END")
        trimmed = mic_recovery.trim_log(self.path, max_bytes=500, keep_bytes=100)
        self.assertTrue(trimmed)
        with open(self.path, "rb") as f:
            data = f.read()
        self.assertEqual(len(data), 100)
        self.assertTrue(data.endswith(b"TAIL-END"))

    def test_small_log_is_left_alone(self):
        with open(self.path, "wb") as f:
            f.write(b"hello")
        self.assertFalse(mic_recovery.trim_log(self.path, max_bytes=500, keep_bytes=100))
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), b"hello")

    def test_missing_file_is_not_an_error(self):
        self.assertFalse(mic_recovery.trim_log(self.path + ".nope", 10, 5))

    def test_append_handle_keeps_writing_after_trim(self):
        # лаунчер открывает лог как `2>>file` (O_APPEND) — после обрезки
        # новые строки должны дописываться в конец, а не в старое смещение
        with open(self.path, "wb") as f:
            f.write(b"x" * 1000)
        appender = open(self.path, "ab")
        self.addCleanup(appender.close)
        mic_recovery.trim_log(self.path, max_bytes=500, keep_bytes=10)
        appender.write(b"NEW")
        appender.flush()
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), b"x" * 10 + b"NEW")


class TestRecorderOldestTeardownAge(unittest.TestCase):
    def setUp(self):
        self.rec = voice_type.Recorder()

    def test_none_when_nothing_in_flight(self):
        self.assertIsNone(self.rec.oldest_teardown_age())

    def test_age_of_oldest_in_flight_teardown(self):
        now = time.time()
        self.rec._teardowns = {
            1: {"phase": "abort", "t0": now - 12.0, "reported": True},
            2: {"phase": "close", "t0": now - 3.0, "reported": False},
        }
        age = self.rec.oldest_teardown_age(now=now)
        self.assertAlmostEqual(age, 12.0, places=3)

    def test_does_not_consume_the_once_only_report(self):
        now = time.time()
        self.rec._teardowns = {1: {"phase": "abort", "t0": now - 9.0, "reported": False}}
        self.rec.oldest_teardown_age(now=now)
        self.assertIsNotNone(self.rec.stuck_teardown(5.0))


class _FakeSide:
    def __init__(self, stuck=None, age=None):
        self._stuck = stuck
        self._age = age

    def stuck_teardown(self, older_than=5.0):
        return self._stuck

    def oldest_teardown_age(self, now=None):
        return self._age


class TestCombinedCallCaptureWatchdogInterface(unittest.TestCase):
    """watchdog зовёт stuck_teardown у любого рекордера звонка. У
    CombinedCallCapture этого метода не было — AttributeError ~3 раза в
    секунду всё время звонка (145 МБ err.log) и обрыв обновления иконки."""

    def test_stuck_teardown_delegates_to_mic(self):
        cap = system_audio.CombinedCallCapture(
            system=object(), mic=_FakeSide(stuck=("abort", 6.0))
        )
        self.assertEqual(cap.stuck_teardown(5.0), ("abort", 6.0))

    def test_stuck_teardown_without_mic_is_none(self):
        cap = system_audio.CombinedCallCapture(system=object(), mic=None)
        self.assertIsNone(cap.stuck_teardown(5.0))

    def test_oldest_teardown_age_delegates_to_mic(self):
        cap = system_audio.CombinedCallCapture(system=object(), mic=_FakeSide(age=7.5))
        self.assertEqual(cap.oldest_teardown_age(), 7.5)

    def test_oldest_teardown_age_without_mic_is_none(self):
        cap = system_audio.CombinedCallCapture(system=object(), mic=None)
        self.assertIsNone(cap.oldest_teardown_age())


if __name__ == "__main__":
    unittest.main()
