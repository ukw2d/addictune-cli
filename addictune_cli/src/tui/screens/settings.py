from textual.app import ComposeResult
from textual.await_complete import AwaitComplete
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Label, ListItem, ListView, Select

from ...auth import load_credentials
from ...settings import STATION_NAMES, Settings
from ..presentation import ACCOUNT_FREE_HINT, ACCOUNT_TIERS
from .dialog import DialogScreen

_SAMPLE_RATE_AUTO = 0  # sentinel: None in Settings, 0 is not a valid Hz value

_SAMPLE_RATES: list[tuple[str, int]] = [
    ("Auto (follow device)", _SAMPLE_RATE_AUTO),
    ("44100 Hz", 44100),
    ("48000 Hz", 48000),
]

_LATENCY_OPTIONS: list[tuple[str, str]] = [
    ("High (stable)", "high"),
    ("Low", "low"),
]

_STARTUP_TABS: list[tuple[str, str]] = [
    ("Channels", "channels"),
    ("Mixshows", "mixshows"),
    ("Playlists", "playlists"),
]

_SETTING_MAP: dict[str, str] = {
    "device-select":      "audio_device_name",
    "sample-rate-select": "audio_sample_rate",
    "latency-select":     "audio_latency",
    "default-tab-select": "default_tab",
}

# Settings the player child applies live through ``configure``.
_AUDIO_SETTING_FIELDS = frozenset(
    {"audio_device_name", "audio_sample_rate", "audio_latency"}
)


class _SettingsSection(Vertical):
    def __init__(self, settings: Settings, **kwargs) -> None:
        super().__init__(**kwargs)
        self._settings = settings


class _AudioSection(_SettingsSection):
    def compose(self) -> ComposeResult:
        yield Label("Output Device", classes="setting-label")
        yield Select(
            self._device_options([]),
            value=self._settings.audio_device_name or Select.NULL,
            allow_blank=True,
            prompt="System default",
            id="device-select",
        )
        yield Label("Sample Rate", classes="setting-label")
        yield Select(
            _SAMPLE_RATES,
            value=_SAMPLE_RATE_AUTO if self._settings.audio_sample_rate is None else self._settings.audio_sample_rate,
            allow_blank=False,
            id="sample-rate-select",
        )

    def set_devices(self, names: list[str]) -> None:
        """Fill the picker from the player child's fresh device table."""
        select = self.query_one("#device-select", Select)
        select.set_options(self._device_options(names))
        select.value = self._settings.audio_device_name or Select.NULL

    def _device_options(self, names: list[str]) -> list[tuple[str, str]]:
        """Devices by name, keeping a saved-but-absent one as its own option.

        ``Select`` rejects a value missing from its options, and dropping the
        saved device silently would hide why playback fell back to the default.
        """
        options = [(name, name) for name in names]
        saved = self._settings.audio_device_name
        if saved and saved not in names:
            options.append((f"{saved} (not connected)", saved))
        return options


class _PlaybackSection(_SettingsSection):
    def compose(self) -> ComposeResult:
        yield Label("Latency", classes="setting-label")
        yield Select(
            _LATENCY_OPTIONS,
            value=self._settings.audio_latency,
            allow_blank=False,
            id="latency-select",
        )


class _GeneralSection(_SettingsSection):
    def compose(self) -> ComposeResult:
        yield Label("Startup Tab", classes="setting-label")
        yield Select(
            _STARTUP_TABS,
            value=self._settings.default_tab,
            allow_blank=False,
            id="default-tab-select",
        )
        yield Label("Account", classes="setting-label")
        yield Label(self._account(), id="account", markup=False)

    def _account(self) -> str:
        email = (load_credentials() or ("",))[0]
        premium = self.app.client.premium
        station = STATION_NAMES.get(self.app.network, self.app.network)
        tier = None if premium is None else ACCOUNT_TIERS[premium]
        line = " · ".join(part for part in (email, station, tier) if part)
        return f"{line}\n{ACCOUNT_FREE_HINT}" if premium is False else line


_SECTIONS: list[tuple[str, type[_SettingsSection]]] = [
    ("General", _GeneralSection),
    ("Audio Output", _AudioSection),
    ("Playback", _PlaybackSection),
]


class SettingsScreen(DialogScreen):
    DEFAULT_CSS = """
SettingsScreen {
    #settings-dialog {
        width: 80%;
    }

    #settings-layout {
        height: 1fr;
    }

    #settings-nav {
        width: 20;
        max-width: 40%;
        height: 1fr;
        border-right: solid $primary;
    }

    #settings-detail {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        background: $surface;
    }

    _SettingsSection {
        height: auto;
    }

    .setting-label {
        margin-top: 1;
        color: $text-muted;
    }

    Select {
        width: 100%;
        margin-bottom: 1;
    }
}
    """

    def __init__(self) -> None:
        super().__init__()
        self._audio_changed = False

    def compose(self) -> ComposeResult:
        settings = self.app.settings
        with Vertical(id="settings-dialog", classes="modal-dialog"):
            with Horizontal(id="settings-layout"):
                with ListView(id="settings-nav"):
                    for label, _ in _SECTIONS:
                        yield ListItem(Label(label))
                with VerticalScroll(id="settings-detail"):
                    for _, section_cls in _SECTIONS:
                        yield section_cls(settings)
            yield Footer()

    def on_mount(self) -> None:
        self._show_section(0)
        self.query_one(ListView).focus()
        from ..widgets.playback_bar import PlaybackBar

        self.app.query_one(PlaybackBar).request_devices(
            self.query_one(_AudioSection).set_devices
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self._show_section(event.list_view.index or 0)

    def dismiss(self, result: bool | None = None) -> AwaitComplete:
        # Both escape (action_dismiss) and click-out dismiss without an explicit
        # result; inject the audio-changed flag so the app can hand the saved
        # device/sample-rate/latency to the player.
        return super().dismiss(self._audio_changed if result is None else result)

    def on_select_changed(self, event: Select.Changed) -> None:
        field = _SETTING_MAP.get(event.select.id or "")
        if not field:
            return
        value: object = event.value
        if value is Select.NULL:
            if event.select.id == "device-select":
                value = None  # blank device → system default
            else:
                return
        elif event.select.id == "sample-rate-select" and value == _SAMPLE_RATE_AUTO:
            value = None  # auto sentinel → None in settings
        settings = self.app.settings
        if getattr(settings, field) == value:
            return
        settings.set(**{field: value})
        if field in _AUDIO_SETTING_FIELDS:
            self._audio_changed = True

    def _show_section(self, index: int) -> None:
        for i, section in enumerate(self.query_one("#settings-detail").children):
            section.display = i == index
