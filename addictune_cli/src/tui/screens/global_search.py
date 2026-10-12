"""Global search: one query across channels, mixshows and playlists."""

from dataclasses import dataclass
from typing import Literal

from addictune_sdk.models.channel import Channel
from addictune_sdk.models.mixshow import MixShow
from addictune_sdk.models.playlist import Playlist
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, ListItem, ListView, Static
from textual.worker import get_current_worker

from ..typed_nodes import AppNode
from ..utils import mark_playing

_PLACEHOLDER = (
    "Type a query and press Enter to search channels, mixshows and playlists."
)
_LOADING = "Searching..."
_NO_RESULTS = "No results for {query}"
_ERROR = "Search failed: {message}"

SearchKind = Literal["channel", "mixshow", "playlist"]


@dataclass(frozen=True)
class GlobalSearchResult:
    kind: SearchKind
    item: Channel | MixShow | Playlist


class SearchResultItem(ListItem):
    def __init__(self, result: GlobalSearchResult, detail: str = "") -> None:
        name = getattr(result.item, "name", "")
        super().__init__(Label(f"{name}  {detail}" if detail else name))
        self.result = result


class SectionItem(ListItem):
    def __init__(self, title: str) -> None:
        super().__init__(Label(title), classes="global-search-section")


class GlobalSearchScreen(AppNode, Screen[GlobalSearchResult | None]):
    DEFAULT_CSS = """
#global-search-input {
    padding: 0 1;
}

#global-search-results {
    height: 1fr;
}

GlobalSearchScreen ListItem.global-search-section {
    background: $background;
    color: $primary;
    text-style: bold;
    padding: 0 1;
}

GlobalSearchScreen SearchResultItem.playing {
    background: $success 20%;
    color: $success;
    text-style: bold;
}

GlobalSearchScreen SearchResultItem.suspended {
    background: $warning 15%;
    color: $warning;
    text-style: bold;
}
    """

    class ResultSelected(Message):
        def __init__(self, result: GlobalSearchResult) -> None:
            self.result = result
            super().__init__()

    # No "/" (local search does not apply here) and no repeated Search binding.
    BINDINGS = [
        Binding("escape", "back", "Back", key_display="Esc"),
        Binding("enter", "submit", "Search/Open", key_display="Enter"),
        Binding("ctrl+u", "clear_search", "Clear", key_display="^U"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._last_query: str | None = None

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Search channels, mixshows, playlists...",
            id="global-search-input",
            classes="search-input",
        )
        yield Static(_PLACEHOLDER, id="global-search-empty", classes="empty-state")
        yield ListView(id="global-search-results")
        yield Footer()

    def on_mount(self) -> None:
        self._input.focus()
        self._results.display = False

    @property
    def _input(self) -> Input:
        return self.query_one("#global-search-input", Input)

    @property
    def _results(self) -> ListView:
        return self.query_one("#global-search-results", ListView)

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        return bool(self._input.value) if action == "clear_search" else True

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        # Typing never sends a request; clearing the field resets the placeholder.
        if not event.value.strip():
            self._show_message(_PLACEHOLDER)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_submit()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if isinstance(event.item, SearchResultItem):
            self.post_message(self.ResultSelected(event.item.result))

    def action_back(self) -> None:
        self.dismiss(None)

    def action_clear_search(self) -> None:
        self._input.value = ""
        self._input.focus()
        self._last_query = None
        self._show_message(_PLACEHOLDER)

    def action_submit(self) -> None:
        """Enter: search from the input, or open the highlighted result.

        Enter on the input with the results of that same query already shown
        moves focus to the list instead of searching again.
        """
        if self._input.has_focus:
            query = self._input.value.strip()
            if not query:
                return
            if (
                self._results.display
                and len(self._results)
                and query == self._last_query
            ):
                self._results.focus()
            else:
                self._run_search(query)
            return
        index = self._results.index
        if index is not None and 0 <= index < len(self._results.children):
            item = self._results.children[index]
            if isinstance(item, SearchResultItem):
                self.post_message(self.ResultSelected(item.result))

    def _show_message(self, message: str) -> None:
        self._results.display = False
        empty = self.query_one("#global-search-empty", Static)
        empty.display = True
        empty.update(message)

    @work(exclusive=True)
    async def _run_search(self, query: str) -> None:
        self._show_message(_LOADING)
        app = self.app
        try:
            payload = await app.client.network(app.network).search.query(query)
        except Exception as exc:
            if not get_current_worker().is_cancelled:
                await self._results.clear()
                self._show_message(_ERROR.format(message=exc))
            return
        if get_current_worker().is_cancelled:
            return
        results = self._results
        await results.clear()
        sections = (
            ("Channels", "channel", payload.channels.items, lambda _: ""),
            ("Mixshows", "mixshow", payload.shows.items, lambda _: ""),
            (
                "Playlists",
                "playlist",
                payload.playlists.items,
                lambda p: f"{p.track_count} tracks" if p.track_count else "",
            ),
        )
        for title, kind, items, detail in sections:
            if items:
                await results.append(SectionItem(title))
                for item in items:
                    await results.append(
                        SearchResultItem(GlobalSearchResult(kind, item), detail(item))
                    )
        if not len(results):
            self._show_message(_NO_RESULTS.format(query=query))
            return
        self._last_query = query
        self.query_one("#global-search-empty", Static).display = False
        results.display = True
        results.index = next(
            (
                i
                for i, child in enumerate(results.children)
                if isinstance(child, SearchResultItem)
            ),
            None,
        )
        app._playback_service._sync_global_search_playback_highlight()
        results.focus()

    def apply_playing_highlight(
        self,
        *,
        channel_id: int | None,
        show_id: int | None,
        playlist_id: int | None,
        suspended: bool,
    ) -> None:
        playing = {"channel": channel_id, "mixshow": show_id, "playlist": playlist_id}
        item = next(
            (
                c
                for c in self.query(SearchResultItem)
                if getattr(c.result.item, "id", None) == playing[c.result.kind]
            ),
            None,
        )
        mark_playing(self, item, suspended=suspended)
