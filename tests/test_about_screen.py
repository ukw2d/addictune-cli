import unittest
from importlib.metadata import version

from textual.app import App
from textual.widgets import Static

from addictune_cli.src.tui.screens.about import AboutScreen, logo


class AboutScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_shows_version_and_closes_on_escape(self) -> None:
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(AboutScreen())
            await pilot.pause()
            name = str(app.screen.query_one("#about-name", Static).render())
            self.assertIn(f"v{version('addictune-cli')}", name)
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, AboutScreen)

    def test_logo_is_two_pixel_rows_per_line(self) -> None:
        lines = logo().plain.split("\n")
        self.assertEqual(len(lines), 5)
        self.assertEqual({len(line) for line in lines}, {18})
