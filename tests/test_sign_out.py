"""Signing out forgets the account everywhere it lives, then asks for a login.

The stored login, the SDK client (session keys, listen key, credentials), the
user id, the stream URL (it carries the listen key, so Space would resume as
the signed-out account), and every list or cache filled for that account.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from textual.app import App, ComposeResult
from textual.widgets import Static

from addictune_cli.src.media.session import NullSession
from addictune_cli.src.settings import Settings
from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.presentation import AUTH_SIGNED_OUT, SYSTEM_SIGN_OUT
from addictune_cli.src.tui.screens.about import AboutScreen
from addictune_cli.src.tui.screens.auth import AuthScreen
from addictune_cli.src.tui.screens.dialog import ConfirmScreen
from addictune_cli.src.tui.services.features import FeatureCache
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar


_APP = "addictune_cli.src.tui.app"


def _signed_in_app():
    """A real app past startup with stored credentials and no network."""
    patches = (
        patch.object(Settings, "load", return_value=Settings(station_selected=True)),
        patch.object(AddictuneApp, "load_channels", return_value=None),
        patch(
            "addictune_cli.src.tui.widgets.playback_bar.make_session",
            return_value=NullSession(),
        ),
        patch(
            "addictune_cli.src.tui.app.load_credentials",
            return_value=("a@b.c", "secret"),
        ),
        patch.object(AddictuneApp, "refresh_feature_availability", return_value=None),
    )
    return patches


class _Started:
    async def __aenter__(self):
        self._stack = []
        for p in _signed_in_app():
            p.start()
            self._stack.append(p)
        self.app = AddictuneApp()
        self._run = self.app.run_test()
        self.pilot = await self._run.__aenter__()
        await self.pilot.pause()
        self.app.user_id = 42
        return self

    async def __aexit__(self, *exc):
        await self._run.__aexit__(*exc)
        for p in self._stack:
            p.stop()


class ConfirmScreenTests(unittest.IsolatedAsyncioTestCase):
    async def _answer(self, act) -> bool | None:
        results: list = []

        class _Host(App):
            CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"

            def compose(self) -> ComposeResult:
                yield Static()

        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(ConfirmScreen("Sure?", "Really.", "Do it"), results.append)
            await pilot.pause()
            await act(pilot, app)
            await pilot.pause()
        return results[0] if results else None

    async def test_confirm_button_answers_yes(self) -> None:
        self.assertIs(await self._answer(lambda p, a: p.click("#confirm")), True)

    async def test_cancel_button_and_escape_answer_no(self) -> None:
        self.assertIs(await self._answer(lambda p, a: p.click("#cancel")), False)
        self.assertIs(await self._answer(lambda p, a: p.press("escape")), False)

    async def test_enter_alone_does_not_confirm(self) -> None:
        """A destructive dialog opens with Cancel focused."""
        self.assertIs(await self._answer(lambda p, a: p.press("enter")), False)


class SignOutFlowTests(unittest.IsolatedAsyncioTestCase):
    async def _confirm(self, started: _Started) -> None:
        started.app.action_sign_out()
        await started.pilot.pause()
        await started.pilot.click("#confirm")
        await started.pilot.pause(0.3)

    async def test_confirming_forgets_the_account_and_asks_for_a_login(self) -> None:
        async with _Started() as s:
            app = s.app
            old_client = app.client
            old_client.close = AsyncMock()
            bar = app.query_one(PlaybackBar)
            bar._controller.play(
                "http://listen.example/x.pls?listen_key=OLD", "Ch", ContentType.LIVE
            )
            app._feature_cache = FeatureCache()
            app._feature_cache.remember("di", SimpleNamespace(tracks=True))
            app.push_screen(AboutScreen())  # a modal stacked under the confirmation
            await s.pilot.pause()
            with patch(f"{_APP}.clear_credentials", return_value=True) as clear:
                await self._confirm(s)

            clear.assert_called_once_with()
            self.assertIsNot(app.client, old_client)
            self.assertIsNone(app.client.listen_key)
            old_client.close.assert_awaited_once()
            self.assertIsNone(app.user_id)
            self.assertIsNone(bar.current_url)
            self.assertIsNone(app._feature_cache.get("di"))
            self.assertEqual(len(app.screen_stack), 2)
            self.assertIsInstance(app.screen, AuthScreen)
            notice = app.screen.query_one("#auth-error", Static)
            self.assertIn(AUTH_SIGNED_OUT, str(notice.render()))

    async def test_cancelling_changes_nothing(self) -> None:
        async with _Started() as s:
            app = s.app
            client = app.client
            with patch(f"{_APP}.clear_credentials") as clear:
                app.action_sign_out()
                await s.pilot.pause()
                await s.pilot.click("#cancel")
                await s.pilot.pause()

            clear.assert_not_called()
            self.assertIs(app.client, client)
            self.assertEqual(app.user_id, 42)
            self.assertNotIsInstance(app.screen, (AuthScreen, ConfirmScreen))

    async def test_a_login_that_could_not_be_removed_is_reported(self) -> None:
        async with _Started() as s:
            s.app.client.close = AsyncMock()
            with patch(f"{_APP}.clear_credentials", return_value=False):
                await self._confirm(s)

            text = str(s.app.screen.query_one("#auth-error", Static).render())
            self.assertIn("could not be removed", text)

    async def test_dismissing_the_login_after_signing_out_exits(self) -> None:
        async with _Started() as s:
            s.app.client.close = AsyncMock()
            s.app.exit = Mock()  # type: ignore[method-assign]
            with patch(f"{_APP}.clear_credentials", return_value=True):
                await self._confirm(s)
            await s.pilot.press("escape")
            await s.pilot.pause()

            s.app.exit.assert_called_once()

    async def test_the_palette_offers_sign_out_while_a_login_exists(self) -> None:
        async with _Started() as s:
            titles = lambda: [  # noqa: E731
                c.title for c in s.app.get_system_commands(s.app.screen)
            ]
            self.assertIn(SYSTEM_SIGN_OUT, titles())
            # Offline start: a stored login but no session is still removable.
            s.app.user_id = None
            self.assertIn(SYSTEM_SIGN_OUT, titles())
            with patch(f"{_APP}.load_credentials", return_value=None):
                self.assertNotIn(SYSTEM_SIGN_OUT, titles())

    async def test_work_started_for_the_old_account_is_cancelled(self) -> None:
        async with _Started() as s:
            app = s.app
            app.client.close = AsyncMock()
            started = asyncio.Event()
            finished: list[str] = []

            async def probe() -> None:
                started.set()
                await asyncio.sleep(30)
                finished.append("probe finished")

            app.run_worker(probe(), group="features")
            await asyncio.wait_for(started.wait(), 2)
            with patch(f"{_APP}.clear_credentials", return_value=True):
                await self._confirm(s)

            self.assertEqual(finished, [])
            self.assertEqual(
                [w for w in app.workers if w.group == "features" and w.is_running], []
            )

    async def test_an_audio_change_made_before_signing_out_is_still_applied(
        self,
    ) -> None:
        async with _Started() as s:
            app = s.app
            app.client.close = AsyncMock()
            bar = app.query_one(PlaybackBar)
            bar.apply_audio_settings = Mock()  # type: ignore[method-assign]
            app.action_settings()
            await s.pilot.pause()
            app.screen._audio_changed = True
            with patch(f"{_APP}.clear_credentials", return_value=True):
                await self._confirm(s)

            bar.apply_audio_settings.assert_called_once_with()

    async def test_the_last_on_demand_track_is_forgotten_too(self) -> None:
        async with _Started() as s:
            app = s.app
            app.client.close = AsyncMock()
            bar = app.query_one(PlaybackBar)
            app._fetch_vote_state = Mock()  # type: ignore[method-assign]
            bar.content_type = ContentType.TRACK
            bar.apply_track(track_id=7, image_url="http://img")
            bar.channel_name = "Artist"
            with patch(f"{_APP}.clear_credentials", return_value=True):
                await self._confirm(s)

            self.assertIsNone(bar.track_id)
            self.assertIsNone(bar.track_image_url)
            self.assertEqual(bar.channel_name, "")


class AuthScreenNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_notice_shows_until_the_user_types(self) -> None:
        class _Host(App):
            CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"
            client = SimpleNamespace()
            network = "di"

        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(AuthScreen(notice="Signed out."))
            await pilot.pause()
            error = app.screen.query_one("#auth-error", Static)
            self.assertIn("Signed out.", str(error.render()))
            self.assertTrue(error.has_class("-visible"))
            self.assertTrue(error.has_class("-notice"))

            await pilot.press("a")
            self.assertFalse(error.has_class("-visible"))


if __name__ == "__main__":
    unittest.main()
