from datetime import UTC, datetime, timedelta

from addictune_sdk import Client
from addictune_sdk.models.mixshow import ShowEpisode

from ..types import MediaStatus, MediaStatusState
from ..utils import parse_iso_datetime

UPCOMING_WINDOW = timedelta(hours=1)


async def get_channel_now_playing_statuses(
    client: Client, network: str
) -> dict[int, MediaStatusState]:
    entries = await client.network(network).channels.get_currently_playing()
    result: dict[int, MediaStatusState] = {}
    for entry in entries:
        if entry.track is None:
            continue
        t = entry.track
        artist = t.display_artist or t.artist or ""
        title = t.display_title or t.title or ""
        if artist or title:
            result[entry.channel_id] = MediaStatusState(
                MediaStatus.NOW_PLAYING,
                now_playing=(artist, title),
            )
    return result


async def get_live_show_statuses(
    client: Client,
    network: str,
    *,
    limit: int = 24,
) -> tuple[
    dict[int, MediaStatusState],
    dict[int, MediaStatusState],
    dict[int, ShowEpisode],
]:
    episodes = await client.network(network).mixshows.get_upcoming(limit=limit)
    statuses_by_channel: dict[int, MediaStatusState] = {}
    statuses_by_show: dict[int, MediaStatusState] = {}
    next_show_by_channel: dict[int, ShowEpisode] = {}
    now = datetime.now(UTC)
    for episode in episodes:
        show = episode.show
        if show is None:
            continue

        start = parse_iso_datetime(episode.start_at)
        if start is not None and start > now:
            for channel in show.channels:
                current_next = next_show_by_channel.get(channel.id)
                current_start = parse_iso_datetime(
                    current_next.start_at if current_next else None
                )
                if current_start is None or start < current_start:
                    next_show_by_channel[channel.id] = episode

        running = _is_running(episode.start_at, episode.end_at, now)
        has_schedule = episode.start_at is not None and episode.end_at is not None
        if running or (show.now_playing and not has_schedule):
            status = MediaStatus.LIVE_NOW
        else:
            status = _upcoming_status(episode.start_at, now)
        if status is None:
            continue

        state = MediaStatusState(status, episode=episode)
        current_show = statuses_by_show.get(show.id)
        if current_show is None or _status_sort_key(state) < _status_sort_key(
            current_show
        ):
            statuses_by_show[show.id] = state
        for channel in show.channels:
            current = statuses_by_channel.get(channel.id)
            if current is None or _status_sort_key(state) < _status_sort_key(current):
                statuses_by_channel[channel.id] = state
    return statuses_by_channel, statuses_by_show, next_show_by_channel


def _is_running(start_at: str | None, end_at: str | None, now: datetime) -> bool:
    start = parse_iso_datetime(start_at)
    end = parse_iso_datetime(end_at)
    return start is not None and end is not None and start <= now < end


def _upcoming_status(start_at: str | None, now: datetime) -> MediaStatus | None:
    episode_start = parse_iso_datetime(start_at)
    if episode_start is None or not now < episode_start <= now + UPCOMING_WINDOW:
        return None
    return MediaStatus.UPCOMING


def _timestamp(value: str | None, fallback: float) -> float:
    parsed = parse_iso_datetime(value)
    return parsed.timestamp() if parsed is not None else fallback


def _status_sort_key(state: MediaStatusState) -> tuple[int, float]:
    if state.status == MediaStatus.LIVE_NOW:
        return (
            0,
            -_timestamp(
                state.episode.start_at if state.episode else None,
                float("-inf"),
            ),
        )
    return (
        1,
        _timestamp(
            state.episode.start_at if state.episode else None,
            datetime.max.replace(tzinfo=UTC).timestamp(),
        ),
    )
