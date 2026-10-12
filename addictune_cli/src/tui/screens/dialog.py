from textual.binding import Binding
from textual.events import Click
from textual.screen import ModalScreen

from ..presentation import BINDING_BACK

class DialogScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss", BINDING_BACK, show=True)]

    def on_click(self, event: Click) -> None:
        dialog = self.query_one(".modal-dialog")
        if not dialog.content_region.contains(event.screen_x, event.screen_y):
            self.dismiss()
