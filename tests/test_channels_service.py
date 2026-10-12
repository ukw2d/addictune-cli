import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from addictune_cli.src.tui.services.channels import ChannelsService
from addictune_cli.src.tui.types import MediaStatus, MediaStatusState


class _ChannelsApp:
    def __init__(self) -> None:
        self.network = "di"
        self._now_playing_by_channel = {}
        self._live_by_channel = {}
        self._statuses_by_channel = {}
        self._statuses_by_show = {}
        self._next_show_by_channel = {}
        self._channels = []
        self._playing_channel_id = None

    def run_worker(self, work, *args, **kwargs) -> None:
        work.close()

    def set_timer(self, *args, **kwargs) -> None:
        pass


class ChannelsServiceTests(unittest.TestCase):
    def test_rebuild_channel_statuses_prefers_live_over_now_playing(self) -> None:
        app = _ChannelsApp()
        service = ChannelsService(app)
        now_playing = MediaStatusState(MediaStatus.NOW_PLAYING)
        also_now_playing = MediaStatusState(MediaStatus.NOW_PLAYING)
        live = MediaStatusState(MediaStatus.LIVE_NOW, episode=SimpleNamespace(id=10))
        app._now_playing_by_channel = {1: now_playing, 2: also_now_playing}
        app._live_by_channel = {1: live}

        service._rebuild_channel_statuses()

        self.assertIs(app._statuses_by_channel[1], live)
        self.assertIs(app._statuses_by_channel[2], also_now_playing)


class _FakeChannelList:
    def __init__(self) -> None:
        self.loading = False


class _LoadChannelsApp(_ChannelsApp):
    def __init__(self) -> None:
        super().__init__()
        self.client = object()
        self.user_id = 1
        self.channel_list = _FakeChannelList()
        self._followed_controllers = {}

    async def ensure_authenticated_session(self, _network: str) -> bool:
        return True

    def refresh_feature_availability(self) -> None:
        pass

    def query_one(self, selector, *_args):
        if selector == "#channel-list":
            return self.channel_list
        return Mock()


class LoadChannelsBodyTests(unittest.IsolatedAsyncioTestCase):
    """channel_list.loading must have exactly one owner (add-0dr)."""

    async def test_loading_clears_even_on_an_unhandled_failure_path(self) -> None:
        app = _LoadChannelsApp()
        service = ChannelsService(app)

        with (
            patch(
                "addictune_cli.src.tui.services.channels.get_current_worker",
                return_value=Mock(is_cancelled=False),
            ),
            patch(
                "addictune_cli.src.tui.services.channels.get_channel_views",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            with self.assertRaises(RuntimeError):
                await service.load_channels_body()

        self.assertFalse(app.channel_list.loading)


if __name__ == "__main__":
    unittest.main()
