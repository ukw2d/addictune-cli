"""The launch check reaches the UI: a toast when a newer release exists, silence
otherwise, no request at all when the setting is off."""

import unittest
from unittest.mock import AsyncMock, patch

from packaging.version import Version

from addictune_cli.src import update
from addictune_cli.src.media.session import NullSession
from addictune_cli.src.settings import Settings
from addictune_cli.src.tui import app as app_module
from addictune_cli.src.tui.app import AddictuneApp

_RELEASE = update.Release(Version("9.0.0"), "https://example.invalid/v9.0.0")


class LaunchCheckTests(unittest.IsolatedAsyncioTestCase):
    async def _launch(self, settings: Settings, check):
        with (
            patch.object(Settings, "load", return_value=settings),
            patch.object(AddictuneApp, "load_channels", return_value=None),
            patch.object(
                AddictuneApp, "refresh_feature_availability", return_value=None
            ),
            patch(
                "addictune_cli.src.tui.widgets.playback_bar.make_session",
                return_value=NullSession(),
            ),
            patch(
                "addictune_cli.src.tui.app.load_credentials", return_value=("a", "b")
            ),
            patch.object(app_module.update, "check", check),
        ):
            app = AddictuneApp()
            toasts: list[tuple[str, str]] = []
            app.notify = lambda message, *, title="", **kw: toasts.append(
                (title, message)
            )
            async with app.run_test() as pilot:
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                return app, toasts

    async def test_newer_release_shows_one_toast_and_is_remembered(self) -> None:
        check = AsyncMock(return_value=_RELEASE)
        app, toasts = await self._launch(Settings(station_selected=True), check)
        self.assertEqual(app.available_update, _RELEASE)
        self.assertEqual(len(toasts), 1)
        title, message = toasts[0]
        self.assertEqual(title, "Update available")
        self.assertIn("9.0.0", message)
        self.assertIn("About", message)
        check.assert_awaited_once()
        _, kwargs = check.await_args
        self.assertTrue(kwargs["prereleases"])

    async def test_up_to_date_is_silent(self) -> None:
        app, toasts = await self._launch(
            Settings(station_selected=True), AsyncMock(return_value=None)
        )
        self.assertIsNone(app.available_update)
        self.assertEqual(toasts, [])

    async def test_opt_out_makes_no_request(self) -> None:
        check = AsyncMock(return_value=_RELEASE)
        app, toasts = await self._launch(
            Settings(station_selected=True, update_check=False), check
        )
        check.assert_not_awaited()
        self.assertIsNone(app.available_update)
        self.assertEqual(toasts, [])


if __name__ == "__main__":
    unittest.main()
