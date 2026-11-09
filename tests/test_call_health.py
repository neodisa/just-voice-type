import unittest

import call_health


class TestRecoveryPolicy(unittest.TestCase):
    def test_first_failure_recovers(self):
        p = call_health.RecoveryPolicy(max_attempts=5, window_sec=60.0, backoff_sec=1.0)
        self.assertEqual(p.record_failure(now=0.0), call_health.RECOVER)

    def test_failure_within_backoff_waits(self):
        p = call_health.RecoveryPolicy(backoff_sec=1.0)
        self.assertEqual(p.record_failure(now=0.0), call_health.RECOVER)
        # ещё не прошёл backoff — не долбим устройство
        self.assertEqual(p.record_failure(now=0.5), call_health.WAIT)

    def test_recovers_again_after_backoff(self):
        p = call_health.RecoveryPolicy(backoff_sec=1.0)
        self.assertEqual(p.record_failure(now=0.0), call_health.RECOVER)
        self.assertEqual(p.record_failure(now=1.01), call_health.RECOVER)

    def test_gives_up_after_max_attempts(self):
        p = call_health.RecoveryPolicy(max_attempts=3, window_sec=60.0, backoff_sec=1.0)
        self.assertEqual(p.record_failure(now=0.0), call_health.RECOVER)
        self.assertEqual(p.record_failure(now=1.1), call_health.RECOVER)
        self.assertEqual(p.record_failure(now=2.2), call_health.RECOVER)
        # исчерпали бюджет попыток в окне
        self.assertEqual(p.record_failure(now=3.3), call_health.GIVE_UP)

    def test_give_up_ignores_backoff(self):
        # даже если backoff ещё активен, при исчерпанном бюджете — сдаёмся
        p = call_health.RecoveryPolicy(max_attempts=2, window_sec=60.0, backoff_sec=5.0)
        self.assertEqual(p.record_failure(now=0.0), call_health.RECOVER)
        self.assertEqual(p.record_failure(now=5.1), call_health.RECOVER)
        self.assertEqual(p.record_failure(now=5.2), call_health.GIVE_UP)

    def test_old_attempts_pruned_from_window(self):
        p = call_health.RecoveryPolicy(max_attempts=2, window_sec=10.0, backoff_sec=1.0)
        self.assertEqual(p.record_failure(now=0.0), call_health.RECOVER)
        self.assertEqual(p.record_failure(now=1.1), call_health.RECOVER)
        # третья попытка спустя > window от первой: старые выпали из окна
        self.assertEqual(p.record_failure(now=12.0), call_health.RECOVER)

    def test_reset_clears_state(self):
        p = call_health.RecoveryPolicy(max_attempts=2, window_sec=60.0, backoff_sec=1.0)
        self.assertEqual(p.record_failure(now=0.0), call_health.RECOVER)
        self.assertEqual(p.record_failure(now=1.1), call_health.RECOVER)
        self.assertEqual(p.record_failure(now=2.2), call_health.GIVE_UP)
        p.reset()
        # после успешного возобновления кадров бюджет снова полон
        self.assertEqual(p.record_failure(now=2.3), call_health.RECOVER)


class TestChannelHealthMonitor(unittest.TestCase):
    def _mon(self, **kw):
        kw.setdefault("active_thresh", 0.02)
        kw.setdefault("silence_sec", 8.0)
        return call_health.ChannelHealthMonitor(**kw)

    def test_never_active_channel_is_never_flagged(self):
        m = self._mon()
        # ch0 всегда громкий, ch1 всегда тихий (никогда не был источником)
        for t in range(0, 20):
            dead = m.update([0.3, 0.0], now=float(t))
            self.assertEqual(dead, [])

    def test_short_silence_not_flagged(self):
        m = self._mon(silence_sec=8.0)
        self.assertEqual(m.update([0.3, 0.3], now=0.0), [])
        # ch1 замолчал, но прошло всего 3с < 8с
        self.assertEqual(m.update([0.3, 0.0], now=3.0), [])

    def test_dead_channel_flagged_once(self):
        m = self._mon(silence_sec=8.0)
        # оба канала активны — оба «были живы»
        m.update([0.3, 0.3], now=0.0)
        # ch1 умолк, ch0 жив; спустя 9с > 8с → флаг на ch1
        self.assertEqual(m.update([0.3, 0.0], now=9.0), [1])
        # повторно не сигналим (warn-once)
        self.assertEqual(m.update([0.3, 0.0], now=12.0), [])

    def test_all_silent_not_flagged(self):
        m = self._mon(silence_sec=8.0)
        m.update([0.3, 0.3], now=0.0)
        # оба замолчали — это просто пауза в разговоре, не отвал источника
        self.assertEqual(m.update([0.0, 0.0], now=10.0), [])

    def test_both_active_flags_nothing(self):
        m = self._mon(silence_sec=8.0)
        m.update([0.3, 0.3], now=0.0)
        self.assertEqual(m.update([0.3, 0.3], now=10.0), [])

    def test_single_channel_never_flagged(self):
        # один канал: мёртвый источник неотличим от паузы → не сигналим
        m = self._mon(silence_sec=8.0)
        m.update([0.3], now=0.0)
        self.assertEqual(m.update([0.0], now=10.0), [])


if __name__ == "__main__":
    unittest.main()
