import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from addictune_sdk.models.mixshow import MixShow, ShowChannel, ShowEpisode

from addictune_cli.src.tui.services.live_shows import get_live_show_statuses


def _iso(value: datetime) -> str:
    return value.isoformat()


def _show(show_id: int, channel_id: int = 1, *, image: str | None = None) -> MixShow:
    return MixShow(
        id=show_id,
        name=f"Show {show_id}",
        slug=f"show-{show_id}",
        channels=[ShowChannel(id=channel_id, name="Progressive", key="progressive")],
        images={"square": image} if image else None,
    )


def _episode(
    episode_id: int,
    show: MixShow,
    *,
    start: datetime,
    end: datetime,
    tracks: list[dict] | None = None,
) -> ShowEpisode:
    return ShowEpisode(
        id=episode_id,
        name=f"Episode {episode_id}",
        show_id=show.id,
        show=show,
        start_at=_iso(start),
        end_at=_iso(end),
        tracks=tracks or [],
    )


class _Mixshows:
    def __init__(self, episodes: list[ShowEpisode]) -> None:
        self._episodes = episodes

    async def get_upcoming(self, limit: int = 24) -> list[ShowEpisode]:
        return self._episodes[:limit]


class _Client:
    def __init__(self, episodes: list[ShowEpisode]) -> None:
        self._mixshows = _Mixshows(episodes)

    def network(self, _network: str):
        return SimpleNamespace(mixshows=self._mixshows)


class LiveShowStatusSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_adjacent_show_start_wins_at_boundary(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        previous = _episode(
            10,
            _show(10),
            start=now - timedelta(hours=1),
            end=now,
        )
        current = _episode(
            20,
            _show(20),
            start=now,
            end=now + timedelta(hours=1),
        )

        live_by_channel, _, _ = await get_live_show_statuses(
            _Client([previous, current]), "di"
        )

        self.assertEqual(live_by_channel[1].episode.id, 20)

    async def test_overlapping_live_shows_prefer_latest_start(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        older = _episode(
            10,
            _show(10),
            start=now - timedelta(minutes=50),
            end=now + timedelta(minutes=10),
        )
        newer = _episode(
            20,
            _show(20),
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=55),
        )

        live_by_channel, _, _ = await get_live_show_statuses(
            _Client([older, newer]), "di"
        )

        self.assertEqual(live_by_channel[1].episode.id, 20)

    async def test_retains_the_earliest_future_show_per_channel(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        later = _episode(
            30,
            _show(30),
            start=now + timedelta(hours=2),
            end=now + timedelta(hours=3),
        )
        next_episode = _episode(
            20,
            _show(20),
            start=now + timedelta(minutes=30),
            end=now + timedelta(hours=1, minutes=30),
        )

        _, _, next_by_channel = await get_live_show_statuses(
            _Client([later, next_episode]), "di"
        )

        self.assertEqual(next_by_channel[1].id, 20)


if __name__ == "__main__":
    unittest.main()
