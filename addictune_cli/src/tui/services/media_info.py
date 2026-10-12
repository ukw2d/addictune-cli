"""Media info panel — open/close, sync, and mixshow description lazy-load.

The @work-decorated load_mixshow_info entry point stays on AddictuneApp (only
Widget/App can host workers); its body delegates to
MediaInfoService.refresh_mixshow_info.
"""

import logging
from time import monotonic
from typing import TYPE_CHECKING

from addictune_sdk import AddictuneError
from textual.widgets import ListView
from textual.worker import get_current_worker

from ..types import ChannelView
from ..utils import normalize_title
from ..widgets.channel_list import ChannelItem
from ..widgets.media_info import (
    MediaInfo,
    MediaInfoPanel,
    channel_media_info,
    mixshow_media_info,
    playlist_media_info,
)
from ..widgets.mixshow_list import MixshowItem
from ..widgets.playlist_list import PlaylistItem

if TYPE_CHECKING:
    from ..app import AddictuneApp


_RECENT_TRACK_LIMIT = 5
_RECENT_TRACK_REFRESH_SECONDS = 60
_log = logging.getLogger("addictune_cli.media_info")


class MediaInfoService:
    def __init__(self, app: "AddictuneApp") -> None:
        self.app = app
        # Plain dict: freshness is a TTL (_history_is_stale) and there is one
        # entry per channel opened in the info panel.
        self._recent_tracks: dict[tuple[str, int], tuple[float, tuple[str, ...]]] = {}
        self._history_loading: set[tuple[str, int]] = set()

    # ── Event / action handlers ───────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self.sync_media_info(event.item)
        self.app.refresh_bindings()

    def toggle_info(self) -> None:
        info = self.app.query_one(MediaInfoPanel)
        if info.is_open:
            info.close()
            return
        item = self.app._selected_list_item()
        if item is not None:
            self.sync_media_info(item, open_panel=True)

    # ── Sync ──────────────────────────────────────────────────────

    def sync_open_media_info(self) -> None:
        if not self.app.query_one(MediaInfoPanel).is_open:
            return
        item = self.app._selected_list_item()
        if item is not None:
            self.sync_media_info(item)

    def sync_media_info(self, item, *, open_panel: bool = False) -> None:
        info = self.app.query_one(MediaInfoPanel)
        if not open_panel and not info.is_open:
            return
        media_info = self.media_info_from_item(item)
        if media_info is None:
            return
        if open_panel:
            info.open(media_info)
        else:
            info.media = media_info
        if isinstance(item, MixshowItem):
            # load_mixshow_info is a @work on the app; trigger it via the app.
            self.app.load_mixshow_info(item, self.app.network)
        elif isinstance(item, ChannelItem):
            key = (self.app.network, item.channel.id)
            if self._history_is_stale(key) and key not in self._history_loading:
                self._history_loading.add(key)
                self.app.load_channel_history(item.channel.id, self.app.network)

    def refresh_live_show_media_info(self) -> None:
        item = self.app._selected_list_item()
        if isinstance(item, ChannelItem | MixshowItem | PlaylistItem):
            self.sync_media_info(item)

    # ── Builders ──────────────────────────────────────────────────

    def media_info_from_item(self, item) -> MediaInfo | None:
        if isinstance(item, ChannelItem):
            return self._channel_media_info(item.model)
        if isinstance(item, MixshowItem):
            return mixshow_media_info(
                item.show,
                item.followed,
                status=self.app._statuses_by_show.get(item.show.id),
            )
        if isinstance(item, PlaylistItem):
            return playlist_media_info(item.playlist)
        return None

    def _channel_media_info(self, channel_view: ChannelView) -> MediaInfo:
        channel = channel_view.channel
        status = self.app._statuses_by_channel.get(channel.id)
        recent = self._recent_tracks.get((self.app.network, channel.id))
        return channel_media_info(
            channel,
            followed=channel_view.favorite,
            status=status,
            recently_played=_without_current_track(recent[1], status) if recent else (),
        )

    def _history_is_stale(self, key: tuple[str, int]) -> bool:
        cached = self._recent_tracks.get(key)
        return cached is None or monotonic() - cached[0] >= _RECENT_TRACK_REFRESH_SECONDS

    # ── Worker body ───────────────────────────────────────────────

    async def refresh_mixshow_info(self, item: MixshowItem, network: str) -> None:
        """Body of the @work-decorated AddictuneApp.load_mixshow_info."""
        if item.show.description:
            return
        worker = get_current_worker()
        show_id = item.show.id
        show = await self.app.client.network(network).mixshows.get_by_id(show_id)
        if worker.is_cancelled or network != self.app.network:
            return
        item = self.app._selected_list_item()
        if not isinstance(item, MixshowItem) or item.show.id != show_id:
            return
        info = self.app.query_one(MediaInfoPanel)
        if info.is_open:
            info.media = mixshow_media_info(
                show,
                item.followed,
                status=self.app._statuses_by_show.get(show.id),
            )

    async def refresh_channel_history(self, channel_id: int, network: str) -> None:
        """Load recent tracks only for the channel still shown in the open panel."""
        worker = get_current_worker()
        key = (network, channel_id)
        try:
            history = await self.app.client.network(network).channels.get_track_history(
                channel_id
            )
        except AddictuneError as exc:
            _log.debug("track history unavailable for channel_id=%s: %s", channel_id, exc)
            return
        finally:
            self._history_loading.discard(key)
        if worker.is_cancelled or network != self.app.network:
            return
        item = self.app._selected_list_item()
        if not isinstance(item, ChannelItem) or item.channel.id != channel_id:
            return
        info = self.app.query_one(MediaInfoPanel)
        if not info.is_open:
            return
        self._recent_tracks[key] = (monotonic(), _recent_track_labels(history))
        info.media = self._channel_media_info(item.model)


def _recent_track_labels(history) -> tuple[str, ...]:
    """Return a small, readable, duplicate-free list from SDK track history.

    The track_history endpoint includes the currently-playing track as its
    first element, so it is dropped here; ``_without_current_track`` still
    guards against the active track or show reappearing later in the list.
    """
    tracks: list[str] = []
    for entry in history[1:]:
        artist = entry.display_artist or entry.artist
        title = entry.display_title or entry.title
        label = " — ".join(part for part in (artist, title) if part)
        if label and label not in tracks:
            tracks.append(label)
        if len(tracks) == _RECENT_TRACK_LIMIT:
            break
    return tuple(tracks)


def _without_current_track(
    tracks: tuple[str, ...], status
) -> tuple[str, ...]:
    if status is None:
        return tracks
    current_labels = _current_labels(status)
    if not current_labels:
        return tracks
    return tuple(
        track
        for track in tracks
        if normalize_title(track) not in current_labels
    )


def _current_labels(status) -> set[str]:
    labels = set()
    if status.now_playing is not None:
        labels.add(_track_label(*status.now_playing))
    episode = status.episode
    if episode is not None:
        labels.update(
            label
            for label in (
                getattr(episode, "name", None),
                getattr(getattr(episode, "show", None), "name", None),
            )
            if label
        )
    return {normalize_title(label) for label in labels}


def _track_label(artist: str | None, title: str | None) -> str:
    return " — ".join(part for part in (artist, title) if part)
