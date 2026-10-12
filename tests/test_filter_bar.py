import unittest
from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import Static


from support import install_services


class _App(App):
    def __init__(self) -> None:
        super().__init__()
        self._label = ""
        # SearchService holds the body of _sync_filter_bar; instantiate it
        # so the inherited _sync_filter_bar wrapper can delegate.
        from addictune_cli.src.tui.services.search import SearchService

        self._search = SearchService(self)
        install_services(self)

    def compose(self) -> ComposeResult:
        yield Static("", id="filter-bar")

    def _active_followed_controller(self):
        return SimpleNamespace(filter=SimpleNamespace(label=lambda: self._label))

    def _sync_filter_bar(self) -> None:

        self._search.sync_filter_bar()


class FilterBarTests(unittest.IsolatedAsyncioTestCase):
    async def test_filter_bar_takes_no_space_when_empty(self) -> None:
        app = _App()

        async with app.run_test():
            bar = app.query_one("#filter-bar", Static)
            app._sync_filter_bar()

            self.assertFalse(bar.display)
            self.assertEqual(str(bar.content), "")

    async def test_filter_bar_marks_active_label(self) -> None:
        app = _App()

        async with app.run_test():
            bar = app.query_one("#filter-bar", Static)
            app._label = "Sort: Popular"
            app._sync_filter_bar()

            self.assertTrue(bar.display)
            self.assertEqual(str(bar.content), "Sort: Popular")


if __name__ == "__main__":
    unittest.main()
