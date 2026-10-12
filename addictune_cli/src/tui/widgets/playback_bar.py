import logging
import re


from addictune_sdk import AddictuneError
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from ...audio.client import PlayerClient
from ...audio.output import OutputConfig
from ...audio.protocol import AudioStreamInfo
from ...audio.state import State
from ...logging_setup import redact_url
from ...media.session import (
    Command,
    MediaInfo,
    MediaSession,
    NullSession,
    make_session,
)
from ..services.clock import PlaybackClock
from ..services.playback_policy import (
    BackendCommand,
    BackendPlay,
    BackendStop,
    PlaybackController,
    ScheduleRetry,
)
from ...auth import is_auth_failure
from ...settings import Settings
from ..services.live_resolver import LiveInfo
from ..presentation import (
    INITIAL_TIME_LABEL,
    PLAYBACK_ERROR_TIMEOUT,
    PLAYBACK_FAILED,
    PLAYBACK_RECONNECTING,
    PLAYBACK_SEPARATOR,
    PLAYBACK_STATE_ICONS,
    PLAYBACK_STOPPED_PLACEHOLDER,
)
from ..typed_nodes import AppNode
from ..types import ContentType
from .content_type_label import apply_content_type_label
from .live_show_follow import apply_live_show_follow_marker
from .marquee_text import MarqueeText
from .playback_format import (
    StreamQuality,
    format_stream_quality,
    format_time_pair,
    format_volume_label,
    stream_quality_from_url,
)

_MAX_VOLUME = 100
_DEFAULT_VOLUME = round(Settings().volume * _MAX_VOLUME)

# OS now-playing widgets render artwork far larger than the terminal preview, so
# request a generously sized square from the CDN to keep it crisp.
_ARTWORK_SIZE = 512


def _hires_artwork_url(url: str | None, size: int = _ARTWORK_SIZE) -> str:
    """Return *url* with the CDN size bumped up for the OS media widget."""
    if not url:
        return ""
    if "size=" in url:
        return re.sub(r"size=\d+", f"size={size}", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}size={size}"


_VOLUME_STEP = 5
SEEK_STEP = 10
_log = logging.getLogger("addictune_cli.playback_bar")


def output_config(settings: Settings) -> OutputConfig:
    return OutputConfig(
        device_name=settings.audio_device_name,
        sample_rate=settings.audio_sample_rate,
        latency=settings.audio_latency,
    )


class PlaybackBar(AppNode, Widget):
    class PlayRequested(Message):
        pass

    class PauseRequested(Message):
        pass

    class TogglePlayRequested(Message):
        pass

    class Stopped(Message):
        def __init__(self, *, natural: bool = False) -> None:
            self.natural = natural
            super().__init__()

    class IcyTitleChanged(Message):
        """The bar's displayed ICY title changed; other components may react."""

        def __init__(self, title: str) -> None:
            self.title = title
            super().__init__()

    class TrackChanged(Message):
        def __init__(self, track_id: int | None) -> None:
            self.track_id = track_id
            super().__init__()

    class LiveShowChanged(Message):
        def __init__(self, show_id: int | None) -> None:
            self.show_id = show_id
            super().__init__()

    class StateChanged(Message):
        def __init__(self, state: "State") -> None:
            self.state = state
            super().__init__()

    state: reactive[State] = reactive(State.STOPPED, init=False)
    now_playing: reactive[str] = reactive("", init=False)
    channel_name: reactive[str] = reactive("", init=False)
    next_playing: reactive[str] = reactive("", init=False)
    track_id: reactive[int | None] = reactive(None, init=False)
    track_image_url: reactive[str | None] = reactive(None, init=False)
    live_show_id: reactive[int | None] = reactive(None, init=False)
    live_show_name: reactive[str] = reactive("", init=False)
    live_show_followed: reactive[bool | None] = reactive(None, init=False)
    vote_state: reactive[str | None] = reactive(None, init=False)
    volume: reactive[int] = reactive(_DEFAULT_VOLUME, init=False)
    muted: reactive[bool] = reactive(False, init=False)
    content_type: reactive[ContentType] = reactive(ContentType.LIVE)
    elapsed_seconds: reactive[int] = reactive(0, init=False)
    duration_seconds: reactive[int | None] = reactive(None, init=False)
    stream_quality: reactive[StreamQuality | None] = reactive(None, init=False)

    def __init__(
        self,
        settings: Settings,
        media_session: MediaSession | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._settings = settings
        self._player = PlayerClient(
            dispatch=self._dispatch,
            on_state=self._on_player_state,
            on_error=self._on_player_error,
            on_position=self._on_player_position,
            on_info=self._on_player_info,
            on_title=self.set_icy_title,
            config=output_config(self._settings),
        )
        self._controller = PlaybackController()
        self._media_session = media_session
        self._media_session_started = False
        self.icy_title: str | None = None
        self._clock = PlaybackClock()
        self._elapsed_timer = None
        self._volume_label: str | None = None
        self._time_label: str | None = None
        # Why the last backend attempt failed, carried from the exit that
        # reported it to whichever handler decides playback is over.
        self._failure_detail: str | None = None
        self._failure_fatal = False

    def compose(self) -> ComposeResult:
        yield Label(PLAYBACK_STATE_ICONS[State.STOPPED], id="state-icon")
        yield Label("Stopped", id="stopped-hint")
        yield Label("", id="type-label")
        yield Label("", id="live-show-follow")
        yield Label(PLAYBACK_SEPARATOR, id="sep-playing", classes="playback-separator")
        yield MarqueeText(id="now-playing")
        with Horizontal(id="playback-right"):
            yield Label(
                format_volume_label(self.volume, muted=False), id="volume-label"
            )
            yield Label(PLAYBACK_SEPARATOR, id="sep-time", classes="playback-separator")
            yield Label(INITIAL_TIME_LABEL, id="time-label")

    def on_mount(self) -> None:
        self._sync_media_session()
        self.volume = round(self._settings.volume * _MAX_VOLUME)

    def on_unmount(self) -> None:
        command = self._controller.stop(post_stopped=False)
        self._execute_backend_command(command)
        self._stop_elapsed_timer()
        if self._media_session_started:
            self._media_session.stop()
        self._player.close()

    def watch_state(self, value: State) -> None:
        self.post_message(self.StateChanged(value))
        self.query_one("#state-icon", Label).update(PLAYBACK_STATE_ICONS[value])
        self.set_class(value != State.STOPPED, "-active")
        if value == State.PLAYING:
            self._start_elapsed_timer()
        elif value == State.PAUSED:
            self._pause_elapsed_timer()
        elif value == State.STOPPED:
            self._reset_time(clear_duration=True)
            self.stream_quality = None
            self.set_next_playing()
        else:
            self._stop_elapsed_timer()
        self._sync_media_session()

    def watch_now_playing(self, value: str) -> None:
        self.query_one("#now-playing", MarqueeText).text = value
        self._sync_media_session()

    def watch_channel_name(self, value: str) -> None:
        self._sync_media_session()

    def watch_track_image_url(self, value: str | None) -> None:
        self._sync_media_session()

    def watch_track_id(self, value: int | None) -> None:
        self.vote_state = None
        self.post_message(self.TrackChanged(value))
        self.app.refresh_bindings()

    def apply_track(self, *, track_id: int | None, image_url: str | None) -> None:
        """Single owner for the (track_id, track_image_url) pair.

        Every producer of "what track is currently associated with
        playback" -- the channel-routine match, the scheduled live episode,
        an on-demand mixshow/playlist/track item, or a reset to nothing --
        must go through here so the two reactives can never disagree about
        which track they describe.
        """
        self.track_id = track_id
        self.track_image_url = image_url

    def watch_live_show_id(self, value: int | None) -> None:
        # Follow state is fetched separately (it needs a round trip; id/name
        # don't), so a show change must invalidate the old value rather than
        # briefly showing the previous show's follow state as this one's --
        # same reasoning as watch_track_id resetting vote_state above.
        self.live_show_followed = None
        self.post_message(self.LiveShowChanged(value))
        self._refresh_live_show_marker()

    def watch_live_show_followed(self, _value: bool | None) -> None:
        self._refresh_live_show_marker()

    def _refresh_live_show_marker(self) -> None:
        if not self.is_mounted:
            return
        apply_live_show_follow_marker(
            self.query_one("#live-show-follow", Label),
            show_id=self.live_show_id,
            show_name=self.live_show_name,
            followed=self.live_show_followed,
            content_type=self.content_type,
        )

    def apply_live_show(self, *, show_id: int | None, name: str) -> None:
        """Single owner for the (live_show_id, live_show_name) pair.

        Every producer of "which live show is airing now" -- ChannelsService
        resolving the schedule, a reset to nothing, or starting a fresh play
        -- must go through here so the two reactives can never disagree about
        which show they describe.
        """
        self.live_show_id = show_id
        self.live_show_name = name

    def set_next_playing(self, text: str = "") -> None:
        """Single owner for the next_playing reactive.

        Every producer of "what's coming up next" -- the live-schedule
        lookahead in ChannelsService, a stop, or starting a fresh play --
        must go through here, so a reset can't race the real computation
        for the last write.
        """
        self.next_playing = text

    def watch_vote_state(self, value: str | None) -> None:
        icons = {"up": " ▲ ", "down": " ▼ "}
        self.query_one("#now-playing", MarqueeText).suffix = icons.get(value, "")
        self.app.refresh_bindings()

    def watch_content_type(self, value: ContentType) -> None:
        if self.is_mounted:
            apply_content_type_label(self.query_one("#type-label", Label), value)
        self._refresh_time_label()
        self._refresh_live_show_marker()

    def watch_elapsed_seconds(self) -> None:
        self._refresh_time_label()

    def watch_duration_seconds(self) -> None:
        self._refresh_time_label()

    def watch_volume(self, value: int) -> None:
        if not self.muted:
            self._player.set_volume(self._effective_volume)
        self._refresh_volume_label()
        self._settings.set(volume=value / _MAX_VOLUME)

    def watch_muted(self, value: bool) -> None:
        self._player.set_volume(self._effective_volume)
        self.query_one("#volume-label").set_class(value, "muted")
        self._refresh_volume_label()

    @property
    def _effective_volume(self) -> float:
        return 0.0 if self.muted else self.volume / _MAX_VOLUME

    def request_devices(self, on_devices) -> None:
        self._player.request_devices(on_devices)

    def apply_audio_settings(self) -> None:
        """Hand the current audio settings to the player; it reopens its output in place."""
        self._player.configure(output_config(self._settings))

    def _refresh_volume_label(self) -> None:
        text = format_volume_label(self.volume, muted=self.muted)
        if text != self._volume_label:
            self.query_one("#volume-label", Label).update(text)
            self._volume_label = text

    def apply_live(self, info: LiveInfo, *, new_track: bool, seed_offset: bool) -> None:
        """Show one resolved live value: track, show, "Next:" and the clock.

        *new_track*: the ICY title changed, so the counter restarts (at the
        routine offset when known, else 0). *seed_offset*: a fresh routine
        arrived for a track already playing, so adopt its offset once. Otherwise
        only the duration is refreshed; a resync never moves the counter.
        """
        self.apply_track(track_id=info.track_id, image_url=info.image_url)
        self.apply_live_show(show_id=info.show_id, name=info.show_name)
        self.set_next_playing(info.next_show)
        running = self.state == State.PLAYING
        adopt = info.show_id is not None or new_track or seed_offset
        if adopt and info.offset is not None and info.length:
            self._clock.adopt_schedule(info.offset, info.length, running=running)
        elif new_track:
            self._clock.adopt_track(info.length, running=running)
        else:
            self._clock.set_duration(info.length)
        self._publish_clock()

    def _refresh_time_label(self) -> None:
        if not self.is_mounted:
            return
        text = format_time_pair(self.elapsed_seconds, self.duration_seconds)
        if text != self._time_label:
            self.query_one("#time-label", Label).update(text)
            self._time_label = text

    def _start_elapsed_timer(self) -> None:
        self._clock.resume()
        if self._elapsed_timer is None:
            self._elapsed_timer = self.set_interval(1.0, self._publish_clock)
        self._publish_clock()

    def _pause_elapsed_timer(self) -> None:
        self._clock.pause()
        self._stop_elapsed_timer()
        self._publish_clock()

    def _stop_elapsed_timer(self) -> None:
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer = None

    def _publish_clock(self) -> None:
        """Mirror the clock onto the reactives other widgets bind to."""
        self.elapsed_seconds = self._clock.elapsed
        self.duration_seconds = self._clock.duration

    def _reset_time(self, *, clear_duration: bool) -> None:
        self._stop_elapsed_timer()
        self._clock.reset(clear_duration=clear_duration)
        self._publish_clock()

    def _sync_media_session(self) -> None:
        stopped = self.state == State.STOPPED
        if stopped and not self._media_session_started:
            return
        self._ensure_media_session().update(
            MediaInfo(
                title=self.now_playing,
                artist=self.channel_name,
                artwork_url="" if stopped else _hires_artwork_url(self.track_image_url),
                playing=self.state == State.PLAYING,
                can_play=self._controller.current_url is not None,
                can_pause=not stopped,
                can_next=self.content_type != ContentType.LIVE,
                can_previous=self.content_type != ContentType.LIVE,
            )
        )

    def _ensure_media_session(self) -> MediaSession:
        if not self._media_session_started:
            self._media_session_started = True  # also on failure: no retry loop
            if self._media_session is None:
                self._media_session = make_session(self.call_later)
            try:
                self._media_session.start(self._on_media_command, self.set_interval)
            except Exception as exc:
                _log.warning("media session failed to start: %r", exc)
                self._media_session = NullSession()
        return self._media_session

    def _on_media_command(self, command: Command) -> None:
        match command:
            case Command.PLAY:
                self.post_message(self.PlayRequested())
            case Command.PAUSE:
                self.post_message(self.PauseRequested())
            case Command.TOGGLE:
                self.post_message(self.TogglePlayRequested())
            case Command.NEXT:
                self.app.action_next_track()
            case Command.PREVIOUS:
                self.app.action_previous_track()

    @property
    def current_url(self) -> str | None:
        return self._controller.current_url

    # ── Playback control ─────────────────────────────────────────

    def play(self, url: str, *, title: str = "") -> None:
        self._player.stop()
        self._reset_time(clear_duration=True)
        self.stream_quality = stream_quality_from_url(url)
        self.icy_title = None
        self.set_next_playing()
        self.apply_live_show(show_id=None, name="")
        self._failure_detail = None
        self._failure_fatal = False
        if self.content_type == ContentType.LIVE:
            self.apply_track(track_id=None, image_url=None)
        command = self._controller.play(url, title, self.content_type)
        self._sync_from_controller()
        self._execute_backend_command(command)

    def stop(self) -> None:
        command = self._controller.stop(post_stopped=True)
        self._sync_from_controller()
        self._execute_backend_command(command)

    def pause(self) -> None:
        self._player.pause()
        self._controller.pause()
        self._sync_from_controller()

    def resume(self) -> None:
        self._player.resume()
        self._controller.resume()
        self._sync_from_controller()

    def toggle_mute(self) -> None:
        self.muted = not self.muted

    def volume_up(self) -> None:
        self.volume = min(self.volume + _VOLUME_STEP, _MAX_VOLUME)

    def volume_down(self) -> None:
        self.volume = max(self.volume - _VOLUME_STEP, 0)

    def seek(self, seconds: int) -> None:
        if self.content_type == ContentType.LIVE or self.state == State.STOPPED:
            return
        self._player.seek(seconds)
        self._clock.seek_to(
            self._clock.clamp_seek_target(seconds),
            running=self.state == State.PLAYING,
        )
        self._publish_clock()

    async def _resolve_with_key_recovery(self, url: str) -> str:
        """Resolve *url*, refreshing an expired listen key on 403 and retrying once."""
        channels = self.app.client.network(self.app.network).channels
        _log.debug("resolving stream url=%s", redact_url(url))
        try:
            return await channels.resolve_stream_url(url)
        except AddictuneError as exc:
            if not is_auth_failure(exc) or not await self.app.recover_auth(
                self.app.network
            ):
                raise
            retry_url = (
                self.app.client.with_listen_key(url)
                if self.app.client.listen_key
                else url
            )
            _log.debug("retrying stream resolution with refreshed listen key")
            return await channels.resolve_stream_url(retry_url)

    @work(exclusive=True, group="playback-resolve")
    async def _resolve_and_play(self, command: BackendPlay) -> None:
        """Resolve the stream URL, then hand it to the player child."""
        generation = command.generation
        try:
            resolved = await self._resolve_with_key_recovery(command.url)
            _log.debug("resolved url=%s", redact_url(resolved))
        except Exception as exc:
            _log.error("stream url resolution failed: %r", exc)
            if self._controller.is_current(generation):
                # str() alone is empty on several httpx errors, so lead with the type.
                self._failure_detail = f"{type(exc).__name__}: {exc}"
                self._finish_backend_exit(self._controller.backend_exited())
            return
        if not self._controller.is_current(generation):
            return
        self._failure_detail = None
        self._failure_fatal = False
        self._player.play(
            resolved,
            live=command.content_type == ContentType.LIVE,
            volume=self._effective_volume,
        )

    # -- player child events (already on the Textual loop) --------------------

    def _dispatch(self, callback) -> None:
        try:
            self.app.call_from_thread(callback)
        except RuntimeError:
            pass  # app is shutting down

    def _on_player_state(self, state: State) -> None:
        match state:
            case State.PLAYING:
                if self._controller.state == State.LOADING:
                    self._controller.playing()
                    self._sync_from_controller()
            case State.STOPPED:
                self._finish_backend_exit(
                    self._controller.backend_exited(fatal=self._failure_fatal),
                    natural=self._failure_detail is None,
                )

    def _on_player_error(self, kind: str, message: str) -> None:
        if kind == "device_missing":
            self.app.notify(
                f"Audio device {message!r} not found; using the system default",
                severity="warning",
            )
            return
        self._failure_detail = message
        self._failure_fatal = kind == "device"

    def _on_player_position(self, seconds: float) -> None:
        if self.content_type == ContentType.LIVE:
            return
        self._clock.seek_to(int(seconds), running=self.state == State.PLAYING)
        self._publish_clock()

    def _on_player_info(self, info: AudioStreamInfo) -> None:
        if self.content_type == ContentType.LIVE:
            return
        self.stream_quality = format_stream_quality(info)
        self.set_track_duration(
            max(0, round(info.duration)) if info.duration is not None else None
        )

    def set_icy_title(self, title: str) -> None:
        if title == self.icy_title:
            return  # ignore ICY heartbeats that repeat the current title
        self.icy_title = title
        self._controller.set_icy_title(title)
        self._sync_from_controller()
        _log.info("posting IcyTitleChanged title=%r", title)
        self.post_message(self.IcyTitleChanged(title))

    def set_track_duration(self, length: int | None) -> None:
        """Attach or clear the current item's total without moving the counter."""
        self._clock.set_duration(length)
        self._publish_clock()

    def _finish_backend_exit(
        self,
        command: BackendCommand | None,
        *,
        natural: bool = False,
    ) -> None:
        """Apply the controller's verdict on a finished backend attempt."""
        self._sync_from_controller()
        match command:
            case BackendStop():
                self._notify_playback_failure()
            case ScheduleRetry(attempt=1):
                # Announce the drop once; the retries behind it stay quiet.
                self.app.notify(PLAYBACK_RECONNECTING, severity="warning")
        self._execute_backend_command(command, natural=natural)

    def _notify_playback_failure(self) -> None:
        """Surface why playback ended, unless it ended cleanly."""
        if self._failure_detail is None:
            return
        self.app.notify(
            PLAYBACK_FAILED.format(detail=self._failure_detail),
            severity="error",
            timeout=PLAYBACK_ERROR_TIMEOUT,
        )

    def _sync_from_controller(self) -> None:
        self.state = self._controller.state
        self.now_playing = self._controller.now_playing
        # A stopped channel isn't "now playing" anything -- replace the last
        # ICY-derived track/artwork with a placeholder rather than leaving it
        # stale. Scoped to LIVE so on-demand track/mixshow/playlist stops
        # (and pause, which never reaches State.STOPPED) are untouched.
        if self.state == State.STOPPED and self.content_type == ContentType.LIVE:
            self.apply_track(track_id=None, image_url=None)
            self.apply_live_show(show_id=None, name="")
            self.now_playing = PLAYBACK_STOPPED_PLACEHOLDER

    def _execute_backend_command(
        self,
        command: BackendCommand | None,
        *,
        natural: bool = False,
    ) -> None:
        match command:
            case None:
                return
            case BackendPlay() as play:
                if self._controller.is_current(play.generation):
                    self._resolve_and_play(play)
            case BackendStop(post_stopped=post_stopped):
                self._player.stop()
                if post_stopped:
                    self.post_message(self.Stopped(natural=natural))
            case ScheduleRetry(
                generation=generation,
                delay=delay,
                url=url,
                attempt=attempt,
                max_attempts=max_attempts,
            ):
                _log.info(
                    "live playback ended; retry %s/%s in %.1fs",
                    attempt,
                    max_attempts,
                    delay,
                )
                self.set_timer(
                    delay,
                    lambda: self._execute_backend_command(
                        BackendPlay(generation, url, self.content_type)
                    ),
                )
