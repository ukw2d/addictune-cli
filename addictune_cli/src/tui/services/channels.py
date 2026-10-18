"""Channels: loading, rendering, live statuses, and the playing channel's live info.

The live stream's ICY title is the "now" signal; ``LiveTracker`` enriches it
from the channel routine (track id, length, position, artwork) and overlays the
airing show from the schedule, through ``LiveResolver``.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from addictune_sdk import AddictuneError, Client
from textual.widgets import Tabs
from textual.worker import get_current_worker

from ...audio.state import State
from .following import ChannelFollowedController
from ...auth import is_auth_failure
from ..routine_cache import RoutineCache
from ..types import ChannelView, MediaStatus, MediaStatusState
from ..widgets.channel_list import ChannelItem, ChannelList
from ..widgets.mixshow_list import MixshowList
from ..widgets.playback_bar import PlaybackBar
from ..widgets.playlist_list import PlaylistList
from ..widgets.track_list import TrackList
from .features import NONE
from .live_resolver import LiveInfo, LiveResolver
from .live_status import LiveStatuses, LiveStatusPoller

if TYPE_CHECKING:
    from ..app import AddictuneApp

_log = logging.getLogger("addictune_cli.channels")


async def get_channel_views(
    client: Client, network: str, user_id: int | None
) -> list[ChannelView]:
    """Every channel of *network*, flagged with the user's favourites when known."""
    api = client.network(network).channels
    if user_id is None:
        channels, favorites = await api.get_all(), []
    else:
        channels, favorites = await asyncio.gather(
            api.get_all(), api.get_favorites(user_id)
        )
    favorite_ids = {favorite.channel_id for favorite in favorites}
    return [
        ChannelView(channel=channel, favorite=channel.id in favorite_ids)
        for channel in channels
    ]


class ChannelsService:
    def __init__(self, app: "AddictuneApp") -> None:
        self.app = app
        self.poller = LiveStatusPoller(app, self._on_statuses)
        self.live = LiveTracker(app)

    # ── Reactive watcher body ────────────────────────────────────

    async def watch_network(self) -> None:
        await self.reset_views()
        self.app.load_channels()

    async def reset_views(self) -> None:
        """Empty every list and per-network cache; the caller reloads."""
        app = self.app
        tabs = app.query_one(Tabs)
        if tabs.active != "channels":
            tabs.active = "channels"
        app._feature_availability = app._feature_cache.get(app.network) or NONE
        app._channels = []
        app._statuses_by_channel = {}
        app._statuses_by_show = {}
        app._live_by_channel = {}
        app._now_playing_by_channel = {}
        app._next_show_by_channel = {}
        controller = app._followed_controllers["channels"]
        assert isinstance(controller, ChannelFollowedController)
        controller.clear_sort_cache()
        channel_list = app.query_one("#channel-list", ChannelList)
        await channel_list.clear()
        app.query_one("#mixshows-list", MixshowList).reset()
        app.query_one("#playlists-list", PlaylistList).reset()
        app.query_one("#tracks-list", TrackList).reset()
        app._sync_feature_tabs()

    # ── @work body ───────────────────────────────────────────────

    async def load_channels_body(self, _reauth: bool = True) -> None:
        """Body of the @work-decorated AddictuneApp.load_channels."""
        app = self.app
        worker = get_current_worker()
        _log.info(
            "load_channels start network=%r user_id=%s reauth=%s",
            app.network,
            app.user_id,
            _reauth,
        )
        channel_list = app.query_one("#channel-list", ChannelList)
        channel_list.loading = True
        self.poller.start()
        # channel_list.loading is cleared exactly once, here, on every exit
        # path (early return, exception, or normal completion) rather than
        # at each individual return statement below -- a future failure path
        # added inside this try can't forget to clear it.
        try:
            if not await app.ensure_authenticated_session(app.network):
                return
            try:
                app.refresh_feature_availability()
                channels = await get_channel_views(app.client, app.network, app.user_id)
                _log.info(
                    "load_channels fetched %d channels for network=%r",
                    len(channels),
                    app.network,
                )
            except AddictuneError as exc:
                _log.error(
                    "load_channels error network=%r reauth=%s: %s",
                    app.network,
                    _reauth,
                    exc,
                )
                # A dead session key surfaces here on startup. Try to recover
                # once from stored credentials; recover_auth prompts for
                # login on failure.
                if (
                    _reauth
                    and is_auth_failure(exc)
                    and await app.recover_auth(app.network)
                ):
                    app.load_channels(_reauth=False)
                return
            if worker.is_cancelled:
                return
            app._channels = channels
            controller = app._followed_controllers["channels"]
            assert isinstance(controller, ChannelFollowedController)
            await controller.prepare_sort()
            if worker.is_cancelled:
                return
            await self._render_channel_list()
        finally:
            channel_list.loading = False

    # ── Rendering ────────────────────────────────────────────────

    async def _render_channel_list(self) -> None:
        app = self.app
        channel_list = app.query_one("#channel-list", ChannelList)
        selected = app._list_item("#channel-list", ChannelList)
        selected_channel_id = (
            selected.channel.id if isinstance(selected, ChannelItem) else None
        )
        visible_channels = self._visible_channels()
        await channel_list.clear()
        await channel_list.extend(ChannelItem(c) for c in visible_channels)
        if selected_channel_id is not None:
            index = next(
                (
                    i
                    for i, channel in enumerate(visible_channels)
                    if channel.channel.id == selected_channel_id
                ),
                None,
            )
            if index is not None:
                channel_list.index = index
        channel_list.apply_statuses(app._statuses_by_channel)
        app._playback_service._notify_playback_changed()
        app._search.sync_empty_results()
        app._search.sync_filter_bar()

    def _visible_channels(self) -> list[ChannelView]:
        app = self.app
        controller = app._followed_controllers["channels"]
        assert isinstance(controller, ChannelFollowedController)
        return controller.visible_channels(app._channels)

    # ── Live statuses (schedule poll) ────────────────────────────

    def _channel_status(self, channel_id: int) -> MediaStatusState | None:
        app = self.app
        return app._live_by_channel.get(channel_id) or app._now_playing_by_channel.get(
            channel_id
        )

    def _rebuild_channel_statuses(self) -> None:
        app = self.app
        channel_ids = set(app._now_playing_by_channel) | set(app._live_by_channel)
        app._statuses_by_channel = {
            channel_id: state
            for channel_id in channel_ids
            if (state := self._channel_status(channel_id)) is not None
        }

    async def _on_statuses(self, message: LiveStatuses) -> None:
        app = self.app
        app._live_by_channel = message.live_by_channel
        app._now_playing_by_channel = message.now_playing_by_channel
        app._statuses_by_show = message.statuses_by_show
        app._next_show_by_channel = message.next_show_by_channel
        self._rebuild_channel_statuses()
        channel_controller = app._followed_controllers["channels"]
        assert isinstance(channel_controller, ChannelFollowedController)
        if channel_controller.filter.status:
            await self._render_channel_list()
        else:
            app.query_one("#channel-list", ChannelList).apply_statuses(
                app._statuses_by_channel
            )
        mixshow_list = app.query_one("#mixshows-list", MixshowList)
        mixshow_list.apply_statuses(message.statuses_by_show)
        mixshow_controller = app._followed_controllers["mixshows"]
        if mixshow_controller.filter.status:
            mixshow_controller.load()
        self.live.resync()
        app._media_info.refresh_live_show_media_info()


class LiveTracker:
    """Live info for the channel that is playing.

    Owns the routine fetch (cached) and applies ``LiveInfo`` to the bar. Three
    entry points: ``start`` on play, ``title_changed`` on each ICY title,
    ``resync`` after a schedule poll. ``stop`` on leaving the channel.
    """

    def __init__(self, app: "AddictuneApp") -> None:
        self.app = app
        self._cache = RoutineCache()
        self._routine = None
        self._key: tuple[str, int] | None = None
        self._refetched_for: str | None = None
        self._fetching = False

    def start(self) -> None:
        app = self.app
        channel_id = app._playing_channel_id
        if channel_id is None:
            return
        key = (app.network, channel_id)
        if key != self._key:
            self._key = key
            self._routine = self._cache.get(*key)
            self._refetched_for = None
            self._fetching = False
        if self._routine is None:
            self._start_fetch()
        self._apply(new_track=False)

    def stop(self) -> None:
        self._key = None
        self._routine = None
        self._fetching = False

    def title_changed(self, title: str) -> None:
        if self._key is None:
            return
        info = self._apply(new_track=True)
        if (
            info is not None
            and info.track_id is None
            and info.show_id is None
            and self._refetched_for != title
        ):
            # Unknown title: the routine has probably rolled over; refetch once.
            self._refetched_for = title
            self._start_fetch()

    def resync(self) -> None:
        if self._key is not None:
            self._apply(new_track=False)

    def _start_fetch(self) -> None:
        if self._fetching or self._key is None:
            return
        self._fetching = True
        self.app.run_worker(self._fetch(self._key), exclusive=True, group="routine")

    async def _fetch(self, key: tuple[str, int]) -> None:
        worker = get_current_worker()
        network, channel_id = key
        client = self.app.client
        try:
            routine = await client.network(network).channels.get_routine(
                channel_id, audio_token=client.listen_key, tune_in=True
            )
        except Exception as exc:
            _log.warning("routine fetch failed: %r", exc)
            return
        finally:
            if key == self._key and not worker.is_cancelled:
                self._fetching = False
        if key != self._key or worker.is_cancelled:
            return
        self._cache.put(network, channel_id, routine)
        self._routine = routine
        self._apply(new_track=False, seed_offset=True)

    def _apply(self, *, new_track: bool, seed_offset: bool = False) -> LiveInfo | None:
        app = self.app
        bar = app.query_one(PlaybackBar)
        channel_id = self._key[1] if self._key else None
        if channel_id is None or bar.state == State.STOPPED:
            return None
        scheduled = app._live_by_channel.get(channel_id)
        resolver = LiveResolver(
            routine=self._routine,
            live_episode=scheduled.episode
            if scheduled and scheduled.status == MediaStatus.LIVE_NOW
            else None,
            next_episode=app._next_show_by_channel.get(channel_id),
            channel_images=self._channel_images(channel_id),
        )
        info = resolver.resolve(bar.icy_title)
        _log.debug(
            "live %r -> track=%s show=%s", bar.icy_title, info.track_id, info.show_id
        )
        bar.apply_live(info, new_track=new_track, seed_offset=seed_offset)
        return info

    def _channel_images(self, channel_id: int):
        return next(
            (
                v.channel.images
                for v in self.app._channels
                if v.channel.id == channel_id
            ),
            None,
        )
