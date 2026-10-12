"""Local search bar, filter bar, empty-state, and global-search dispatch.

All the UI plumbing for the in-tab search
input, the filter-description label, the "No results for X" message, and
routing a global-search selection into the normal list handlers. The app
keeps the message-handler shells (on_input_changed etc.) and action_*
methods (Textual routing), delegating the bodies here.
"""

from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Input, Static, Tabs

from ..presentation import ANIMATION_FAST, TRACKS_EMPTY, TRACKS_HISTORY_PLACEHOLDER
from ..widgets.channel_list import ChannelList
from ..widgets.media_list import MediaList
from ..widgets.mixshow_list import MixshowList
from ..widgets.playlist_list import PlaylistList

if TYPE_CHECKING:
    from ..app import AddictuneApp
    from ..screens.global_search import GlobalSearchResult


class SearchService:
    def __init__(self, app: "AddictuneApp") -> None:
        self.app = app
        self._local_search_open = False

    # ── Search bar visibility ─────────────────────────────────────

    def sync_local_search_bar(self) -> None:
        try:
            bar = self.app.query_one("#local-search-bar", Horizontal)
            search_input = self.app.query_one("#local-search-input", Input)
        except NoMatches:
            return
        controller = self.app._active_followed_controller()
        query = controller.filter.search if controller is not None else ""
        if search_input.value != query:
            search_input.value = query
        bar.display = controller is not None and self._local_search_open

    def open_local_search_bar(self) -> None:
        bar = self.app.query_one("#local-search-bar", Horizontal)
        if self._local_search_open and bar.display:
            return
        self._local_search_open = True
        bar.display = True
        bar.styles.height = 0
        bar.styles.animate(
            "height",
            1,
            duration=ANIMATION_FAST,
            easing="out_sine",
        )

    def close_local_search_bar(self) -> None:
        if not self._local_search_open:
            return
        self._local_search_open = False
        bar = self.app.query_one("#local-search-bar", Horizontal)
        bar.styles.animate(
            "height",
            0,
            duration=ANIMATION_FAST,
            easing="out_sine",
            on_complete=lambda: self._on_local_search_closed(bar),
        )

    def _on_local_search_closed(self, bar: Horizontal) -> None:
        if self._local_search_open:
            return
        bar.display = False

    @property
    def local_search_open(self) -> bool:
        return self._local_search_open

    # ── Filter bar ────────────────────────────────────────────────

    def sync_filter_bar(self) -> None:
        try:
            bar = self.app.query_one("#filter-bar", Static)
        except NoMatches:
            return
        controller = self.app._active_followed_controller()
        label = controller.filter.label() if controller is not None else ""
        bar.update(label)
        bar.display = bool(label)

    # ── Actions ───────────────────────────────────────────────────

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "local-search-input":
            return
        event.stop()
        controller = self.app._active_followed_controller()
        if controller is None:
            return
        await controller.set_search(event.input.value)
        self.sync_empty_results()
        self.sync_local_search_bar()
        self.app._media_info.sync_open_media_info()
        self.app.refresh_bindings()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "local-search-input":
            return
        event.stop()
        self.focus_active_list()

    async def focus_local_search(self) -> None:
        controller = self.app._active_followed_controller()
        if controller is None:
            return
        self.open_local_search_bar()
        search_input = self.app.query_one("#local-search-input", Input)
        self.sync_local_search_bar()
        search_input.focus()
        search_input.cursor_position = len(search_input.value)

    async def cancel_local_search(self) -> None:
        controller = self.app._active_followed_controller()
        if controller is None:
            return
        search_input = self.app.query_one("#local-search-input", Input)
        if controller.filter.search:
            search_input.value = ""
            await controller.set_search("")
        self.sync_empty_results()
        self.close_local_search_bar()
        self.focus_active_list()
        self.app._media_info.sync_open_media_info()
        self.app.refresh_bindings()

    async def clear_local_search(self) -> None:
        controller = self.app._active_followed_controller()
        if controller is None:
            return
        search_input = self.app.query_one("#local-search-input", Input)
        search_input.value = ""
        await controller.set_search("")
        self.sync_empty_results()
        self.sync_local_search_bar()
        search_input.focus()
        self.app._media_info.sync_open_media_info()
        self.app.refresh_bindings()

    # ── Global search ─────────────────────────────────────────────

    def dispatch_global_search_result(self, result: "GlobalSearchResult") -> None:
        """Dispatch a global-search selection to the same handlers list rows use.

        Keep the search screen on the stack. If the result opens another screen
        (for example mixshow episodes), that screen appears above global search.
        Playback still updates the underlying tab lists and any matching search
        rows through the normal playback-highlight path.
        """
        match result.kind:
            case "channel":
                self.app.post_message(
                    ChannelList.ChannelSelected(result.item)  # type: ignore[arg-type]
                )
            case "mixshow":
                self.app.post_message(
                    MixshowList.ShowSelected(result.item)  # type: ignore[arg-type]
                )
            case "playlist":
                self.app.post_message(
                    PlaylistList.PlaylistSelected(result.item)  # type: ignore[arg-type]
                )

    # ── Helpers ───────────────────────────────────────────────────

    def active_search_query(self) -> str:
        controller = self.app._active_followed_controller()
        return controller.filter.search if controller is not None else ""

    def local_search_has_focus(self) -> bool:
        try:
            return self.app.query_one("#local-search-input", Input).has_focus
        except NoMatches:
            return False

    def focus_active_list(self) -> None:
        from ..app import TAB_LISTS

        if self.sync_empty_results():
            return
        active_tab = self.app.query_one(Tabs).active
        target = TAB_LISTS.get(active_tab)
        if target is None:
            return
        selector, list_type = target
        self.app.query_one(selector, list_type).focus()

    def sync_empty_results(self) -> bool:
        from ..app import TAB_LISTS

        try:
            empty = self.app.query_one("#empty-results", Static)
        except NoMatches:
            return False
        message = self.active_empty_message()
        show_empty = message is not None
        empty.update(message or "")
        empty.display = show_empty
        active_tab = self.app.query_one(Tabs).active
        for tab_id, (selector, list_type) in TAB_LISTS.items():
            try:
                widget = self.app.query_one(selector, list_type)
            except NoMatches:
                continue
            widget.display = tab_id == active_tab and not show_empty
        return show_empty

    def active_empty_message(self) -> str | None:
        controller = self.app._active_followed_controller()
        if controller is not None and not controller.searchable:
            return TRACKS_HISTORY_PLACEHOLDER
        if not self._active_list_is_settled_and_empty():
            return None
        if query := self.active_search_query():
            return f"No results for “{query}”"
        if self.app.query_one(Tabs).active == "tracks":
            return TRACKS_EMPTY
        return None

    def _active_list_is_settled_and_empty(self) -> bool:
        from ..app import TAB_LISTS

        active_tab = self.app.query_one(Tabs).active
        target = TAB_LISTS.get(active_tab)
        if target is None:
            return False
        selector, list_type = target
        try:
            widget = self.app.query_one(selector, list_type)
        except NoMatches:
            return False
        if len(widget):
            return False
        if not isinstance(widget, MediaList):
            return True
        return widget.is_exhausted and not widget.is_loading
