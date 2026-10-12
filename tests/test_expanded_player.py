import asyncio
import unittest

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widget import Widget

from addictune_cli.src.audio.state import State
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.expanded_player import (
    ExpandedPlayer,
)
from addictune_cli.src.tui.widgets.marquee_text import MarqueeText
from addictune_cli.src.tui.widgets.playback_format import format_volume_label


class _PlaybackState(Widget):
    state = reactive(State.STOPPED)
    now_playing = reactive("")
    channel_name = reactive("")
    next_playing = reactive("")
    live_show_id: reactive[int | None] = reactive(None)
    live_show_name = reactive("")
    live_show_followed: reactive[bool | None] = reactive(None)
    content_type = reactive(ContentType.LIVE)
    elapsed_seconds = reactive(0)
    duration_seconds = reactive(None)
    volume = reactive(10)
    muted = reactive(False)
    vote_state = reactive(None)
    track_image_url = reactive(None)
    stream_quality: reactive[tuple[str, str] | None] = reactive(None)


class _App(App):
    CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.client = object()

    def compose(self) -> ComposeResult:
        yield ExpandedPlayer(id="expanded-player")
        yield _PlaybackState(id="playback-bar")


async def _wait_for_player_bindings(ep: ExpandedPlayer) -> None:
    refreshed = asyncio.Event()
    ep.call_after_refresh(refreshed.set)
    await asyncio.wait_for(refreshed.wait(), timeout=5)


class ExpandedPlayerTests(unittest.IsolatedAsyncioTestCase):
    async def test_starts_closed_and_toggles_open_close(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            ep = app.query_one(ExpandedPlayer)
            self.assertFalse(ep.is_open)
            self.assertTrue(ep.query_one("#expanded-type").has_class("live"))

            ep.open()
            await pilot.pause()
            self.assertTrue(ep.is_open)

            ep.close()
            await pilot.pause()
            self.assertFalse(ep.is_open)

    async def test_vote_state_toggles_active_class(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            ep = app.query_one(ExpandedPlayer)
            bar = app.query_one(_PlaybackState)
            ep.open()
            await pilot.pause()

            bar.vote_state = "up"
            await pilot.pause()
            self.assertTrue(ep.query_one("#expanded-like").has_class("active"))
            self.assertFalse(ep.query_one("#expanded-dislike").has_class("active"))

            bar.vote_state = "down"
            await pilot.pause()
            self.assertFalse(ep.query_one("#expanded-like").has_class("active"))
            self.assertTrue(ep.query_one("#expanded-dislike").has_class("active"))

            bar.vote_state = None
            await pilot.pause()
            self.assertFalse(ep.query_one("#expanded-like").has_class("active"))
            self.assertFalse(ep.query_one("#expanded-dislike").has_class("active"))

    async def test_live_content_keeps_known_duration_progress_visible(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            ep = app.query_one(ExpandedPlayer)
            bar = app.query_one(_PlaybackState)
            ep.open()
            await pilot.pause()

            # Force the transition that previously ran watch_content_type and
            # collapsed the live bar after it had appeared correctly at startup.
            bar.content_type = ContentType.MIXSHOW
            await pilot.pause()
            bar.content_type = ContentType.LIVE
            bar.elapsed_seconds = 1_831
            bar.duration_seconds = 7_260
            bar.state = State.PLAYING
            await pilot.pause()

            seek = ep.query_one("#expanded-seek")
            self.assertTrue(seek.display)
            self.assertEqual(seek.total, 7_260)
            self.assertEqual(seek.progress, 1_831)
            self.assertEqual(str(ep.query_one("#expanded-elapsed").render()), "0:30:31")
            self.assertEqual(
                str(ep.query_one("#expanded-duration").render()), "2:01:00"
            )
            self.assertTrue(ep.query_one("#expanded-type").has_class("live"))

    async def test_unknown_duration_animates_only_while_loading(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            ep = app.query_one(ExpandedPlayer)
            bar = app.query_one(_PlaybackState)
            bar.content_type = ContentType.MIXSHOW
            bar.duration_seconds = None
            ep.open()
            await pilot.pause()

            seek = ep.query_one("#expanded-seek")
            bar.state = State.LOADING
            await pilot.pause()
            self.assertIsNone(seek.total)

            bar.state = State.PAUSED
            await pilot.pause()
            self.assertEqual(seek.total, 1.0)
            self.assertEqual(seek.progress, 0.0)

    async def test_tracks_playback_bar_state(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            bar = app.query_one(_PlaybackState)
            ep = app.query_one(ExpandedPlayer)
            await _wait_for_player_bindings(ep)
            bar.state = State.PLAYING
            bar.now_playing = "Solarstone — Solarcoaster"
            bar.next_playing = "Next: Above & Beyond - Sun In Your Eyes"
            bar.volume = 65
            await pilot.pause()

            self.assertEqual(
                str(ep.query_one("#expanded-next").render()), bar.next_playing
            )
            self.assertEqual(
                str(ep.query_one("#expanded-volume").render()),
                format_volume_label(65, muted=False),
            )

    async def test_title_and_channel_reuse_overflow_only_marquee(self) -> None:
        app = _App()

        async with app.run_test(size=(100, 24)) as pilot:
            bar = app.query_one(_PlaybackState)
            ep = app.query_one(ExpandedPlayer)
            bar.channel_name = "Trance"
            bar.live_show_id = 42
            bar.live_show_name = "Melodik"
            bar.live_show_followed = False
            bar.now_playing = "Short track"
            ep.open()
            await pilot.pause()
            await pilot.pause()

            channel = ep.query_one("#expanded-channel", MarqueeText)
            title = ep.query_one("#expanded-title", MarqueeText)
            self.assertEqual(channel.text, "Trance · Melodik")
            self.assertEqual(title.text, "Short track")
            self.assertIsNone(channel._timer)
            self.assertIsNone(title._timer)

            bar.live_show_name = "A very long live show name " * 5
            bar.now_playing = "Artist — A very long track title " * 5
            await pilot.pause()

            self.assertGreater(len(channel.text), channel.size.width)
            self.assertGreater(len(title.text), title.size.width)
            self.assertIsNotNone(channel._timer)
            self.assertIsNotNone(title._timer)
            self.assertLessEqual(
                channel.region.right, ep.query_one("#expanded-follow").region.x
            )
            self.assertLessEqual(
                title.region.right, ep.query_one("#expanded-like").region.x
            )

    async def test_next_row_is_visible_only_when_it_has_content(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            bar = app.query_one(_PlaybackState)
            ep = app.query_one(ExpandedPlayer)
            await _wait_for_player_bindings(ep)
            channel = ep.query_one("#expanded-channel")
            next_item = ep.query_one("#expanded-next")
            bar.channel_name = "Trance"
            await pilot.pause()

            self.assertEqual(str(channel.render()), "Trance")
            self.assertFalse(next_item.visible)
            self.assertEqual(str(next_item.render()), "")

            bar.next_playing = "Next: One"
            await pilot.pause()
            self.assertTrue(next_item.visible)
            self.assertEqual(str(next_item.render()), "Next: One")
            self.assertEqual(str(channel.render()), "Trance")

            bar.next_playing = ""
            await pilot.pause()
            self.assertFalse(next_item.visible)
            self.assertEqual(str(channel.render()), "Trance")

    async def test_tracks_playback_bar_track_image_url(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            bar = app.query_one(_PlaybackState)
            ep = app.query_one(ExpandedPlayer)
            requested: list[str | None] = []
            ep._image_loader.request = lambda url, **_: requested.append(url)

            bar.track_image_url = "https://example.test/track.png?size=200"
            await pilot.pause()
            self.assertEqual(requested, [])  # closed: no fetch

            ep.open()
            await pilot.pause()
            self.assertEqual(requested, ["https://example.test/track.png?size=200"])

    async def test_stream_quality_uses_the_follow_action_rail(self) -> None:
        app = _App()

        async with app.run_test(size=(100, 24)) as pilot:
            bar = app.query_one(_PlaybackState)
            ep = app.query_one(ExpandedPlayer)
            bar.channel_name = "Trance"
            bar.live_show_id = 42
            bar.live_show_name = "Melodik Revolution"
            bar.live_show_followed = False
            bar.next_playing = "Next: The Official Trance Podcast"
            bar.stream_quality = (
                "AAC · 128k",
                "Source: AAC · 128 kbps · 44.1 kHz · Stereo",
            )
            ep.open()
            await pilot.pause()
            await pilot.pause()

            quality = ep.query_one("#expanded-quality")
            follow = ep.query_one("#expanded-follow")
            self.assertTrue(quality.display)
            self.assertEqual(str(quality.render()), "AAC · 128k")
            self.assertEqual(
                quality.tooltip,
                "Source: AAC · 128 kbps · 44.1 kHz · Stereo",
            )
            state = ep.query_one("#expanded-state")
            dislike = ep.query_one("#expanded-dislike")
            channel = ep.query_one("#expanded-channel")
            next_item = ep.query_one("#expanded-next")
            title = ep.query_one("#expanded-title")
            like = ep.query_one("#expanded-like")
            elapsed = ep.query_one("#expanded-elapsed")
            volume = ep.query_one(".expanded--volume-control")
            self.assertEqual(state.region.y, quality.region.y)
            self.assertEqual(channel.region.y, follow.region.y)
            self.assertLessEqual(channel.region.right, follow.region.x)
            self.assertNotEqual(channel.region.y, next_item.region.y)
            self.assertEqual(title.region.y, like.region.y)
            self.assertEqual(title.region.y, dislike.region.y)
            self.assertEqual(elapsed.region.y, volume.region.y)
            self.assertEqual(quality.region.right, follow.region.right)
            self.assertEqual(quality.region.right, dislike.region.right)

            bar.stream_quality = None
            await pilot.pause()
            self.assertFalse(quality.display)

class LiveShowFollowChipTests(unittest.IsolatedAsyncioTestCase):
    """The follow chip owns a spaced action rail aligned with Nope.

    Chip/channel-label render logic is plain Python (no pure-function
    extraction here, unlike the bar marker) because the chip reuses the
    existing vote styling.
    """

    async def test_hidden_when_no_show_is_airing(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            bar = app.query_one(_PlaybackState)
            ep = app.query_one(ExpandedPlayer)
            bar.channel_name = "Trance"
            await pilot.pause()

            self.assertFalse(ep.query_one("#expanded-follow").display)
            self.assertEqual(str(ep.query_one("#expanded-channel").render()), "Trance")

    async def test_hidden_while_follow_state_is_unresolved(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            bar = app.query_one(_PlaybackState)
            ep = app.query_one(ExpandedPlayer)
            bar.channel_name = "Trance"
            bar.live_show_id = 42
            bar.live_show_name = "FSOE 978"
            await pilot.pause()

            self.assertFalse(ep.query_one("#expanded-follow").display)
            # The show name itself is not gated on follow state resolving.
            self.assertEqual(
                str(ep.query_one("#expanded-channel").render()), "Trance · FSOE 978"
            )

    async def test_not_followed_and_followed_are_visually_distinct(self) -> None:
        app = _App()

        async with app.run_test():
            bar = app.query_one(_PlaybackState)
            ep = app.query_one(ExpandedPlayer)
            await _wait_for_player_bindings(ep)
            bar.live_show_id = 42
            bar.live_show_name = "FSOE 978"
            chip = ep.query_one("#expanded-follow")

            bar.live_show_followed = False
            self.assertTrue(chip.display)
            self.assertEqual(str(chip.render()), "[♡ Follow]")
            self.assertFalse(chip.has_class("active"))

            bar.live_show_followed = True
            self.assertTrue(chip.display)
            self.assertEqual(str(chip.render()), "[♥ Following]")
            self.assertTrue(chip.has_class("active"))

    async def test_hidden_when_switching_to_on_demand_playback(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            bar = app.query_one(_PlaybackState)
            ep = app.query_one(ExpandedPlayer)
            bar.channel_name = "Trance"
            bar.live_show_id = 42
            bar.live_show_name = "FSOE 978"
            bar.live_show_followed = True
            await pilot.pause()
            self.assertTrue(ep.query_one("#expanded-follow").display)

            bar.content_type = ContentType.MIXSHOW
            await pilot.pause()

            self.assertFalse(ep.query_one("#expanded-follow").display)
            self.assertEqual(str(ep.query_one("#expanded-channel").render()), "Trance")

if __name__ == "__main__":
    unittest.main()
