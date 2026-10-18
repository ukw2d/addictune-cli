"""Whoever is airing must be a single, unambiguous field pair -- add-d6m.1.

PlaybackBar.apply_live_show() is the one place that may set
(live_show_id, live_show_name). This covers that it sets both together, and
the clearing paths that live on PlaybackBar itself: a stop on a live channel,
and starting any play (live or not) discarding the previous show until
ChannelsService resolves the new one. The "no effective episode" clearing
path lives in ChannelsService and is covered in test_channels_service.py.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from textual.app import App, ComposeResult

from addictune_cli.src.media.session import NullSession
from addictune_cli.src.audio.state import State
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar


from support import temp_settings


class _App(App):
    CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"
    client = SimpleNamespace(premium=None)

    def compose(self) -> ComposeResult:
        yield PlaybackBar(temp_settings(), media_session=NullSession())


class PlaybackBarLiveShowTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_live_show_sets_both_fields_together(self) -> None:
        app = _App()
        async with app.run_test():
            bar = app.query_one(PlaybackBar)

            bar.apply_live_show(show_id=42, name="Group Therapy")

            self.assertEqual(bar.live_show_id, 42)
            self.assertEqual(bar.live_show_name, "Group Therapy")

    async def test_a_new_show_id_invalidates_the_old_follow_state(self) -> None:
        # Follow state is fetched separately (add-d6m.2) and needs a round
        # trip, unlike id/name -- so it must not keep showing the previous
        # show's answer while the new one is still in flight.
        app = _App()
        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            bar.apply_live_show(show_id=42, name="Group Therapy")
            bar.live_show_followed = True

            bar.apply_live_show(show_id=99, name="A State of Trance")

            self.assertIsNone(bar.live_show_followed)

    async def test_reapplying_the_same_show_id_keeps_the_follow_state(self) -> None:
        # A periodic resync for a show that is still airing must not discard
        # an already-fetched answer and force a redundant refetch.
        app = _App()
        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            bar.apply_live_show(show_id=42, name="Group Therapy")
            bar.live_show_followed = True

            bar.apply_live_show(show_id=42, name="Group Therapy")

            self.assertTrue(bar.live_show_followed)

    async def test_stop_on_a_live_channel_clears_the_airing_show(self) -> None:
        app = _App()
        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            bar.content_type = ContentType.LIVE
            bar.apply_live_show(show_id=42, name="Group Therapy")

            bar.stop()

            self.assertIsNone(bar.live_show_id)
            self.assertEqual(bar.live_show_name, "")

    async def test_live_progress_remains_read_only(self) -> None:
        app = _App()
        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            bar.content_type = ContentType.LIVE
            bar.state = State.PLAYING
            bar._player.seek = Mock()

            bar.seek(10)

            bar._player.seek.assert_not_called()

    async def test_pause_does_not_clear_the_airing_show(self) -> None:
        # Pause never reaches State.STOPPED, so it must not be swept up by
        # the same clearing branch as an actual stop.
        app = _App()
        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            bar.content_type = ContentType.LIVE
            bar.apply_live_show(show_id=42, name="Group Therapy")

            bar.pause()

            self.assertEqual(bar.live_show_id, 42)
            self.assertEqual(bar.live_show_name, "Group Therapy")

    async def test_stop_on_non_live_content_does_not_touch_the_field(self) -> None:
        # On-demand playback never carries a live show, so a stop there has
        # nothing of this kind to clear -- confirms the clear is LIVE-scoped.
        app = _App()
        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            bar.content_type = ContentType.TRACK

            bar.stop()

            self.assertIsNone(bar.live_show_id)
            self.assertEqual(bar.live_show_name, "")

    async def test_starting_non_live_playback_clears_the_airing_show(self) -> None:
        app = _App()
        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            bar.content_type = ContentType.LIVE
            bar.apply_live_show(show_id=42, name="Group Therapy")

            bar.content_type = ContentType.TRACK
            bar.play("http://example.test/track.mp3", title="Some Track")

            self.assertIsNone(bar.live_show_id)
            self.assertEqual(bar.live_show_name, "")
            await pilot.pause()

    async def test_starting_a_fresh_live_play_clears_the_previous_show(self) -> None:
        # A channel switch must not keep showing the old channel's airing
        # show until ChannelsService resolves the new one.
        app = _App()
        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            bar.content_type = ContentType.LIVE
            bar.apply_live_show(show_id=42, name="Group Therapy")

            bar.play("http://example.test/stream", title="Trance")

            self.assertIsNone(bar.live_show_id)
            self.assertEqual(bar.live_show_name, "")
            await pilot.pause()


class PlaybackBarLiveShowMarkerTests(unittest.IsolatedAsyncioTestCase):
    """The #live-show-follow label reacts to live_show_id/_followed/content_type
    together (add-d6m.3); apply_live_show_follow_marker's own render logic is
    covered directly in test_live_show_follow_marker.py.
    """

    async def test_marker_appears_once_follow_state_resolves(self) -> None:
        # Emptiness (not .display, which only tracks -active/STOPPED here --
        # see test_marker_hides_on_stop) is how the finer-grained cases hide.
        app = _App()
        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            bar.state = State.PLAYING
            bar.content_type = ContentType.LIVE
            marker = bar.query_one("#live-show-follow")

            self.assertEqual(str(marker.render()), "")

            bar.apply_live_show(show_id=42, name="Group Therapy")
            await pilot.pause()
            self.assertEqual(str(marker.render()), "")  # follow state unresolved

            bar.live_show_followed = False
            await pilot.pause()
            self.assertNotEqual(str(marker.render()), "")

    async def test_marker_hides_when_switching_to_on_demand_playback(self) -> None:
        app = _App()
        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            bar.state = State.PLAYING
            bar.content_type = ContentType.LIVE
            bar.apply_live_show(show_id=42, name="Group Therapy")
            bar.live_show_followed = True
            await pilot.pause()
            marker = bar.query_one("#live-show-follow")
            self.assertNotEqual(str(marker.render()), "")

            bar.content_type = ContentType.TRACK
            await pilot.pause()

            self.assertEqual(str(marker.render()), "")

    async def test_marker_hides_on_stop(self) -> None:
        app = _App()
        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            bar.content_type = ContentType.LIVE
            bar.apply_live_show(show_id=42, name="Group Therapy")
            bar.live_show_followed = True
            bar.state = State.PLAYING
            await pilot.pause()
            marker = bar.query_one("#live-show-follow")
            self.assertTrue(marker.display)

            bar.stop()
            await pilot.pause()

            self.assertFalse(marker.display)


if __name__ == "__main__":
    unittest.main()
