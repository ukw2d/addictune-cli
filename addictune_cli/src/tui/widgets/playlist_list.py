from addictune_sdk import Client
from addictune_sdk.models.playlist import Playlist
from textual.message import Message

from ..types import PlaylistSort
from .media_list import ListSpec, MediaList, ModelItem, matches_query, normalize_query


class PlaylistItem(ModelItem):
    def __init__(self, playlist: Playlist) -> None:
        super().__init__(playlist, PlaylistList.spec)

    @property
    def playlist(self) -> Playlist:
        return self.model


class PlaylistList(MediaList):
    class PlaylistSelected(Message):
        def __init__(self, playlist: Playlist) -> None:
            self.playlist = playlist
            super().__init__()

    item_type = PlaylistItem
    spec = ListSpec(
        label=lambda p: p.name,
        model_id=lambda p: p.id,
        message=lambda m: PlaylistList.PlaylistSelected(m),
        # The SDK cannot follow/unfollow playlists; the Followed filter still works.
    )

    def load(
        self,
        client: Client,
        network: str,
        *,
        user_id: int | None = None,
        followed_only: bool = False,
        sort: PlaylistSort = PlaylistSort.POPULAR,
        search_query: str = "",
    ) -> None:
        api = client.network(network).playlists
        if followed_only:
            key, playlists = "followed", api.iter_followed(user_id)
        else:
            key, order = (
                ("newest", "newest")
                if sort == PlaylistSort.NEWEST
                else ("popular", "popularity")
            )
            playlists = api.iter_playlists(order_by=order)
        if query := normalize_query(search_query):
            key += f"|search={query}"
        self.show(key, self._filtered(playlists, search_query))

    async def _filtered(self, playlists, search_query: str):
        async for playlist in playlists:
            if not search_query or matches_query(playlist.name, search_query):
                yield playlist
