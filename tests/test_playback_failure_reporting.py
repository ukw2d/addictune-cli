"""Playback must not retry a failure it cannot fix, and must say why it stopped.

A misconfigured output device used to kill the player on every attempt; the UI
showed a stream that loaded, retried twelve times and stopped, which looked like
a network problem.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from textual.app import App, ComposeResult

from addictune_sdk import AddictuneAuthError

from addictune_cli.src.audio import protocol
from addictune_cli.src.audio.state import State
from addictune_cli.src.media.session import NullSession
from addictune_cli.src.tui.services.playback_policy import (
    MAX_RETRY_ATTEMPTS,
    MAX_RETRY_DELAY,
    RETRY_DELAY,
    BackendStop,
    PlaybackController,
    ScheduleRetry,
    retry_delay,
)
from addictune_cli.src.tui.presentation import PLAYBACK_NEEDS_PREMIUM
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar

from support import temp_settings


class _ResolutionApp(App):
    def __init__(self, resolve, *, premium: bool | None = None) -> None:
        super().__init__()
        self.network = "di"
        self.client = SimpleNamespace(
            premium=premium,
            listen_key=None,
            network=lambda _network: SimpleNamespace(
                channels=SimpleNamespace(resolve_stream_url=resolve)
            ),
        )

    async def recover_auth(self, network: str | None = None) -> bool:
        return True  # a free account's login is valid; the key is simply not premium

    def compose(self) -> ComposeResult:
        yield PlaybackBar(temp_settings(), media_session=NullSession())


class PlaybackSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_retry_does_not_cancel_pending_selection(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        urls: list[str] = []

        async def resolve(url):
            urls.append(url)
            started.set()
            await release.wait()
            return "resolved-new"

        app = _ResolutionApp(resolve)
        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            bar._player.play = mock.Mock()
            stale = bar._controller.play("old", "Old", ContentType.LIVE)
            bar.play("new", title="New")
            await asyncio.wait_for(started.wait(), 2)

            bar._execute_backend_command(stale)
            release.set()
            await app.workers.wait_for_complete()

            self.assertEqual(urls, ["new"])
            bar._player.play.assert_called_once_with(
                "resolved-new", live=True, volume=bar._effective_volume
            )

    async def test_new_selection_retires_old_events_before_resolution(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def resolve(url):
            started.set()
            await release.wait()
            return "resolved-new"

        app = _ResolutionApp(resolve)
        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            bar.content_type = ContentType.PLAYLIST
            bar._player.play = mock.Mock()
            bar._player._dispatch = lambda callback: callback()
            old_generation = bar._player._generation
            bar._controller.play("old", "Old", ContentType.PLAYLIST)
            bar._controller.playing()
            bar.play("new", title="New")
            await asyncio.wait_for(started.wait(), 2)

            bar._player._handle(
                protocol.StateEvent(generation=old_generation, state=State.STOPPED)
            )
            self.assertEqual(bar.state, State.LOADING)
            release.set()
            await app.workers.wait_for_complete()

            bar._player.play.assert_called_once_with(
                "resolved-new", live=False, volume=bar._effective_volume
            )


class FreeAccountRefusalTests(unittest.IsolatedAsyncioTestCase):
    """The stream server answers a free account's premium stream with 401.

    For a live channel that used to enter the reconnect loop: two minutes of
    "Stream dropped" and twelve more refusals before the real reason showed.
    """

    _REFUSED = (
        "[Errno 825242872] Server returned 401 Unauthorized (authorization "
        "failed): 'http://prem2.example/bigbeat_hi?***'"
    )

    async def _bar(self, premium: bool | None, resolve) -> tuple[list, PlaybackBar]:
        app = _ResolutionApp(resolve, premium=premium)
        toasts: list = []
        async with app.run_test():
            app.notify = lambda message, **kw: toasts.append((message, kw))
            bar = app.query_one(PlaybackBar)
            bar._player.play = mock.Mock()
            bar._player.stop = mock.Mock()
            yield toasts, bar

    async def _refused_live_play(self, premium: bool | None) -> tuple[list, PlaybackBar]:
        async for toasts, bar in self._bar(premium, mock.AsyncMock()):
            bar._controller.play("http://stream", "Big Beat", ContentType.LIVE)
            bar._on_player_error("decode", self._REFUSED)
            bar._on_player_state(State.STOPPED)
            return toasts, bar

    async def _refused_resolution(self, premium: bool | None) -> tuple[list, PlaybackBar]:
        refuse = mock.AsyncMock(side_effect=AddictuneAuthError("Access Denied"))
        async for toasts, bar in self._bar(premium, refuse):
            bar.content_type = ContentType.LIVE
            bar.play("http://listen.example/x.pls?listen_key=k", title="Big Beat")
            await bar.app.workers.wait_for_complete()
            return toasts, bar

    async def test_a_free_account_stops_at_once_with_the_premium_notice(self) -> None:
        toasts, bar = await self._refused_live_play(False)

        self.assertEqual(bar.state, State.STOPPED)
        self.assertEqual(len(toasts), 1)
        message, kwargs = toasts[0]
        self.assertIn("Premium", message)
        self.assertIn("trial", message)
        self.assertNotIn("401", message)
        self.assertEqual(kwargs.get("severity"), "warning")

    async def test_a_premium_account_still_gets_the_reconnect_policy(self) -> None:
        toasts, bar = await self._refused_live_play(True)

        self.assertEqual(bar.state, State.LOADING)
        self.assertEqual([m for m, _ in toasts], ["Stream dropped \u2014 reconnecting\u2026"])

    async def test_a_cdn_refusal_counts_too(self) -> None:
        async for toasts, bar in self._bar(False, mock.AsyncMock()):
            bar._controller.play("http://t", "Track", ContentType.TRACK)
            bar._on_player_error("decode", "Server returned 403 Forbidden: 'https://x'")
            bar._on_player_state(State.STOPPED)

        self.assertEqual([m for m, _ in toasts], [PLAYBACK_NEEDS_PREMIUM])

    async def test_a_free_account_still_sees_a_real_network_error(self) -> None:
        async for toasts, bar in self._bar(False, mock.AsyncMock()):
            bar._controller.play("http://t", "Track", ContentType.TRACK)
            bar._on_player_error("decode", "[Errno 5] Input/output error: 'https://x'")
            bar._on_player_state(State.STOPPED)

        self.assertIn("Input/output error", toasts[0][0])
        self.assertNotIn("Premium", toasts[0][0])

    async def test_a_refused_playlist_fetch_stops_a_free_account_too(self) -> None:
        toasts, bar = await self._refused_resolution(False)

        self.assertEqual(bar.state, State.STOPPED)
        self.assertEqual([m for m, _ in toasts], [PLAYBACK_NEEDS_PREMIUM])

    async def test_an_unknown_tier_sees_the_real_error_when_playback_ends(self) -> None:
        # Stays on the reconnect policy; the detail surfaces once retries are spent.
        toasts, bar = await self._refused_live_play(None)
        bar._controller._retry_attempts = MAX_RETRY_ATTEMPTS
        bar._on_player_error("decode", self._REFUSED)
        bar._on_player_state(State.STOPPED)

        self.assertEqual(bar.state, State.STOPPED)
        self.assertIn("401", toasts[-1][0])
        self.assertNotIn("Premium", toasts[-1][0])


class StoppedReasonTests(unittest.TestCase):
    def _bar(self, messages: list) -> SimpleNamespace:
        return SimpleNamespace(
            Stopped=PlaybackBar.Stopped,
            _player=mock.Mock(),
            post_message=messages.append,
        )

    def test_backend_stop_preserves_natural_completion_reason(self) -> None:
        messages: list = []
        bar = self._bar(messages)

        PlaybackBar._execute_backend_command(
            bar, BackendStop(generation=7, post_stopped=True), natural=True
        )

        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0].natural)
        bar._player.stop.assert_called_once_with()

    def test_explicit_stop_defaults_to_not_natural(self) -> None:
        messages: list = []

        PlaybackBar._execute_backend_command(
            self._bar(messages), BackendStop(generation=7, post_stopped=True)
        )

        self.assertFalse(messages[0].natural)


class RetryPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = PlaybackController()
        self.play = self.controller.play("http://stream", "Trance", ContentType.LIVE)

    def test_a_dropped_live_stream_is_retried(self) -> None:
        command = self.controller.backend_exited()

        self.assertIsInstance(command, ScheduleRetry)
        self.assertEqual(command.attempt, 1)
        self.assertEqual(self.controller.state, State.LOADING)

    def test_a_device_failure_stops_instead_of_retrying(self) -> None:
        command = self.controller.backend_exited(fatal=True)

        self.assertIsInstance(command, BackendStop)
        self.assertTrue(command.post_stopped)
        self.assertEqual(self.controller.state, State.STOPPED)

    def test_an_on_demand_track_ending_stops(self) -> None:
        controller = PlaybackController()
        controller.play("http://file", "Track", ContentType.PLAYLIST)
        controller.playing()

        self.assertIsInstance(controller.backend_exited(), BackendStop)

    def test_a_confirmed_play_resets_the_retry_budget(self) -> None:
        self.controller.backend_exited()
        self.controller.playing()

        self.assertEqual(self.controller.state, State.PLAYING)
        self.assertEqual(self.controller.backend_exited().attempt, 1)

    def test_reconnects_back_off_to_span_a_real_outage(self) -> None:
        delays = [retry_delay(n) for n in range(1, MAX_RETRY_ATTEMPTS + 1)]

        self.assertEqual(delays[0], RETRY_DELAY)
        self.assertEqual(delays, sorted(delays))
        self.assertEqual(max(delays), MAX_RETRY_DELAY)
        # A flat 0.5s delay gave up ~6s in, while the network was still
        # returning; the budget has to outlast an ordinary outage.
        self.assertGreater(sum(delays), 60.0)

    def test_each_reconnect_waits_longer_than_the_last(self) -> None:
        seen = []
        for _ in range(5):
            command = self.controller.backend_exited()
            assert isinstance(command, ScheduleRetry)
            seen.append(command.delay)

        self.assertEqual(seen, [retry_delay(n) for n in range(1, 6)])

    def test_transient_failures_still_give_up_eventually(self) -> None:
        for _ in range(MAX_RETRY_ATTEMPTS):
            assert isinstance(self.controller.backend_exited(), ScheduleRetry)

        self.assertIsInstance(self.controller.backend_exited(), BackendStop)


if __name__ == "__main__":
    unittest.main()
