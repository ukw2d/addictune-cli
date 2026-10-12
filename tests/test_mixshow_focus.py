import asyncio
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from addictune_sdk.models.mixshow import MixShow
from textual.app import App, ComposeResult
from textual.widgets import Tab, Tabs

from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.services.following import MixshowFollowedController
from addictune_cli.src.tui.services.features import NetworkFeatures
from addictune_cli.src.tui.services.playback import PlaybackService
from addictune_cli.src.audio.state import State
from addictune_cli.src.tui.services.queue import TrackQueue
from addictune_cli.src.tui.types import (
    MediaStatus,
    MediaStatusState,
)
from addictune_cli.src.tui.widgets.channel_list import ChannelList
from addictune_cli.src.tui.widgets.mixshow_list import MixshowList
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar
from addictune_cli.src.tui.widgets.playlist_list import PlaylistList

from support import app_chrome, install_services, temp_settings


class _Mixshows:
    def __init__(self, shows: list[MixShow] | None = None) -> None:
        self.shows_calls = 0
        self.popular_calls = 0
        self.shows = shows or [MixShow(id=1, name="First show", slug="first-show")]

    async def iter_shows(self):
        self.shows_calls += 1
        for show in self.shows:
            yield show

    async def iter_popular(self):
        self.popular_calls += 1
        yield MixShow(id=2, name="Popular show", slug="popular-show")


class _Client:
    def __init__(self, shows: list[MixShow] | None = None) -> None:
        self.mixshows = _Mixshows(shows)

    def network(self, _network: str):
        return SimpleNamespace(mixshows=self.mixshows)

    async def close(self) -> None:
        pass


class _App(App):
    _feature_availability = NetworkFeatures()

    def __init__(self, shows: list[MixShow] | None = None) -> None:
        super().__init__()
        self.client = _Client(shows)
        self.network = "di"
        self.user_id = None
        self._followed_controllers = {"mixshows": MixshowFollowedController(self)}
        self._playing_channel_id = None
        self.track_queue = None
        self.playing_episode_id = None
        self._statuses_by_show = {}
        self._next_show_by_channel = {}
        self._playback_service = PlaybackService(self)
        install_services(self)

    def play_show(self, show_id: int) -> None:
        """Fake playback of a mixshow the way PlaybackService would set it up."""
        self.track_queue = TrackQueue(
            "mixshow",
            show_id,
            self.network,
            "Q",
            (SimpleNamespace(id=show_id, tracks=[SimpleNamespace(id=show_id)]),),
        )
        self.query_one("#playback-bar", PlaybackBar).state = State.PLAYING

    def compose(self) -> ComposeResult:
        yield Tabs(Tab("Channels", id="channels"), Tab("Mixshows", id="mixshows"))
        yield from app_chrome()
        yield ChannelList(id="channel-list")
        yield MixshowList(id="mixshows-list")
        yield PlaylistList(id="playlists-list")
        yield PlaybackBar(temp_settings(), id="playback-bar")

    on_tabs_tab_activated = AddictuneApp.on_tabs_tab_activated
    _active_followed_controller = AddictuneApp._active_followed_controller
    _selected_list_item = AddictuneApp._selected_list_item
    _list_item = AddictuneApp._list_item
    _tab_available = AddictuneApp._tab_available
    _load_lazy_tab_if_needed = AddictuneApp._load_lazy_tab_if_needed

    def _apply_playback_highlight(self) -> None:
        self._playback_service._apply_playback_highlight()

    def _notify_playback_changed(self) -> None:
        self._playback_service._notify_playback_changed()

    def _find_playing_item(self, *, within=None):
        return self._playback_service._find_playing_item(within=within)


class _Shows:
    def iter_shows(self):
        async def gen():
            return
            yield

        return gen()

    iter_popular = iter_followed = iter_shows


class MixshowListCacheKeyTests(unittest.IsolatedAsyncioTestCase):
    """add-2w1: which shows are live right now is state, not part of the view key,
    so a status change must not add a cache entry."""

    async def _views_after(self, statuses_a, statuses_b, filter_b) -> int:
        app = _KeyApp()
        async with app.run_test() as pilot:
            lst = app.query_one(MixshowList)
            client = SimpleNamespace(
                network=lambda _n: SimpleNamespace(mixshows=_Shows())
            )
            lst.apply_statuses(statuses_a)
            lst.load(client, "di", status_filter={MediaStatus.LIVE_NOW})
            await pilot.pause()
            lst.apply_statuses(statuses_b)
            lst.load(client, "di", status_filter=filter_b)
            await pilot.pause()
            return len(lst._views)

    async def test_view_key_is_stable_while_which_shows_match_changes(self) -> None:
        live = {MediaStatus.LIVE_NOW}
        views = await self._views_after(
            {1: MediaStatusState(MediaStatus.LIVE_NOW)},
            {2: MediaStatusState(MediaStatus.LIVE_NOW)},
            live,
        )
        self.assertEqual(views, 0)  # same key: the second load() was a no-op

    async def test_view_key_still_distinguishes_filtered_from_unfiltered(self) -> None:
        views = await self._views_after({}, {}, None)
        self.assertEqual(views, 1)  # the filtered view was saved when switching away

    async def test_pending_page_respects_current_search_and_restores_models(self) -> None:
        app = _KeyApp()
        started, done = asyncio.Event(), asyncio.Event()

        async def shows():
            for i in range(1, 21):
                yield MixShow(id=i, name=f"Show {i}", slug=f"show-{i}")
            started.set()
            await done.wait()
            for i in range(21, 42):
                yield MixShow(
                    id=i,
                    name="Wanted show" if i == 21 else f"Show {i}",
                    slug=f"show-{i}",
                )

        async with app.run_test(size=(80, 10)) as pilot:
            try:
                lst = app.query_one(MixshowList)
                lst.show("all", shows())
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual(len(lst), 20)
                lst.request_more()
                await asyncio.wait_for(started.wait(), timeout=5)
                self.assertTrue(started.is_set())
                await lst.apply_local_search("No match")
                await lst.apply_local_search("Wanted")

                done.set()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual([show.id for show in lst.models], [21])
                self.assertFalse(lst.is_loading)

                await lst.apply_local_search("")
                await pilot.pause()
                self.assertEqual([show.id for show in lst.models], list(range(1, 41)))
                lst.request_more()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual([show.id for show in lst.models], list(range(1, 42)))
                self.assertTrue(lst.is_exhausted)

                lst.show("other", _Shows().iter_shows())
                await app.workers.wait_for_complete()
                await pilot.pause()
                lst.show("all", _Shows().iter_shows())
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual([show.id for show in lst.models], list(range(1, 42)))
            finally:
                done.set()

    async def test_clearing_search_does_not_start_a_second_pending_page(self) -> None:
        app = _KeyApp()
        started, done = asyncio.Event(), asyncio.Event()

        async def shows():
            for i in range(1, 21):
                yield MixShow(id=i, name=f"Show {i}", slug=f"show-{i}")
            started.set()
            await done.wait()
            yield MixShow(id=21, name="Last show", slug="last-show")

        async with app.run_test(size=(80, 10)) as pilot:
            try:
                lst = app.query_one(MixshowList)
                lst.show("all", shows())
                await app.workers.wait_for_complete()
                await pilot.pause()
                lst.request_more()
                await asyncio.wait_for(started.wait(), timeout=5)
                self.assertTrue(started.is_set())
                await lst.apply_local_search("Show 1")
                await lst.apply_local_search("")
                self.assertTrue(lst.is_loading)
                lst.request_more()
                done.set()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual([show.id for show in lst.models], list(range(1, 22)))
                self.assertFalse(lst.is_loading)
            finally:
                done.set()

    async def _clear_search_during_page(self, *, pending: bool) -> None:
        app = _KeyApp()
        page_started, page_done = asyncio.Event(), asyncio.Event()
        cleared, restore = asyncio.Event(), asyncio.Event()

        async def shows():
            for i in range(1, 21):
                yield MixShow(id=i, name=f"Show {i}", slug=f"show-{i}")
            page_started.set()
            await page_done.wait()
            yield MixShow(id=21, name="Last show", slug="last-show")

        async with app.run_test(size=(80, 10)) as pilot:
            lst = app.query_one(MixshowList)
            lst.show("all", shows())
            await app.workers.wait_for_complete()
            await pilot.pause()
            if pending:
                lst.request_more()
                await asyncio.wait_for(page_started.wait(), timeout=5)
            await lst.apply_local_search("Show 1")
            original_clear = lst.clear

            async def paused_clear():
                await original_clear()
                cleared.set()
                await restore.wait()

            with patch.object(lst, "clear", paused_clear):
                rebuilding = asyncio.create_task(lst.apply_local_search(""))
                try:
                    await asyncio.wait_for(cleared.wait(), timeout=5)
                    page_done.set()
                    await pilot.pause()
                    lst._fill_viewport()
                    await app.workers.wait_for_complete()
                finally:
                    restore.set()
                    page_done.set()
                    await rebuilding

            await pilot.pause()
            expected = list(range(1, 22 if pending else 21))
            self.assertEqual([show.id for show in lst.models], expected)
            if not pending:
                self.assertFalse(page_started.is_set())
                lst.request_more()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual([show.id for show in lst.models], list(range(1, 22)))

    async def test_clearing_search_blocks_prefetch_until_models_are_restored(self) -> None:
        await self._clear_search_during_page(pending=False)

    async def test_page_finishing_during_search_clear_keeps_model_order(self) -> None:
        await self._clear_search_during_page(pending=True)


class _KeyApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.network = "di"
        self._search = self._playback_service = Mock()

    def compose(self) -> ComposeResult:
        yield MixshowList(id="mixshows-list")


class MixshowFocusTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_mixshows_page_accepts_keyboard_navigation(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(Tabs).active = "mixshows"
            await pilot.pause()
            await pilot.pause()

            mixshows = app.query_one(MixshowList)
            self.assertEqual(len(mixshows), 1)

            await pilot.press("down")

            self.assertTrue(mixshows.has_focus)
            self.assertEqual(mixshows.index, 0)

    async def test_popular_mixshows_use_popular_iterator(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            controller = app._followed_controllers["mixshows"]
            await controller.apply_option("sort", "popular")
            await pilot.pause()
            await pilot.pause()

            mixshows = app.query_one(MixshowList)
            self.assertEqual(len(mixshows), 1)
            self.assertEqual(mixshows.children[0].show.name, "Popular show")

    async def test_reselecting_current_sort_does_not_reload(self) -> None:
        app = _App()

        async with app.run_test():
            mixshows = app.query_one(MixshowList)
            calls = 0
            original = mixshows.load

            def count_load(*args, **kwargs):
                nonlocal calls
                calls += 1
                return original(*args, **kwargs)

            mixshows.load = count_load
            controller = app._followed_controllers["mixshows"]

            await controller.apply_option("filter", "all")
            self.assertEqual(calls, 0)

            await controller.apply_option("sort", "popular")
            self.assertEqual(calls, 1)

            await controller.apply_option("sort", "popular")
            self.assertEqual(calls, 1)

    async def test_live_now_filter_shows_only_live_mixshows(self) -> None:
        app = _App(
            [
                MixShow(id=1, name="First show", slug="first-show"),
                MixShow(id=2, name="Live show", slug="live-show"),
                MixShow(id=3, name="Upcoming show", slug="upcoming-show"),
            ]
        )
        app._statuses_by_show = {
            2: MediaStatusState(MediaStatus.LIVE_NOW),
            3: MediaStatusState(MediaStatus.UPCOMING),
        }

        async with app.run_test() as pilot:
            controller = app._followed_controllers["mixshows"]
            await controller.apply_option("status", "live_now", True)
            await pilot.pause()
            await pilot.pause()

            mixshows = app.query_one(MixshowList)
            self.assertEqual(len(mixshows), 1)
            self.assertEqual(mixshows.children[0].show.name, "Live show")
            self.assertEqual(controller.filter.label(), "Filter: Live now")

    async def test_mixshow_sort_restores_loaded_items_without_refetching(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            controller = app._followed_controllers["mixshows"]
            controller.load()
            await pilot.pause()
            await pilot.pause()
            self.assertEqual(app.client.mixshows.shows_calls, 1)

            await controller.apply_option("sort", "popular")
            await pilot.pause()
            await pilot.pause()
            self.assertEqual(app.client.mixshows.popular_calls, 1)

            await controller.apply_option("sort", "default")
            await pilot.pause()
            await pilot.pause()

            mixshows = app.query_one(MixshowList)
            self.assertEqual(app.client.mixshows.shows_calls, 1)
            self.assertEqual(len(mixshows), 1)
            self.assertEqual(mixshows.children[0].show.name, "First show")

    async def test_playing_mixshow_highlights_when_tab_loads_after_playback(
        self,
    ) -> None:
        shows = [MixShow(id=1, name="State of Trance", slug="asot")]
        app = _App(shows)

        async with app.run_test() as pilot:
            await pilot.pause()
            app.play_show(1)
            app.query_one(Tabs).active = "mixshows"
            await pilot.pause()
            await app.workers.wait_for_complete()

            mixshows = app.query_one(MixshowList)
            await mixshows.wait_for_refresh()
            self.assertEqual(len(mixshows), 1)
            self.assertTrue(mixshows.children[0].has_class("playing"))

    async def test_playing_mixshow_highlights_when_later_page_loads(self) -> None:
        shows = [
            MixShow(id=i, name=f"Show {i}", slug=f"show-{i}") for i in range(1, 26)
        ]
        app = _App(shows)

        async with app.run_test() as pilot:
            app.play_show(25)
            app.query_one(Tabs).active = "mixshows"
            await pilot.pause()
            await app.workers.wait_for_complete()

            mixshows = app.query_one(MixshowList)
            self.assertEqual(len(mixshows), 20)
            self.assertFalse(
                any(child.has_class("playing") for child in mixshows.children)
            )

            mixshows.request_more()
            await app.workers.wait_for_complete()
            await mixshows.wait_for_refresh()

            playing = [
                child.show.id
                for child in mixshows.children
                if child.has_class("playing")
            ]
            self.assertEqual(playing, [25])


if __name__ == "__main__":
    unittest.main()
