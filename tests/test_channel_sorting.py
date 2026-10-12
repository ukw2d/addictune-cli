import unittest
from types import SimpleNamespace

from addictune_sdk.models.channel import Channel

from addictune_cli.src.tui.services.following import ChannelFollowedController
from addictune_cli.src.tui.types import (
    ChannelView,
    MediaStatus,
    MediaStatusState,
)


def _channel(channel_id: int, name: str) -> Channel:
    return Channel(id=channel_id, key=name.lower(), name=name, network_id=1)


class _ChannelsApi:
    def __init__(self) -> None:
        self.calls = 0

    async def get_filter(self, key: str):
        self.calls += 1
        return SimpleNamespace(channels=[_channel(2, "Beta"), _channel(1, "Zed")])


class _Client:
    def __init__(self, api: _ChannelsApi) -> None:
        self.api = api

    def network(self, network: str):
        return SimpleNamespace(channels=self.api)


class _App:
    def __init__(self) -> None:
        self.network = "di"
        self.api = _ChannelsApi()
        self.client = _Client(self.api)
        self.renders = 0
        self.user_id = None
        self._live_by_channel = {}
        # Rendering belongs to ChannelsService; the controller reaches it there.
        self._channels_service = SimpleNamespace(
            _render_channel_list=self._render_channel_list
        )

    async def _render_channel_list(self) -> None:
        self.renders += 1


class ChannelSortingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = _App()
        self.controller = ChannelFollowedController(self.app)
        self.channels = [
            ChannelView(_channel(1, "Zed"), favorite=True),
            ChannelView(_channel(2, "Beta")),
            ChannelView(_channel(3, "Alpha"), favorite=True),
        ]

    async def test_alpha_sort_composes_with_favorites_filter(self) -> None:
        self.app.user_id = 1
        await self.controller.apply_option("filter", "followed")
        await self.controller.apply_option("sort", "alpha")

        self.assertEqual(
            [
                item.channel.name
                for item in self.controller.visible_channels(self.channels)
            ],
            ["Alpha", "Zed"],
        )
        self.assertEqual(self.app.api.calls, 0)
        self.assertEqual(
            self.controller.filter.label(), "Filter: Favorites | Sort: A-Z"
        )

    async def test_search_composes_with_filter_and_sort(self) -> None:
        self.app.user_id = 1
        await self.controller.apply_option("filter", "followed")
        await self.controller.set_search("a")
        await self.controller.apply_option("sort", "alpha")

        self.assertEqual(
            [
                item.channel.name
                for item in self.controller.visible_channels(self.channels)
            ],
            ["Alpha"],
        )

    async def test_live_status_filters_can_be_combined(self) -> None:
        self.app._live_by_channel = {
            1: MediaStatusState(MediaStatus.LIVE_NOW),
            2: MediaStatusState(MediaStatus.UPCOMING),
        }

        await self.controller.apply_option("status", "live_now", True)
        self.assertEqual(
            [
                item.channel.name
                for item in self.controller.visible_channels(self.channels)
            ],
            ["Zed"],
        )

        await self.controller.apply_option("status", "upcoming", True)
        self.assertEqual(
            [
                item.channel.name
                for item in self.controller.visible_channels(self.channels)
            ],
            ["Zed", "Beta"],
        )
        self.assertEqual(
            self.controller.filter.label(),
            "Filter: Live now + Upcoming",
        )

    async def test_favorites_require_a_login(self) -> None:
        self.app.user_id = None
        self.app.notify = lambda *a, **k: self.app.__dict__.setdefault(
            "notices", []
        ).append(a[0])

        await self.controller.apply_option("filter", "followed")

        self.assertFalse(self.controller.filter.followed_only)
        self.assertEqual(self.app.renders, 0)
        self.assertEqual(self.app.notices, ["Log in to view favorites."])

    async def test_popular_uses_and_caches_api_order(self) -> None:
        await self.controller.apply_option("sort", "popular")
        await self.controller.apply_option("sort", "popular")  # no-op: same filter

        self.assertEqual(
            [
                item.channel.name
                for item in self.controller.visible_channels(self.channels)
            ],
            ["Beta", "Zed"],
        )
        self.assertEqual(self.app.api.calls, 1)

    async def test_clearing_popular_cache_fetches_for_current_network(self) -> None:
        await self.controller.apply_option("sort", "popular")
        self.controller.clear_sort_cache()
        self.app.network = "rock"

        await self.controller.prepare_sort()

        self.assertEqual(self.app.api.calls, 2)

    def test_default_view_has_no_status_label(self) -> None:
        self.assertEqual(self.controller.filter.label(), "")


if __name__ == "__main__":
    unittest.main()
