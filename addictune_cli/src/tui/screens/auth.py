from addictune_sdk import AddictuneError
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from ...auth import is_auth_failure, login
from ..presentation import (
    AUTH_BRAND,
    AUTH_EMAIL_LABEL,
    AUTH_EMAIL_PLACEHOLDER,
    AUTH_EMAIL_REQUIRED,
    AUTH_ERROR_GENERIC,
    AUTH_ERROR_INVALID,
    AUTH_HINT,
    AUTH_LOGIN_LABEL,
    AUTH_PASSWORD_LABEL,
    AUTH_PASSWORD_PLACEHOLDER,
    AUTH_PASSWORD_REQUIRED,
    AUTH_TAGLINE,
    AUTH_TITLE,
)
from ..typed_nodes import AppNode


class AuthScreen(AppNode, ModalScreen[int | None]):
    DEFAULT_CSS = """
AuthScreen {
    align: center middle;

    #auth-dialog {
        width: 52;
        border-title-style: bold;
    }

    #auth-brand {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $primary;
    }

    #auth-tagline {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }

    .field-label {
        margin-top: 1;
        color: $text-muted;
        text-style: bold;
    }


    #auth-error {
        display: none;
        width: 100%;
        margin-top: 1;
        padding: 0 1;
        color: $error;
        background: $error 15%;
        text-align: center;
    }

    #auth-error.-visible {
        display: block;
    }

    #login {
        width: 100%;
        margin-top: 1;
    }

    #auth-hint {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
}
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="auth-dialog", classes="modal-dialog"):
            yield Static(AUTH_BRAND, id="auth-brand")
            yield Static(AUTH_TAGLINE, id="auth-tagline")
            yield Label(AUTH_EMAIL_LABEL, classes="field-label")
            yield Input(placeholder=AUTH_EMAIL_PLACEHOLDER, id="email")
            yield Label(AUTH_PASSWORD_LABEL, classes="field-label")
            yield Input(
                placeholder=AUTH_PASSWORD_PLACEHOLDER,
                password=True,
                id="password",
            )
            yield Static("", id="auth-error")
            yield Button(AUTH_LOGIN_LABEL, variant="primary", id="login")
            yield Static(AUTH_HINT, id="auth-hint")

    def on_mount(self) -> None:
        dialog = self.query_one("#auth-dialog", VerticalScroll)
        dialog.border_title = AUTH_TITLE
        self.query_one("#email", Input).focus()

    # ── Events ───────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        # Any edit clears the previous (server-side) error banner.
        self._clear_error()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter on the email field advances to the password rather than
        # submitting a half-filled form.
        if event.input.id == "email":
            self.query_one("#password", Input).focus()
        else:
            self._login()

    def on_button_pressed(self) -> None:
        self._login()

    def action_cancel(self) -> None:
        self.dismiss(None)

    # ── Helpers ──────────────────────────────────────────────────

    def _show_error(self, message: str) -> None:
        error = self.query_one("#auth-error", Static)
        error.update(message)
        error.add_class("-visible")

    def _clear_error(self) -> None:
        error = self.query_one("#auth-error", Static)
        if error.has_class("-visible"):
            error.update("")
            error.remove_class("-visible")

    def _set_busy(self, busy: bool) -> None:
        self.query_one("#login", Button).loading = busy
        self.query_one("#email", Input).disabled = busy
        self.query_one("#password", Input).disabled = busy

    @work(exclusive=True)
    async def _login(self) -> None:
        email_input = self.query_one("#email", Input)
        password_input = self.query_one("#password", Input)

        for field, message in (
            (email_input, AUTH_EMAIL_REQUIRED),
            (password_input, AUTH_PASSWORD_REQUIRED),
        ):
            if not field.value:
                self._show_error(message)
                field.focus()
                return

        self._clear_error()
        self._set_busy(True)
        try:
            user_id = await login(
                self.app.client,
                email_input.value,
                password_input.value,
                network=self.app.network,
            )
        except Exception as exc:  # noqa: BLE001 — surface every failure as a badge
            self._set_busy(False)
            invalid = isinstance(exc, AddictuneError) and is_auth_failure(exc)
            # Blanking the field posts Input.Changed, and its handler clears
            # the banner. Suppress that message so the reset stays silent and
            # the error we show below survives.
            with self.prevent(Input.Changed):
                password_input.value = ""
            self._show_error(AUTH_ERROR_INVALID if invalid else AUTH_ERROR_GENERIC)
            password_input.focus()
            return
        self.dismiss(user_id)
