"""Shared scaffolding for app doubles.

Several tests drive real AddictuneApp methods (``on_tabs_tab_activated``,
``check_action``, …) from a slim ``App`` subclass. Those methods delegate to
the app's services, so a double that omits one fails in a way that says
nothing about the behaviour under test — and, worse, a double that drifts
from the real app lets genuine bugs pass. ``install_services`` gives a double
the same service surface the real app builds in ``__init__``.
"""

import tempfile
from pathlib import Path

from textual.containers import Horizontal
from textual.widgets import Input, Static

from addictune_cli.src.settings import Settings

from addictune_cli.src.tui.services.channels import ChannelsService
from addictune_cli.src.tui.services.features import FeatureCache
from addictune_cli.src.tui.services.follow import FollowService
from addictune_cli.src.tui.services.media_info import MediaInfoService
from addictune_cli.src.tui.services.playback import PlaybackService
from addictune_cli.src.tui.services.search import SearchService
from addictune_cli.src.tui.services.votes import VoteService

_SERVICES = {
    "_search": SearchService,
    "_votes": VoteService,
    "_media_info": MediaInfoService,
    "_follow": FollowService,
    "_channels_service": ChannelsService,
    "_playback_service": PlaybackService,
}


# Plain state AddictuneApp.__init__ seeds. A double that omits one of these
# fails inside a service with an AttributeError that reads like a bug in the
# service rather than a gap in the double.
_STATE: dict[str, object] = {
    "network": "di",
    "user_id": None,
    "playing_episode_id": None,
    "track_queue": None,
    "_playing_channel_id": None,
    "_statuses_by_channel": dict,
    "_statuses_by_show": dict,
    "_live_by_channel": dict,
    "_now_playing_by_channel": dict,
    "_next_show_by_channel": dict,
    "_channels": list,
    "_followed_controllers": dict,
    "_feature_cache": FeatureCache,
}


def install_services(app, *, only: tuple[str, ...] | None = None) -> None:
    """Give *app* the services and state AddictuneApp builds in ``__init__``.

    Anything the double already defines is left alone, so a test can still
    override a single collaborator. Pass *only* to limit which services are
    attached; state is always seeded.
    """
    for name, default in _STATE.items():
        if not hasattr(app, name):
            setattr(app, name, default() if callable(default) else default)
    for name, service in _SERVICES.items():
        if only is not None and name not in only:
            continue
        if getattr(app, name, None) is None:
            setattr(app, name, service(app))


def app_chrome():
    """Yield the non-list widgets AddictuneApp's own methods expect to find.

    A double that borrows ``on_tabs_tab_activated`` also inherits its calls
    into SearchService and MediaInfoService, which query these by id. Composing
    them keeps the double honest instead of guarding the production code with
    ``getattr``.
    """
    from addictune_cli.src.tui.widgets.media_info import MediaInfoPanel

    with Horizontal(id="local-search-bar"):
        yield Input(placeholder="Search...", id="local-search-input")
    yield Static("", id="filter-bar")
    yield Static("", id="empty-results")
    yield MediaInfoPanel()


def temp_settings(**values: object) -> Settings:
    """A Settings bound to a throwaway file, so test bars never touch the user's config."""
    tmp = tempfile.mkdtemp()
    settings = Settings.load(Path(tmp) / "settings.json")
    settings.set(**values)
    return settings
