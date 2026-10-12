"""Turn the live ICY title into what the bar shows for a channel.

The stream's in-band title is the only timely "now" signal. The channel
routine enriches it (track id for voting, length, position, artwork) and the
show schedule overlays the airing live show. ``resolve`` is pure: the caller
owns fetching and knows whether the title changed.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from addictune_sdk.models.common import ImageSet
from addictune_sdk.models.mixshow import ShowEpisode
from addictune_sdk.models.track import ChannelTracklist, RoutineTrack

from .live_shows import UPCOMING_WINDOW
from ..utils import normalize_title, parse_iso_datetime
from ..widgets.media_info import media_image_url


@dataclass(frozen=True, slots=True)
class LiveInfo:
    track_id: int | None = None
    length: int | None = None
    offset: int | None = None
    image_url: str | None = None
    show_id: int | None = None
    show_name: str = ""
    next_show: str = ""


class LiveResolver:
    def __init__(
        self,
        *,
        routine: ChannelTracklist | None,
        live_episode: ShowEpisode | None,
        next_episode: ShowEpisode | None,
        channel_images: ImageSet | None = None,
    ) -> None:
        self._routine = routine
        self._live = live_episode if _on_air(live_episode) else None
        self._next = next_episode
        self._channel_images = channel_images

    def resolve(self, icy_title: str | None) -> LiveInfo:
        title = icy_title or ""
        track = self._routine_track(title)
        live = self._live
        if live is None and _on_air(self._next):
            live, self._next = self._next, None  # the poll has not caught up yet
        if live is not None and (track is None or _in_tracklist(live, title)):
            return self._from_show(live)
        if track is not None:
            return LiveInfo(
                track_id=track.id,
                length=int(track.content_length or track.length or 0) or None,
                offset=track.offset,
                image_url=media_image_url(track.images, size=200),
                next_show=self._next_show(),
            )
        return LiveInfo(next_show=self._next_show())

    def _next_show(self, airing_until: datetime | None = None) -> str:
        """ "Next: X" when the next show is UPCOMING in the list's sense (starts
        within the window) or, during a live show, starts before that show ends."""
        start = parse_iso_datetime(self._next.start_at) if self._next else None
        if self._next is None or self._next.show is None or start is None:
            return ""
        limit = datetime.now(UTC) + UPCOMING_WINDOW
        if airing_until is not None:
            limit = max(limit, airing_until)
        return f"Next: {self._next.show.name}" if start <= limit else ""

    def _routine_track(self, title: str) -> RoutineTrack | None:
        if not title or self._routine is None:
            return None
        key = normalize_title(title)
        return next(
            (
                t
                for t in self._routine.tracks
                if normalize_title(f"{t.display_artist} - {t.display_title or t.title}")
                == key
            ),
            None,
        )

    def _from_show(self, episode: ShowEpisode) -> LiveInfo:
        start = parse_iso_datetime(episode.start_at)
        end = parse_iso_datetime(episode.end_at)
        length = int((end - start).total_seconds()) if start and end else None
        offset = int((datetime.now(UTC) - start).total_seconds()) if start else None
        first = episode.tracks[0] if episode.tracks else None
        show = episode.show
        return LiveInfo(
            track_id=first.id if first else None,
            length=length,
            offset=offset,
            image_url=media_image_url(
                first.images if first else None,
                show.images if show else None,
                self._channel_images,
                size=200,
            ),
            show_id=show.id if show else None,
            show_name=show.name if show else "",
            next_show=self._next_show(end),
        )


def _in_tracklist(episode: ShowEpisode, title: str) -> bool:
    key = normalize_title(title)
    return any(
        normalize_title(f"{t.display_artist} - {t.display_title or t.title}") == key
        for t in episode.tracks
    )


def _on_air(episode: ShowEpisode | None) -> bool:
    if episode is None:
        return False
    start = parse_iso_datetime(episode.start_at)
    end = parse_iso_datetime(episode.end_at)
    now = datetime.now(UTC)
    return start is not None and start <= now and (end is None or now < end)
