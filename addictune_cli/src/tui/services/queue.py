"""The one player queue, shared by playlists, mixshow episodes and tracks (D16).

A ``TrackQueue`` is a frozen value: ``next``, ``previous``, ``refill``,
``repositioned`` and ``with_skip_used`` return the next queue instead of
mutating. The app holds the current value and compares identity to drop stale
async results. Channels (live streams) do not use a queue.
"""

from dataclasses import dataclass
from typing import Literal

from ..types import ContentType

Kind = Literal["mixshow", "playlist", "track"]
_CONTENT_TYPE = {
    "mixshow": ContentType.MIXSHOW,
    "playlist": ContentType.PLAYLIST,
    "track": ContentType.TRACK,
}


def track_id_of(item) -> int | None:
    """Playable track id of a queue item: episode -> first track, LikedTrack -> track_id, Track -> id."""
    if hasattr(item, "tracks"):  # episode: its first track, or nothing to play
        return item.tracks[0].id if item.tracks else None
    return getattr(item, "track_id", None) or getattr(item, "id", None)


@dataclass(frozen=True, slots=True)
class TrackQueue:
    kind: Kind
    source_id: int  # show id, playlist id, or the selected track id
    network: str
    name: str
    items: tuple
    index: int = 0
    skip_used: bool = False  # playlists: one manual skip past the window

    # -- constructors ---------------------------------------------------------

    @classmethod
    def playlist(
        cls, playlist_id: int, network: str, name: str, tracks: tuple
    ) -> "TrackQueue":
        return cls("playlist", playlist_id, network, name, tracks)

    @classmethod
    def mixshow(
        cls, show_id: int, network: str, name: str, episodes: tuple, *, start_id: int
    ) -> "TrackQueue":
        index = next((i for i, e in enumerate(episodes) if e.id == start_id), 0)
        return cls("mixshow", show_id, network, name, episodes, index)

    @classmethod
    def tracks(cls, network: str, tracks: tuple, *, start_id: int) -> "TrackQueue":
        index = next((i for i, t in enumerate(tracks) if track_id_of(t) == start_id), 0)
        return cls("track", start_id, network, "Tracks", tracks, index)

    # -- queries --------------------------------------------------------------

    @property
    def current(self):
        return self.items[self.index]

    @property
    def current_track_id(self) -> int | None:
        return track_id_of(self.current)

    @property
    def content_type(self) -> ContentType:
        return _CONTENT_TYPE[self.kind]

    @property
    def has_more(self) -> bool:
        return self.index < len(self.items) - 1

    @property
    def has_previous(self) -> bool:
        return self.index > 0

    def same_tracks(self, tracks: tuple) -> bool:
        return [track_id_of(t) for t in tracks] == [track_id_of(t) for t in self.items]

    # -- transitions (each returns the next value) ----------------------------

    def next(self) -> "TrackQueue":
        return self._at(self.index + 1) if self.has_more else self

    def previous(self) -> "TrackQueue":
        return self._at(self.index - 1) if self.has_previous else self

    def refill(self, items: tuple) -> "TrackQueue":
        """A fresh window from the server: restart at its first item.

        ``skip_used`` carries over: it records that the window boundary was
        crossed by a manual skip, and resets only when a window ends naturally.
        """
        return TrackQueue(
            self.kind, self.source_id, self.network, self.name, items, 0, self.skip_used
        )

    def repositioned(self, items: tuple) -> "TrackQueue":
        """The list reloaded a bigger page: keep playing the same track inside it."""
        current = self.current_track_id
        index = next(
            (i for i, t in enumerate(items) if track_id_of(t) == current), self.index
        )
        return TrackQueue(
            self.kind,
            self.source_id,
            self.network,
            self.name,
            items,
            index,
            self.skip_used,
        )

    def with_skip_used(self, used: bool) -> "TrackQueue":
        return TrackQueue(
            self.kind,
            self.source_id,
            self.network,
            self.name,
            self.items,
            self.index,
            used,
        )

    def _at(self, index: int) -> "TrackQueue":
        return TrackQueue(
            self.kind,
            self.source_id,
            self.network,
            self.name,
            self.items,
            index,
            self.skip_used,
        )
