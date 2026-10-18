"""Settings > General tells the user which account they are signed in with.

A free account logs in and lists channels like a premium one, then every
stream fails; the row makes the tier visible before that happens.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Label

from addictune_cli.src.media.session import NullSession
from addictune_cli.src.tui.screens import settings as settings_module
from addictune_cli.src.tui.screens.settings import SettingsScreen
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar

from support import temp_settings


class _App(App):
    CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"

    def __init__(self, premium: bool | None) -> None:
        super().__init__()
        self.settings = temp_settings(station_slug="rockradio")
        self.network = "rockradio"
        self.client = SimpleNamespace(premium=premium)

    def compose(self) -> ComposeResult:
        yield PlaybackBar(self.settings, media_session=NullSession())


async def _account_text(
    premium: bool | None,
    credentials: tuple[str, str] | None = ("[EMAIL_REDACTED]", "pw"),
) -> str:
    app = _App(premium)
    with patch.object(settings_module, "load_credentials", return_value=credentials):
        async with app.run_test() as pilot:
            app.query_one(PlaybackBar).request_devices = lambda callback: None
            app.push_screen(SettingsScreen())
            await pilot.pause()
            return str(app.screen.query_one("#account", Label).render())


class AccountRowTests(unittest.IsolatedAsyncioTestCase):
    async def test_premium_account(self) -> None:
        text = await _account_text(True)
        self.assertIn("[EMAIL_REDACTED]", text)
        self.assertIn("Rock Radio", text)
        self.assertIn("Premium", text)

    async def test_free_account_gets_the_hint(self) -> None:
        text = await _account_text(False)
        self.assertIn("Free", text)
        self.assertIn("Premium subscription", text)

    async def test_unknown_tier_shows_only_the_account(self) -> None:
        text = await _account_text(None)
        self.assertIn("[EMAIL_REDACTED]", text)
        self.assertNotIn("Premium", text)
        self.assertNotIn("Free", text)

    async def test_without_stored_credentials_the_row_has_no_empty_field(self) -> None:
        self.assertEqual(
            await _account_text(True, credentials=None), "Rock Radio · Premium"
        )
