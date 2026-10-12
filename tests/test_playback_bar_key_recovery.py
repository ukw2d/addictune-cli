"""A stream resolution that hits a 403 must recover the listen key and retry
once, not just fail with the stale key -- and it must leave unrelated errors
(a dead network, a 5xx) alone rather than treating every failure as an
auth problem.
"""

import unittest

from addictune_sdk import AddictuneAPIError, AddictuneAuthError
from textual.app import App, ComposeResult

from addictune_cli.src.media.session import NullSession
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar

from support import temp_settings

_STALE_URL = "https://listen.di.fm/premium_high/trance.pls?listen_key=stale"


class _Channels:
    """Fake ChannelsAPI.resolve_stream_url: pops one canned result per call."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def resolve_stream_url(self, url: str) -> str:
        self.calls.append(url)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _Network:
    def __init__(self, channels: _Channels) -> None:
        self.channels = channels


class _Client:
    def __init__(
        self, channels: _Channels, listen_key: str | None = "fresh-key"
    ) -> None:
        self._channels = channels
        self.listen_key = listen_key

    def network(self, _name: str) -> _Network:
        return _Network(self._channels)

    def with_listen_key(self, url: str) -> str:
        return url.replace("listen_key=stale", f"listen_key={self.listen_key}")


class _App(App):
    CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"

    def __init__(self, channels: _Channels, *, recover_result: bool = True) -> None:
        super().__init__()
        self.client = _Client(channels)
        self.network = "di"
        self.recover_result = recover_result
        self.recovered_networks: list[str | None] = []

    def compose(self) -> ComposeResult:
        yield PlaybackBar(temp_settings(), media_session=NullSession())

    async def recover_auth(self, network: str | None = None) -> bool:
        self.recovered_networks.append(network)
        return self.recover_result


class PlaybackBarKeyRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_with_refreshed_listen_key_on_403(self) -> None:
        channels = _Channels(
            [
                AddictuneAuthError("listen key expired"),
                "http://stream.example/audio",
            ]
        )
        app = _App(channels)

        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            resolved = await bar._resolve_with_key_recovery(_STALE_URL)

            self.assertEqual(resolved, "http://stream.example/audio")
            self.assertEqual(app.recovered_networks, ["di"])
            self.assertEqual(len(channels.calls), 2)
            self.assertIn("listen_key=fresh-key", channels.calls[1])
            self.assertNotIn("listen_key=stale", channels.calls[1])

    async def test_reraises_when_recovery_fails(self) -> None:
        channels = _Channels([AddictuneAuthError("listen key expired")])
        app = _App(channels, recover_result=False)

        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            with self.assertRaises(AddictuneAuthError):
                await bar._resolve_with_key_recovery(_STALE_URL)

            self.assertEqual(app.recovered_networks, ["di"])
            self.assertEqual(len(channels.calls), 1)

    async def test_non_auth_error_propagates_without_recovery_attempt(self) -> None:
        channels = _Channels([AddictuneAPIError(500, "boom")])
        app = _App(channels)

        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            with self.assertRaises(AddictuneAPIError):
                await bar._resolve_with_key_recovery(_STALE_URL)

            self.assertEqual(app.recovered_networks, [])
            self.assertEqual(len(channels.calls), 1)


if __name__ == "__main__":
    unittest.main()
