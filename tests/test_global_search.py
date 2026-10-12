import unittest
from types import SimpleNamespace

from addictune_sdk import AddictuneAPIError
from addictune_sdk.models.channel import Channel
from addictune_sdk.models.mixshow import MixShow
from addictune_sdk.models.playlist import Playlist
from addictune_sdk.models.search import SearchBucket, SearchResults
from textual.app import App, ComposeResult
from textual.widgets import Input, ListView, Static

from support import install_services

from addictune_cli.src.tui.screens.global_search import (
    GlobalSearchResult,
    GlobalSearchScreen,
    SearchResultItem,
)


def _search_results(*, channels=None, shows=None, playlists=None) -> SearchResults:
    return SearchResults(
        channels=SearchBucket(items=channels or []),
        shows=SearchBucket(items=shows or []),
        playlists=SearchBucket(items=playlists or []),
    )


class _SearchAPI:
    def __init__(
        self,
        results: SearchResults | None = None,
        raises: AddictuneAPIError | None = None,
    ) -> None:
        self._results = results
        self._raises = raises

    async def query(self, _q: str) -> SearchResults:
        if self._raises is not None:
            raise self._raises
        return self._results or _search_results()


class _Client:
    def __init__(self, search: _SearchAPI | None = None) -> None:
        self._search = search or _SearchAPI()

    def network(self, _network: str):
        return SimpleNamespace(search=self._search)


class _App(App):
    def __init__(self, client: _Client | None = None) -> None:
        super().__init__()
        self.network = "di"
        self.client = client or _Client()
        self.selected: list[GlobalSearchResult] = []
        self.sync_highlight_calls = 0
        # The screen reaches the highlight through PlaybackService, so the
        # counter has to live where the real implementation does.
        self._playback_service = SimpleNamespace(
            _sync_global_search_playback_highlight=(
                self._sync_global_search_playback_highlight
            )
        )
        install_services(self)

    def compose(self) -> ComposeResult:
        yield GlobalSearchScreen()

    def on_global_search_screen_result_selected(
        self, message: GlobalSearchScreen.ResultSelected
    ) -> None:
        self.selected.append(message.result)

    def _sync_global_search_playback_highlight(self) -> None:
        self.sync_highlight_calls += 1
        self.query_one(GlobalSearchScreen).apply_playing_highlight(
            channel_id=None,
            show_id=10,
            playlist_id=None,
            suspended=False,
        )


def _set_input_value(app: _App, value: str) -> None:
    """Programmatically set the input value *without* dispatching Enter."""
    app.query_one(Input).value = value


async def _submit_input(pilot) -> None:
    """Press Enter on the search input."""
    await pilot.press("enter")


class GlobalSearchTests(unittest.IsolatedAsyncioTestCase):
    def _app_with(
        self,
        *,
        channels=None,
        shows=None,
        playlists=None,
        raises: AddictuneAPIError | None = None,
    ) -> _App:
        results = _search_results(channels=channels, shows=shows, playlists=playlists)
        return _App(client=_Client(search=_SearchAPI(results=results, raises=raises)))

    async def test_typing_alone_does_not_send_request(self) -> None:
        """User feedback: typing must NOT fire the network search."""
        app = self._app_with(
            channels=[Channel(id=1, name="Trance")],
            shows=[MixShow(id=10, name="Trance Show", slug="trance-show")],
            playlists=[Playlist(id=20, name="Trance Playlist", track_count=10)],
        )
        async with app.run_test() as pilot:
            _set_input_value(app, "trance")
            await pilot.pause()
            await pilot.pause()

            results = app.query_one(ListView)
            self.assertFalse(results.display)
            self.assertEqual(len(results.children), 0)
            empty = app.query_one("#global-search-empty", Static)
            # Placeholder may have been re-rendered but must NOT be "Searching..."
            self.assertNotIn("Searching", str(empty.content))

    async def test_enter_triggers_search_and_groups_results(self) -> None:
        """Pressing Enter sends the request and renders grouped results."""
        app = self._app_with(
            channels=[Channel(id=1, name="Trance")],
            shows=[MixShow(id=10, name="Trance Show", slug="trance-show")],
            playlists=[Playlist(id=20, name="Trance Playlist", track_count=10)],
        )
        async with app.run_test() as pilot:
            _set_input_value(app, "trance")
            await pilot.pause()
            await _submit_input(pilot)
            await pilot.pause()
            await pilot.pause()

            from addictune_cli.src.tui.screens.global_search import SectionItem

            children = app.query_one(ListView).children
            # Section headers must carry the global-search-section class so the
            # CSS rule that visually distinguishes them from result rows applies.
            sections = [c for c in children if isinstance(c, SectionItem)]
            self.assertEqual(len(sections), 3)
            for s in sections:
                self.assertTrue(s.has_class("global-search-section"))
            kinds = [
                item.result.kind
                for item in children
                if isinstance(item, SearchResultItem)
            ]
            self.assertEqual(kinds, ["channel", "mixshow", "playlist"])

    async def test_no_results_shows_empty_state(self) -> None:
        app = self._app_with()  # empty SearchResults
        async with app.run_test() as pilot:
            _set_input_value(app, "zzz-nothing-matches")
            await pilot.pause()
            await _submit_input(pilot)
            await pilot.pause()
            await pilot.pause()

            list_view = app.query_one(ListView)
            self.assertFalse(list_view.display)
            empty = app.query_one("#global-search-empty", Static)
            self.assertIn("No results", str(empty.content))

    async def test_sdk_error_shows_error_state(self) -> None:
        app = self._app_with(raises=AddictuneAPIError(404, "Not Found"))
        async with app.run_test() as pilot:
            _set_input_value(app, "trance")
            await pilot.pause()
            await _submit_input(pilot)
            await pilot.pause()
            await pilot.pause()

            list_view = app.query_one(ListView)
            self.assertFalse(list_view.display)
            empty = app.query_one("#global-search-empty", Static)
            self.assertIn("Search failed", str(empty.content))


class GlobalSearchSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_selecting_result_emits_message_without_dismissing_search(
        self,
    ) -> None:
        app = _App(
            client=_Client(
                search=_SearchAPI(
                    results=_search_results(
                        shows=[MixShow(id=10, name="State of Trance", slug="asot")]
                    )
                )
            )
        )

        async with app.run_test() as pilot:
            _set_input_value(app, "state")
            await _submit_input(pilot)
            await pilot.pause()
            await pilot.pause()

            list_view = app.query_one(ListView)
            list_view.index = next(
                i
                for i, child in enumerate(list_view.children)
                if isinstance(child, SearchResultItem)
            )
            row = list_view.children[list_view.index]
            assert isinstance(row, SearchResultItem)
            app.query_one(
                GlobalSearchScreen
            ).action_submit()  # Enter on the focused result
            await pilot.pause()

            self.assertIsNotNone(app.query_one(GlobalSearchScreen))
            self.assertEqual(len(app.selected), 1)
            self.assertEqual(app.selected[0].kind, "mixshow")
            self.assertEqual(app.selected[0].item.id, 10)

    async def test_playing_highlight_marks_matching_result(self) -> None:
        app = _App(
            client=_Client(
                search=_SearchAPI(
                    results=_search_results(
                        channels=[Channel(id=1, name="Trance")],
                        shows=[MixShow(id=10, name="State of Trance", slug="asot")],
                        playlists=[
                            Playlist(id=20, name="State Playlist", track_count=10)
                        ],
                    )
                )
            )
        )

        async with app.run_test() as pilot:
            _set_input_value(app, "state")
            await _submit_input(pilot)
            await pilot.pause()
            await pilot.pause()

            screen = app.query_one(GlobalSearchScreen)
            screen.apply_playing_highlight(
                channel_id=None,
                show_id=10,
                playlist_id=None,
                suspended=False,
            )

            rows = [
                child
                for child in app.query_one(ListView).children
                if isinstance(child, SearchResultItem)
            ]
            highlighted = [
                row.result.item.id for row in rows if row.has_class("playing")
            ]
            self.assertEqual(highlighted, [10])

    async def test_rendered_results_sync_existing_playback_highlight(self) -> None:
        app = _App(
            client=_Client(
                search=_SearchAPI(
                    results=_search_results(
                        shows=[MixShow(id=10, name="State of Trance", slug="asot")]
                    )
                )
            )
        )

        async with app.run_test() as pilot:
            _set_input_value(app, "state")
            await _submit_input(pilot)
            await pilot.pause()
            await pilot.pause()

            rows = [
                child
                for child in app.query_one(ListView).children
                if isinstance(child, SearchResultItem)
            ]
            self.assertEqual(app.sync_highlight_calls, 1)
            self.assertEqual(
                [row.result.item.id for row in rows if row.has_class("playing")],
                [10],
            )


class DispatchResultTests(unittest.TestCase):
    def _posted_messages_for(self, result: GlobalSearchResult) -> list:
        from addictune_cli.src.tui.services.search import SearchService

        posted: list = []

        class _App:
            def post_message(self, message):
                posted.append(message)

        SearchService(_App()).dispatch_global_search_result(result)
        return posted

    def test_channel_result_posts_channel_selected(self) -> None:
        from addictune_cli.src.tui.widgets.channel_list import ChannelList

        result = GlobalSearchResult(
            kind="channel",
            item=Channel(id=42, key="trance", name="Trance", network_id=1),
        )
        posted = self._posted_messages_for(result)
        matches = [m for m in posted if isinstance(m, ChannelList.ChannelSelected)]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].channel.id, 42)

    def test_mixshow_result_posts_show_selected(self) -> None:
        from addictune_cli.src.tui.widgets.mixshow_list import MixshowList

        result = GlobalSearchResult(
            kind="mixshow",
            item=MixShow(id=10, name="Trance Show", slug="trance-show"),
        )
        posted = self._posted_messages_for(result)
        self.assertTrue(any(isinstance(m, MixshowList.ShowSelected) for m in posted))

    def test_playlist_result_posts_playlist_selected(self) -> None:
        from addictune_cli.src.tui.widgets.playlist_list import PlaylistList

        result = GlobalSearchResult(
            kind="playlist",
            item=Playlist(id=20, name="Trance Playlist", track_count=10),
        )
        posted = self._posted_messages_for(result)
        self.assertTrue(
            any(isinstance(m, PlaylistList.PlaylistSelected) for m in posted)
        )


if __name__ == "__main__":
    unittest.main()
