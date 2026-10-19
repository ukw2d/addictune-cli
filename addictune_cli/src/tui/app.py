import logging
from collections.abc import Iterable
from typing import Any

from addictune_sdk import Client
from addictune_sdk.models.mixshow import ShowEpisode
from addictune_sdk.models.playlist import Playlist
from textual import work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.screen import Screen
from textual.theme import Theme
from textual.widgets import Header, Input, ListView, Static, Tab, Tabs

from ..audio.state import State
from .. import telemetry, update
from ..auth import clear_credentials, load_credentials
from ..settings import STATION_NAMES, Settings
from .command_palette import OrderedSystemCommandsProvider
from .services.following import (
    ChannelFollowedController,
    FollowedController,
    MixshowFollowedController,
    PlaylistFollowedController,
    RemoteListController,
    TracksController,
)
from .palettes import STATION_PALETTES, THEME_FIELDS
from .presentation import (
    APP_TITLE,
    AUTH_SIGNED_OUT,
    AUTH_SIGNED_OUT_KEPT,
    BINDING_EXPANDED_PLAYER,
    BINDING_INFO_PANEL,
    BINDING_MUTE,
    BINDING_NEXT_TRACK,
    BINDING_PLAY_PAUSE,
    BINDING_PREVIOUS_TRACK,
    BINDING_SEEK_LEFT,
    BINDING_SEEK_RIGHT,
    BINDING_SETTINGS,
    BINDING_STOP,
    BINDING_VOLUME_DOWN,
    BINDING_VOLUME_UP,
    SIGN_OUT_BODY,
    SIGN_OUT_TITLE,
    SYSTEM_SIGN_OUT,
    SYSTEM_TOGGLE_DARK,
    SYSTEM_TOGGLE_DARK_DESCRIPTION,
    TAB_CHANNELS,
    TAB_MIXSHOWS,
    TAB_PLAYLISTS,
    TAB_TRACKS,
)
from .screens.global_search import GlobalSearchScreen
from .screens.list_options import ListOptionsScreen
from .services.auth import AuthRecoveryService
from .services.channels import ChannelsService
from .services.features import FeatureCache, NetworkFeatures
from .services.follow import FollowService
from .services.media_info import MediaInfoService
from .services.playback import PlaybackService
from .services.queue import TrackQueue
from .services.search import SearchService
from .services.votes import VoteService
from .types import ChannelView, ContentType, MediaStatusState
from .widgets.app_footer import AppFooter
from .widgets.channel_list import ChannelList
from .widgets.expanded_player import ExpandedPlayer
from .widgets.media_info import MediaInfoPanel
from .widgets.media_list import MediaList, selected_child
from .widgets.mixshow_list import MixshowItem, MixshowList
from .widgets.playback_bar import SEEK_STEP, PlaybackBar
from .widgets.playlist_list import PlaylistList
from .widgets.track_list import TrackList

_log = logging.getLogger("addictune_cli.app")

TAB_LISTS = {
    "channels": ("#channel-list", ChannelList),
    "mixshows": ("#mixshows-list", MixshowList),
    "playlists": ("#playlists-list", PlaylistList),
    "tracks": ("#tracks-list", TrackList),
}
# Channels load eagerly on startup; the other tabs load on first activation.
_LAZY_TABS = tuple(tab for tab in TAB_LISTS if tab != "channels")

# Footer shows these only while they can do something.
_PLAYBACK_ACTIONS = frozenset(
    {
        "toggle_playback",
        "stop",
        "seek_backward",
        "seek_forward",
        "previous_track",
        "next_track",
    }
)


class AddictuneApp(App):
    TITLE = APP_TITLE
    COMMANDS = {OrderedSystemCommandsProvider}
    BINDINGS = [
        Binding(
            "e",
            "toggle_expanded",
            BINDING_EXPANDED_PLAYER,
            key_display="E",
            tooltip="Open / close expanded player",
        ),
        Binding(
            "i",
            "toggle_info",
            BINDING_INFO_PANEL,
            key_display="I",
            tooltip="Open / close media info",
        ),
        Binding(
            "f", "toggle_follow_selected", "Follow / unfollow selected item", show=False
        ),
        Binding("ctrl+f", "list_options", "Filter", key_display="^F"),
        Binding(
            "slash",
            "focus_local_search",
            "Find",
            key_display="/",
            tooltip="Current list",
        ),
        # Ctrl+/ never reaches stdin in many terminals (macOS Terminal.app swallows
        # it); Ctrl+G is the primary shortcut, ctrl+underscore the alias
        # some terminals send for Ctrl+/.
        Binding(
            "ctrl+g,ctrl+underscore",
            "global_search",
            "Search",
            key_display="^G",
            tooltip="All categories",
        ),
        Binding("escape", "cancel_local_search", "Close Search", show=False),
        Binding("ctrl+u", "clear_local_search", "Clear", show=False),
        Binding(
            "space",
            "toggle_playback",
            BINDING_PLAY_PAUSE,
            key_display="Space",
            tooltip="Play / pause / stop",
        ),
        Binding("s", "stop", BINDING_STOP, key_display="S"),
        Binding("m", "toggle_mute", BINDING_MUTE, show=False),
        Binding("plus", "volume_up", BINDING_VOLUME_UP, show=False),
        Binding("=", "volume_up", BINDING_VOLUME_UP, show=False),
        Binding("minus", "volume_down", BINDING_VOLUME_DOWN, show=False),
        Binding(
            "left",
            "seek_backward",
            f"-{SEEK_STEP}s",
            key_display=BINDING_SEEK_LEFT,
            priority=True,
            show=False,
        ),
        Binding(
            "right",
            "seek_forward",
            f"+{SEEK_STEP}s",
            key_display=BINDING_SEEK_RIGHT,
            priority=True,
            show=False,
        ),
        Binding("p", "previous_track", BINDING_PREVIOUS_TRACK, key_display="P"),
        Binding("n", "next_track", BINDING_NEXT_TRACK, key_display="N"),
        Binding("l", "vote('up')", "Like / unlike current track", show=False),
        Binding("d", "vote('down')", "Dislike / remove dislike", show=False),
        # Hidden: the bar's heart marker and the expanded player's chip already show it.
        Binding(
            "ctrl+l",
            "toggle_live_show_follow",
            "Follow / unfollow airing show",
            show=False,
        ),
    ]
    CSS_PATH = "styles/app.tcss"

    network: reactive[str] = reactive("di", init=False)
    content_type: reactive[ContentType] = reactive(ContentType.LIVE, bindings=True)
    track_queue: reactive[TrackQueue | None] = reactive(None, bindings=True, init=False)

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        # Seed without firing watch_network: on_mount owns the initial load.
        self.set_reactive(AddictuneApp.network, self.settings.station_slug)
        self.client = Client()
        self.user_id: int | None = None
        # Set once by check_for_update; About reads it for the rest of the session.
        self.available_update: update.Release | None = None
        self.playing_episode_id: int | None = None
        self._playing_channel_id: int | None = None
        self._channels: list[ChannelView] = []
        self._statuses_by_channel: dict[int, MediaStatusState] = {}
        self._statuses_by_show: dict[int, MediaStatusState] = {}
        self._live_by_channel: dict[int, MediaStatusState] = {}
        self._now_playing_by_channel: dict[int, MediaStatusState] = {}
        self._next_show_by_channel: dict[int, ShowEpisode] = {}
        self._feature_availability = NetworkFeatures()
        self._feature_cache = FeatureCache()
        self._followed_controllers: dict[str, FollowedController] = {
            "channels": ChannelFollowedController(self),
            "mixshows": MixshowFollowedController(self),
            "playlists": PlaylistFollowedController(self),
            "tracks": TracksController(self),
        }
        self._search = SearchService(self)
        self._votes = VoteService(self)
        self._auth_service = AuthRecoveryService(self)
        self._media_info = MediaInfoService(self)
        self._follow = FollowService(self)
        self._channels_service = ChannelsService(self)
        self._playback_service = PlaybackService(self)

    # ── Lifecycle ────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-content"):
            yield Tabs(
                Tab(TAB_CHANNELS, id="channels"),
                Tab(TAB_MIXSHOWS, id="mixshows"),
                Tab(TAB_PLAYLISTS, id="playlists"),
                Tab(TAB_TRACKS, id="tracks"),
            )
            with Horizontal(id="local-search-bar"):
                yield Input(
                    placeholder="Search",
                    id="local-search-input",
                    classes="search-input",
                )
            yield Static("", id="filter-bar")
            yield Static("", id="empty-results", classes="empty-state")
            yield ChannelList(id="channel-list", classes="app-content-list")
            yield MixshowList(id="mixshows-list", classes="app-content-list")
            yield PlaylistList(id="playlists-list", classes="app-content-list")
            yield TrackList(id="tracks-list", classes="app-content-list")
        yield MediaInfoPanel()
        yield ExpandedPlayer(id="expanded-player")
        yield PlaybackBar(settings=self.settings, id="playback-bar").data_bind(
            AddictuneApp.content_type
        )
        yield AppFooter()

    async def on_mount(self) -> None:
        for slug, palette in STATION_PALETTES.items():
            colors: dict[str, Any] = {
                k: v for k, v in palette.items() if k in THEME_FIELDS
            }
            self.register_theme(
                Theme(
                    name=f"station-{slug}",
                    **colors,
                    success="#09bd5f",
                    warning="#f5a623",
                    error="#f44741",
                    dark=True,
                    variables={"footer-key-foreground": palette["key"]}
                    if "key" in palette
                    else {},
                )
            )
        self.title = STATION_NAMES.get(self.network, APP_TITLE)
        self._apply_station_theme(self.network)
        telemetry.set_network(self.network)
        self.query_one(Tabs).active = self.settings.default_tab
        if self.settings.update_check:
            self.check_for_update()
        if load_credentials() is not None:
            self.call_after_refresh(self.load_channels)
            self._prompt_station_selection_if_needed()
        else:
            self._prompt_login()

    def _handle_exception(self, error: Exception) -> None:
        # Textual's (private) funnel for every unhandled exception in handlers
        # and workers; re-check the signature when upgrading Textual.
        telemetry.capture(error)
        super()._handle_exception(error)

    def set_telemetry(self, enabled: bool) -> None:
        """Apply the Settings toggle now: this process at once, the player on respawn."""
        self.settings.set(telemetry=enabled)
        telemetry.init("app", enabled)
        telemetry.set_network(self.network)
        self.query_one(PlaybackBar).restart_player_when_idle()

    async def on_unmount(self) -> None:
        self.settings.flush()
        await self.client.close()

    async def watch_network(self, network: str) -> None:
        # Only fires on a runtime switch; the startup value is seeded with set_reactive.
        self.title = STATION_NAMES.get(network, APP_TITLE)
        self._apply_station_theme(network)
        telemetry.set_network(network)
        await self._channels_service.watch_network()

    def _apply_station_theme(self, slug: str) -> None:
        self.theme = f"station-{slug}" if slug in STATION_PALETTES else "textual-dark"

    @property
    def playback_active(self) -> bool:
        return self.query_one(PlaybackBar).state != State.STOPPED

    # ── Workers (bodies live in the services; @work needs a DOM node) ─────

    @work(exclusive=True, group="update")
    async def check_for_update(self) -> None:
        import httpx

        # Every installed build is a prerelease today, so offer them; flip to
        # update.CURRENT.is_prerelease once a stable release exists.
        async with httpx.AsyncClient() as http:
            release = await update.check(http, update.CURRENT, prereleases=True)
        if release is None:
            return
        self.available_update = release
        self.notify(
            f"addictune-cli {release.version} is out (you have {update.CURRENT}). "
            "Open About for the release page.",
            title="Update available",
        )

    @work(exclusive=True)
    async def load_channels(self, _reauth: bool = True) -> None:
        await self._channels_service.load_channels_body(_reauth)

    @work(exclusive=True, group="features")
    async def refresh_feature_availability(self) -> None:
        network = self.network
        features = await self._feature_cache.detect(
            self.client, network, user_id=self.user_id
        )
        if network == self.network:
            self._feature_availability = features
            self._sync_feature_tabs()

    @work(exclusive=True)
    async def load_mixshow_info(self, item: MixshowItem, network: str) -> None:
        await self._media_info.refresh_mixshow_info(item, network)

    @work(exclusive=True)
    async def load_channel_history(self, channel_id: int, network: str) -> None:
        await self._media_info.refresh_channel_history(channel_id, network)

    @work(exclusive=True)
    async def play_latest_mixshow_episode(self, show, network: str) -> None:
        await self._playback_service.play_latest_mixshow_episode_body(show, network)

    @work(exclusive=True)
    async def play_playlist(self, playlist: Playlist, network: str) -> None:
        await self._playback_service.play_playlist_body(playlist, network)

    @work(exclusive=True)
    async def play_track_queue_item(self, queue: TrackQueue) -> None:
        await self._playback_service.play_track_queue_item_body(queue)

    @work(exclusive=True)
    async def load_next_playlist_window(self, queue: TrackQueue) -> None:
        await self._playback_service.load_next_playlist_window_body(queue)

    @work(group="playlist-events")
    async def record_playlist_event(
        self,
        network: str,
        playlist_id: int,
        track_id: int,
        *,
        skipped: bool,
        length: int | None,
    ) -> None:
        await self._playback_service.record_playlist_event_body(
            network, playlist_id, track_id, skipped=skipped, length=length
        )

    @work
    async def _fetch_vote_state(self, track_id: int) -> None:
        await self._votes.fetch_vote_state(track_id)

    @work
    async def _fetch_live_show_follow_state(self, show_id: int) -> None:
        await self._follow.fetch_live_show_follow_state(show_id)

    @work
    async def _do_vote(self, direction: str) -> None:
        await self._votes.cast(direction)

    @work(exclusive=True)
    async def set_item_followed(
        self,
        controller: FollowedController,
        item: object,
        followed: bool,
        user_id: int,
        network: str,
    ) -> None:
        await self._follow.run_followed_update(
            controller, item, followed, user_id, network
        )

    @work(exclusive=True)
    async def set_live_show_followed(
        self,
        show_id: int,
        name: str,
        followed: bool,
        previous: bool | None,
        user_id: int,
        network: str,
    ) -> None:
        await self._follow.run_live_show_follow_update(
            show_id, name, followed, previous, user_id, network
        )

    # ── Messages ─────────────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self._media_info.on_list_view_highlighted(event)

    def on_channel_list_channel_selected(
        self, msg: ChannelList.ChannelSelected
    ) -> None:
        self._playback_service.on_channel_list_channel_selected(msg)

    def on_mixshow_list_show_selected(self, msg: MixshowList.ShowSelected) -> None:
        self._playback_service.on_mixshow_list_show_selected(msg)

    def on_playlist_list_playlist_selected(
        self, msg: PlaylistList.PlaylistSelected
    ) -> None:
        self._playback_service.on_playlist_list_playlist_selected(msg)

    def on_track_list_track_selected(self, msg: TrackList.TrackSelected) -> None:
        self._playback_service.on_track_list_track_selected(msg)

    def on_track_list_page_loaded(self, message: TrackList.PageLoaded) -> None:
        self._playback_service.on_track_list_page_loaded(message)

    def on_playback_bar_icy_title_changed(
        self, message: PlaybackBar.IcyTitleChanged
    ) -> None:
        self._channels_service.live.title_changed(message.title)

    def on_playback_bar_state_changed(self, message: PlaybackBar.StateChanged) -> None:
        self._playback_service.on_playback_bar_state_changed(message)

    def on_playback_bar_stopped(self, message: PlaybackBar.Stopped) -> None:
        self._playback_service.on_playback_bar_stopped(message)

    def on_playback_bar_play_requested(self, _: PlaybackBar.PlayRequested) -> None:
        self._playback_service._play_current()

    def on_playback_bar_pause_requested(self, _: PlaybackBar.PauseRequested) -> None:
        self._playback_service._pause_current()

    def on_playback_bar_toggle_play_requested(
        self, _: PlaybackBar.TogglePlayRequested
    ) -> None:
        self._playback_service._toggle_current_playback()

    def on_playback_bar_track_changed(self, message: PlaybackBar.TrackChanged) -> None:
        if message.track_id is not None and self.user_id is not None:
            self._fetch_vote_state(message.track_id)

    def on_playback_bar_live_show_changed(
        self, message: PlaybackBar.LiveShowChanged
    ) -> None:
        if message.show_id is not None and self.user_id is not None:
            self._fetch_live_show_follow_state(message.show_id)

    def on_global_search_screen_result_selected(
        self, message: GlobalSearchScreen.ResultSelected
    ) -> None:
        message.stop()
        self._search.dispatch_global_search_result(message.result)

    async def on_list_options_screen_option_changed(
        self, message: ListOptionsScreen.OptionChanged
    ) -> None:
        controller = self._active_followed_controller()
        if controller is not None:
            await controller.apply_option(
                message.group_id, message.choice_id, message.value
            )
        self._search.sync_filter_bar()
        self._media_info.sync_open_media_info()
        self.refresh_bindings()

    async def on_input_changed(self, event: Input.Changed) -> None:
        await self._search.on_input_changed(event)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._search.on_input_submitted(event)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab = event.tab.id
        if not self._tab_available(tab):
            self._activate_first_available_tab()
            return
        if not self._search.sync_empty_results():
            self.query_one(TAB_LISTS[tab][0]).focus()
        self._search.sync_local_search_bar()
        self._search.sync_filter_bar()
        self._load_lazy_tab_if_needed(tab)
        self._playback_service._notify_playback_changed()
        self._media_info.sync_open_media_info()
        self.refresh_bindings()

    # ── Actions ──────────────────────────────────────────────────

    def action_toggle_info(self) -> None:
        self._media_info.toggle_info()

    def action_toggle_playback(self) -> None:
        self._playback_service._toggle_current_playback()

    def action_stop(self) -> None:
        self.query_one(PlaybackBar).stop()

    def action_toggle_mute(self) -> None:
        self.query_one(PlaybackBar).toggle_mute()

    def action_toggle_expanded(self) -> None:
        expanded = self.query_one(ExpandedPlayer)
        expanded.close() if expanded.is_open else expanded.open()

    def action_volume_up(self) -> None:
        self.query_one(PlaybackBar).volume_up()

    def action_volume_down(self) -> None:
        self.query_one(PlaybackBar).volume_down()

    def action_seek_backward(self) -> None:
        self.query_one(PlaybackBar).seek(-SEEK_STEP)

    def action_seek_forward(self) -> None:
        self.query_one(PlaybackBar).seek(SEEK_STEP)

    def action_previous_track(self) -> None:
        self._playback_service.action_previous_track()

    def action_next_track(self) -> None:
        self._playback_service.action_next_track()

    def action_vote(self, direction: str) -> None:
        self._do_vote(direction)

    def action_toggle_follow_selected(self) -> None:
        self._follow.toggle_selected()

    def action_toggle_live_show_follow(self) -> None:
        self._follow.toggle_live_show_follow()

    def action_list_options(self) -> None:
        controller = self._active_followed_controller()
        if controller is not None:
            self.push_screen(ListOptionsScreen(controller.filter.option_groups()))

    def action_global_search(self) -> None:
        self.push_screen(GlobalSearchScreen())

    async def action_focus_local_search(self) -> None:
        await self._search.focus_local_search()

    async def action_cancel_local_search(self) -> None:
        await self._search.cancel_local_search()

    async def action_clear_local_search(self) -> None:
        await self._search.clear_local_search()

    def action_settings(self) -> None:
        from .screens.settings import SettingsScreen

        def on_dismiss(audio_changed: object) -> None:
            if audio_changed:
                self.query_one(PlaybackBar).apply_audio_settings()

        self.push_screen(SettingsScreen(), on_dismiss)

    def action_choose_station(self) -> None:
        from .screens.station_select import StationSelectScreen

        def on_selected(slug: str | None) -> None:
            if slug:
                self.settings.set(station_selected=True, station_slug=slug)
                self.network = slug

        self.push_screen(StationSelectScreen(current=self.network), on_selected)

    def action_toggle_dark(self) -> None:
        self.theme = "textual-light" if self.theme == "textual-dark" else "textual-dark"

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            SYSTEM_TOGGLE_DARK, SYSTEM_TOGGLE_DARK_DESCRIPTION, self.action_toggle_dark
        )
        yield SystemCommand(
            BINDING_SETTINGS,
            "Configure audio output, startup tab and playback options",
            self.action_settings,
        )
        yield SystemCommand(
            "Choose radio station",
            "Switch the active AudioAddict radio station",
            self.action_choose_station,
        )
        yield SystemCommand(
            "About", "Version, links and credits", self.action_about
        )
        if self.user_id is not None or load_credentials() is not None:
            yield SystemCommand(
                SYSTEM_SIGN_OUT,
                "Forget the saved login and return to the login screen",
                self.action_sign_out,
            )

    def action_sign_out(self) -> None:
        from .screens.dialog import ConfirmScreen

        self.push_screen(
            ConfirmScreen(
                SIGN_OUT_TITLE.format(station=STATION_NAMES.get(self.network, "")),
                SIGN_OUT_BODY,
                SYSTEM_SIGN_OUT,
            ),
            lambda confirmed: self._sign_out() if confirmed else None,
        )

    @work(exclusive=True, group="sign-out")
    async def _sign_out(self) -> None:
        """Forget the account everywhere it lives, then ask for a login."""
        # Workers still using the old session must end before it is torn down:
        # a feature probe would re-cache the old account's tabs after the
        # clear, and a list page failing on a closed client exits the app.
        # Workers on other nodes (list pages) are discarded by reset_views().
        self.workers.cancel_group(self, "default")
        self.workers.cancel_group(self, "features")
        self.workers.cancel_group(self, "live-status")
        bar = self.query_one(PlaybackBar)
        bar.forget_stream()
        removed = clear_credentials()
        self.user_id = None
        self._playing_channel_id = None
        self.track_queue = None
        self.playing_episode_id = None
        self._feature_cache.clear()
        self._follow.clear()
        await self._channels_service.reset_views()
        old_client, self.client = self.client, Client()
        await old_client.close()
        while len(self.screen_stack) > 1:
            await self.screen.dismiss()
        self._prompt_login(AUTH_SIGNED_OUT if removed else AUTH_SIGNED_OUT_KEPT)

    def action_about(self) -> None:
        from .screens.about import AboutScreen

        self.push_screen(AboutScreen())

    # ── Binding availability (Textual hooks; AppFooter reads the two footer_* ones) ──

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        bar = self.query_one(PlaybackBar)
        is_live = self.content_type == ContentType.LIVE
        queue = self.track_queue
        controller = self._active_followed_controller()
        item = self._selected_list_item()
        on_modal = len(self.screen_stack) > 1
        if action in _PLAYBACK_ACTIONS and not self.playback_active:
            resumable = (
                is_live
                and self._playing_channel_id is not None
                and bar.current_url is not None
            )
            startable = self.query_one(Tabs).active == "mixshows" and isinstance(
                item, MixshowItem
            )
            if not (action == "toggle_playback" and (resumable or startable)):
                return False
        match action:
            case "toggle_follow_selected":
                return (
                    controller is not None
                    and self.user_id is not None
                    and controller.followed(item) is not None
                )
            case "list_options":
                return controller is not None and not on_modal
            case "focus_local_search":
                return (
                    controller is not None
                    and controller.searchable
                    and not self._search.local_search_has_focus()
                    and not on_modal
                )
            case "global_search":
                return not on_modal
            case "cancel_local_search":
                return self._search.local_search_open
            case "clear_local_search":
                return (
                    self._search.local_search_open
                    and self._search.active_search_query() != ""
                )
            case "stop" | "seek_backward" | "seek_forward":
                return not is_live
            case "previous_track":  # D16: any queue, never a live channel
                return queue is not None and queue.has_previous
            case "next_track":
                return (
                    not is_live
                    and queue is not None
                    and (
                        queue.has_more
                        or queue.kind == "playlist"
                        or (queue.kind == "track" and self._tracks_have_more())
                    )
                )
            case "vote":
                return bar.track_id is not None
            case "toggle_live_show_follow":
                return (
                    is_live
                    and bar.live_show_id is not None
                    and self.user_id is not None
                    and bar.live_show_followed is not None
                )
        return True

    def footer_action_visible(self, action: str, disabled: bool) -> bool:
        return action not in _PLAYBACK_ACTIONS or not disabled

    def footer_description_for_action(self, action: str, description: str) -> str:
        if action != "toggle_playback":
            return description
        playing = self.query_one(PlaybackBar).state in {State.LOADING, State.PLAYING}
        if self.content_type == ContentType.LIVE:
            return "Stop" if playing else "Play"
        return "Pause" if playing else "Play"

    def _tracks_have_more(self) -> bool:
        return self.query_one("#tracks-list", TrackList).can_load_more

    # ── Auth ─────────────────────────────────────────────────────

    async def ensure_authenticated_session(self, network: str) -> bool:
        return await self._auth_service.ensure_authenticated_session(network)

    async def recover_auth(self, network: str | None = None) -> bool:
        return await self._auth_service.recover_auth(network)

    def _prompt_login(self, notice: str = "") -> None:
        from .screens.auth import AuthScreen

        if not isinstance(self.screen, AuthScreen):
            self.push_screen(AuthScreen(notice), self._on_auth)

    def _on_auth(self, user_id: int | None) -> None:
        _log.info("_on_auth signed_in=%s network=%r", user_id is not None, self.network)
        if user_id is not None:
            self.user_id = user_id
            self.call_after_refresh(self.load_channels)
            self._prompt_station_selection_if_needed()
        elif self.user_id is None:
            self.exit()  # no usable session and the login prompt was dismissed

    def _prompt_station_selection_if_needed(self) -> None:
        if not self.settings.station_selected:
            self.call_after_refresh(self.action_choose_station)

    # ── Tabs ─────────────────────────────────────────────────────

    def _tab_available(self, tab_id: str | None) -> bool:
        return bool(tab_id) and self._feature_availability.available(tab_id)

    def _available_tabs(self) -> tuple[str, ...]:
        return tuple(tab for tab in TAB_LISTS if self._tab_available(tab))

    def _activate_first_available_tab(self) -> None:
        if available := self._available_tabs():
            tabs = self.query_one(Tabs)
            if tabs.active != available[0]:
                tabs.active = available[0]

    def _sync_feature_tabs(self) -> None:
        tabs = self.query_one(Tabs)
        for tab_id in _LAZY_TABS:
            available = self._tab_available(tab_id)
            tab = tabs.query_one(f"#{tab_id}", Tab)
            tab.disabled = not available
            tab.display = available
            if not available:
                selector, list_type = TAB_LISTS[tab_id]
                self.query_one(selector, list_type).reset()
        if not self._tab_available(tabs.active):
            self._activate_first_available_tab()
        else:
            self._load_lazy_tab_if_needed(tabs.active)
        self._search.sync_empty_results()
        self._search.sync_filter_bar()
        self.refresh_bindings()

    def _load_lazy_tab_if_needed(self, tab: str | None) -> None:
        if tab is None or tab not in _LAZY_TABS or not self._tab_available(tab):
            return
        selector, list_type = TAB_LISTS[tab]
        widget = self.query_one(selector, list_type)
        if len(widget) or widget.is_loading or widget.is_exhausted:
            return
        controller = self._followed_controllers[tab]
        assert isinstance(controller, RemoteListController)
        controller.load()

    def _retry_lazy_list_after_auth(self, widget: MediaList) -> None:
        """A lazy list hit an auth error and the session was recovered: reload it."""
        tab = self.query_one(Tabs).active
        if tab in _LAZY_TABS and self.query_one(TAB_LISTS[tab][0]) is widget:
            widget.reset()
            self._load_lazy_tab_if_needed(tab)

    # ── Selection helpers (read by the services) ─────────────────

    def _active_followed_controller(self) -> FollowedController | None:
        return self._followed_controllers.get(self.query_one(Tabs).active)

    def _selected_list_item(self):
        if target := TAB_LISTS.get(self.query_one(Tabs).active):
            return self._list_item(*target)
        return None

    def _list_item(self, selector: str, list_type: type[ListView]):
        return selected_child(self.query_one(selector, list_type))
