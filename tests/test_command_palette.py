from collections import namedtuple

from addictune_cli.src.tui.command_palette import ordered_system_commands


Command = namedtuple("Command", ("title", "help", "callback", "discover"))


def _command(title: str) -> Command:
    return Command(title, "", lambda: None, True)


def test_system_commands_are_ordered_for_palette_discovery() -> None:
    commands = [
        _command("Quit"),
        _command("Sign out"),
        _command("Screenshot"),
        _command("Settings"),
        _command("Theme"),
        _command("Choose radio station"),
        _command("Keys"),
        _command("About"),
        _command("Toggle dark mode"),
        _command("Minimize"),
        _command("Maximize"),
    ]

    ordered = [command.title for command in ordered_system_commands(commands)]

    assert ordered == [
        "Choose radio station",
        "Settings",
        "Theme",
        "Toggle dark mode",
        "Maximize",
        "Minimize",
        "Screenshot",
        "Keys",
        "About",
        "Sign out",
        "Quit",
    ]
