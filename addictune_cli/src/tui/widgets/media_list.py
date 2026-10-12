"""One lazy list widget for channels, mixshows, playlists and tracks.

``MediaList`` loads models from an async iterator in pages as the user scrolls,
keeps a per-view cache so switching sort/filter back restores what was loaded,
filters locally by search text, and retries after an auth recovery. What
differs per list lives in a ``ListSpec``: label, id, follow flag, selected
message, live badge. Rows wrap immutable models; follow state is an overlay
kept on the item, never a copied model.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import MouseScrollDown
from textual.message import Message
from textual.widgets import Label, ListItem, ListView
from textual.worker import get_current_worker

from ...auth import is_auth_failure
from ..types import MediaStatusState
from .live_show_badge import apply_live_show_badge

_PAGE = 20
_PREFETCH_FRACTION = 0.6  # fetch the next page once scrolled this far down


def matches_query(text: str, query: str) -> bool:
    """True when every whitespace-separated term of *query* is in *text*."""
    haystack = text.casefold()
    return all(term in haystack for term in query.casefold().split())


def normalize_query(query: str) -> str:
    return " ".join(query.casefold().split())


@dataclass(frozen=True, slots=True)
class ListSpec:
    label: Callable[[object], str]
    model_id: Callable[[object], int | None]
    message: Callable[[object], Message]  # built from the model on selection
    followed: Callable[[object], bool | None] = lambda m: None  # None: cannot follow
    live_badge: bool = False


class ModelItem(ListItem):
    """A row for one model; ``followed`` can be overridden without touching the model."""

    def __init__(self, model, spec: ListSpec) -> None:
        super().__init__()
        self.model = model
        self.spec = spec
        self.followed: bool | None = spec.followed(model)
        self.status: MediaStatusState | None = None

    @property
    def model_id(self) -> int | None:
        return self.spec.model_id(self.model)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="media-list-row"):
            yield Label(self.spec.label(self.model), classes="media-list-name")
            if self.spec.live_badge:
                yield Label("", classes="live-show-badge")

    def on_mount(self) -> None:
        self.apply_status(self.status)

    def apply_status(self, status: MediaStatusState | None) -> None:
        """Remember *status* and draw it; the badge exists only once mounted."""
        self.status = status
        if self.spec.live_badge and (badges := self.query(".live-show-badge")):
            apply_live_show_badge(badges.first(Label), status)


@dataclass
class _Load:
    """One loading session; a new ``show`` or ``reset`` retires the previous one."""

    source: AsyncIterator | None
    exhausted: bool = False
    busy: bool = False
    restore_index: int | None = None
    local: str | None = None  # local search query (paging paused)
    models: list = field(default_factory=list)


class MediaList(ListView):
    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "scroll_home", show=False),
        Binding("G", "scroll_end", show=False),
    ]

    spec: ListSpec

    item_type: type[ModelItem]  # row class; takes the model

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._load = _Load(None)
        self._view_key: str | None = None
        self._views: dict[str, _Load] = {}
        self._statuses: dict[int, MediaStatusState] = {}

    # -- public -----------------------------------------------------------------

    def on_mount(self) -> None:
        self.focus()

    @property
    def models(self) -> tuple:
        """The models currently shown (rows that were added directly count too)."""
        return tuple(
            item.model for item in self.children if isinstance(item, ModelItem)
        )

    @property
    def is_loading(self) -> bool:
        return self._load.busy or self.loading

    @property
    def is_exhausted(self) -> bool:
        return self._load.exhausted

    @property
    def can_load_more(self) -> bool:
        return not self._load.exhausted and self._load.source is not None

    def show(self, key: str, source: AsyncIterator) -> None:
        """Switch to the view *key*; a cached view restores without refetching."""
        if key == self._view_key:
            return
        self._save_view()
        self._view_key = key
        self._start(self._views.pop(key, None) or _Load(source))

    def reset(self) -> None:
        self._view_key = None
        self._views.clear()
        self._start(_Load(None))

    def request_more(self) -> bool:
        if not self.can_load_more:
            return False
        self._request_page()
        return True

    async def apply_local_search(self, query: str) -> None:
        """Filter the loaded models in place; an empty query shows them all again."""
        load = self._load
        load.local = query
        shown = [m for m in load.models if matches_query(self.spec.label(m), query)]
        self.loading = False
        await self.clear()
        # A pending page may have appended rows while the old rows were removed.
        await self.insert(0, (self.item_type(m) for m in shown))
        if not query:
            load.local = None
        self.call_after_refresh(self.app._search.sync_empty_results)

    def apply_statuses(self, statuses: dict[int, MediaStatusState]) -> None:
        self._statuses = statuses
        for item in self.query(ModelItem):
            item.apply_status(statuses.get(item.model_id))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ModelItem):
            self.post_message(self.spec.message(event.item.model))

    # -- paging -----------------------------------------------------------------

    def on_resize(self) -> None:
        self.call_after_refresh(self._fill_viewport)

    def on_list_view_highlighted(self) -> None:
        self._prefetch()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        self._prefetch()

    def _prefetch(self) -> None:
        if (
            self.max_scroll_y
            and self.scroll_y >= self.max_scroll_y * _PREFETCH_FRACTION
        ):
            self._request_page()

    def _fill_viewport(self) -> None:
        if self.max_scroll_y == 0:
            self._request_page()

    def _request_page(self) -> None:
        load = self._load
        if load.exhausted or load.source is None or load.busy or load.local is not None:
            return
        load.busy = True
        self._load_page(load)

    def _start(self, load: _Load) -> None:
        self._load = load
        self.clear()
        self.loading = load.source is not None and not load.models
        if load.models:
            load.busy = True
            self._show_cached(load)
        else:
            self._request_page()
        self.call_after_refresh(self.app._search.sync_empty_results)

    @work(exclusive=True)
    async def _show_cached(self, load: _Load) -> None:
        await self.extend(self.item_type(m) for m in load.models)
        if self.display:
            self.focus()
        load.busy = False
        self._after_page(load, [])

    @work(exclusive=True)
    async def _load_page(self, load: _Load) -> None:
        worker = get_current_worker()
        first_page = not len(self)
        page: list = []
        try:
            async for model in load.source:
                if worker.is_cancelled or load is not self._load:
                    return
                page.append(model)
                if len(page) >= _PAGE:
                    break
            else:
                load.exhausted = True
        except Exception as exc:
            if load is not self._load:
                return
            load.busy = False
            self.loading = False
            if is_auth_failure(exc):
                await self._recover_auth()
                return
            raise
        if load is not self._load:
            return
        load.models += page
        if load.local is not None:
            page = [m for m in page if matches_query(self.spec.label(m), load.local)]
        if page:
            self.loading = False
            await self.extend(self.item_type(m) for m in page)
            if first_page and self.display:
                self.focus()
        elif load.exhausted:
            self.loading = False
        load.busy = False
        self._after_page(load, page)

    def _after_page(self, load: _Load, page: list) -> None:
        if load.restore_index is not None and len(self):
            self.index = min(load.restore_index, len(self) - 1)
            load.restore_index = None
        self.apply_statuses(self._statuses)
        app = self.app
        self.call_after_refresh(app._search.sync_empty_results)
        self.call_after_refresh(app._playback_service._notify_playback_changed)
        self.call_after_refresh(app._playback_service._focus_playing_item_in, self)
        self.call_after_refresh(self._fill_viewport)

    def _save_view(self) -> None:
        load = self._load
        if self._view_key is None or (not load.models and load.source is None):
            return
        load.restore_index, load.busy, load.local = self.index, False, None
        self._views[self._view_key] = load

    async def _recover_auth(self) -> None:
        app = self.app
        if await app.recover_auth(app.network):
            app._retry_lazy_list_after_auth(self)
        else:
            self.reset()


def selected_child(list_view: ListView):
    index = list_view.index
    if index is None or not 0 <= index < len(list_view.children):
        return None
    return list_view.children[index]
