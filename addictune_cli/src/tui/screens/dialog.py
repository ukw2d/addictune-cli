from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ..presentation import BINDING_BACK, CONFIRM_CANCEL


class DialogScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss", BINDING_BACK, show=True)]

    def on_click(self, event: Click) -> None:
        dialog = self.query_one(".modal-dialog")
        if not dialog.content_region.contains(event.screen_x, event.screen_y):
            self.dismiss()


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no for a destructive action: True only for the confirm button.

    Cancel has focus, so a stray Enter backs out; Esc and a click outside
    the dialog are a no.
    """

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;

        #confirm-dialog {
            width: 50;
        }

        #confirm-body {
            margin-bottom: 1;
        }

        #confirm-buttons {
            height: auto;
            align-horizontal: right;
            margin-bottom: 1;
        }

        Button {
            margin-left: 2;
        }
    }
    """
    BINDINGS = [Binding("escape", "cancel", CONFIRM_CANCEL)]

    def __init__(self, title: str, body: str, confirm_label: str) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog", classes="modal-dialog"):
            yield Static(self._title, classes="dialog-heading")
            yield Static(self._body, id="confirm-body")
            with Horizontal(id="confirm-buttons"):
                yield Button(CONFIRM_CANCEL, id="cancel")
                yield Button(self._confirm_label, variant="error", id="confirm")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def on_click(self, event: Click) -> None:
        dialog = self.query_one(".modal-dialog")
        if not dialog.content_region.contains(event.screen_x, event.screen_y):
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
