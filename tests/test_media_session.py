"""The bar publishes one MediaInfo per change and routes media commands back
through its own request messages (so OS keys behave like the keyboard)."""

import unittest

from textual.app import App, ComposeResult

from addictune_cli.src.audio.state import State
from addictune_cli.src.media.session import Command, MediaInfo
from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.services.playback import PlaybackService
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar

from support import install_services, temp_settings


class _RecordingSession:
    def __init__(self) -> None:
        self.on_command = None
        self.infos: list[MediaInfo] = []
        self.stopped = False

    def start(self, on_command, schedule) -> None:
        self.on_command = on_command
        schedule(0.05, lambda: None)

    def update(self, info: MediaInfo) -> None:
        self.infos.append(info)

    def stop(self) -> None:
        self.stopped = True


class _PlaybackApp(App):
    def __init__(self, session: _RecordingSession) -> None:
        super().__init__()
        self.session = session
        self.content_type = ContentType.LIVE
        self.track_queue = None
        self._playing_channel_id = None
        self.next_calls = 0
        self._playback_service = PlaybackService(self)
        install_services(self)

    def compose(self) -> ComposeResult:
        yield PlaybackBar(temp_settings(), self.session, id="playback-bar")

    def _apply_playback_highlight(self) -> None:
        pass

    def on_playback_bar_stopped(self, _: PlaybackBar.Stopped) -> None:
        pass

    def action_next_track(self) -> None:
        self.next_calls += 1

    on_playback_bar_pause_requested = AddictuneApp.on_playback_bar_pause_requested
    on_playback_bar_toggle_play_requested = (
        AddictuneApp.on_playback_bar_toggle_play_requested
    )

    def _pause_current(self) -> None:
        self._playback_service._pause_current()

    def _toggle_current_playback(self) -> None:
        self._playback_service._toggle_current_playback()

    def _playback_bar(self):
        return self._playback_service._playback_bar()


def _start_playing(bar: PlaybackBar, content_type: ContentType) -> None:
    bar.content_type = content_type
    bar._controller.play("url", "Title", content_type)
    bar._controller.playing()
    bar._sync_from_controller()


class MediaSessionWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_starts_lazily_on_first_playback(self) -> None:
        session = _RecordingSession()
        app = _PlaybackApp(session)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIsNone(session.on_command)
            self.assertEqual(session.infos, [])

            bar = app.query_one(PlaybackBar)
            _start_playing(bar, ContentType.MIXSHOW)
            await pilot.pause()

            self.assertIsNotNone(session.on_command)
            self.assertTrue(session.infos[-1].playing)
            self.assertEqual(session.infos[-1].title, "Title")
            self.assertTrue(session.infos[-1].can_next)
            self.assertTrue(session.infos[-1].can_previous)  # any queue, never live
        self.assertTrue(session.stopped)

    async def test_commands_route_through_the_bar(self) -> None:
        session = _RecordingSession()
        app = _PlaybackApp(session)
        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            app.content_type = ContentType.MIXSHOW
            _start_playing(bar, ContentType.MIXSHOW)
            await pilot.pause()

            session.on_command(Command.PAUSE)
            await pilot.pause()
            self.assertEqual(bar.state, State.PAUSED)
            self.assertFalse(session.infos[-1].playing)
            self.assertTrue(session.infos[-1].can_play)

            session.on_command(Command.TOGGLE)
            await pilot.pause()
            self.assertEqual(bar.state, State.PLAYING)

            session.on_command(Command.NEXT)
            await pilot.pause()
            self.assertEqual(app.next_calls, 1)

    async def test_pause_key_stops_a_live_channel(self) -> None:
        session = _RecordingSession()
        app = _PlaybackApp(session)
        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            _start_playing(bar, ContentType.LIVE)
            await pilot.pause()
            self.assertFalse(session.infos[-1].can_next)

            session.on_command(Command.PAUSE)
            await pilot.pause()

            self.assertEqual(bar.state, State.STOPPED)
            self.assertFalse(session.infos[-1].can_pause)


if __name__ == "__main__":
    unittest.main()
