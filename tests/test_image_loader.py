import asyncio
import unittest
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from addictune_cli.src.tui.services.image_loader import DebouncedImageLoader

_DEBOUNCE_SETTLE = 0.35  # > IMAGE_DEBOUNCE (0.25s), matches other image-load tests


class _LoaderHost(Widget):
    """Minimal widget hosting a DebouncedImageLoader, for testing the loader
    on its own rather than through ExpandedPlayer/MediaInfoPanel.
    """

    def __init__(self) -> None:
        super().__init__()
        self.relevant_url: str | None = None
        self.loader = DebouncedImageLoader(
            self,
            width=4,
            height=2,
            image_selector="#test-image",
            placeholder="placeholder",
        )

    def compose(self) -> ComposeResult:
        yield Static("", id="test-image")

    def request(self, url: str | None) -> None:
        self.loader.request(url, is_relevant=lambda: self.relevant_url == url)


class _LoaderApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.client = object()

    def compose(self) -> ComposeResult:
        yield _LoaderHost()


class DebouncedImageLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_size_change_invalidates_decoded_image(self) -> None:
        app = _LoaderApp()

        async with app.run_test():
            loader = app.query_one(_LoaderHost).loader
            loader._displayed_url = "a.png"

            loader.set_size(8, 4)

            self.assertEqual((loader._width, loader._height), (8, 4))
            self.assertIsNone(loader._displayed_url)

    async def test_resize_during_fetch_reloads_same_url_at_new_size(self) -> None:
        app = _LoaderApp()
        first_fetch_started = asyncio.Event()
        release_first_fetch = asyncio.Event()
        calls: list[tuple[str, int, int]] = []

        async def fetch_pixels(url, width, height, _client, *, scope="media"):
            calls.append((url, width, height))
            if (width, height) == (4, 2):
                first_fetch_started.set()
                await release_first_fetch.wait()
            return f"pixels:{width}x{height}"

        async with app.run_test():
            host = app.query_one(_LoaderHost)
            host.relevant_url = "a.png"

            with patch(
                "addictune_cli.src.tui.services.images.fetch_pixels", fetch_pixels
            ):
                host.request("a.png")
                await asyncio.wait_for(first_fetch_started.wait(), 1)

                host.loader.set_size(8, 4)
                host.request("a.png")
                release_first_fetch.set()
                await asyncio.sleep(_DEBOUNCE_SETTLE)

            image = host.query_one("#test-image", Static)
            self.assertEqual(
                calls,
                [("a.png", 4, 2), ("a.png", 8, 4)],
            )
            self.assertEqual(str(image.content), "pixels:8x4")

    async def test_a_single_request_fetches_once_after_the_debounce_window(
        self,
    ) -> None:
        app = _LoaderApp()
        calls: list[str] = []

        async def fetch_pixels(url, _w, _h, _client, *, scope="media"):
            calls.append(url)
            return f"pixels:{url}"

        async with app.run_test():
            host = app.query_one(_LoaderHost)
            host.relevant_url = "a.png"

            with patch(
                "addictune_cli.src.tui.services.images.fetch_pixels", fetch_pixels
            ):
                host.request("a.png")
                await asyncio.sleep(_DEBOUNCE_SETTLE)

            self.assertEqual(calls, ["a.png"])
            image = host.query_one("#test-image", Static)
            self.assertEqual(str(image.content), "pixels:a.png")

    async def test_a_superseding_request_cancels_the_earlier_one(self) -> None:
        app = _LoaderApp()
        calls: list[str] = []

        async def fetch_pixels(url, _w, _h, _client, *, scope="media"):
            calls.append(url)
            return f"pixels:{url}"

        async with app.run_test():
            host = app.query_one(_LoaderHost)
            host.relevant_url = "b.png"

            with patch(
                "addictune_cli.src.tui.services.images.fetch_pixels", fetch_pixels
            ):
                host.request("a.png")
                host.request("b.png")
                await asyncio.sleep(_DEBOUNCE_SETTLE)

        # The debounce coalesced the first request; only the latest url is
        # ever fetched.
        self.assertEqual(calls, ["b.png"])

    async def test_requesting_the_already_displayed_url_skips_the_fetch(self) -> None:
        app = _LoaderApp()
        calls: list[str] = []

        async def fetch_pixels(url, _w, _h, _client, *, scope="media"):
            calls.append(url)
            return f"pixels:{url}"

        async with app.run_test():
            host = app.query_one(_LoaderHost)
            host.relevant_url = "a.png"

            with patch(
                "addictune_cli.src.tui.services.images.fetch_pixels", fetch_pixels
            ):
                host.request("a.png")
                await asyncio.sleep(_DEBOUNCE_SETTLE)
                host.request("a.png")
                await asyncio.sleep(_DEBOUNCE_SETTLE)

        self.assertEqual(calls, ["a.png"])

    async def test_a_none_request_clears_an_already_displayed_image(self) -> None:
        # The common case: playback stops well after the last track's
        # artwork finished loading (loader is idle, _requested_url is
        # already None), so a None request must still clear the display
        # rather than being swallowed as a false "already idle" no-op.
        app = _LoaderApp()

        async def fetch_pixels(url, _w, _h, _client, *, scope="media"):
            return f"pixels:{url}"

        async with app.run_test():
            host = app.query_one(_LoaderHost)
            host.relevant_url = "a.png"

            with patch(
                "addictune_cli.src.tui.services.images.fetch_pixels", fetch_pixels
            ):
                host.request("a.png")
                await asyncio.sleep(_DEBOUNCE_SETTLE)

                host.request(None)
                await asyncio.sleep(_DEBOUNCE_SETTLE)

            image = host.query_one("#test-image", Static)
            self.assertEqual(str(image.content), "placeholder")
            self.assertFalse(image.loading)
            self.assertIsNone(host.loader._displayed_url)

    async def test_a_none_request_abandons_an_in_flight_fetch(self) -> None:
        # e.g. playback stops right after a track change but before its
        # artwork finished loading -- the abandoned fetch's result must not
        # overwrite the placeholder once it resolves.
        app = _LoaderApp()

        async def fetch_pixels(url, _w, _h, _client, *, scope="media"):
            if url == "b.png":
                await asyncio.sleep(_DEBOUNCE_SETTLE)
            return f"pixels:{url}"

        async with app.run_test():
            host = app.query_one(_LoaderHost)
            host.relevant_url = "a.png"

            with patch(
                "addictune_cli.src.tui.services.images.fetch_pixels", fetch_pixels
            ):
                host.request("a.png")
                await asyncio.sleep(_DEBOUNCE_SETTLE)

                # Start a second, slower load, then abandon it for None while
                # its fetch is still pending.
                host.request("b.png")
                await asyncio.sleep(_DEBOUNCE_SETTLE)
                host.request(None)
                await asyncio.sleep(_DEBOUNCE_SETTLE * 2)

            image = host.query_one("#test-image", Static)
            self.assertEqual(str(image.content), "placeholder")
            self.assertFalse(image.loading)
            self.assertIsNone(host.loader._displayed_url)

    async def test_a_none_request_while_already_idle_is_a_no_op(self) -> None:
        app = _LoaderApp()
        calls: list[str | None] = []

        async def fetch_pixels(url, _w, _h, _client, *, scope="media"):
            calls.append(url)
            return f"pixels:{url}"

        async with app.run_test():
            host = app.query_one(_LoaderHost)

            with patch(
                "addictune_cli.src.tui.services.images.fetch_pixels", fetch_pixels
            ):
                host.request(None)
                await asyncio.sleep(_DEBOUNCE_SETTLE)

            self.assertEqual(calls, [])

    async def test_a_stale_result_is_dropped_when_no_longer_relevant(self) -> None:
        app = _LoaderApp()

        async def fetch_pixels(url, _w, _h, _client, *, scope="media"):
            return f"pixels:{url}"

        async with app.run_test():
            host = app.query_one(_LoaderHost)
            # Never becomes relevant (e.g. the widget closed before the
            # fetch completed) — the result must not be applied.
            host.relevant_url = None

            with patch(
                "addictune_cli.src.tui.services.images.fetch_pixels", fetch_pixels
            ):
                host.request("a.png")
                await asyncio.sleep(_DEBOUNCE_SETTLE)

            image = host.query_one("#test-image", Static)
            self.assertEqual(str(image.content), "")
            self.assertFalse(image.loading)
            self.assertIsNone(host.loader._displayed_url)


if __name__ == "__main__":
    unittest.main()
