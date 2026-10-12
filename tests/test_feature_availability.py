import unittest
from types import SimpleNamespace

from addictune_sdk.exceptions import AddictuneNotFoundError
from textual.app import App, ComposeResult
from textual.widgets import Static, Tab, Tabs

from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.services.following import ChannelFollowedController
from addictune_cli.src.tui.services.channels import ChannelsService
from addictune_cli.src.tui.services.features import FeatureCache, NetworkFeatures
from addictune_cli.src.tui.widgets.channel_list import ChannelList
from addictune_cli.src.tui.widgets.mixshow_list import MixshowList
from addictune_cli.src.tui.widgets.playlist_list import PlaylistList
from addictune_cli.src.tui.widgets.track_list import TrackList

from support import install_services


async def _items(*items):
    for item in items:
        yield item


class _Mixshows:
    def __init__(self, *items, error: Exception | None = None) -> None:
        self.items = items
        self.error = error
        self.calls = []

    async def iter_shows(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        async for item in _items(*self.items):
            yield item


class _Playlists:
    def __init__(self, *items, error: Exception | None = None) -> None:
        self.items = items
        self.error = error
        self.calls = []

    async def iter_playlists(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        async for item in _items(*self.items):
            yield item


class _Tracks:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    async def get_liked_tracks(self, user_id: int, **kwargs):
        self.calls.append((user_id, kwargs))
        if self.error is not None:
            raise self.error
        return []


class _Client:
    def __init__(self, mixshows, playlists, tracks) -> None:
        self._network = SimpleNamespace(
            mixshows=mixshows,
            playlists=playlists,
            tracks=tracks,
        )

    def network(self, _network: str):
        return self._network


class FeatureDetectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_tabs_use_one_page_content_probe(self) -> None:
        mixshows = _Mixshows(object())
        playlists = _Playlists()
        tracks = _Tracks()

        cache = FeatureCache()
        features = await cache.detect(
            _Client(mixshows, playlists, tracks), "di", user_id=7
        )

        self.assertEqual(
            features,
            NetworkFeatures(mixshows=True, playlists=False, tracks=True),
        )
        self.assertEqual(mixshows.calls, [{"per_page": 1, "end_page": 1}])
        self.assertEqual(playlists.calls, [{"per_page": 1, "end_page": 1}])
        self.assertEqual(tracks.calls, [(7, {"per_page": 1, "page": 1})])
        # Known for the session: a second detect does not probe again.
        await cache.detect(_Client(mixshows, playlists, tracks), "di", user_id=7)
        self.assertEqual(len(mixshows.calls), 1)

    async def test_anonymous_probe_is_repeated_after_login(self) -> None:
        mixshows, playlists, tracks = (
            _Mixshows(object()),
            _Playlists(object()),
            _Tracks(),
        )
        cache = FeatureCache()
        anonymous = await cache.detect(
            _Client(mixshows, playlists, tracks), "di", user_id=None
        )
        self.assertTrue(anonymous.tracks)  # default: unknown until logged in
        self.assertEqual(tracks.calls, [])

        await cache.detect(_Client(mixshows, playlists, tracks), "di", user_id=7)
        self.assertEqual(len(mixshows.calls), 2)
        self.assertEqual(len(tracks.calls), 1)

    async def test_not_found_marks_feature_unavailable(self) -> None:
        features = await FeatureCache().detect(
            _Client(
                _Mixshows(error=AddictuneNotFoundError()),
                _Playlists(object()),
                _Tracks(error=AddictuneNotFoundError()),
            ),
            "di",
            user_id=7,
        )

        self.assertEqual(
            features,
            NetworkFeatures(mixshows=False, playlists=True, tracks=False),
        )


class _FeatureApp(App):
    def __init__(self, features: NetworkFeatures) -> None:
        super().__init__()
        self._feature_availability = features
        self._feature_cache = FeatureCache()
        self.network = "di"
        self.user_id = 7
        self._channels = [object()]
        self._statuses_by_channel = {1: object()}
        self._statuses_by_show = {2: object()}
        self._live_by_channel = {1: object()}
        self._now_playing_by_channel = {1: object()}
        self._followed_controllers = {"channels": ChannelFollowedController(self)}
        self._channels_service = ChannelsService(self)
        install_services(self)
        self.load_channels_calls = 0
        self.refresh_feature_calls = 0

    def compose(self) -> ComposeResult:
        yield Tabs(
            Tab("Channels", id="channels"),
            Tab("Mixshows", id="mixshows"),
            Tab("Playlists", id="playlists"),
            Tab("Tracks", id="tracks"),
        )
        yield Static("", id="filter-bar")
        yield Static("", id="empty-results")
        yield ChannelList(id="channel-list")
        yield MixshowList(id="mixshows-list")
        yield PlaylistList(id="playlists-list")
        yield TrackList(id="tracks-list")

    _active_followed_controller = AddictuneApp._active_followed_controller
    _selected_list_item = AddictuneApp._selected_list_item
    _list_item = AddictuneApp._list_item
    _sync_feature_tabs = AddictuneApp._sync_feature_tabs
    _activate_first_available_tab = AddictuneApp._activate_first_available_tab
    _available_tabs = AddictuneApp._available_tabs
    _tab_available = AddictuneApp._tab_available
    _load_lazy_tab_if_needed = AddictuneApp._load_lazy_tab_if_needed

    def _sync_empty_results(self) -> bool:
        return False

    def _sync_filter_bar(self) -> None:
        pass

    def load_channels(self) -> None:
        self.load_channels_calls += 1

    def refresh_feature_availability(self) -> None:
        self.refresh_feature_calls += 1


class FeatureTabTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_tabs_are_hidden_and_disabled(self) -> None:
        app = _FeatureApp(NetworkFeatures(mixshows=False, playlists=True, tracks=False))

        async with app.run_test() as pilot:
            app._sync_feature_tabs()
            await pilot.pause()

            tabs = app.query_one(Tabs)
            self.assertFalse(tabs.query_one("#mixshows", Tab).display)
            self.assertTrue(tabs.query_one("#mixshows", Tab).disabled)
            self.assertTrue(tabs.query_one("#playlists", Tab).display)
            self.assertFalse(tabs.query_one("#tracks", Tab).display)
            self.assertEqual(tabs.active, "channels")

    async def test_active_unavailable_tab_falls_back_to_channels(self) -> None:
        app = _FeatureApp(NetworkFeatures(mixshows=True, playlists=False, tracks=True))

        async with app.run_test() as pilot:
            tabs = app.query_one(Tabs)
            tabs.active = "playlists"
            app._sync_feature_tabs()
            await pilot.pause()

            self.assertEqual(tabs.active, "channels")

    async def test_network_switch_resets_optional_tab_to_channels(self) -> None:
        app = _FeatureApp(NetworkFeatures(mixshows=True, playlists=True, tracks=True))
        app.network = "classicalradio"
        app._feature_cache.remember(
            "classicalradio",
            NetworkFeatures(mixshows=False, playlists=True, tracks=True),
        )

        async with app.run_test() as pilot:
            tabs = app.query_one(Tabs)
            tabs.active = "mixshows"
            await pilot.pause()

            await app._channels_service.watch_network()
            await pilot.pause()

            self.assertEqual(tabs.active, "channels")
            self.assertFalse(tabs.query_one("#mixshows", Tab).display)
            self.assertTrue(app.query_one("#channel-list", ChannelList).display)
            self.assertFalse(app.query_one("#mixshows-list", MixshowList).display)
            self.assertEqual(app._channels, [])
            self.assertEqual(app._statuses_by_channel, {})
            self.assertEqual(app._live_by_channel, {})
            self.assertEqual(app.load_channels_calls, 1)
            self.assertEqual(app.refresh_feature_calls, 0)

    async def test_network_switch_hides_unknown_optional_tabs_while_probing(
        self,
    ) -> None:
        app = _FeatureApp(NetworkFeatures(mixshows=True, playlists=True, tracks=True))
        app.network = "jazzradio"

        async with app.run_test() as pilot:
            tabs = app.query_one(Tabs)
            tabs.active = "playlists"
            await pilot.pause()

            await app._channels_service.watch_network()
            await pilot.pause()

            self.assertEqual(tabs.active, "channels")
            self.assertFalse(tabs.query_one("#mixshows", Tab).display)
            self.assertFalse(tabs.query_one("#playlists", Tab).display)
            self.assertFalse(tabs.query_one("#tracks", Tab).display)


if __name__ == "__main__":
    unittest.main()
