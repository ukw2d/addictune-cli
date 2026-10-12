from importlib.metadata import version

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Static

from .dialog import DialogScreen

# docs/assets/logo-mark.svg as a pixel grid; letters index _LOGO_COLORS.
_LOGO = (
    "..iii...cc........",
    ".ii.ii..aaaa......",
    "ii...ii.bbbbbb....",
    "ii...ii.dddddddd..",
    "iiiiiii.eeeeeeeeee",
    "ii...ii.jjjjjjjj..",
    "ii...ii.hhhhhh....",
    "ii...ii.ffff......",
    "ii...ii.gg........",
)
_LOGO_COLORS = {
    "a": "#1ca2c6", "b": "#1eb5a6", "c": "#288cfb", "d": "#35c3a2", "e": "#9ad150",
    "f": "#e99a2d", "g": "#eb8700", "h": "#ecb336", "i": "#eef3fb", "j": "#f7d509",
}  # fmt: skip
_CURSOR = "#288cfb"
_REPO = "https://github.com/ukw2d/addictune-cli"
_VERSION = version("addictune-cli")


def logo() -> Text:
    """The mark in half-block cells: two pixel rows per terminal line."""
    rows = (*_LOGO, "." * len(_LOGO[0]))  # pad to an even row count
    lines = []
    for top, bottom in zip(rows[::2], rows[1::2]):
        line = Text()
        for t, b in zip(top, bottom):
            fg, bg = _LOGO_COLORS.get(t), _LOGO_COLORS.get(b)
            match fg, bg:
                case None, None:
                    line.append(" ")
                case _, None:
                    line.append("▀", style=fg)
                case None, _:
                    line.append("▄", style=bg)
                case _:
                    line.append("▀", style=f"{fg} on {bg}")
        lines.append(line)
    return Text("\n").join(lines)


class AboutScreen(DialogScreen):
    _cursor_on = True
    DEFAULT_CSS = """
AboutScreen {
    .modal-dialog {
        width: 70;
        padding-bottom: 1;
    }

    #about-logo {
        width: 100%;
        content-align: center middle;
    }

    #about-name {
        width: 100%;
        text-align: center;
        text-style: bold;
        margin-top: 1;
    }

    #about-tagline {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }

    .about-row {
        width: 100%;
        text-align: center;
    }

    #about-disclaimer {
        margin-top: 1;
        color: $text-muted;
        text-style: italic;
    }
}
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="about-dialog", classes="modal-dialog"):
            yield Static(logo(), id="about-logo")
            yield Static(id="about-name")
            yield Static(
                "Client for AudioAddict radio stations.",
                id="about-tagline",
            )
            yield Static(
                f"[@click=app.open_url('{_REPO}')]GitHub[/]  ·  "
                f"[@click=app.open_url('{_REPO}/issues')]Report a bug[/]  ·  "
                f"[@click=app.open_url('{_REPO}/releases')]Releases[/]",
                classes="about-row",
            )
            yield Static(
                "Built with Textual, PyAV, sounddevice and addictune-sdk",
                classes="about-row",
            )
            yield Static(
                "Not affiliated with AudioAddict, DI.FM, RadioTunes, ROCKRADIO.COM, "
                "JAZZRADIO.com, Classical Radio or ZenRadio.",
                id="about-disclaimer",
                classes="about-row",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#about-dialog").border_title = "About"
        self._render_name()
        self.set_interval(0.6, self._blink)

    def _blink(self) -> None:
        self._cursor_on = not self._cursor_on
        self._render_name()

    def _render_name(self) -> None:
        cursor = "▌" if self._cursor_on else " "
        self.query_one("#about-name", Static).update(
            f"addictune [{_CURSOR}]{cursor}[/]  [dim]v{_VERSION} · MIT © ukw2d[/]"
        )
