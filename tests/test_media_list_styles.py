import unittest

from addictune_sdk.models.channel import Channel
from addictune_sdk.models.mixshow import MixShow, ShowEpisode
from addictune_sdk.models.playlist import Playlist
from addictune_sdk.models.track import LikedTrack
from textual.app import App, ComposeResult
from textual.color import Color
from textual.widgets import ListView

from addictune_cli.src.tui.screens.episodes import EpisodeItem
from addictune_cli.src.tui.types import ChannelView
from addictune_cli.src.tui.widgets.channel_list import ChannelItem
from addictune_cli.src.tui.widgets.mixshow_list import MixshowItem
from addictune_cli.src.tui.widgets.playlist_list import PlaylistItem
from addictune_cli.src.tui.widgets.track_list import TrackItem


class _App(App):
    CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.playing_episode_id = None

    def compose(self) -> ComposeResult:
        yield ListView(
            ChannelItem(ChannelView(Channel(id=1, key="one", name="One"))),
            MixshowItem(MixShow(id=2, name="Two", slug="two")),
            PlaylistItem(Playlist(id=3, name="Three", track_count=3)),
            TrackItem(
                LikedTrack.model_validate(
                    {
                        "id": 4,
                        "track_id": 4,
                        "title": "Four",
                        "channel_id": 1,
                        "network_id": 1,
                        "position": 1,
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                        "up": True,
                        "down": False,
                    }
                )
            ),
            EpisodeItem(ShowEpisode(id=5, name="Five", show_id=2)),
        )


class MediaListStyleTests(unittest.IsolatedAsyncioTestCase):
    async def test_standard_rows_share_playback_state_styles(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            rows = list(app.query_one(ListView).children)
            default_color = rows[0].styles.color
            for row in rows:
                row.add_class("playing")
            await pilot.pause()

            expected_playing = Color.parse(app.get_css_variables()["success-muted"])
            for row in rows:
                self.assertEqual(row.styles.background, expected_playing)
                self.assertEqual(row.styles.color, default_color)

            for row in rows:
                row.remove_class("playing")
                row.add_class("suspended")
            await pilot.pause()

            expected_suspended = Color.parse(
                app.get_css_variables()["success"]
            ).with_alpha(0.1)
            for row in rows:
                self.assertEqual(row.styles.background, expected_suspended)
                self.assertEqual(row.styles.color.a, 0.6)

    async def test_only_live_capable_rows_have_trailing_badges(self) -> None:
        app = _App()

        async with app.run_test():
            channel, mixshow, playlist, track, episode = app.query_one(
                ListView
            ).children
            for row in (channel, mixshow):
                badges = list(row.query(".live-show-badge"))
                self.assertEqual(len(badges), 1)
                badge = badges[0]
                self.assertTrue(badge.styles.width.is_auto)
                self.assertEqual(badge.styles.padding.left, 1)
                self.assertEqual(badge.styles.padding.right, 1)

            for row in (playlist, track, episode):
                self.assertFalse(row.query(".live-show-badge"))


if __name__ == "__main__":
    unittest.main()
