import unittest

import call_detect as cd
from call_detect import Ask, Stop, Withdraw

ZOOM, CHROME, SIRI = "us.zoom.xos", "com.google.Chrome", "com.apple.siri"
CLAUDE = "com.anthropic.claudefordesktop"  # голосовой ввод, не звонок


class Base(unittest.TestCase):
    def setUp(self):
        self.d = cd.Detector()

    def poll(self, t, on_mic=(), playing=(), recording=False, busy=False, ask=True, auto_stop=True,
             ignore=()):
        return self.d.poll(t, set(on_mic), set(playing), recording=recording, busy=busy,
                           ask=ask, auto_stop=auto_stop, ignore=set(ignore))

    def hold(self, t0, t1, **kw):
        """Опрос каждые POLL_SEC на отрезке [t0, t1]; все события подряд."""
        out, t = [], t0
        while t <= t1:
            out += self.poll(t, **kw)
            t += cd.POLL_SEC
        return out


class TestOffer(Base):
    def test_offer_after_eight_seconds_once(self):
        self.assertEqual(self.hold(0, 6, on_mic=[ZOOM]), [])
        self.assertEqual(self.poll(8, on_mic=[ZOOM]), [Ask(ZOOM)])
        self.assertEqual(self.hold(10, 60, on_mic=[ZOOM]), [])

    def test_short_siri_gets_no_offer(self):
        self.assertEqual(self.hold(0, 4, on_mic=[SIRI]) + self.poll(6), [])

    def test_offer_is_withdrawn_and_comes_back_next_session(self):
        self.hold(0, 8, on_mic=[ZOOM])
        self.assertEqual(self.poll(10), [Withdraw(ZOOM)])
        self.assertEqual(self.hold(12, 18, on_mic=[ZOOM]), [])
        self.assertEqual(self.poll(20, on_mic=[ZOOM]), [Ask(ZOOM)])

    def test_no_offer_while_recording(self):
        self.assertEqual(self.hold(0, 20, on_mic=[ZOOM], recording=True), [])

    def test_no_offer_while_busy(self):
        self.assertEqual(self.hold(0, 20, on_mic=[ZOOM], busy=True), [])

    def test_no_offer_when_off(self):
        self.assertEqual(self.hold(0, 20, on_mic=[ZOOM], ask=False), [])

    def test_offer_after_busy_ends(self):
        self.hold(0, 10, on_mic=[ZOOM], busy=True)
        self.assertEqual(self.poll(12, on_mic=[ZOOM]), [Ask(ZOOM)])

    def test_two_apps_are_offered_separately(self):
        self.hold(0, 6, on_mic=[ZOOM, CHROME])
        self.assertEqual(self.poll(8, on_mic=[ZOOM, CHROME]), [Ask(CHROME), Ask(ZOOM)])


class TestAutoStop(Base):
    def test_manual_start_links_the_app_on_the_mic(self):
        self.poll(0, on_mic=[ZOOM])
        self.poll(2, on_mic=[ZOOM], recording=True)
        self.assertEqual(self.d.linked, {ZOOM})

    def test_stop_twenty_seconds_after_the_app_leaves(self):
        self.hold(0, 30, on_mic=[ZOOM], playing=[ZOOM], recording=True)
        self.assertEqual(self.hold(32, 50, recording=True), [])
        self.assertEqual(self.poll(52, recording=True), [Stop(ZOOM, 20.0)])
        self.assertEqual(self.hold(54, 70, recording=True), [])

    def test_muted_listener_keeps_recording(self):
        self.hold(0, 30, on_mic=[ZOOM], playing=[ZOOM], recording=True)
        self.assertEqual(self.hold(32, 300, playing=[ZOOM], recording=True), [])

    def test_in_person_meeting_never_stops(self):
        self.assertEqual(self.hold(0, 600, recording=True), [])

    def test_short_siri_during_in_person_meeting_is_not_linked(self):
        self.hold(0, 8, recording=True)
        self.hold(10, 14, on_mic=[SIRI], recording=True)
        self.assertEqual(self.d.linked, set())
        self.assertEqual(self.hold(16, 120, recording=True), [])

    def test_late_call_app_gets_linked(self):
        self.hold(0, 8, recording=True)
        self.hold(10, 20, on_mic=[ZOOM], recording=True)
        self.assertEqual(self.d.linked, {ZOOM})

    def test_two_linked_apps_one_leaves(self):
        self.hold(0, 10, on_mic=[ZOOM, CHROME], recording=True)
        self.assertEqual(self.hold(12, 120, on_mic=[CHROME], recording=True), [])

    def test_auto_stop_off(self):
        self.hold(0, 10, on_mic=[ZOOM], recording=True)
        self.assertEqual(self.hold(12, 120, recording=True, auto_stop=False), [])

    def test_returning_app_resets_the_quiet_clock(self):
        self.hold(0, 30, on_mic=[ZOOM], recording=True)
        self.hold(32, 40, recording=True)
        self.poll(42, playing=[ZOOM], recording=True)
        self.assertEqual(self.hold(44, 62, recording=True), [])
        self.assertEqual(self.poll(64, recording=True), [Stop(ZOOM, 20.0)])

    def test_manual_stop_resets_links_and_keeps_the_offer_memory(self):
        self.hold(0, 8, on_mic=[ZOOM])
        self.hold(10, 20, on_mic=[ZOOM], recording=True)
        self.assertEqual(self.hold(22, 60, on_mic=[ZOOM]), [])
        self.assertEqual(self.d.linked, set())


class TestIgnore(Base):
    """Программы из списка исключений для детектора как будто не существуют."""

    def test_ignored_app_gets_no_offer(self):
        self.assertEqual(self.hold(0, 60, on_mic=[CLAUDE], ignore=[CLAUDE]), [])

    def test_other_apps_are_still_offered(self):
        self.hold(0, 6, on_mic=[CLAUDE, ZOOM], ignore=[CLAUDE])
        self.assertEqual(self.poll(8, on_mic=[CLAUDE, ZOOM], ignore=[CLAUDE]), [Ask(ZOOM)])

    def test_ignoring_withdraws_the_shown_offer(self):
        self.hold(0, 8, on_mic=[CLAUDE])
        self.assertEqual(self.poll(10, on_mic=[CLAUDE], ignore=[CLAUDE]), [Withdraw(CLAUDE)])
        self.assertEqual(self.hold(12, 60, on_mic=[CLAUDE], ignore=[CLAUDE]), [])

    def test_offered_again_once_removed_from_the_list(self):
        self.hold(0, 20, on_mic=[CLAUDE], ignore=[CLAUDE])
        self.hold(22, 28, on_mic=[CLAUDE])
        self.assertEqual(self.poll(30, on_mic=[CLAUDE]), [Ask(CLAUDE)])

    def test_dictation_during_in_person_meeting_does_not_stop_it(self):
        self.hold(0, 8, recording=True, ignore=[CLAUDE])
        self.hold(10, 40, on_mic=[CLAUDE], recording=True, ignore=[CLAUDE])
        self.assertEqual(self.d.linked, set())
        self.assertEqual(self.hold(42, 200, recording=True, ignore=[CLAUDE]), [])

    def test_ignored_app_on_the_mic_at_start_is_not_linked(self):
        self.hold(0, 10, on_mic=[CLAUDE, ZOOM], recording=True, ignore=[CLAUDE])
        self.assertEqual(self.d.linked, {ZOOM})

    def test_app_ignored_mid_recording_is_unlinked(self):
        self.hold(0, 10, on_mic=[CLAUDE, ZOOM], recording=True)
        self.hold(12, 30, on_mic=[CLAUDE, ZOOM], recording=True, ignore=[CLAUDE])
        self.hold(32, 50, on_mic=[CLAUDE], recording=True, ignore=[CLAUDE])
        self.assertEqual(self.poll(52, on_mic=[CLAUDE], recording=True, ignore=[CLAUDE]),
                         [Stop(ZOOM, 20.0)])


class TestIgnorable(unittest.TestCase):
    def test_bundle_keys_can_be_ignored(self):
        self.assertTrue(cd.ignorable(CLAUDE))

    def test_pid_keys_and_blanks_cannot(self):
        # pid меняется при каждом запуске — в списке он бесполезен
        self.assertFalse(cd.ignorable("pid:4242"))
        self.assertFalse(cd.ignorable(""))


if __name__ == "__main__":
    unittest.main()
