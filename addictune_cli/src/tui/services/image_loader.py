"""Shared debounced artwork loading for ExpandedPlayer and MediaInfoPanel.

Both widgets render artwork fetched via `services.images.fetch_pixels`,
driven by a reactive image url that can change several times in quick
succession (ICY updates, schedule changes, list navigation) before the
widget is even open. `request` debounces those transient values down to one
fetch; the fetch itself is still guarded against a superseding request or
the widget having moved on by the time it completes.

"""

from typing import Callable

from textual.widget import Widget
from textual.widgets import Static
from textual.worker import get_current_worker

from .images import ImageCacheScope
from ..presentation import IMAGE_DEBOUNCE


class DebouncedImageLoader:
    """Debounces and fetches artwork into a `Static` widget owned by *host*.

    `host` provides `set_timer`, `query_one`, `run_worker`, and `app.client`;
    its worker group ("default") is used for exclusive cancellation, so a
    superseding request cancels a fetch still in flight.
    """

    def __init__(
        self,
        host: Widget,
        *,
        width: int,
        height: int,
        image_selector: str,
        scope: ImageCacheScope = "media",
        placeholder: str = "",
    ) -> None:
        self._host = host
        self._width = width
        self._height = height
        self._image_selector = image_selector
        self._scope = scope
        self._placeholder = placeholder
        self._size_generation = 0
        self._requested_url: str | None = None
        self._requested_generation: int | None = None
        self._displayed_url: str | None = None
        self._displayed_generation: int | None = None
        self._timer = None

    def set_size(self, width: int, height: int) -> None:
        """Update fetch dimensions, invalidating an image decoded at the old size."""
        if (width, height) == (self._width, self._height):
            return
        self._width, self._height = width, height
        self._size_generation += 1
        self._requested_url = None
        self._requested_generation = None
        self._displayed_url = None
        self._displayed_generation = None

    def request(self, url: str | None, *, is_relevant: Callable[[], bool]) -> None:
        """Debounce loading *url*; a no-op if it's already requested/shown.

        `is_relevant` is re-checked once the fetch completes, to drop a
        result that a superseding request or a widget close has since made
        stale — it should reflect *url* specifically, not just "still open".
        """
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if url is None:
            # `None` means "clear" -- only a no-op if there is truly
            # nothing shown or in flight to clear. Unlike a real url, it
            # can't be compared against the idle `_requested_url`/
            # `_displayed_url` sentinel (which is also `None`), or a
            # request to clear a displayed image would be swallowed here.
            if self._requested_url is None and self._displayed_url is None:
                return
        elif (
            url == self._requested_url
            and self._requested_generation == self._size_generation
        ) or (
            url == self._displayed_url
            and self._displayed_generation == self._size_generation
        ):
            return
        generation = self._size_generation
        width, height = self._width, self._height
        self._timer = self._host.set_timer(
            IMAGE_DEBOUNCE,
            lambda: self._start_load(
                url,
                is_relevant,
                generation=generation,
                width=width,
                height=height,
            ),
        )

    def _start_load(
        self,
        url: str | None,
        is_relevant: Callable[[], bool],
        *,
        generation: int,
        width: int,
        height: int,
    ) -> None:
        self._host.run_worker(
            self._load(
                url,
                is_relevant,
                generation=generation,
                width=width,
                height=height,
            ),
            exclusive=True,
        )

    async def _load(
        self,
        url: str | None,
        is_relevant: Callable[[], bool],
        *,
        generation: int,
        width: int,
        height: int,
    ) -> None:
        from .images import fetch_pixels

        image = self._host.query_one(self._image_selector, Static)
        if generation != self._size_generation:
            return
        if url is None:
            image.loading = False
            image.update(self._placeholder)
            self._requested_url = None
            self._requested_generation = None
            self._displayed_url = None
            self._displayed_generation = None
            return
        if (
            url == self._requested_url and self._requested_generation == generation
        ) or (
            url == self._displayed_url and self._displayed_generation == generation
        ):
            return

        worker = get_current_worker()
        self._requested_url = url
        self._requested_generation = generation
        image.loading = True
        pixels = await fetch_pixels(
            url, width, height, self._host.app.client, scope=self._scope
        )
        if (
            worker.is_cancelled
            or generation != self._size_generation
            or not is_relevant()
        ):
            if (
                self._requested_url == url
                and self._requested_generation == generation
            ):
                self._requested_url = None
                self._requested_generation = None
                image.loading = False
            return
        image.update(pixels or self._placeholder)
        image.loading = False
        self._displayed_url = url
        self._displayed_generation = generation
        self._requested_url = None
        self._requested_generation = None
