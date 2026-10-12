"""Playback — track-queue playback, selection handlers, and playback controls.

Reaches app state via self.app.* (network, client, content_type, track_queue,
playing_episode_id, _playing_channel_id). Module helpers (_PLAYBACK_SOURCES)
live here; TrackQueue lives in services/queue.

@work-decorated entry points (play_latest_mixshow_episode, play_playlist,
play_track_queue_item, load_next_playlist_window) stay on AddictuneApp as
@work shells (only Widget/App can host workers); their bodies delegate here.
All message handlers and action_* methods also keep thin shells on the app.
"""

import logging
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING

from addictune_sdk import Client
from addictune_sdk.models.mixshow import ShowEpisode
from addictune_sdk.models.playlist import Playlist
from textual.css.query import NoMatches
from textual.worker import get_current_worker

from ...audio.state import State
from ..presentation import (
    NO_TRACKS_AVAILABLE,
    PLAYLIST_NO_NEW_TRACKS,
    PLAYLIST_SKIP_UNAVAILABLE,
)
from ..screens.episodes import EpisodesScreen
from ..types import ContentType
from ..utils import format_artist_title
from .queue import TrackQueue, track_id_of
from ..utils import mark_playing
from ..widgets.channel_list import ChannelItem, ChannelList
from ..widgets.media_info import media_image_url
from ..widgets.mixshow_list import MixshowItem, MixshowList
from ..widgets.playback_bar import PlaybackBar
from ..widgets.playlist_list import PlaylistItem, PlaylistList
from ..widgets.track_list import TrackItem, TrackList

if TYPE_CHECKING:
    from ..app import AddictuneApp

_log = logging.getLogger("addictune_cli.playback")


@dataclass(frozen=True)
class TrackPlaybackInfo:
    url: str | None
    title: str
    image_url: str | None = None


async def get_track_playback_info(
    client: Client,
    network: str,
    track_id: int,
) -> TrackPlaybackInfo:
    track = await client.network(network).tracks.get_by_id(track_id)
    url = track.url
    # Only a bare ``listen_key`` placeholder needs the key; a signed URL
    # (audio_token/auth) breaks if any parameter is added.
    if url and "listen_key" in url and client.listen_key:
        url = client.with_listen_key(url)
    return TrackPlaybackInfo(
        url,
        format_artist_title(track.display_artist, track.title),
        media_image_url(track.images, size=200),
    )


@dataclass(frozen=True)
class EpisodePlaybackInfo:
    url: str | None
    title: str
    track_id: int | None
    image_url: str | None = None


async def get_episode_playback_info(
    client: Client,
    network: str,
    episode: ShowEpisode,
) -> EpisodePlaybackInfo | None:
    if not episode.tracks:
        return None

    track_id = episode.tracks[0].id
    info = await get_track_playback_info(client, network, track_id)
    return EpisodePlaybackInfo(
        url=info.url,
        title=info.title,
        track_id=track_id,
        image_url=info.image_url,
    )


# (selector, list_type, item_type, kind, item_id_getter) for each playback source.
# kind is the TrackQueue.kind that drives playback for this list, or "channel"
# for live radio (which bypasses the queue and sets _playing_channel_id directly).
_PLAYBACK_SOURCES = (
    (
        "#channel-list",
        ChannelList,
        ChannelItem,
        "channel",
        lambda item: item.channel.id,
    ),
    ("#mixshows-list", MixshowList, MixshowItem, "mixshow", lambda item: item.show.id),
    (
        "#playlists-list",
        PlaylistList,
        PlaylistItem,
        "playlist",
        lambda item: item.playlist.id,
    ),
    ("#tracks-list", TrackList, TrackItem, "track", lambda item: item.track_id),
)


class PlaybackService:
    def __init__(self, app: "AddictuneApp") -> None:
        self.app = app
        self._playlist_sessions: dict[tuple[str, int], TrackQueue] = {}
        self._pending_playlist: tuple[str, int] | None = None
        self._pending_track_next: TrackQueue | None = None  # waiting for a page

    # ── Playback bar accessor ────────────────────────────────────

    def _playback_bar(self) -> PlaybackBar:
        return self.app.query_one("#playback-bar", PlaybackBar)

    # ── Playback source ──────────────────────────────────────────

    def _set_source(
        self,
        *,
        channel_id: int | None = None,
        queue: TrackQueue | None = None,
        episode_id: int | None = None,
    ) -> None:
        """Point playback at a live channel or at a track queue — never both.

        Live radio bypasses the queue (it has no item list), so "what is
        playing" lives in two fields that are mutually exclusive. Routing every
        change through here means neither call site can set one and forget to
        clear the other.
        """
        app = self.app
        assert channel_id is None or queue is None, "a source is a channel or a queue"
        current = app.track_queue
        if current is not None and current.kind == "playlist":
            self._playlist_sessions[(current.network, current.source_id)] = current
        app.track_queue = queue
        if queue is not None and queue.kind == "playlist":
            self._playlist_sessions.pop((queue.network, queue.source_id), None)
        app.playing_episode_id = episode_id
        app._playing_channel_id = channel_id
        if channel_id is None:
            app._channels_service.live.stop()

    # ── Selection handlers ───────────────────────────────────────

    def on_channel_list_channel_selected(
        self, msg: ChannelList.ChannelSelected
    ) -> None:
        app = self.app
        msg.stop()
        channel = msg.channel
        if not app.client.listen_key:
            return
        self._set_source(channel_id=channel.id)
        url = app.client.network(app.network).channels.get_stream_url(
            channel.key, app.client.listen_key
        )
        message = (
            f"channel selected id={channel.id} key={channel.key!r} "
            f"name={channel.name!r} network={app.network}"
        )
        _log.info(message)
        app.content_type = ContentType.LIVE
        self._playback_bar().channel_name = channel.name
        self._playback_bar().play(url, title=channel.name)
        app._channels_service.live.start()
        self._notify_playback_changed()

    def on_mixshow_list_show_selected(self, msg: MixshowList.ShowSelected) -> None:
        msg.stop()
        self.app.push_screen(EpisodesScreen(msg.show, self.app.network))

    def on_playlist_list_playlist_selected(
        self, msg: PlaylistList.PlaylistSelected
    ) -> None:
        msg.stop()
        key = (self.app.network, msg.playlist.id)
        if self._pending_playlist == key:
            return
        self._pending_playlist = key
        self.app.play_playlist(msg.playlist, self.app.network)
        self._notify_playback_changed()

    def on_track_list_track_selected(self, msg: TrackList.TrackSelected) -> None:
        msg.stop()
        self.play_track(msg.track, self.app.network)
        self._notify_playback_changed()

    # ── Episode playback ─────────────────────────────────────────

    def play_episode(
        self,
        episode,
        show,
        network: str,
        episodes: tuple[ShowEpisode, ...] | None = None,
    ) -> None:
        app = self.app
        if not episode.tracks:
            app.notify(NO_TRACKS_AVAILABLE, severity="warning")
            return
        episodes = episodes or (episode,)
        queue = TrackQueue.mixshow(
            show.id, network, show.name, episodes, start_id=episode.id
        )
        self._start_queue(queue, episode_id=episode.id)

    async def play_latest_mixshow_episode_body(self, show, network: str) -> None:
        """Body of the @work-decorated AddictuneApp.play_latest_mixshow_episode."""
        app = self.app
        worker = get_current_worker()
        async for episode in app.client.network(network).mixshows.iter_episodes(
            show.id
        ):
            if worker.is_cancelled or network != app.network:
                return
            if not episode.tracks:
                continue
            self.play_episode(episode, show, network)
            return
        app.notify(NO_TRACKS_AVAILABLE, severity="warning")

    # ── Playlist playback ────────────────────────────────────────

    async def play_playlist_body(self, playlist: Playlist, network: str) -> None:
        """Body of the @work-decorated AddictuneApp.play_playlist."""
        app = self.app
        worker = get_current_worker()
        key = (network, playlist.id)
        try:
            current = app.track_queue
            if (
                current is not None
                and current.kind == "playlist"
                and (current.network, current.source_id) == key
            ):
                if self._playback_bar().state == State.STOPPED:
                    app.play_track_queue_item(current)
                return
            if cached := self._playlist_sessions.get(key):
                self._start_queue(cached)
                return
            content = await app.client.network(network).playlists.get_content(
                playlist.id
            )
            if worker.is_cancelled or network != app.network:
                return
            if not content.tracks:
                app.notify(NO_TRACKS_AVAILABLE, severity="warning")
                return
            self._start_queue(
                TrackQueue.playlist(
                    playlist.id, network, playlist.name, tuple(content.tracks)
                )
            )
        finally:
            if self._pending_playlist == key:
                self._pending_playlist = None

    def play_track(self, track, network: str) -> None:
        app = self.app
        track_id = track_id_of(track)
        if track_id is None:
            app.notify(NO_TRACKS_AVAILABLE, severity="warning")
            return
        self._start_queue(
            TrackQueue.tracks(network, self._track_queue_items(track), start_id=track_id)
        )

    def _track_queue_items(self, selected_track) -> tuple:
        """The loaded Tracks page when it contains the selection, else just the track."""
        app = self.app
        try:
            tracks = app.query_one("#tracks-list", TrackList).loaded_tracks
        except NoMatches:
            tracks = ()
        if tracks and any(track_id_of(t) == track_id_of(selected_track) for t in tracks):
            return tracks
        return (selected_track,)

    def _start_queue(self, queue: TrackQueue, *, episode_id: int | None = None) -> None:
        """Set the active queue, clear live-channel state, and start playback."""
        self._set_source(queue=queue, episode_id=episode_id)
        self._notify_playback_changed()
        self.app.play_track_queue_item(queue)

    async def play_track_queue_item_body(self, queue: TrackQueue) -> None:
        """Body of the @work-decorated AddictuneApp.play_track_queue_item."""
        app = self.app
        worker = get_current_worker()
        track_id = queue.current_track_id
        if track_id is None:
            app.notify(NO_TRACKS_AVAILABLE, severity="warning")
            return
        match queue.kind:
            case "mixshow":
                playback_info = await get_episode_playback_info(
                    app.client, queue.network, queue.current
                )
                if playback_info is None:
                    app.notify(NO_TRACKS_AVAILABLE, severity="warning")
                    return
                resolved_track_id = playback_info.track_id
            case _:
                playback_info = await get_track_playback_info(
                    app.client, queue.network, track_id
                )
                resolved_track_id = track_id
        if worker.is_cancelled or app.track_queue != queue:
            return
        if queue.kind == "mixshow":
            app.playing_episode_id = queue.current.id
        app.content_type = queue.content_type
        bar = self._playback_bar()
        bar.apply_track(
            track_id=resolved_track_id,
            image_url=playback_info.image_url,
        )
        bar.channel_name = queue.name
        bar.play(playback_info.url, title=playback_info.title)

    async def record_playlist_event_body(
        self,
        network: str,
        playlist_id: int,
        track_id: int,
        *,
        skipped: bool,
        length: int | None,
    ) -> None:
        """Best-effort skip telemetry for playlist playback.

        Natural track ends are not reported: the SDK dropped ``add_listen_history``
        in 0.4 (telemetry only, no visible effect).
        """
        if not skipped:
            return
        try:
            await self.app.client.network(network).tracks.skip_track(
                track_id,
                playlist_id=playlist_id,
                skipped_at=int(time()),
                length=length,
            )
        except Exception as exc:
            _log.debug("playlist event failed: %r", exc)

    async def load_next_playlist_window_body(self, queue: TrackQueue) -> None:
        """Body of the @work-decorated AddictuneApp.load_next_playlist_window."""
        app = self.app
        worker = get_current_worker()
        content = await app.client.network(queue.network).playlists.get_content(
            queue.source_id
        )
        if worker.is_cancelled or app.track_queue != queue:
            return
        next_items = tuple(content.tracks)
        if not next_items:
            app.notify(NO_TRACKS_AVAILABLE, severity="warning")
            return
        if queue.same_tracks(next_items):
            app.notify(PLAYLIST_NO_NEW_TRACKS, severity="warning")
            return
        self._play(queue.refill(next_items))

    def load_next_track_page(self, queue: TrackQueue) -> None:
        """Last loaded track reached: use the bigger page if the list has it, else ask for more."""
        app = self.app
        try:
            tracks = app.query_one("#tracks-list", TrackList)
        except NoMatches:
            return
        if tracks.loaded_tracks:
            queue = queue.repositioned(tracks.loaded_tracks)
            app.track_queue = queue
            if queue.has_more:
                self._play(queue.next())
                return
        self._pending_track_next = queue
        if not tracks.request_more():
            self._pending_track_next = None

    def on_track_list_page_loaded(self, _: TrackList.PageLoaded) -> None:
        app = self.app
        pending = self._pending_track_next
        if pending is None or app.track_queue != pending:
            return
        self._pending_track_next = None
        try:
            tracks = app.query_one("#tracks-list", TrackList).loaded_tracks
        except NoMatches:
            return
        queue = pending.repositioned(tracks)
        if queue.has_more:
            self._play(queue.next())

    def _play(self, queue: TrackQueue) -> None:
        """Make *queue* current and start its current item."""
        self.app.track_queue = queue
        self.app.play_track_queue_item(queue)

    # ── Highlight helpers ────────────────────────────────────────

    def _notify_playback_changed(self) -> None:
        """Re-apply playback highlight after any state change affecting which
        row is 'playing' or 'suspended'.

        Single choke point: future sync targets (now-playing widgets, etc.)
        hook in here rather than at every call site.
        """
        self._apply_playback_highlight()

    def _playback_suspended(self) -> bool:
        """Whether the current source is paused or a stopped-but-resumable channel.

        Live radio has no pause, so stopping it leaves the row resumable rather
        than idle — that is what "suspended" means here.
        """
        state = self._playback_bar().state
        return state == State.PAUSED or (
            state == State.STOPPED and self.app._playing_channel_id is not None
        )

    def _apply_playback_highlight(self) -> None:
        app = self.app
        item = self._find_playing_item()
        suspended = self._playback_suspended()
        if suspended:
            mark_playing(app, item, suspended=True)
        else:
            # A queue that ran out is neither playing nor resumable, so it
            # keeps no highlight — unlike a stopped channel, which is suspended.
            stopped = self._playback_bar().state == State.STOPPED
            mark_playing(app, None if stopped else item)
        self._sync_global_search_playback_highlight(suspended)

    def _sync_global_search_playback_highlight(
        self, suspended: bool | None = None
    ) -> None:
        app = self.app
        if suspended is None:
            suspended = self._playback_suspended()
        channel_id = self._playing_id_for("channel")
        show_id = self._playing_id_for("mixshow")
        playlist_id = self._playing_id_for("playlist")
        for screen in app.screen_stack:
            apply_highlight = getattr(screen, "apply_playing_highlight", None)
            if apply_highlight is not None:
                apply_highlight(
                    channel_id=channel_id,
                    show_id=show_id,
                    playlist_id=playlist_id,
                    suspended=suspended,
                )

    def _focus_playing_item_in(self, list_view) -> None:
        """If *list_view* contains the currently-playing row, focus and scroll
        to it.

        Called by MediaList after each page loads so that, e.g., a mixshow
        chosen from global search becomes the focused row whenever the user
        later pages into it — even if it lives on a not-yet-fetched page.
        """
        item = self._find_playing_item(within=list_view)
        if item is None:
            return
        try:
            list_view.index = list_view.children.index(item)
        except ValueError:
            return
        item.scroll_visible()

    def _find_playing_item(self, *, within=None):
        """Find the list row matching the currently-playing source.

        If *within* is given, restrict the search to that ListView instance
        (used by _focus_playing_item_in to scope to the list that just loaded
        a page). Returns the ListItem, or None when no row matches.
        """
        app = self.app
        for selector, list_type, item_type, kind, get_id in _PLAYBACK_SOURCES:
            try:
                lv = app.query_one(selector, list_type)
            except NoMatches:
                continue
            if within is not None and lv is not within:
                continue
            item_id = self._playing_id_for(kind)
            if item_id is None:
                continue
            match = next(
                (
                    c
                    for c in lv.children
                    if isinstance(c, item_type) and get_id(c) == item_id
                ),
                None,
            )
            if match is not None:
                return match
        return None

    def _playing_id_for(self, kind: str) -> int | None:
        """Return the id of the currently-playing item for *kind*.

        Channels bypass the queue (live URLs), so they read
        ``app._playing_channel_id`` directly. Everything else is derived
        from ``app.track_queue``.
        """
        app = self.app
        match kind:
            case "channel":
                return app._playing_channel_id
            case _:
                q = app.track_queue
                if q is None or q.kind != kind:
                    return None
                if q.kind == "track":
                    return q.current_track_id
                return q.source_id

    # ── Playback event handlers ──────────────────────────────────

    def on_playback_bar_state_changed(self, message: PlaybackBar.StateChanged) -> None:
        app = self.app
        if (
            message.state in (State.LOADING, State.PLAYING)
            and app.content_type == ContentType.LIVE
        ):
            app._channels_service.live.start()  # idempotent; re-arms after a stop

        if message.state in (State.PAUSED, State.PLAYING):
            self._notify_playback_changed()
        app.refresh_bindings()

    def on_playback_bar_stopped(self, message: PlaybackBar.Stopped) -> None:
        app = self.app
        queue = app.track_queue
        if message.natural and queue is not None:
            match queue.kind, queue.has_more:
                case ("playlist", _) | ("mixshow", True):
                    self._advance_track(queue, manual=False)
                    return
        app._channels_service.live.stop()
        self._notify_playback_changed()

    # ── Playback actions ─────────────────────────────────────────

    def _play_current(self) -> None:
        bar = self._playback_bar()
        if bar.state == State.PAUSED:
            bar.resume()
            return
        if bar.state == State.STOPPED and bar.current_url:
            bar.play(bar.current_url, title=bar.now_playing)
            self._notify_playback_changed()

    def _pause_current(self) -> None:
        app = self.app
        bar = self._playback_bar()
        if bar.state not in (State.PLAYING, State.LOADING):
            return
        if app.content_type == ContentType.LIVE:
            bar.stop()
        else:
            bar.pause()

    def _toggle_current_playback(self) -> None:
        app = self.app
        bar = self._playback_bar()
        if bar.state == State.STOPPED and not bar.current_url:
            if self._play_selected_mixshow():
                return
        if app.content_type == ContentType.LIVE:
            if bar.state in (State.PLAYING, State.LOADING):
                bar.stop()
            else:
                self._play_current()
            return

        if bar.state == State.PAUSED:
            bar.resume()
        elif bar.state in (State.PLAYING, State.LOADING):
            bar.pause()
        else:
            self._play_current()

    def _play_selected_mixshow(self) -> bool:
        app = self.app
        try:
            item = app._list_item("#mixshows-list", MixshowList)
        except NoMatches:
            return False
        if not isinstance(item, MixshowItem):
            return False
        app.play_latest_mixshow_episode(item.show, app.network)
        return True

    def action_previous_track(self) -> None:
        queue = self.app.track_queue
        if queue is not None and queue.has_previous:
            self._play(queue.previous())

    def action_next_track(self) -> None:
        queue = self.app.track_queue
        if queue is not None:
            self._advance_track(queue, manual=True)

    def _advance_track(self, queue: TrackQueue, *, manual: bool) -> None:
        app = self.app
        match queue.kind:
            case "playlist" if manual and not queue.has_more and queue.skip_used:
                app.notify(PLAYLIST_SKIP_UNAVAILABLE, severity="warning")
                return
            case "playlist":
                self._record_playlist_event(queue, skipped=manual)
        if queue.has_more:
            self._play(queue.next())
            return
        match queue.kind:
            case "playlist":
                next_queue = queue.with_skip_used(manual)
                app.track_queue = next_queue
                app.load_next_playlist_window(next_queue)
            case "track" if manual:
                self.load_next_track_page(queue)

    def _record_playlist_event(self, queue: TrackQueue, *, skipped: bool) -> None:
        track_id = queue.current_track_id
        if track_id is not None:
            self.app.record_playlist_event(
                queue.network,
                queue.source_id,
                track_id,
                skipped=skipped,
                length=self._playback_bar().elapsed_seconds if skipped else None,
            )
