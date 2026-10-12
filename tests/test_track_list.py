import unittest
from unittest.mock import Mock

from addictune_sdk import AddictuneAuthError
from addictune_sdk.models.track import LikedTrack
from textual.app import App, ComposeResult
from textual.widgets import Label, Static, Tab, Tabs

from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.services.features import NetworkFeatures
from addictune_cli.src.tui.services.following import TracksController
from addictune_cli.src.tui.types import TracksView
from addictune_cli.src.tui.services.search import SearchService
from addictune_cli.src.tui.widgets.channel_list import ChannelList
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar
from addictune_cli.src.tui.widgets.track_list import TrackItem, TrackList

from support import app_chrome, install_services, temp_settings


def _liked_track(track_id: int) -> LikedTrack:
    return LikedTrack.model_validate(
        {
            "id": track_id + 1000,
            "track_id": track_id,
            "channel_id": 1,
            "network_id": 1,
            "position": 1,
            "created_at": "2026-07-17T11:00:00Z",
            "updated_at": "2026-07-17T11:00:00Z",
            "up": True,
            "down": False,
            "display_artist": f"Favorite Artist {track_id}",
            "title": f"Favorite Track {track_id}",
        }
    )


class _TracksAPI:
    def __init__(self, tracks=None, error: Exception | None = None) -> None:
        self.tracks = tracks if tracks is not None else [_liked_track(20)]
        self.error = error
        self.calls: list[tuple[int, str]] = []

    def iter_liked_tracks(self, user_id: int, vote_type: str = "up"):
        self.calls.append((user_id, vote_type))
        return self._iter_tracks()

    async def _iter_tracks(self):
        if self.error is not None:
            raise self.error
        for track in self.tracks:
            yield track


class _Client:
    def __init__(self, tracks_api=None) -> None:
        self.tracks_api = tracks_api or _TracksAPI()

    def network(self, _network: str):
        return type("_Network", (), {"tracks": self.tracks_api})()


class _App(App):
    CSS_PATH = ["../addictune_cli/src/tui/styles/app.tcss"]

    def __init__(self) -> None:
        super().__init__()
        self.selected: list[int] = []
        self.network = "di"
        self.recovered_networks: list[str | None] = []
        self.retry_widgets = []
        self.recover_result = False
        self._search = self._playback_service = Mock()

    def compose(self) -> ComposeResult:
        yield TrackList(id="tracks-list")

    def on_track_list_track_selected(self, message: TrackList.TrackSelected) -> None:
        self.selected.append(message.track.track_id)

    async def recover_auth(self, network: str | None = None) -> bool:
        self.recovered_networks.append(network)
        return self.recover_result

    def _retry_lazy_list_after_auth(self, widget) -> None:
        self.retry_widgets.append(widget)


class _EmptyTracksApp(App):
    CSS_PATH = ["../addictune_cli/src/tui/styles/app.tcss"]
    _feature_availability = NetworkFeatures()

    def __init__(self, tracks_api: _TracksAPI) -> None:
        super().__init__()
        self.client = _Client(tracks_api)
        self.network = "zedradio"
        self.user_id = 7
        self._search = SearchService(self)
        self._followed_controllers = {"tracks": TracksController(self)}
        install_services(self)

    def compose(self) -> ComposeResult:
        yield Tabs(
            Tab("Channels", id="channels"),
            Tab("Tracks", id="tracks"),
        )
        yield from app_chrome()
        yield ChannelList(id="channel-list")
        yield TrackList(id="tracks-list")
        yield PlaybackBar(temp_settings(), id="playback-bar")

    def _sync_empty_results(self) -> bool:
        return self._search.sync_empty_results()

    def _sync_filter_bar(self) -> None:
        pass

    def _sync_open_media_info(self) -> None:
        pass

    def _notify_playback_changed(self) -> None:
        pass

    _active_followed_controller = AddictuneApp._active_followed_controller
    _selected_list_item = AddictuneApp._selected_list_item
    _list_item = AddictuneApp._list_item
    on_tabs_tab_activated = AddictuneApp.on_tabs_tab_activated
    _tab_available = AddictuneApp._tab_available
    _load_lazy_tab_if_needed = AddictuneApp._load_lazy_tab_if_needed


async def _settle(pilot) -> None:
    for _ in range(4):
        await pilot.pause()


class TrackListTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_uses_paginated_liked_tracks_api(self) -> None:
        tracks_api = _TracksAPI()
        app = _App()

        async with app.run_test() as pilot:
            tracks = app.query_one(TrackList)
            tracks.load(_Client(tracks_api), "di", user_id=7)
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(tracks_api.calls, [(7, "up")])
            self.assertEqual(len(tracks.children), 1)
            self.assertIsInstance(tracks.children[0], TrackItem)
            self.assertEqual(
                str(tracks.children[0].query_one(".media-list-name", Label).content),
                "Favorite Artist 20 — Favorite Track 20",
            )

    async def test_selecting_track_posts_track_selected(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            tracks = app.query_one(TrackList)
            tracks.load(_Client(), "di", user_id=7)
            await pilot.pause()
            await pilot.pause()

            tracks.index = 0
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.selected, [20])

    async def test_empty_favorites_stop_loading(self) -> None:
        tracks_api = _TracksAPI(tracks=[])
        app = _App()

        async with app.run_test() as pilot:
            tracks = app.query_one(TrackList)
            tracks.load(_Client(tracks_api), "zedradio", user_id=7)
            await pilot.pause()
            await pilot.pause()

            self.assertFalse(tracks.loading)
            self.assertFalse(tracks.is_loading)
            self.assertTrue(tracks.is_exhausted)
            self.assertEqual(len(tracks), 0)

    async def test_auth_failure_from_lazy_load_does_not_crash_worker(self) -> None:
        tracks_api = _TracksAPI(error=AddictuneAuthError("missing"))
        app = _App()

        async with app.run_test() as pilot:
            app.network = "classicalradio"
            tracks = app.query_one(TrackList)
            tracks.load(_Client(tracks_api), "classicalradio", user_id=7)
            await pilot.pause()
            await pilot.pause()

            self.assertFalse(tracks.loading)
            self.assertFalse(tracks.is_loading)
            self.assertFalse(tracks.is_exhausted)
            self.assertEqual(app.recovered_networks, ["classicalradio"])
            self.assertEqual(app.retry_widgets, [])

    async def test_auth_recovery_from_lazy_load_requests_retry(self) -> None:
        tracks_api = _TracksAPI(error=AddictuneAuthError("missing"))
        app = _App()
        app.recover_result = True

        async with app.run_test() as pilot:
            app.network = "classicalradio"
            tracks = app.query_one(TrackList)
            tracks.load(_Client(tracks_api), "classicalradio", user_id=7)
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.recovered_networks, ["classicalradio"])
            self.assertEqual(app.retry_widgets, [tracks])

    async def test_empty_favorites_show_center_placeholder(self) -> None:
        tracks_api = _TracksAPI(tracks=[])
        app = _EmptyTracksApp(tracks_api)

        async with app.run_test() as pilot:
            app.query_one(Tabs).active = "tracks"
            await pilot.pause()
            tracks = app.query_one(TrackList)
            await pilot.pause()
            await pilot.pause()

            empty = app.query_one("#empty-results", Static)
            self.assertTrue(empty.display)
            self.assertEqual(str(empty.content), "No liked tracks yet")
            self.assertFalse(tracks.display)

    async def test_returning_to_empty_tracks_does_not_focus_hidden_list(self) -> None:
        app = _EmptyTracksApp(_TracksAPI(tracks=[]))

        async with app.run_test() as pilot:
            tabs = app.query_one(Tabs)
            tabs.active = "tracks"
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            tabs.active = "channels"
            await pilot.pause()
            tabs.active = "tracks"
            await pilot.pause()

            tracks = app.query_one(TrackList)
            self.assertFalse(tracks.display)
            self.assertFalse(tracks.has_focus)

    async def test_focus_active_list_keeps_focus_off_empty_hidden_list(self) -> None:
        app = _EmptyTracksApp(_TracksAPI(tracks=[]))

        async with app.run_test() as pilot:
            app.query_one(Tabs).active = "tracks"
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()
            tabs = app.query_one(Tabs)
            tabs.focus()

            app._search.focus_active_list()

            self.assertTrue(tabs.has_focus)
            self.assertFalse(app.query_one(TrackList).has_focus)

    async def test_options_offer_a_view_switch_with_liked_tracks_first(self) -> None:
        app = _EmptyTracksApp(_TracksAPI())

        async with app.run_test():
            groups = {
                g.id: g
                for g in app._followed_controllers["tracks"].filter.option_groups()
            }

            self.assertEqual(list(groups), ["sort"])  # no Followed filter for tracks
            self.assertEqual(groups["sort"].title, "View")
            self.assertEqual(
                [(c.label, c.selected) for c in groups["sort"].choices],
                [("Liked tracks", True), ("History", False)],
            )

    async def test_history_view_shows_only_the_placeholder(self) -> None:
        app = _EmptyTracksApp(_TracksAPI())

        async with app.run_test() as pilot:
            controller = app._followed_controllers["tracks"]
            app.query_one(Tabs).active = "tracks"
            await _settle(pilot)
            tracks = app.query_one(TrackList)
            self.assertEqual(len(tracks), 1)  # liked tracks load by default
            self.assertTrue(controller.searchable)

            await controller.apply_option("sort", "history")
            await _settle(pilot)

            empty = app.query_one("#empty-results", Static)
            self.assertEqual(str(empty.content), "Listening history is coming soon")
            self.assertTrue(empty.display)
            self.assertFalse(tracks.display)
            self.assertEqual(len(tracks), 0)
            self.assertFalse(controller.searchable)  # nothing to search in it

            await controller.apply_option("sort", "liked")
            await _settle(pilot)
            self.assertEqual(len(tracks), 1)
            self.assertTrue(tracks.display)
            self.assertEqual(controller.filter.sort, TracksView.LIKED)

    def test_the_filter_picker_cannot_turn_on_a_followed_filter_for_tracks(
        self,
    ) -> None:
        initial = TracksController.initial
        self.assertEqual(initial.with_option("filter", "followed", None), initial)


if __name__ == "__main__":
    unittest.main()
