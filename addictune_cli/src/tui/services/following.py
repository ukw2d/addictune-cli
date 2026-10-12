"""Per-tab list filter state and follow handling.

One ``ListFilter`` value holds what the user chose for a tab (followed-only,
sort, live-status, search). The four controllers share its option groups and
labels and differ only in how a change is applied: channels filter a list that
is already in memory, mixshows, playlists and tracks reload from the API.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from ..types import (
    ChannelSort,
    ChannelView,
    MediaStatus,
    MixshowSort,
    OptionChoice,
    OptionGroup,
    PlaylistSort,
    TracksView,
)
from ..widgets.channel_list import ChannelItem
from ..widgets.media_list import ModelItem, matches_query
from ..widgets.mixshow_list import MixshowItem, MixshowList
from ..widgets.playlist_list import PlaylistItem, PlaylistList
from ..widgets.track_list import TrackItem, TrackList

if TYPE_CHECKING:
    from ..app import AddictuneApp


@dataclass(frozen=True, slots=True)
class ListFilter:
    """What the user chose for one tab. Built once per change (frozen value)."""

    sorts: tuple[
        tuple[str, str, Enum], ...
    ]  # (choice_id, label, enum); first is default
    sort: Enum
    statuses: tuple[tuple[str, str, MediaStatus], ...] = ()
    followed_label: str | None = "Followed"  # None: no Filter-by group
    sort_title: str = "Sort by"
    followed_only: bool = False
    status: frozenset[MediaStatus] = frozenset()
    search: str = ""

    @classmethod
    def default(
        cls, sorts, statuses=(), followed_label="Followed", sort_title="Sort by"
    ) -> "ListFilter":
        return cls(sorts, sorts[0][2], statuses, followed_label, sort_title)

    def option_groups(self) -> list[OptionGroup]:
        groups = []
        if self.followed_label is not None:
            groups.append(
                OptionGroup(
                    "filter",
                    "Filter by",
                    [
                        OptionChoice("all", "All", not self.followed_only),
                        OptionChoice(
                            "followed", self.followed_label, self.followed_only
                        ),
                    ],
                )
            )
        if len(self.sorts) > 1:
            groups.append(
                OptionGroup(
                    "sort",
                    self.sort_title,
                    [
                        OptionChoice(cid, label, self.sort == s)
                        for cid, label, s in self.sorts
                    ],
                )
            )
        if self.statuses:
            groups.append(
                OptionGroup(
                    "status",
                    "Live status",
                    [
                        OptionChoice(cid, label, st in self.status)
                        for cid, label, st in self.statuses
                    ],
                    multiple=True,
                )
            )
        return groups

    def label(self) -> str:
        parts = []
        if self.followed_only:
            parts.append(self.followed_label)
        parts += [label for _, label, st in self.statuses if st in self.status]
        pieces = [f"Filter: {' + '.join(parts)}"] if parts else []
        if self.sort != self.sorts[0][2]:
            label = next(label for _, label, s in self.sorts if s == self.sort)
            pieces.append(f"{self.sort_title.removesuffix(' by')}: {label}")
        return " | ".join(pieces)

    def with_option(
        self, group_id: str, choice_id: str, value: bool | None
    ) -> "ListFilter":
        """The filter after one picker change; equal to self when nothing changes."""
        followed_only, sort, status = self.followed_only, self.sort, self.status
        match group_id:
            case "filter" if self.followed_label is not None:
                followed_only = choice_id == "followed"
            case "sort":
                sort = next(s for cid, _, s in self.sorts if cid == choice_id)
            case "status":
                st = next(st for cid, _, st in self.statuses if cid == choice_id)
                on = (st not in status) if value is None else value
                status = status | {st} if on else status - {st}
        return self._build(followed_only, sort, status, self.search)

    def with_search(self, query: str) -> "ListFilter":
        return self._build(self.followed_only, self.sort, self.status, query)

    def _build(
        self, followed_only: bool, sort: Enum, status: frozenset, search: str
    ) -> "ListFilter":
        return ListFilter(
            self.sorts,
            sort,
            self.statuses,
            self.followed_label,
            self.sort_title,
            followed_only,
            status,
            search,
        )


class FollowedController:
    """Shared surface over a ``ListFilter`` for one tab; subclasses apply changes."""

    item_type: type[ModelItem]
    initial: ListFilter

    def __init__(self, app: "AddictuneApp") -> None:
        self.app = app
        self.filter = self.initial

    # -- read by follow/search/bindings services -----------------------------

    def accepts(self, item: object) -> bool:
        return isinstance(item, self.item_type)

    def followed(self, item: object) -> bool | None:
        return item.followed if isinstance(item, self.item_type) else None

    def item_name(self, item: object) -> str:
        return item.spec.label(item.model) if isinstance(item, self.item_type) else ""

    def live_show_id(self, item: object) -> int | None:
        return None

    @property
    def searchable(self) -> bool:
        """False while the tab shows a placeholder instead of a list."""
        return True

    # -- changes -------------------------------------------------------------

    async def apply_option(
        self, group_id: str, choice_id: str, value: bool | None = None
    ) -> None:
        new = self.filter.with_option(group_id, choice_id, value)
        if new == self.filter or not self._allowed(new):
            return
        self.filter = new
        await self.refresh()

    async def set_search(self, query: str) -> None:
        if query != self.filter.search:
            self.filter = self.filter.with_search(query)
            await self.refresh_search()

    def _allowed(self, new: ListFilter) -> bool:
        if new.followed_only and self.app.user_id is None:
            self.app.notify(
                f"Log in to view {new.followed_label.lower()}.", severity="warning"
            )
            return False
        return True

    async def refresh(self) -> None:
        raise NotImplementedError

    async def refresh_search(self) -> None:
        await self.refresh()

    async def update_remote(
        self, item: object, followed: bool, user_id: int, network: str
    ) -> None:
        raise NotImplementedError

    async def apply_update(self, item: object, followed: bool) -> None:
        raise NotImplementedError


class ChannelFollowedController(FollowedController):
    item_type = ChannelItem
    initial = ListFilter.default(
        sorts=(
            ("default", "Default", ChannelSort.DEFAULT),
            ("alpha", "A-Z", ChannelSort.ALPHA),
            ("popular", "Popular", ChannelSort.POPULAR),
        ),
        statuses=(
            ("live_now", "Live now", MediaStatus.LIVE_NOW),
            ("upcoming", "Upcoming", MediaStatus.UPCOMING),
        ),
        followed_label="Favorites",
    )

    def __init__(self, app: "AddictuneApp") -> None:
        super().__init__(app)
        self._popular_order: dict[str, list[int]] = {}

    async def refresh(self) -> None:
        await self.prepare_sort()
        await self.app._channels_service._render_channel_list()

    def visible_channels(self, channels: list[ChannelView]) -> list[ChannelView]:
        f = self.filter
        views = [c for c in channels if not f.followed_only or c.favorite]
        if f.status:
            live = self.app._live_by_channel  # scheduled shows only, not now-playing
            views = [
                c
                for c in views
                if (s := live.get(c.channel.id)) and s.status in f.status
            ]
        if f.search:
            views = [c for c in views if matches_query(c.channel.name, f.search)]
        match f.sort:
            case ChannelSort.ALPHA:
                views.sort(key=lambda c: c.channel.name.casefold())
            case ChannelSort.POPULAR:
                by_id = {c.channel.id: c for c in views}
                views = [
                    by_id[cid]
                    for cid in self._popular_order.get(self.app.network, [])
                    if cid in by_id
                ]
        return views

    async def prepare_sort(self) -> None:
        if (
            self.filter.sort != ChannelSort.POPULAR
            or self.app.network in self._popular_order
        ):
            return
        popular = await self.app.client.network(self.app.network).channels.get_filter(
            "popular"
        )
        self._popular_order[self.app.network] = [c.id for c in popular.channels]

    def clear_sort_cache(self) -> None:
        self._popular_order.clear()

    async def update_remote(
        self, item: object, followed: bool, user_id: int, network: str
    ) -> None:
        api = self.app.client.network(network).channels
        if followed:
            await api.add_favorite(user_id, item.channel.id)
        else:
            await api.remove_favorite(user_id, item.channel.id)

    async def apply_update(self, item: object, followed: bool) -> None:
        channel_id = item.channel.id
        self.app._channels = [
            ChannelView(c.channel, followed) if c.channel.id == channel_id else c
            for c in self.app._channels
        ]
        if self.filter.followed_only:
            await self.app._channels_service._render_channel_list()
        else:
            item.followed = followed


class RemoteListController(FollowedController):
    """Mixshows and playlists: a filter change reloads the list from the API."""

    list_selector: str
    list_type: type

    def _list(self):
        return self.app.query_one(self.list_selector, self.list_type)

    def load(self) -> None:
        f = self.filter
        self._list().load(
            self.app.client,
            self.app.network,
            user_id=self.app.user_id,
            followed_only=f.followed_only,
            sort=f.sort,
            search_query=f.search,
            **self._load_kwargs(),
        )

    def _load_kwargs(self) -> dict[str, object]:
        return {}

    async def refresh(self) -> None:
        self.load()

    async def refresh_search(self) -> None:
        await self._list().apply_local_search(self.filter.search)

    async def apply_update(self, item: object, followed: bool) -> None:
        if self.filter.followed_only:
            self.load()
        else:
            item.followed = followed


class MixshowFollowedController(RemoteListController):
    item_type = MixshowItem
    list_selector = "#mixshows-list"
    list_type = MixshowList
    initial = ListFilter.default(
        sorts=(
            ("default", "Default", MixshowSort.DEFAULT),
            ("popular", "Popular", MixshowSort.POPULAR),
        ),
        statuses=(("live_now", "Live now", MediaStatus.LIVE_NOW),),
        followed_label="Followed mixshows",
    )

    def load(self) -> None:
        self._list().apply_statuses(self.app._statuses_by_show)
        super().load()

    def _load_kwargs(self) -> dict[str, object]:
        return {"status_filter": set(self.filter.status)} if self.filter.status else {}

    def live_show_id(self, item: object) -> int | None:
        return item.show.id if isinstance(item, MixshowItem) else None

    async def update_remote(
        self, item: object, followed: bool, user_id: int, network: str
    ) -> None:
        api = self.app.client.network(network).mixshows
        if followed:
            await api.follow(user_id, item.show.id)
        else:
            await api.unfollow(user_id, item.show.id)


class PlaylistFollowedController(RemoteListController):
    item_type = PlaylistItem
    list_selector = "#playlists-list"
    list_type = PlaylistList
    initial = ListFilter.default(
        sorts=(
            ("popular", "Popular", PlaylistSort.POPULAR),
            ("newest", "Newest", PlaylistSort.NEWEST),
        ),
    )

    def followed(self, item: object) -> bool | None:
        return None  # the SDK has no follow/unfollow for playlists; the Followed filter still works

    async def update_remote(
        self, item: object, followed: bool, user_id: int, network: str
    ) -> None:
        raise NotImplementedError("playlists cannot be followed from the CLI")


class TracksController(RemoteListController):
    """Tracks tab: liked tracks by default, History as a placeholder view.

    The View group switches between them. Tracks cannot be followed; the list
    is the user's own, so it loads only once someone is logged in.
    """

    item_type = TrackItem
    list_selector = "#tracks-list"
    list_type = TrackList
    initial = ListFilter.default(
        sorts=(
            ("liked", "Liked tracks", TracksView.LIKED),
            ("history", "History", TracksView.HISTORY),
        ),
        followed_label=None,
        sort_title="View",
    )

    def followed(self, item: object) -> bool | None:
        return None

    @property
    def searchable(self) -> bool:
        return self.filter.sort != TracksView.HISTORY

    def load(self) -> None:
        if self.filter.sort == TracksView.HISTORY:
            self._list().reset()  # the placeholder is drawn by SearchService
        elif self.app.user_id is not None:
            super().load()

    async def apply_update(self, item: object, followed: bool) -> None:
        raise NotImplementedError("tracks cannot be followed")

    async def update_remote(
        self, item: object, followed: bool, user_id: int, network: str
    ) -> None:
        raise NotImplementedError("tracks cannot be followed")
