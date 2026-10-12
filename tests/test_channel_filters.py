import unittest

from textual.app import App
from textual.widgets import Checkbox, Footer

from addictune_cli.src.tui.screens.list_options import ListOptionsScreen
from addictune_cli.src.tui.types import OptionChoice, OptionGroup


def _groups(favorites: bool, sort: str) -> list[OptionGroup]:
    return [
        OptionGroup(
            "filter",
            "Filter by",
            [
                OptionChoice("all", "All", not favorites),
                OptionChoice("favorites", "Favorites", favorites),
            ],
        ),
        OptionGroup(
            "sort",
            "Sort by",
            [
                OptionChoice("default", "Default", sort == "default"),
                OptionChoice("alpha", "A-Z", sort == "alpha"),
                OptionChoice("popular", "Popular", sort == "popular"),
            ],
        ),
    ]


class _App(App):
    CSS_PATH = [
        "../addictune_cli/src/tui/styles/app.tcss",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.changed: list[object] = []

    def on_list_options_screen_option_changed(
        self, message: ListOptionsScreen.OptionChanged
    ) -> None:
        self.changed.append((message.group_id, message.choice_id))


class ChannelFiltersTests(unittest.IsolatedAsyncioTestCase):
    async def test_reopens_with_current_choices_selected(self) -> None:
        app = _App()

        async with app.run_test():
            app.push_screen(ListOptionsScreen(_groups(favorites=True, sort="alpha")))
            await app.screen.wait_for_refresh()

            self.assertEqual(app.screen.query_one("#filter-mode").pressed_index, 1)
            self.assertEqual(app.screen.query_one("#sort-mode").pressed_index, 1)

    async def test_option_groups_render_in_filter_sort_status_order(self) -> None:
        app = _App()
        groups = [
            *_groups(favorites=False, sort="default"),
            OptionGroup(
                "status",
                "Live status",
                [
                    OptionChoice("live_now", "Live now"),
                    OptionChoice("upcoming", "Upcoming"),
                ],
                multiple=True,
            ),
        ]

        async with app.run_test():
            app.push_screen(ListOptionsScreen(groups))
            await app.screen.wait_for_refresh()

            option_group_ids = [
                widget.id
                for widget in app.screen.query(".filters-option-group, RadioSet")
            ]
            self.assertEqual(
                option_group_ids,
                ["filter-mode", "sort-mode", "status-mode"],
            )

    async def test_arrow_keys_move_across_filter_grid(self) -> None:
        app = _App()
        groups = [
            *_groups(favorites=False, sort="default"),
            OptionGroup(
                "status",
                "Live status",
                [
                    OptionChoice("live_now", "Live now"),
                    OptionChoice("upcoming", "Upcoming"),
                ],
                multiple=True,
            ),
        ]

        async with app.run_test() as pilot:
            app.push_screen(ListOptionsScreen(groups))
            await pilot.pause()

            await pilot.press("down", "down")
            self.assertTrue(app.screen.query_one("#sort-mode").has_focus)

            await pilot.press("down", "down", "down")
            self.assertTrue(
                app.screen.query_one("#status-live_now", Checkbox).has_focus
            )

            await pilot.press("down")
            self.assertTrue(
                app.screen.query_one("#status-upcoming", Checkbox).has_focus
            )

            await pilot.press("up")
            self.assertTrue(
                app.screen.query_one("#status-live_now", Checkbox).has_focus
            )

    async def test_radio_change_posts_selected_value(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            app.push_screen(ListOptionsScreen(_groups(favorites=False, sort="default")))
            await pilot.pause()
            await pilot.press("down", "space", "tab", "down", "down", "space")

            self.assertEqual(
                app.changed, [("filter", "favorites"), ("sort", "popular")]
            )

    async def test_checkbox_change_posts_selected_value(self) -> None:
        app = _App()
        groups = [
            OptionGroup(
                "status",
                "Live status",
                [
                    OptionChoice("live_now", "Live now"),
                    OptionChoice("upcoming", "Upcoming", True),
                ],
                multiple=True,
            )
        ]

        async with app.run_test() as pilot:
            app.push_screen(ListOptionsScreen(groups))
            await pilot.pause()
            await pilot.press("space", "tab", "space")

            self.assertEqual(
                app.changed,
                [("status", "live_now"), ("status", "upcoming")],
            )
            self.assertTrue(app.screen.query_one("#status-live_now", Checkbox).value)
            self.assertFalse(app.screen.query_one("#status-upcoming", Checkbox).value)

    async def test_uses_dialog_footer_and_closes_on_outside_click(self) -> None:
        app = _App()

        async with app.run_test() as pilot:
            app.push_screen(ListOptionsScreen(_groups(favorites=False, sort="default")))
            await pilot.pause()

            self.assertIsNotNone(app.screen.query_one(Footer))
            await pilot.click(offset=(0, 0))
            await pilot.pause()

            self.assertNotIsInstance(app.screen, ListOptionsScreen)


if __name__ == "__main__":
    unittest.main()
