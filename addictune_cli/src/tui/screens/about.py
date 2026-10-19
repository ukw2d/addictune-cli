from importlib.metadata import requires, version

from packaging.requirements import Requirement
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


def stack_names() -> str:
    requirements = map(Requirement, requires("addictune-cli") or ())
    return "  ·  ".join(
        requirement.name
        for requirement in requirements
        if requirement.marker is None or requirement.marker.evaluate()
    )


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
    _stack_offset = 0
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

    #about-built-with {
        margin-top: 1;
    }

    #about-stack {
        width: 100%;
        height: 1;
        overflow: hidden;
        color: $text-muted;
    }

    #about-stack.still {
        height: auto;
        text-align: center;
    }

    #about-disclaimer {
        margin-top: 1;
        color: $text-muted;
        text-style: italic;
    }

    #about-update {
        width: 100%;
        margin-top: 1;
        text-align: center;
        border: round $success;
        color: $success;
        text-style: bold;
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
                f"[@click=screen.open_url('{_REPO}')]GitHub[/]  ·  "
                f"[@click=screen.open_url('{_REPO}/issues')]Report a bug[/]  ·  "
                f"[@click=screen.open_url('{_REPO}/releases')]Releases[/]  ·  "
                f"[@click=screen.open_url('{_REPO}#-support')]Support[/]",
                id="about-links",
                classes="about-row",
            )
            if release := getattr(self.app, "available_update", None):
                yield Static(
                    f"⬆ Update available: v{release.version}  ·  "
                    f"[@click=screen.open_url('{release.html_url}')]View release[/]",
                    id="about-update",
                )
            yield Static("Built with", id="about-built-with", classes="about-row")
            self._stack_text = stack_names()
            still = self.app.animation_level == "none"
            yield Static(
                Text(
                    self._stack_text,
                    no_wrap=not still,
                    overflow="fold" if still else "crop",
                ),
                id="about-stack",
                classes="still" if still else "",
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
        if self.app.animation_level != "none":
            self.set_interval(0.6, self._blink)
            self.set_interval(0.25, self._advance_stack)

    def action_open_url(self, url: str) -> None:
        # Textual's App has open_url() but no matching action for @click markup.
        self.app.open_url(url)

    def _blink(self) -> None:
        self._cursor_on = not self._cursor_on
        self._render_name()

    def _advance_stack(self) -> None:
        if not self.is_current or not self._stack_text:
            return
        ticker = self._stack_text + "     "
        self._stack_offset = (self._stack_offset + 1) % len(ticker)
        self.query_one("#about-stack", Static).update(
            Text(
                ticker[self._stack_offset :] + ticker[: self._stack_offset],
                no_wrap=True,
                overflow="crop",
            )
        )

    def _render_name(self) -> None:
        cursor = "▌" if self._cursor_on else " "
        self.query_one("#about-name", Static).update(
            f"addictune [{_CURSOR}]{cursor}[/]  [dim]v{_VERSION} · MIT © ukw2d[/]"
        )
