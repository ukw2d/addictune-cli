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
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar

from support import temp_settings


class _ResolutionApp(App):
    def __init__(self, resolve) -> None:
        super().__init__()
        self.network = "di"
        self.client = SimpleNamespace(
            network=lambda _network: SimpleNamespace(
                channels=SimpleNamespace(resolve_stream_url=resolve)
            )
        )

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
