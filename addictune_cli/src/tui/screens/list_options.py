from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.css.query import NoMatches
from textual.widgets import Checkbox, Footer, Label, RadioButton, RadioSet, Static

from ..types import OptionGroup
from .dialog import DialogScreen


class _OptionRadioSet(RadioSet):
    BINDINGS = [
        Binding("down,right", "next_option", "Next option", show=False),
        Binding("enter,space", "toggle_button", "Toggle", show=False),
        Binding("up,left", "previous_option", "Previous option", show=False),
    ]

    def action_next_option(self) -> None:
        if self._selected is None or self._selected < len(self.children) - 1:
            self.action_next_button()
        else:
            self.screen.focus_next_option(self)

    def action_previous_option(self) -> None:
        if self._selected is None or self._selected > 0:
            self.action_previous_button()
        else:
            self.screen.focus_previous_option(self)

    def focus_first_option(self) -> None:
        self.focus()
        if self.children:
            self._selected = 0

    def focus_last_option(self) -> None:
        self.focus()
        if self.children:
            self._selected = len(self.children) - 1


class _OptionCheckbox(Checkbox):
    BINDINGS = [
        Binding("enter,space", "toggle_button", "Toggle", show=False),
        Binding("down,right", "focus_next_option", "Next option", show=False),
        Binding("up,left", "focus_previous_option", "Previous option", show=False),
    ]

    def action_focus_next_option(self) -> None:
        self.screen.focus_next_option(self)

    def action_focus_previous_option(self) -> None:
        self.screen.focus_previous_option(self)


class ListOptionsScreen(DialogScreen):
    DEFAULT_CSS = """
ListOptionsScreen {
    #filters-dialog {
        width: 34;
    }

    .filters-section-title {
        text-style: bold;
    }

    .filters-option-group {
        border: none;
        padding: 0 1;
    }
}
    """
    class OptionChanged(Message):
        def __init__(
            self,
            group_id: str,
            choice_id: str,
            value: bool | None = None,
        ) -> None:
            self.group_id = group_id
            self.choice_id = choice_id
            self.value = value
            super().__init__()

    def __init__(self, groups: list[OptionGroup], *, title: str = "Filters") -> None:
        super().__init__()
        self._groups = groups
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="filters-dialog", classes="modal-dialog"):
            yield Label(self._title, id="filters-title", classes="dialog-heading")
            for group in self._groups:
                yield Static(group.title, classes="filters-section-title")
                if group.multiple:
                    with Vertical(id=f"{group.id}-mode", classes="filters-option-group"):
                        for choice in group.choices:
                            yield _OptionCheckbox(
                                choice.label,
                                value=choice.selected,
                                id=f"{group.id}-{choice.id}",
                                classes="filters-option-control",
                                compact=True,
                            )
                else:
                    yield _OptionRadioSet(
                        *(
                            RadioButton(
                                choice.label,
                                value=choice.selected,
                                id=f"{group.id}-{choice.id}",
                            )
                            for choice in group.choices
                        ),
                        id=f"{group.id}-mode",
                        classes="filters-option-control filters-option-group",
                        compact=True,
                    )
            yield Footer()

    def on_mount(self) -> None:
        try:
            self.query_one(_OptionRadioSet).focus()
        except NoMatches:
            self.query_one(_OptionCheckbox).focus()

    def focus_next_option(self, current) -> None:
        controls = list(self.query(".filters-option-control"))
        if current not in controls:
            return
        index = controls.index(current)
        target = controls[(index + 1) % len(controls)]
        if isinstance(target, _OptionRadioSet):
            target.focus_first_option()
        else:
            target.focus()

    def focus_previous_option(self, current) -> None:
        controls = list(self.query(".filters-option-control"))
        if current not in controls:
            return
        index = controls.index(current)
        target = controls[(index - 1) % len(controls)]
        if isinstance(target, _OptionRadioSet):
            target.focus_last_option()
        else:
            target.focus()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        group_id = event.radio_set.id.removesuffix("-mode")
        choice_id = event.pressed.id.removeprefix(f"{group_id}-")
        self.post_message(self.OptionChanged(group_id, choice_id))

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        checkbox_id = event.checkbox.id or ""
        group_id, _, choice_id = checkbox_id.partition("-")
        self.post_message(self.OptionChanged(group_id, choice_id, event.value))
