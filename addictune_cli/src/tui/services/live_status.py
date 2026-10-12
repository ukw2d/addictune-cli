"""Polls the show schedule and channel now-playing for the current network.

One worker, one timer: the next poll runs at the next show start or end, or
after 60 s, whichever is sooner. Results land on the app's per-channel dicts
and are pushed to the lists through ``ChannelsService``.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from addictune_sdk.models.mixshow import ShowEpisode
from textual.timer import Timer

from .live_shows import (
    get_channel_now_playing_statuses,
    get_live_show_statuses,
)
from ..types import MediaStatus, MediaStatusState
from ..utils import next_event_delay, parse_iso_datetime

_log = logging.getLogger("addictune_cli.live_status")
_REFRESH_SECONDS = 60.0


@dataclass(frozen=True)
class LiveStatuses:
    network: str
    live_by_channel: dict[int, MediaStatusState]
    now_playing_by_channel: dict[int, MediaStatusState]
    statuses_by_show: dict[int, MediaStatusState]
    next_show_by_channel: dict[int, ShowEpisode]


def _next_refresh_delay(statuses_by_show: dict[int, MediaStatusState]) -> float:
    events = []
    for state in statuses_by_show.values():
        if state.episode is None:
            continue
        at = (
            state.episode.end_at
            if state.status == MediaStatus.LIVE_NOW
            else state.episode.start_at
            if state.status == MediaStatus.UPCOMING
            else None
        )
        if (t := parse_iso_datetime(at)) is not None:
            events.append(t)
    return next_event_delay(events, max_delay=_REFRESH_SECONDS)


class LiveStatusPoller:
    def __init__(
        self, app, on_update: Callable[[LiveStatuses], Awaitable[None]]
    ) -> None:
        self._app = app
        self._on_update = on_update
        self._timer: Timer | None = None

    def start(self) -> None:
        """(Re)start polling for the app's current network."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._app.run_worker(self._poll(), exclusive=True, group="live-status")

    async def _poll(self) -> None:
        network = self._app.network
        client = self._app.client
        try:
            live, by_show, next_show = await get_live_show_statuses(
                client, network, limit=100
            )
            now_playing = await get_channel_now_playing_statuses(client, network)
        except Exception as exc:
            _log.warning("live status refresh failed: %r", exc)
            self._schedule(_REFRESH_SECONDS)
            return
        if network != self._app.network:
            return
        await self._on_update(
            LiveStatuses(network, live, now_playing, by_show, next_show)
        )
        self._schedule(_next_refresh_delay(by_show))

    def _schedule(self, delay: float) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self._app.set_timer(delay, self.start)
