from textual.app import RenderResult
from textual.geometry import Size
from textual.reactive import reactive
from textual.widget import Widget

_TICK = 0.15
_PAUSE_TICKS = 5


class MarqueeText(Widget):
    text: reactive[str] = reactive("", init=False)
    suffix: reactive[str] = reactive("", init=False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pos: int = 0
        self._dir: int = 1
        self._pause: int = _PAUSE_TICKS
        self._timer = None
        self._reset_key: tuple[str, str, int] | None = None

    def get_content_width(self, container: Size, viewport: Size) -> int:
        return len(self.text) + len(self.suffix)

    def render(self) -> RenderResult:
        width = self.size.width
        if width <= 0:
            return ""
        suffix = self.suffix[-width:]
        text_width = width - len(suffix)
        text = (
            self.text[self._pos : self._pos + text_width]
            if len(self.text) > text_width
            else self.text
        )
        return text + suffix

    def watch_text(self) -> None:
        self._reset()

    def watch_suffix(self) -> None:
        self._reset()

    def on_resize(self) -> None:
        self._reset()

    def _reset(self) -> None:
        reset_key = (self.text, self.suffix, self.size.width)
        if reset_key == self._reset_key:
            return
        self._reset_key = reset_key
        if self._timer:
            self._timer.stop()
        self._timer = None
        self._pos, self._dir, self._pause = 0, 1, _PAUSE_TICKS
        self.refresh(layout=True)
        text_width = self.size.width - len(self.suffix)
        if text_width > 0 and len(self.text) > text_width:
            self._timer = self.set_interval(_TICK, self._tick)

    def _tick(self) -> None:
        text_width = self.size.width - len(self.suffix)
        overflow = len(self.text) - text_width
        if overflow <= 0:
            if self._timer is not None:
                self._timer.stop()
            self._timer = None
            return
        if self._pause > 0:
            self._pause -= 1
            return
        self._pos = max(0, min(overflow, self._pos + self._dir))
        if self._pos in (0, overflow):
            self._dir = -self._dir
            self._pause = _PAUSE_TICKS
        self.refresh()
