import unittest

import gestures
from gestures import ARM_TIMER, DISARM_TIMER, FINALIZE, START


class TestPushToTalk(unittest.TestCase):
    def setUp(self):
        self.g = gestures.GestureRecognizer(hold_min=0.35, window=0.5)

    def test_hold_and_release_is_ptt(self):
        self.assertEqual(self.g.on_press(0.0), [START])
        self.assertTrue(self.g.is_recording)
        # держали 1s → нормальный стоп с транскрипцией
        self.assertEqual(self.g.on_release(1.0), [FINALIZE])
        self.assertFalse(self.g.is_recording)
        self.assertEqual(self.g.mode, "idle")

    def test_duplicate_press_while_holding_is_ignored(self):
        self.g.on_press(0.0)
        self.assertEqual(self.g.on_press(0.1), [])  # автоповтор модификатора


class TestShortTapThenTimeout(unittest.TestCase):
    def setUp(self):
        self.g = gestures.GestureRecognizer(hold_min=0.35, window=0.5)

    def test_short_tap_waits_then_finalizes(self):
        self.assertEqual(self.g.on_press(0.0), [START])
        # отпустил через 0.1s (короткий тап) — запись продолжается, ждём
        self.assertEqual(self.g.on_release(0.1), [ARM_TIMER])
        self.assertTrue(self.g.is_recording)
        self.assertEqual(self.g.mode, "pending")
        # второй тап не пришёл → финализируем как короткую диктовку
        self.assertEqual(self.g.on_timeout(0.6), [FINALIZE])
        self.assertFalse(self.g.is_recording)

    def test_timeout_ignored_when_not_pending(self):
        self.assertEqual(self.g.on_timeout(9.0), [])


class TestDoubleTapHandsFree(unittest.TestCase):
    def setUp(self):
        self.g = gestures.GestureRecognizer(hold_min=0.35, window=0.5)

    def test_double_tap_enters_handsfree_without_stopping(self):
        self.assertEqual(self.g.on_press(0.0), [START])
        self.assertEqual(self.g.on_release(0.1), [ARM_TIMER])  # первый тап
        # второй тап в окне → hands-free, запись НЕ прерывалась
        self.assertEqual(self.g.on_press(0.3), [DISARM_TIMER])
        self.assertTrue(self.g.is_recording)
        self.assertTrue(self.g.is_handsfree)

    def test_tap_stops_handsfree(self):
        self.g.on_press(0.0)
        self.g.on_release(0.1)
        self.g.on_press(0.3)  # → handsfree
        # клавишу отпустили — в hands-free это ничего не значит
        self.assertEqual(self.g.on_release(0.35), [])
        self.assertTrue(self.g.is_handsfree)
        # одиночный тап позже → стоп + транскрипция
        self.assertEqual(self.g.on_press(30.0), [FINALIZE])
        self.assertFalse(self.g.is_recording)
        self.assertEqual(self.g.mode, "idle")

    def test_late_second_press_after_timeout_starts_new_recording(self):
        self.g.on_press(0.0)
        self.g.on_release(0.1)
        self.g.on_timeout(0.6)  # окно истекло → finalize, idle
        # нажатие после этого — обычный новый push-to-talk, не hands-free
        self.assertEqual(self.g.on_press(0.7), [START])
        self.assertEqual(self.g.mode, "ptt")


class TestCallToggle(unittest.TestCase):
    def setUp(self):
        self.t = gestures.CallToggle()

    def test_first_press_activates_and_returns_call_start(self):
        self.assertEqual(self.t.on_press(0.0), "call_start")
        self.assertTrue(self.t.active)

    def test_repeat_press_while_held_is_ignored(self):
        self.t.on_press(0.0)
        self.assertIsNone(self.t.on_press(0.05))  # автоповтор ОС, клавиша ещё держится
        self.assertTrue(self.t.active)

    def test_release_then_press_toggles_off(self):
        self.t.on_press(0.0)
        self.t.on_release(0.5)
        self.assertEqual(self.t.on_press(1.0), "call_stop")
        self.assertFalse(self.t.active)

    def test_release_alone_has_no_return_value(self):
        self.assertIsNone(self.t.on_release(0.0))

    def test_second_full_cycle_starts_again(self):
        self.t.on_press(0.0)
        self.t.on_release(0.1)
        self.t.on_press(1.0)   # → call_stop
        self.t.on_release(1.1)
        self.assertEqual(self.t.on_press(2.0), "call_start")
        self.assertTrue(self.t.active)


if __name__ == "__main__":
    unittest.main()
