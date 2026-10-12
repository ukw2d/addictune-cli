import unittest
from unittest.mock import patch

from addictune_sdk import AddictuneAuthError
from textual.app import App
from textual.widgets import Input, Static

from addictune_cli.src.tui.screens.auth import AuthScreen


class _App(App):
    """Minimal host for AuthScreen: it only reaches `client` and `network`."""

    def __init__(self) -> None:
        super().__init__()
        self.client = object()
        self.network = "di"


async def _fail_422(*args, **kwargs):
    raise AddictuneAuthError("invalid credentials")


async def _fail_network(*args, **kwargs):
    raise OSError("connection refused")


class AuthErrorBannerTests(unittest.IsolatedAsyncioTestCase):
    async def _submit(self, pilot, screen, failure):
        screen.query_one("#email", Input).value = "listener@example.com"
        screen.query_one("#password", Input).value = "wrong-password"
        await pilot.pause()

        with patch("addictune_cli.src.tui.screens.auth.login", failure):
            await screen._login().wait()
        # Drain the message loop so any deferred Input.Changed lands.
        for _ in range(5):
            await pilot.pause()

    async def test_banner_stays_visible_after_invalid_credentials(self) -> None:
        app = _App()
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await pilot.pause()

            await self._submit(pilot, screen, _fail_422)

            error = screen.query_one("#auth-error", Static)
            self.assertTrue(
                error.has_class("-visible"),
                f"banner hidden; classes={list(error.classes)}",
            )
            self.assertTrue(error.display)
            self.assertEqual(screen.query_one("#password", Input).value, "")

    async def test_banner_stays_visible_after_generic_failure(self) -> None:
        app = _App()
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await pilot.pause()

            await self._submit(pilot, screen, _fail_network)

            error = screen.query_one("#auth-error", Static)
            self.assertTrue(
                error.has_class("-visible"),
                f"banner hidden; classes={list(error.classes)}",
            )

    async def test_user_edit_still_clears_the_banner(self) -> None:
        """The guard must not survive the reset and swallow real edits."""
        app = _App()
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await pilot.pause()

            await self._submit(pilot, screen, _fail_422)
            error = screen.query_one("#auth-error", Static)
            self.assertTrue(error.has_class("-visible"))

            # Simulate the user typing into the password field again.
            screen.query_one("#password", Input).focus()
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()

            self.assertFalse(
                error.has_class("-visible"),
                "typing should dismiss the stale error banner",
            )

    async def test_blank_email_is_caught_before_the_round_trip(self) -> None:
        app = _App()
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#password", Input).value = "pw"
            await pilot.pause()

            with patch("addictune_cli.src.tui.screens.auth.login") as login:
                await screen._login().wait()
            await pilot.pause()

            login.assert_not_called()
            self.assertTrue(
                screen.query_one("#auth-error", Static).has_class("-visible")
            )

    async def test_successful_login_dismisses_with_the_user_id(self) -> None:
        app = _App()
        async with app.run_test() as pilot:
            results = []
            screen = AuthScreen()
            await app.push_screen(screen, results.append)
            await pilot.pause()
            screen.query_one("#email", Input).value = "a@b.c"
            screen.query_one("#password", Input).value = "pw"

            async def ok(*args, **kwargs):
                return 42

            with patch("addictune_cli.src.tui.screens.auth.login", ok):
                await screen._login().wait()
            await pilot.pause()

            self.assertEqual(results, [42])


if __name__ == "__main__":
    unittest.main()
