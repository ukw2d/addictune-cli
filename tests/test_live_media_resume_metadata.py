"""Live channel metadata through the real PlaybackBar and LiveTracker.

ICY drives the title; the routine attaches id/length/offset; the schedule
overlays the airing show. A resync must never move the counter.
"""

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from textual.app import App, ComposeResult

from addictune_cli.src.media.session import NullSession
from addictune_cli.src.audio.state import State
from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.services.channels import ChannelsService
from addictune_cli.src.tui.services.playback import PlaybackService
from addictune_cli.src.tui.types import ContentType, MediaStatus, MediaStatusState
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar

from support import install_services, temp_settings

_ROUTINE = SimpleNamespace(
    expires_on=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
    tracks=[
        SimpleNamespace(
            id=42,
            display_artist="Artist",
            display_title="Track",
            title="Track",
            content_length=None,
            length=180,
            offset=75,
            images=None,
        )
    ],
)


class _Channels:
    def __init__(self, routine) -> None:
        self.routine = routine
        self.fetches = 0

    async def get_routine(self, channel_id, audio_token, tune_in):
        self.fetches += 1
        return self.routine


class _LivePlaybackApp(App):
    def __init__(self, routine=_ROUTINE) -> None:
        super().__init__()
        self.network = "di"
        self.channels = _Channels(routine)
        self.client = SimpleNamespace(
            listen_key="key",
            network=lambda _slug: SimpleNamespace(channels=self.channels),
        )
        self.content_type = ContentType.LIVE
        self._playing_channel_id = 1
        self.track_queue = None
        self.playing_episode_id = None
        self._channels = []
        self._statuses_by_channel = {
            1: MediaStatusState(
                MediaStatus.NOW_PLAYING, now_playing=("Artist", "Title")
            )
        }
        self._live_by_channel = {}
        self._now_playing_by_channel = {}
        self._next_show_by_channel = {}
        self._channels_service = ChannelsService(self)
        self._playback_service = PlaybackService(self)
        install_services(self)

    def compose(self) -> ComposeResult:
        yield PlaybackBar(
            temp_settings(), id="playback-bar", media_session=NullSession()
        )

    on_playback_bar_icy_title_changed = AddictuneApp.on_playback_bar_icy_title_changed
    on_playback_bar_state_changed = AddictuneApp.on_playback_bar_state_changed
    on_playback_bar_pause_requested = AddictuneApp.on_playback_bar_pause_requested

    def _pause_current(self) -> None:
        self._playback_service._pause_current()

    def _playback_bar(self):
        return self._playback_service._playback_bar()

    def _apply_playback_highlight(self) -> None:
        pass


async def _playing(app: _LivePlaybackApp, pilot) -> PlaybackBar:
    """Start channel 1 the way the app does: play, then LiveTracker.start()."""
    bar = app.query_one(PlaybackBar)
    bar._controller.play("url", "Channel", ContentType.LIVE)
    bar._controller.playing()
    bar.state = State.PLAYING
    app._channels_service.live.start()
    await pilot.pause()  # routine fetch worker
    return bar


class LiveMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_restart_preserves_icy_title(self) -> None:
        app = _LivePlaybackApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one(PlaybackBar)
            bar.state = State.LOADING
            bar.now_playing = "ICY Artist - ICY Title"
            await pilot.pause()

            self.assertEqual(bar.now_playing, "ICY Artist - ICY Title")

    async def test_icy_title_is_applied_verbatim(self) -> None:
        app = _LivePlaybackApp(
            routine=SimpleNamespace(expires_on=_ROUTINE.expires_on, tracks=[])
        )
        async with app.run_test() as pilot:
            bar = await _playing(app, pilot)
            bar.set_icy_title("Artist - Track")
            await pilot.pause()
            self.assertEqual(bar.now_playing, "Artist - Track")

    async def test_icy_attaches_routine_id_and_length_and_clears_off_schedule(
        self,
    ) -> None:
        app = _LivePlaybackApp()
        async with app.run_test() as pilot:
            bar = await _playing(app, pilot)

            bar.set_icy_title("Artist - Track")
            await pilot.pause()
            self.assertEqual((bar.now_playing, bar.track_id), ("Artist - Track", 42))
            self.assertEqual((bar.elapsed_seconds, bar.duration_seconds), (75, 180))

            bar.set_icy_title("Different Artist - Different Track")
            await pilot.pause()
            self.assertEqual(bar.now_playing, "Different Artist - Different Track")
            self.assertIsNone(bar.track_id)
            self.assertIsNone(bar.duration_seconds)
            self.assertEqual(bar.elapsed_seconds, 0)

            bar.set_icy_title("Artist - Track")
            await pilot.pause()
            self.assertEqual((bar.track_id, bar.duration_seconds), (42, 180))

    async def test_resync_does_not_reapply_routine_offset(self) -> None:
        app = _LivePlaybackApp()
        async with app.run_test() as pilot:
            bar = await _playing(app, pilot)
            bar.set_icy_title("Artist - Track")
            await pilot.pause()
            self.assertEqual(bar.elapsed_seconds, 75)

            bar._clock.seek_to(170, running=False)
            app._channels_service.live.resync()

            self.assertEqual((bar.elapsed_seconds, bar.duration_seconds), (170, 180))

    async def test_unmatched_icy_refetches_the_routine_once(self) -> None:
        app = _LivePlaybackApp()
        async with app.run_test() as pilot:
            bar = await _playing(app, pilot)
            self.assertEqual(app.channels.fetches, 1)  # on start
            bar.set_icy_title("Unknown - Title")
            await pilot.pause()
            app._channels_service.live.resync()
            bar.set_icy_title("Unknown - Title")  # ICY heartbeat; no second fetch
            await pilot.pause()

            self.assertEqual(app.channels.fetches, 2)

    async def test_title_on_a_stopped_bar_is_ignored(self) -> None:
        app = _LivePlaybackApp()
        async with app.run_test() as pilot:
            bar = await _playing(app, pilot)
            bar.state = State.STOPPED

            app._channels_service.live.title_changed("Artist - Track")
            await pilot.pause()

            self.assertIsNone(bar.track_id)
            self.assertEqual(app.channels.fetches, 1)

    async def test_title_during_the_first_fetch_does_not_refetch(self) -> None:
        app = _LivePlaybackApp()
        gate = asyncio.Event()

        async def slow_get_routine(channel_id, audio_token, tune_in):
            app.channels.fetches += 1
            await gate.wait()
            return _ROUTINE

        app.channels.get_routine = slow_get_routine
        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            bar._controller.play("url", "Channel", ContentType.LIVE)
            bar._controller.playing()
            bar.state = State.PLAYING
            app._channels_service.live.start()
            bar.set_icy_title("Artist - Track")  # arrives before the routine
            await pilot.pause()
            gate.set()
            await pilot.pause()

            self.assertEqual(app.channels.fetches, 1)
            self.assertEqual(bar.track_id, 42)  # applied when the routine landed

    async def test_stop_then_play_re_arms_live_metadata(self) -> None:
        app = _LivePlaybackApp()
        async with app.run_test() as pilot:
            bar = await _playing(app, pilot)
            bar.set_icy_title("Artist - Track")
            await pilot.pause()
            self.assertEqual(bar.track_id, 42)

            app._channels_service.live.stop()
            app.on_playback_bar_state_changed(PlaybackBar.StateChanged(State.LOADING))
            await pilot.pause()
            bar.set_icy_title("Artist - Track")
            await pilot.pause()

            self.assertEqual(bar.track_id, 42)

    async def test_switching_channels_replaces_pending_routine_fetch(self) -> None:
        app = _LivePlaybackApp()
        first_started, second_started = asyncio.Event(), asyncio.Event()
        first_done, second_done = asyncio.Event(), asyncio.Event()
        calls = []
        second_routine = SimpleNamespace(
            expires_on=_ROUTINE.expires_on,
            tracks=[
                SimpleNamespace(
                    id=43,
                    display_artist="Second",
                    display_title="Track",
                    content_length=None,
                    length=240,
                    offset=0,
                    images=None,
                )
            ],
        )

        async def get_routine(channel_id, audio_token, tune_in):
            calls.append(channel_id)
            started, done = (
                (first_started, first_done)
                if channel_id == 1
                else (second_started, second_done)
            )
            started.set()
            try:
                await done.wait()
            except asyncio.CancelledError:
                await done.wait()
            return _ROUTINE if channel_id == 1 else second_routine

        app.channels.get_routine = get_routine
        async with app.run_test() as pilot:
            try:
                bar = await _playing(app, pilot)
                self.assertTrue(first_started.is_set())
                app._playing_channel_id = 2
                bar.set_icy_title("Second - Track")
                app._channels_service.live.start()
                await pilot.pause()
                self.assertTrue(second_started.is_set())

                first_done.set()
                await pilot.pause()
                bar.set_icy_title("Unknown - Title")
                await pilot.pause()
                self.assertEqual(calls, [1, 2])
                self.assertIsNone(bar.track_id)

                bar.set_icy_title("Second - Track")
                second_done.set()
                await pilot.pause()
                self.assertEqual((bar.track_id, bar.duration_seconds), (43, 240))
            finally:
                first_done.set()
                second_done.set()

    async def test_retired_fetch_cannot_replace_reselected_channel(self) -> None:
        app = _LivePlaybackApp()
        started = [asyncio.Event() for _ in range(3)]
        done = [asyncio.Event() for _ in range(3)]
        calls = []

        async def get_routine(channel_id, audio_token, tune_in):
            index = len(calls)
            calls.append(channel_id)
            if index >= len(started):
                return _ROUTINE
            started[index].set()
            while not done[index].is_set():
                try:
                    await done[index].wait()
                except asyncio.CancelledError:
                    pass
            return _ROUTINE

        app.channels.get_routine = get_routine
        async with app.run_test() as pilot:
            try:
                bar = await _playing(app, pilot)
                self.assertTrue(started[0].is_set())
                for index, channel_id in enumerate((2, 1), start=1):
                    app._playing_channel_id = channel_id
                    app._channels_service.live.start()
                    await pilot.pause()
                    self.assertTrue(started[index].is_set())

                bar.set_icy_title("Artist - Track")
                done[0].set()
                await pilot.pause()
                self.assertIsNone(bar.track_id)
                bar.set_icy_title("Unknown - Title")
                await pilot.pause()
                self.assertEqual(calls, [1, 2, 1])

                bar.set_icy_title("Artist - Track")
                done[2].set()
                await pilot.pause()
                self.assertEqual(bar.track_id, 42)
            finally:
                for gate in done:
                    gate.set()

    async def test_live_show_owns_the_clock_even_when_icy_names_its_track(self) -> None:
        app = _LivePlaybackApp()
        now = datetime.now(UTC)
        episode = SimpleNamespace(
            id=10,
            show=SimpleNamespace(id=20, name="FSOE", images=None),
            start_at=(now - timedelta(minutes=10)).isoformat(),
            end_at=(now + timedelta(minutes=50)).isoformat(),
            tracks=[
                SimpleNamespace(
                    id=99,
                    display_artist="Aly and Fila",
                    display_title="Future Sound Of Egypt 971",
                    title="Future Sound Of Egypt 971",
                    images=None,
                )
            ],
        )
        app._live_by_channel = {
            1: MediaStatusState(MediaStatus.LIVE_NOW, episode=episode)
        }
        async with app.run_test() as pilot:
            bar = await _playing(app, pilot)
            app._channels_service.live.resync()
            self.assertEqual((bar.track_id, bar.duration_seconds), (99, 3600))
            self.assertGreaterEqual(bar.elapsed_seconds, 599)
            self.assertEqual((bar.live_show_id, bar.live_show_name), (20, "FSOE"))

            bar.set_icy_title("Aly and Fila — Future Sound Of Egypt 971")
            await pilot.pause()
            self.assertEqual((bar.track_id, bar.duration_seconds), (99, 3600))
            self.assertGreaterEqual(bar.elapsed_seconds, 599)

            # A plain routine track in the ICY title proves the show is not on air.
            bar.set_icy_title("Artist - Track")
            await pilot.pause()
            self.assertEqual((bar.track_id, bar.live_show_id), (42, None))

    async def test_live_pause_request_stops_instead_of_pausing(self) -> None:
        app = _LivePlaybackApp()
        async with app.run_test():
            bar = app.query_one(PlaybackBar)
            app._playing_channel_id = None
            bar.state = State.PLAYING
            bar.stop = Mock()  # type: ignore[method-assign]
            bar.pause = Mock()  # type: ignore[method-assign]

            app.on_playback_bar_pause_requested(PlaybackBar.PauseRequested())

            bar.stop.assert_called_once_with()
            bar.pause.assert_not_called()


if __name__ == "__main__":
    unittest.main()
