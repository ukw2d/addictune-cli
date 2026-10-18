from collections.abc import Iterable

from textual.command import DiscoveryHit, Hit
from textual.system_commands import SystemCommandsProvider

from .presentation import BINDING_SETTINGS, SYSTEM_SIGN_OUT, SYSTEM_TOGGLE_DARK


COMMAND_PALETTE_ORDER: tuple[str, ...] = (
    "Choose radio station",
    BINDING_SETTINGS,
    "Theme",
    SYSTEM_TOGGLE_DARK,
    "Maximize",
    "Minimize",
    "Screenshot",
    "Keys",
    "About",
    SYSTEM_SIGN_OUT,
    "Quit",
)

_COMMAND_PRIORITY = {title: index for index, title in enumerate(COMMAND_PALETTE_ORDER)}


def ordered_system_commands(commands: Iterable) -> list:
    return sorted(
        commands,
        key=lambda command: (
            _COMMAND_PRIORITY.get(command.title, len(_COMMAND_PRIORITY)),
            command.title.casefold(),
        ),
    )


class OrderedSystemCommandsProvider(SystemCommandsProvider):
    """System command provider with app-defined discovery ordering.

    Textual's default provider alphabetically sorts the command-palette
    discovery list. The app menu is easier to scan when product actions come
    first, utility actions follow, and the destructive Quit action is last.
    """

    async def discover(self):
        for name, help_text, callback, discover in ordered_system_commands(
            self.app.get_system_commands(self.screen)
        ):
            if discover:
                yield DiscoveryHit(name, callback, help=help_text)

    async def search(self, query: str):
        matcher = self.matcher(query)
        for name, help_text, callback, *_ in ordered_system_commands(
            self.app.get_system_commands(self.screen)
        ):
            if (match := matcher.match(name)) > 0:
                yield Hit(match, matcher.highlight(name), callback, help=help_text)
