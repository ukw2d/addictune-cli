import sys
import tomllib
import unittest
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from textual.app import App
from textual.widgets import Static

from addictune_cli.src.tui.screens.about import AboutScreen, logo, stack_names


class AboutTestApp(App):
    CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"


class AboutScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_shows_version_and_closes_on_escape(self) -> None:
        app = AboutTestApp()
        async with app.run_test() as pilot:
            app.push_screen(AboutScreen())
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, AboutScreen)
            name = str(screen.query_one("#about-name", Static).render())
            self.assertIn(f"v{version('addictune-cli')}", name)
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, AboutScreen)
            offset = screen._stack_offset
            await pilot.pause(0.3)
            self.assertEqual(screen._stack_offset, offset)

    async def test_support_link_opens_readme_section(self) -> None:
        app = AboutTestApp()
        async with app.run_test() as pilot:
            app.push_screen(AboutScreen())
            await pilot.pause()
            links = app.screen.query_one("#about-links", Static)
            text = str(links.render())
            left = (links.content_size.width - len(text)) // 2
            with patch.object(app, "open_url") as open_url:
                await pilot.click(links, offset=(left + text.index("Support"), 0))
            open_url.assert_called_once_with(
                "https://github.com/ukw2d/addictune-cli#-support"
            )

    def test_stack_names_follow_project_runtime_dependencies(self) -> None:
        project = tomllib.loads(
            (Path(__file__).parents[1] / "pyproject.toml").read_text()
        )["project"]
        expected = {
            canonicalize_name(requirement.name)
            for requirement in map(Requirement, project["dependencies"])
            if requirement.marker is None or requirement.marker.evaluate()
        }
        self.assertEqual(set(stack_names().split("  ·  ")), expected)

    def test_stack_names_filter_markers_and_extras(self) -> None:
        with patch(
            "addictune_cli.src.tui.screens.about.requires",
            return_value=[
                "example-ui>=1.0",
                f"example-native; sys_platform == '{sys.platform}'",
                "example-other; sys_platform == 'not-this-os'",
                "example-extra; extra == 'dev'",
            ],
        ):
            self.assertEqual(stack_names(), "example-ui  ·  example-native")

    async def test_dependency_strip_moves_wraps_and_resizes(self) -> None:
        app = AboutTestApp()
        async with app.run_test() as pilot:
            app.push_screen(AboutScreen())
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, AboutScreen)
            strip = screen.query_one("#about-stack", Static)
            initial = str(strip.render())
            await pilot.pause(0.3)
            self.assertNotEqual(str(strip.render()), initial)
            self.assertEqual(strip.size.height, 1)

            ticker = stack_names() + "     "
            screen._stack_offset = len(ticker) - 1
            screen._advance_stack()
            self.assertEqual(str(strip.render()), ticker)
            screen._advance_stack()
            self.assertEqual(str(strip.render()), ticker[1:] + ticker[:1])

            await pilot.resize_terminal(50, 24)
            await pilot.pause()
            self.assertEqual(strip.size.height, 1)
            self.assertLessEqual(strip.size.width, 50)

    async def test_disabled_animation_shows_full_static_credits(self) -> None:
        app = AboutTestApp()
        app.animation_level = "none"
        async with app.run_test() as pilot:
            app.push_screen(AboutScreen())
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, AboutScreen)
            strip = screen.query_one("#about-stack", Static)
            self.assertEqual(str(strip.render()), stack_names())
            self.assertGreater(strip.size.height, 1)
            await pilot.pause(0.3)
            self.assertEqual(screen._stack_offset, 0)
            self.assertEqual(str(strip.render()), stack_names())

    def test_logo_is_two_pixel_rows_per_line(self) -> None:
        lines = logo().plain.split("\n")
        self.assertEqual(len(lines), 5)
        self.assertEqual({len(line) for line in lines}, {18})
