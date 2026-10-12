"""`LiveStatusPoller`: one worker, one timer, rescheduled from the schedule."""

import unittest
from unittest.mock import AsyncMock, patch

from addictune_cli.src.tui.services.live_status import LiveStatusPoller
from addictune_cli.src.tui.types import MediaStatus, MediaStatusState


class _Timer:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _App:
    def __init__(self) -> None:
        self.network = "di"
        self.client = object()
        self.timers: list[_Timer] = []
        self.workers = []

    def run_worker(self, work, **kwargs):
        self.workers.append(work)

    def set_timer(self, delay, callback):
        timer = _Timer(delay)
        self.timers.append(timer)
        return timer


class LiveStatusPollerTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_pushes_statuses_and_schedules_the_next_run(self) -> None:
        app = _App()
        updates = AsyncMock()
        poller = LiveStatusPoller(app, updates)
        statuses_by_show = {1: MediaStatusState(MediaStatus.NOW_PLAYING)}

        with (
            patch(
                "addictune_cli.src.tui.services.live_status.get_live_show_statuses",
                new=AsyncMock(return_value=({}, statuses_by_show, {})),
            ),
            patch(
                "addictune_cli.src.tui.services.live_status.get_channel_now_playing_statuses",
                new=AsyncMock(return_value={}),
            ),
        ):
            poller.start()
            await app.workers[0]

        updates.assert_awaited_once()
        self.assertEqual(updates.await_args.args[0].statuses_by_show, statuses_by_show)
        self.assertEqual(len(app.timers), 1)
        self.assertLessEqual(app.timers[0].delay, 60.0)

    async def test_restart_replaces_the_pending_timer(self) -> None:
        app = _App()
        poller = LiveStatusPoller(app, AsyncMock())
        with patch(
            "addictune_cli.src.tui.services.live_status.get_live_show_statuses",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            poller.start()
            await app.workers[0]  # failure path reschedules
        first = app.timers[0]

        poller.start()  # e.g. network switch
        app.workers[1].close()

        self.assertTrue(first.stopped)
        self.assertEqual(len(app.workers), 2)

    async def test_stale_network_result_is_dropped(self) -> None:
        app = _App()
        updates = AsyncMock()
        poller = LiveStatusPoller(app, updates)

        async def switch_network(*_a, **_k):
            app.network = "rockradio"
            return ({}, {}, {})

        with (
            patch(
                "addictune_cli.src.tui.services.live_status.get_live_show_statuses",
                new=switch_network,
            ),
            patch(
                "addictune_cli.src.tui.services.live_status.get_channel_now_playing_statuses",
                new=AsyncMock(return_value={}),
            ),
        ):
            poller.start()
            await app.workers[0]

        updates.assert_not_awaited()
        self.assertEqual(app.timers, [])


if __name__ == "__main__":
    unittest.main()
