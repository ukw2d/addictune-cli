import unittest
from unittest import mock

from textual.app import App, ComposeResult

from addictune_cli.src.media.session import NullSession
from addictune_cli.src.audio.state import State
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar


from support import temp_settings


class _App(App):
    CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"

    def compose(self) -> ComposeResult:
        yield PlaybackBar(temp_settings(), media_session=NullSession())


class PlaybackBarLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_stopped_state_collapses_playback_details(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            bar.state = State.PLAYING
            await pilot.pause()
            bar.state = State.STOPPED
            await pilot.pause()

            for widget_id in (
                "#type-label",
                "#sep-playing",
                "#now-playing",
                "#sep-time",
                "#time-label",
            ):
                self.assertFalse(bar.query_one(widget_id).display)
            self.assertFalse(bar.query("#sep-vol"))
            self.assertTrue(bar.query_one("#volume-label").display)
            self.assertEqual(
                bar.query_one("#playback-right").region.right,
                bar.content_region.right,
            )

    async def test_track_id_is_not_rendered_in_bar(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            bar.track_id = 12345
            await pilot.pause()

            self.assertFalse(bar.query("#debug-track-id"))

    async def test_live_quality_uses_the_existing_sdk_stream_tier(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            bar = app.query_one(PlaybackBar)
            with mock.patch.object(bar, "_execute_backend_command"):
                bar.play(
                    "https://listen.di.fm/premium_high/trance.pls?listen_key=secret"
                )
                self.assertEqual(
                    bar.stream_quality,
                    ("MP3 · 320k", "Source: MP3 · 320 kbps"),
                )

                bar.stop()
                await pilot.pause()
                self.assertIsNone(bar.stream_quality)


if __name__ == "__main__":
    unittest.main()
