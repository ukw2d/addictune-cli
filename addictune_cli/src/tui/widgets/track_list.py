from addictune_sdk import Client
from addictune_sdk.models.track import LikedTrack
from textual.message import Message

from ..types import TracksView
from ..utils import format_artist_title
from .media_list import ListSpec, MediaList, ModelItem, matches_query, normalize_query


def _label(track: LikedTrack) -> str:
    return format_artist_title(track.display_artist, track.display_title or track.title)


class TrackItem(ModelItem):
    def __init__(self, track: LikedTrack) -> None:
        super().__init__(track, TrackList.spec)

    @property
    def track(self) -> LikedTrack:
        return self.model

    @property
    def track_id(self) -> int | None:
        return self.track.track_id or self.track.id


class TrackList(MediaList):
    """The user's liked tracks."""

    class TrackSelected(Message):
        def __init__(self, track: LikedTrack) -> None:
            self.track = track
            super().__init__()

    class PageLoaded(Message):
        """Another page of liked tracks arrived (the queue may continue into it)."""

    item_type = TrackItem
    spec = ListSpec(
        label=_label,
        model_id=lambda t: t.track_id or t.id,
        message=lambda m: TrackList.TrackSelected(m),
    )

    @property
    def loaded_tracks(self) -> tuple[LikedTrack, ...]:
        return self.models

    def _after_page(self, load, page: list) -> None:
        super()._after_page(load, page)
        if page:
            self.post_message(self.PageLoaded())

    def load(
        self,
        client: Client,
        network: str,
        *,
        user_id: int | None = None,
        followed_only: bool = False,
        sort: TracksView = TracksView.LIKED,
        search_query: str = "",
    ) -> None:
        """Liked tracks of *user_id*.

        *followed_only* and *sort* only complete the signature every list shares
        with ``RemoteListController.load``; the History view never gets here
        (``TracksController.load`` resets the list instead).
        """
        if user_id is None:
            raise ValueError("user_id is required for liked tracks")
        key = "liked"
        if query := normalize_query(search_query):
            key += f"|search={query}"
        self.show(
            key,
            self._filtered(
                client.network(network).tracks.iter_liked_tracks(user_id), search_query
            ),
        )

    async def _filtered(self, tracks, search_query: str):
        async for track in tracks:
            if not search_query or matches_query(_label(track), search_query):
                yield track
