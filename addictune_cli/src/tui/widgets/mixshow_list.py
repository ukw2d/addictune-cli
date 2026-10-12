from addictune_sdk import Client
from addictune_sdk.models.mixshow import MixShow
from textual.message import Message

from ..types import MediaStatus, MixshowSort
from .media_list import ListSpec, MediaList, ModelItem, matches_query, normalize_query


class MixshowItem(ModelItem):
    def __init__(self, show: MixShow) -> None:
        super().__init__(show, MixshowList.spec)

    @property
    def show(self) -> MixShow:
        return self.model


class MixshowList(MediaList):
    class ShowSelected(Message):
        def __init__(self, show: MixShow) -> None:
            self.show = show
            super().__init__()

    item_type = MixshowItem
    spec = ListSpec(
        label=lambda show: show.name,
        model_id=lambda show: show.id,
        message=lambda m: MixshowList.ShowSelected(m),
        followed=lambda show: show.following,
        live_badge=True,
    )

    def load(
        self,
        client: Client,
        network: str,
        *,
        user_id: int | None = None,
        followed_only: bool = False,
        sort: MixshowSort = MixshowSort.DEFAULT,
        search_query: str = "",
        status_filter: set[MediaStatus] | None = None,
    ) -> None:
        api = client.network(network).mixshows
        match followed_only, sort:
            case True, _:
                key, shows = "followed", api.iter_followed(user_id)
            case _, MixshowSort.POPULAR:
                key, shows = "popular", api.iter_popular()
            case _:
                key, shows = "all", api.iter_shows()
        if query := normalize_query(search_query):
            key += f"|search={query}"
        if status_filter:
            # The *set of statuses* is a fetch parameter; which shows currently
            # match is live state checked on every pull, not part of the key.
            key += "|status=" + ",".join(sorted(s.name for s in status_filter))
        self.show(key, self._filtered(shows, search_query, status_filter))

    async def _filtered(
        self, shows, search_query: str, status_filter: set[MediaStatus] | None
    ):
        async for show in shows:
            if search_query and not matches_query(show.name, search_query):
                continue
            if status_filter:
                state = self._statuses.get(show.id)
                if state is None or state.status not in status_filter:
                    continue
            yield show
