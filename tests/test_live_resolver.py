"""`LiveResolver.resolve(icy_title)` turns the live ICY title into one value.

Pure tests: the routine and the schedule are given, no I/O. Precedence under
test: a scheduled live show wins unless the ICY title proves it wrong
(matches nothing in the show's tracklist but something in the routine); then
the routine track; then the title alone.
"""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from addictune_sdk.models import ImageSet

from addictune_cli.src.tui.services.live_resolver import LiveInfo, LiveResolver


def _track(
    id_: int, artist: str, title: str, *, length: int = 300, offset=None, image=None
):
    return SimpleNamespace(
        id=id_,
        display_artist=artist,
        display_title=title,
        title=title,
        length=length,
        content_length=None,
        offset=offset,
        images=ImageSet(default=image) if image else None,
    )


def _routine(*tracks):
    return SimpleNamespace(routine_id=1, channel_id=7, tracks=list(tracks))


def _episode(
    show_id: int,
    name: str,
    *,
    minutes_ago: int,
    length: int = 60,
    tracks=(),
    next_name=None,
):
    start = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    end = start + timedelta(minutes=length)
    return SimpleNamespace(
        id=show_id * 10,
        show=SimpleNamespace(id=show_id, name=name, images=None),
        start_at=start.isoformat(),
        end_at=end.isoformat(),
        tracks=list(tracks),
    )


class RoutineOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.routine = _routine(
            _track(1, "Artist A", "Song A", offset=42, image="https://img/a.png"),
            _track(2, "Artist B", "Song B"),
        )
        self.resolver = LiveResolver(
            routine=self.routine, live_episode=None, next_episode=None
        )

    def test_matching_title_carries_id_length_offset_and_art(self) -> None:
        info = self.resolver.resolve("Artist A - Song A")
        self.assertEqual(info.track_id, 1)
        self.assertEqual(info.length, 300)
        self.assertEqual(info.offset, 42)
        self.assertIn("a.png", info.image_url)

    def test_match_ignores_punctuation_and_case(self) -> None:
        self.assertEqual(self.resolver.resolve("artist b — song b").track_id, 2)

    def test_offset_only_for_the_routine_current_track(self) -> None:
        self.assertIsNone(self.resolver.resolve("Artist B - Song B").offset)

    def test_miss_keeps_title_and_nothing_else(self) -> None:
        info = self.resolver.resolve("Unknown - Track")
        self.assertEqual(info, LiveInfo())

    def test_no_title_yet(self) -> None:
        self.assertEqual(self.resolver.resolve(None), LiveInfo())

    def test_no_routine_yet(self) -> None:
        resolver = LiveResolver(routine=None, live_episode=None, next_episode=None)
        self.assertEqual(resolver.resolve("X - Y"), LiveInfo())


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.routine = _routine(_track(1, "Artist A", "Song A"))
        self.show = _episode(
            5,
            "Group Therapy",
            minutes_ago=10,
            tracks=[
                _track(
                    99,
                    "Above & Beyond",
                    "Group Therapy 600",
                    image="https://img/show.png",
                )
            ],
        )

    def test_live_show_supplies_show_fields_track_and_position(self) -> None:
        resolver = LiveResolver(
            routine=self.routine, live_episode=self.show, next_episode=None
        )
        info = resolver.resolve("Above & Beyond - Group Therapy 600")
        self.assertEqual((info.show_id, info.show_name), (5, "Group Therapy"))
        self.assertEqual(info.track_id, 99)
        self.assertEqual(info.length, 3600)
        self.assertAlmostEqual(info.offset, 600, delta=5)
        self.assertIn("show.png", info.image_url)

    def test_live_show_stays_when_title_matches_nothing(self) -> None:
        # A show's ICY titles are usually not in the routine; the schedule wins.
        resolver = LiveResolver(
            routine=self.routine, live_episode=self.show, next_episode=None
        )
        info = resolver.resolve("Some Guest - Live Set")
        self.assertEqual(info.show_id, 5)
        self.assertEqual(info.track_id, 99)

    def test_routine_track_overrides_a_stale_live_show(self) -> None:
        # The ICY title is a plain routine track: the show is not actually on air.
        resolver = LiveResolver(
            routine=self.routine, live_episode=self.show, next_episode=None
        )
        info = resolver.resolve("Artist A - Song A")
        self.assertIsNone(info.show_id)
        self.assertEqual(info.track_id, 1)

    def test_next_show_is_shown_when_it_starts_within_the_upcoming_window(self) -> None:
        soon = _episode(6, "Next Show", minutes_ago=-20)
        later = _episode(7, "Later Show", minutes_ago=-120)
        # During a live show.
        self.assertEqual(
            LiveResolver(routine=None, live_episode=self.show, next_episode=soon)
            .resolve("x")
            .next_show,
            "Next: Next Show",
        )
        self.assertEqual(
            LiveResolver(routine=None, live_episode=self.show, next_episode=later)
            .resolve("x")
            .next_show,
            "",
        )
        # During regular tracks (the list shows the UPCOMING badge): same rule.
        self.assertEqual(
            LiveResolver(routine=self.routine, live_episode=None, next_episode=soon)
            .resolve("Artist A - Song A")
            .next_show,
            "Next: Next Show",
        )
        self.assertEqual(
            LiveResolver(routine=self.routine, live_episode=None, next_episode=later)
            .resolve("Artist A - Song A")
            .next_show,
            "",
        )
        self.assertEqual(
            LiveResolver(routine=None, live_episode=None, next_episode=soon)
            .resolve("Unknown - Track")
            .next_show,
            "Next: Next Show",
        )

    def test_long_live_show_keeps_a_back_to_back_next_beyond_the_window(self) -> None:
        long_show = _episode(5, "Long", minutes_ago=10, length=240)  # ends in 230 min
        back_to_back = _episode(6, "After", minutes_ago=-229)
        info = LiveResolver(
            routine=None, live_episode=long_show, next_episode=back_to_back
        ).resolve("x")
        self.assertEqual(info.next_show, "Next: After")

    def test_next_show_already_started_is_promoted(self) -> None:
        started = _episode(6, "Started Show", minutes_ago=1)
        resolver = LiveResolver(routine=None, live_episode=None, next_episode=started)
        info = resolver.resolve("Whatever - Title")
        self.assertEqual((info.show_id, info.show_name), (6, "Started Show"))

    def test_show_artwork_falls_back_track_then_show_then_channel(self) -> None:
        bare = _episode(5, "Show", minutes_ago=5, tracks=[_track(1, "A", "B")])
        bare.show.images = ImageSet(default="https://img/show.png")
        channel = ImageSet(default="https://img/channel.png")
        self.assertIn(
            "show.png",
            LiveResolver(
                routine=None,
                live_episode=bare,
                next_episode=None,
                channel_images=channel,
            )
            .resolve("x")
            .image_url,
        )
        bare.show.images = None
        self.assertIn(
            "channel.png",
            LiveResolver(
                routine=None,
                live_episode=bare,
                next_episode=None,
                channel_images=channel,
            )
            .resolve("x")
            .image_url,
        )

    def test_ended_live_show_is_ignored(self) -> None:
        ended = _episode(5, "Over", minutes_ago=90, length=60)
        resolver = LiveResolver(
            routine=self.routine, live_episode=ended, next_episode=None
        )
        self.assertIsNone(resolver.resolve("Artist A - Song A").show_id)


if __name__ == "__main__":
    unittest.main()
