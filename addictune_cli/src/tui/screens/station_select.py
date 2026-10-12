from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.widgets import Footer, RadioButton, RadioSet

from ...settings import STATION_NAMES
from .dialog import DialogScreen

_STATIONS: list[tuple[str, str]] = list(STATION_NAMES.items())  # [(slug, name), ...]


class StationSelectScreen(DialogScreen):
    DEFAULT_CSS = """
StationSelectScreen {
    .modal-dialog {
        width: 42;
    }

    RadioSet {
        width: 100%;
        margin-bottom: 1;
        padding: 0;
        border: none;
    }
}
    """
    BINDINGS = [Binding("enter", "confirm", "Select", show=True)]

    def __init__(self, current: str | None = None) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="station-dialog", classes="modal-dialog"):
            with RadioSet(id="station-radio"):
                for slug, name in _STATIONS:
                    yield RadioButton(name, value=slug == self._current)
            yield Footer()

    def on_mount(self) -> None:
        self.query_one("#station-dialog").border_title = "Choose Radio Station"
        self.query_one(RadioSet).focus()

    def on_click(self, event: Click) -> None:
        rs = self.query_one(RadioSet)
        if rs.region.contains(event.screen_x, event.screen_y):
            # RadioSet has updated pressed_index by the time click bubbles here
            self._confirm()
        else:
            super().on_click(event)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()

    def action_confirm(self) -> None:
        self._confirm()

    def _confirm(self) -> None:
        index = self.query_one(RadioSet).pressed_index
        if index is not None and 0 <= index < len(_STATIONS):
            self.dismiss(_STATIONS[index][0])
