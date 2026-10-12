import unittest

from addictune_cli.src.tui.services.clock import PlaybackClock


class _FakeTime:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class PlaybackClockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.time = _FakeTime()
        self.clock = PlaybackClock(now=self.time)

    def test_a_stopped_clock_does_not_advance(self) -> None:
        self.clock.adopt_track(180, running=False)
        self.time.advance(30)

        self.assertEqual(self.clock.elapsed, 0)
        self.assertFalse(self.clock.running)

    def test_a_running_clock_advances_from_its_base(self) -> None:
        self.clock.adopt_schedule(600, 3600, running=True)
        self.time.advance(45)

        self.assertEqual(self.clock.elapsed, 645)
        self.assertEqual(self.clock.duration, 3600)

    def test_setting_a_duration_leaves_the_counter_alone(self) -> None:
        self.clock.adopt_schedule(600, 3600, running=True)
        self.time.advance(45)

        self.clock.set_duration(None)

        self.assertEqual(self.clock.elapsed, 645)
        self.assertIsNone(self.clock.duration)

    def test_pause_freezes_then_resume_continues_from_there(self) -> None:
        self.clock.adopt_track(300, running=True)
        self.time.advance(20)

        self.clock.pause()
        self.time.advance(120)  # paused: this must not count
        self.assertEqual(self.clock.elapsed, 20)

        self.clock.resume()
        self.time.advance(5)
        self.assertEqual(self.clock.elapsed, 25)

    def test_resume_is_idempotent(self) -> None:
        self.clock.adopt_track(300, running=True)
        self.time.advance(10)

        self.clock.resume()
        self.time.advance(10)

        self.assertEqual(self.clock.elapsed, 20)

    def test_reset_can_keep_a_known_duration(self) -> None:
        self.clock.adopt_track(300, running=True)
        self.time.advance(30)

        self.clock.reset(clear_duration=False)

        self.assertEqual(self.clock.elapsed, 0)
        self.assertEqual(self.clock.duration, 300)
        self.assertFalse(self.clock.running)

        self.clock.reset(clear_duration=True)
        self.assertIsNone(self.clock.duration)

    def test_seek_target_is_clamped_inside_the_duration(self) -> None:
        self.clock.adopt_track(300, running=False)

        self.assertEqual(self.clock.clamp_seek_target(-10), 0)
        self.assertEqual(self.clock.clamp_seek_target(10), 10)
        self.assertEqual(self.clock.clamp_seek_target(9999), 299)

    def test_seek_target_is_unbounded_without_a_duration(self) -> None:
        self.clock.adopt_track(None, running=False)

        self.assertEqual(self.clock.clamp_seek_target(9999), 9999)

    def test_seeking_while_running_keeps_counting_from_the_target(self) -> None:
        self.clock.adopt_track(300, running=True)
        self.time.advance(30)

        self.clock.seek_to(self.clock.clamp_seek_target(10), running=True)
        self.assertEqual(self.clock.elapsed, 40)
        self.time.advance(5)
        self.assertEqual(self.clock.elapsed, 45)

    def test_a_schedule_overrides_a_track_that_was_counting(self) -> None:
        # The live-show regression: an ICY track had seeded the clock, then the
        # scheduled show reclaims it. Position and total both come from the show.
        self.clock.adopt_track(180, running=True)
        self.time.advance(60)

        self.clock.adopt_schedule(600, 3600, running=True)

        self.assertEqual(self.clock.elapsed, 600)
        self.assertEqual(self.clock.duration, 3600)


if __name__ == "__main__":
    unittest.main()
