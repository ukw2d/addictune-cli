import asyncio
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from addictune_sdk.models.channel import Channel, TrackHistoryEntry
from addictune_sdk.models.mixshow import MixShow
from addictune_sdk.models.playlist import Playlist
from textual.app import App, ComposeResult
from textual.widgets import Label

from addictune_cli.src.tui.services.media_info import (
    MediaInfoService,
    _recent_track_labels,
    _without_current_track,
)
from addictune_cli.src.tui.types import ChannelView, MediaStatus, MediaStatusState
from addictune_cli.src.tui.widgets.channel_list import ChannelItem
from addictune_cli.src.tui.widgets.media_info import (
    MediaInfo,
    MediaInfoPanel,
)
from addictune_cli.src.tui.widgets.mixshow_list import MixshowItem
from addictune_cli.src.tui.widgets.playlist_list import PlaylistItem

from support import install_services


class _App(App):
    def __init__(self) -> None:
        super().__init__()
        self.selected_calls = 0
        self.history_loads = 0
        self.network = "di"
        self._statuses_by_channel = {}
        # MediaInfoService holds the body of the _media_info_* wrappers.
        from addictune_cli.src.tui.services.media_info import MediaInfoService

        self._media_info = MediaInfoService(self)
        install_services(self)

    def compose(self) -> ComposeResult:
        yield MediaInfoPanel()

    def _selected_list_item(self):
        self.selected_calls += 1
        channel = Channel(id=1, key="chill", name="Chill", network_id=1)
        return ChannelItem(ChannelView(channel))

    def load_channel_history(self, _channel_id: int, _network: str) -> None:
        self.history_loads += 1

    def _channel_media_info(self, view):

        return self._media_info._channel_media_info(view)

    def _media_info_from_item(self, item):
        return self._media_info.media_info_from_item(item)

    def _sync_media_info(self, item, *, open_panel=False):
        self._media_info.sync_media_info(item, open_panel=open_panel)

    def _sync_open_media_info(self) -> None:
        self._media_info.sync_open_media_info()


class _ImageApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.client = object()

    def compose(self) -> ComposeResult:
        yield MediaInfoPanel()


class MediaInfoPerformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_followed_badge_tracks_media_without_reserving_hidden_space(
        self,
    ) -> None:
        app = _ImageApp()

        async with app.run_test() as pilot:
            panel = app.query_one(MediaInfoPanel)
            badge = panel.query_one("#info-followed-badge", Label)

            panel.media = MediaInfo("Channel")
            await pilot.pause()
            self.assertFalse(badge.display)

            panel.media = MediaInfo("Channel", followed=True)
            await pilot.pause()
            self.assertTrue(badge.display)
            self.assertEqual(str(badge.render()), "\u2605 Followed")

    def test_followed_state_is_propagated_for_each_media_type(self) -> None:
        channel = Channel(id=1, key="chill", name="Chill")
        show = MixShow(
            id=2,
            name="Group Therapy",
            slug="group-therapy",
            following=True,
        )
        playlist = Playlist(id=3, name="Favorites", following=True)
        app = SimpleNamespace(
            network="di",
            _statuses_by_channel={},
            _statuses_by_show={},
        )
        service = MediaInfoService(app)
        items = (
            ChannelItem(ChannelView(channel, favorite=True)),
            MixshowItem(show),
            PlaylistItem(playlist),
        )

        for item in items:
            media = service.media_info_from_item(item)
            self.assertIsNotNone(media)
            self.assertTrue(media.followed)

    def test_recent_track_labels_use_display_values_and_limit_to_five(self) -> None:
        # The first entry is the currently-playing track and is dropped.
        history = [
            TrackHistoryEntry(artist="Current", title="Currently Playing"),
            *(
                TrackHistoryEntry(artist=f"Artist {index}", title=f"Track {index}")
                for index in range(1, 7)
            ),
        ]
        history[1] = TrackHistoryEntry(
            artist="Raw Artist",
            title="Raw Title",
            display_artist="Visible Artist",
            display_title="Visible Title",
        )

        self.assertEqual(
            _recent_track_labels(history),
            (
                "Visible Artist — Visible Title",
                "Artist 2 — Track 2",
                "Artist 3 — Track 3",
                "Artist 4 — Track 4",
                "Artist 5 — Track 5",
            ),
        )

    def test_recent_track_labels_drop_the_currently_playing_first_entry(self) -> None:
        # The SDK track_history endpoint returns the currently-playing track
        # as its first element; it must not appear in Recently Played.
        history = [
            TrackHistoryEntry(artist="Current", title="Right Now"),
            TrackHistoryEntry(artist="Previous", title="Earlier"),
        ]

        self.assertEqual(_recent_track_labels(history), ("Previous — Earlier",))

    def test_recent_tracks_exclude_the_current_track(self) -> None:
        tracks = (
            "Artist One — Track One",
            "Artist Two — Track Two",
        )
        status = MediaStatusState(
            MediaStatus.NOW_PLAYING,
            now_playing=("artist one", "track one"),
        )

        self.assertEqual(
            _without_current_track(tracks, status), ("Artist Two — Track Two",)
        )

    def test_recent_tracks_exclude_the_current_show(self) -> None:
        status = MediaStatusState(
            MediaStatus.LIVE_NOW,
            episode=SimpleNamespace(
                name="Episode 171", show=SimpleNamespace(name="Echoes")
            ),
        )

        self.assertEqual(
            _without_current_track(("Echoes", "Episode 171", "Earlier Track"), status),
            ("Earlier Track",),
        )

    async def test_closed_panel_skips_selected_item_lookup(self) -> None:
        app = _App()

        async with app.run_test():
            app._sync_open_media_info()

            self.assertEqual(app.selected_calls, 0)

    async def test_open_panel_syncs_selected_media_info(self) -> None:
        app = _App()

        async with app.run_test():
            panel = app.query_one(MediaInfoPanel)
            panel.is_open = True
            app._sync_open_media_info()

            self.assertEqual(app.selected_calls, 1)
            self.assertEqual(panel.media.title, "Chill")
            self.assertEqual(app.history_loads, 1)

            app._media_info._recent_tracks[("di", 1)] = (monotonic(), ())
            app._sync_open_media_info()
            self.assertEqual(app.history_loads, 1)

            app._media_info._recent_tracks[("di", 1)] = (0, ())
            app._media_info._history_loading.clear()
            app._sync_open_media_info()
            self.assertEqual(app.history_loads, 2)

    async def test_mixshow_detail_refresh_keeps_the_rows_follow_state(self) -> None:
        app = _App()
        app._statuses_by_show = {}
        app.client = None
        item = MixshowItem(MixShow(id=2, slug="s", name="Show", following=True))
        item.followed = False
        detail = MixShow(id=2, slug="s", name="Show", description="Full text")
        app._selected_list_item = lambda: item

        async with app.run_test() as pilot:
            panel = app.query_one(MediaInfoPanel)
            panel.is_open = True
            app.client = SimpleNamespace(
                network=lambda _n: SimpleNamespace(
                    mixshows=SimpleNamespace(get_by_id=AsyncMock(return_value=detail))
                )
            )
            worker = app.run_worker(
                app._media_info.refresh_mixshow_info(item, "di"), thread=False
            )
            await worker.wait()
            await pilot.pause()

            self.assertEqual(panel.media.description, "Full text")
            self.assertFalse(panel.media.followed)

    async def test_returning_to_displayed_image_cancels_pending_load(self) -> None:
        app = _ImageApp()
        loaded_urls: list[str] = []

        async def fetch_pixels(
            url: str, _width: int, _height: int, _client, *, scope: str = "media"
        ) -> str:
            loaded_urls.append(url)
            return f"pixels:{url}"

        async with app.run_test():
            panel = app.query_one(MediaInfoPanel)
            panel.is_open = True
            panel._image_loader._displayed_url = "trance.png"
            panel._image_loader._displayed_generation = (
                panel._image_loader._size_generation
            )

            with patch(
                "addictune_cli.src.tui.services.images.fetch_pixels",
                fetch_pixels,
            ):
                panel.media = MediaInfo("Progressive", image_url="progressive.png")
                panel.media = MediaInfo("Trance", image_url="trance.png")
                await asyncio.sleep(0.35)

        self.assertEqual(loaded_urls, [])

    async def test_status_widget_hidden_when_media_has_no_status(self) -> None:
        app = _ImageApp()

        async with app.run_test():
            panel = app.query_one(MediaInfoPanel)
            panel.media = MediaInfo("Playlist")

            self.assertFalse(panel.query_one("#info-status").display)

    async def test_status_widget_hides_after_status_media(self) -> None:
        app = _ImageApp()

        async with app.run_test():
            panel = app.query_one(MediaInfoPanel)
            status = MediaStatusState(
                MediaStatus.NOW_PLAYING,
                now_playing=("Artist", "Title"),
            )

            panel.media = MediaInfo("Channel", status=status)
            self.assertTrue(panel.query_one("#info-status").display)

            panel.media = MediaInfo("Playlist")
            self.assertFalse(panel.query_one("#info-status").display)

    async def test_recent_tracks_are_rendered_only_when_available(self) -> None:
        app = _ImageApp()

        async with app.run_test():
            panel = app.query_one(MediaInfoPanel)
            panel.media = MediaInfo(
                "Trance",
                recently_played=(
                    "Artist One — Track One",
                    "Artist Two — Track Two",
                ),
            )

            self.assertTrue(panel.query_one("#info-recent").display)
            rendered = [
                str(label.render()) for label in panel.query(".info--recent-track")
            ]
            self.assertEqual(
                rendered,
                [
                    "\u25b8 Artist One — Track One",
                    "\u25b8 Artist Two — Track Two",
                ],
            )

            panel.media = MediaInfo("Playlist")
            self.assertFalse(panel.query_one("#info-recent").display)


if __name__ == "__main__":
    unittest.main()
