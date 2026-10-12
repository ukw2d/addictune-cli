import unittest
from types import SimpleNamespace

from addictune_sdk.models.playlist import Playlist
from textual.app import App, ComposeResult
from textual.widgets import Tab, Tabs

from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.services.following import PlaylistFollowedController
from addictune_cli.src.tui.services.features import NetworkFeatures
from addictune_cli.src.tui.widgets.channel_list import ChannelList
from addictune_cli.src.tui.widgets.mixshow_list import MixshowList
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar
from addictune_cli.src.tui.widgets.playlist_list import PlaylistList

from support import app_chrome, install_services, temp_settings


class _Playlists:
    def __init__(self) -> None:
        self.playlists_calls = 0

    async def iter_playlists(self, **_kwargs):
        self.playlists_calls += 1
        yield Playlist(id=1, name="First playlist", track_count=42)
        yield Playlist(id=2, name="Second playlist", track_count=12)


class _Client:
    def __init__(self) -> None:
        self.playlists = _Playlists()

    def network(self, _network: str):
        return SimpleNamespace(playlists=self.playlists)


class _App(App):
    _feature_availability = NetworkFeatures()

    def __init__(self) -> None:
        super().__init__()
        install_services(self)
        self.client = _Client()
        self.network = "di"
        self.user_id = None
        self._followed_controllers = {"playlists": PlaylistFollowedController(self)}

    def compose(self) -> ComposeResult:
        yield Tabs(
            Tab("Channels", id="channels"),
            Tab("Mixshows", id="mixshows"),
            Tab("Playlists", id="playlists"),
        )
        yield from app_chrome()
        yield ChannelList(id="channel-list")
        yield MixshowList(id="mixshows-list")
        yield PlaylistList(id="playlists-list")
        yield PlaybackBar(temp_settings(), id="playback-bar")

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


class PlaylistListTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_playlists_page_loads_on_tab_activation(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(Tabs).active = "playlists"
            await pilot.pause()
            await pilot.pause()

            playlists = app.query_one(PlaylistList)
            self.assertEqual(app.client.playlists.playlists_calls, 1)
            self.assertEqual(len(playlists), 2)
            self.assertEqual(playlists.children[0].playlist.name, "First playlist")
            self.assertFalse(playlists.children[0].query(".live-show-badge"))
            self.assertTrue(playlists.has_focus)

    async def test_local_search_filters_paginated_playlist_source(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            app.query_one(Tabs).active = "playlists"
            await pilot.pause()
            await pilot.pause()
            controller = app._followed_controllers["playlists"]
            await controller.set_search("second")
            await pilot.pause()
            await pilot.pause()

            playlists = app.query_one(PlaylistList)
            self.assertEqual(app.client.playlists.playlists_calls, 1)
            self.assertEqual(len(playlists), 1)
            self.assertEqual(playlists.children[0].playlist.name, "Second playlist")


if __name__ == "__main__":
    unittest.main()
