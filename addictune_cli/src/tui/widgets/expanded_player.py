from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ProgressBar, Static

from ...audio.state import State
from ..services.image_loader import DebouncedImageLoader
from ..presentation import (
    ANIMATION_FAST,
    CONTENT_TYPE_LABELS,
    PLAYBACK_SEPARATOR,
    PLAYBACK_STATE_ICONS,
)
from ..typed_nodes import AppNode
from ..types import ContentType
from .content_type_label import apply_content_type_label
from .live_show_follow import is_live_show_airing
from .marquee_text import MarqueeText
from .playback_format import format_time_pair, format_volume_label

_PANEL_HEIGHT_FRACTION = 0.22
_IMAGE_WIDTH = 16
_IMAGE_HEIGHT = 14
_IMAGE_ROWS = _IMAGE_HEIGHT // 2
_PANEL_HEIGHT_MIN = _IMAGE_ROWS + 2  # one padding row above and below

_PLACEHOLDER_IMAGE = "\n".join("▓" * _IMAGE_WIDTH for _ in range(_IMAGE_ROWS))

# The bar reactives this view renders.
_MIRRORED = (
    "state",
    "now_playing",
    "channel_name",
    "next_playing",
    "live_show_id",
    "live_show_name",
    "live_show_followed",
    "content_type",
    "elapsed_seconds",
    "duration_seconds",
    "volume",
    "muted",
    "vote_state",
    "track_image_url",
    "stream_quality",
)
# Words, not just colour, since the expanded view has room for them (unlike
# the bar's width-1 heart glyph) -- matching Variant A's approved wireframe.
_FOLLOW_CHIP_LABEL = "[♡ Follow]"
_FOLLOWING_CHIP_LABEL = "[♥ Following]"


class ExpandedPlayer(AppNode, Widget):
    """Slide-up expanded view for PlaybackBar — image, seekbar, volume, votes."""

    can_focus = False

    is_open: reactive[bool] = reactive(False, init=False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._bar = None
        self._image_loader = DebouncedImageLoader(
            self,
            width=_IMAGE_WIDTH,
            height=_IMAGE_HEIGHT,
            image_selector="#expanded-image",
            scope="track",
            placeholder=_PLACEHOLDER_IMAGE,
        )

    def compose(self) -> ComposeResult:
        with Horizontal(classes="expanded--row"):
            yield Static(
                _PLACEHOLDER_IMAGE, id="expanded-image", classes="expanded--image"
            )
            with Vertical(classes="expanded--controls"):
                with Horizontal(classes="expanded--header"):
                    yield Label(
                        PLAYBACK_STATE_ICONS[State.STOPPED],
                        id="expanded-state",
                        classes="expanded--state",
                    )
                    yield Label(
                        CONTENT_TYPE_LABELS[ContentType.LIVE].label,
                        id="expanded-type",
                        classes="expanded--type live",
                    )
                    yield Label("", id="expanded-quality", classes="expanded--quality")
                with Horizontal(classes="expanded--channel-row"):
                    yield MarqueeText(
                        id="expanded-channel", classes="expanded--channel"
                    )
                    yield Label("", id="expanded-follow", classes="expanded--action")
                yield Label("", id="expanded-next", classes="expanded--next")
                with Horizontal(classes="expanded--title-row"):
                    yield MarqueeText(id="expanded-title", classes="expanded--title")
                    yield Label(
                        "[▲ Like]", id="expanded-like", classes="expanded--action"
                    )
                    yield Label(
                        "[▼ Nope]", id="expanded-dislike", classes="expanded--action"
                    )
                with Horizontal(classes="expanded--seek-row"):
                    with Horizontal(classes="expanded--transport"):
                        yield Label(
                            "00:00", id="expanded-elapsed", classes="expanded--elapsed"
                        )
                        yield ProgressBar(
                            total=1.0,
                            show_percentage=False,
                            show_eta=False,
                            id="expanded-seek",
                        )
                        yield Label(
                            "--:--",
                            id="expanded-duration",
                            classes="expanded--duration",
                        )
                    with Horizontal(classes="expanded--volume-control"):
                        yield Label(
                            format_volume_label(0, muted=False),
                            id="expanded-volume",
                            classes="expanded--volume",
                        )
                        yield ProgressBar(
                            total=100.0,
                            show_percentage=False,
                            show_eta=False,
                            id="expanded-vol-bar",
                        )

    def on_mount(self) -> None:
        self._sync_layout_classes()
        self.call_after_refresh(self._bind_playback_bar)

    def on_resize(self) -> None:
        self._sync_layout_classes()

    def _sync_layout_classes(self) -> None:
        self.set_class(self.size.width < 60, "-compact")
        self.set_class(self.size.width < 42, "-narrow")

    def _bind_playback_bar(self) -> None:
        """Render whenever anything the bar shows changes; the bar owns the state."""
        self._bar = self.app.query_one_optional("#playback-bar")
        if self._bar is None:
            return
        for name in _MIRRORED:
            self.watch(self._bar, name, self._refresher(name), init=True)

    def _refresher(self, name: str):
        # Textual counts the callback's parameters to decide how to call it, so a
        # default-argument lambda would receive (old, new) instead of the name.
        def refresh() -> None:
            self._on_bar(name)

        return refresh

    def _on_bar(self, name: str) -> None:
        """Refresh only the parts of the view that depend on *name*."""
        bar = self._bar
        match name:
            case "state":
                self.query_one("#expanded-state", Label).update(
                    PLAYBACK_STATE_ICONS[bar.state]
                )
                self._refresh_seek()
            case "now_playing":
                self.query_one("#expanded-title", MarqueeText).text = bar.now_playing
            case (
                "channel_name"
                | "live_show_id"
                | "live_show_name"
                | "live_show_followed"
            ):
                self._refresh_live_show_display()
            case "content_type":
                apply_content_type_label(
                    self.query_one("#expanded-type", Label), bar.content_type
                )
                self._refresh_live_show_display()
            case "next_playing":
                label = self.query_one("#expanded-next", Label)
                label.update(bar.next_playing)
                label.visible = bool(bar.next_playing)
            case "elapsed_seconds" | "duration_seconds":
                self._refresh_seek()
            case "volume" | "muted":
                self._refresh_volume()
            case "vote_state":
                self.query_one("#expanded-like", Label).set_class(
                    bar.vote_state == "up", "active"
                )
                self.query_one("#expanded-dislike", Label).set_class(
                    bar.vote_state == "down", "active"
                )
            case "track_image_url":
                if self.is_open:
                    self._request_image(bar.track_image_url)
            case "stream_quality":
                label = self.query_one("#expanded-quality", Label)
                label.display = bar.stream_quality is not None
                text, tooltip = bar.stream_quality or ("", None)
                label.update(text)
                label.tooltip = tooltip

    def watch_is_open(self, is_open: bool) -> None:
        if is_open and self._bar is not None:
            self._request_image(self._bar.track_image_url)

    # ── Refresh helpers ──────────────────────────────────────────

    def _refresh_live_show_display(self) -> None:
        """Channel label + follow chip together: both gate on the
        same "is a live show airing" check, computed once here rather than
        separately in two watchers.
        """
        bar = self._bar
        airing = is_live_show_airing(bar.live_show_id, bar.content_type)

        channel = self.query_one("#expanded-channel", MarqueeText)
        if airing and bar.live_show_name:
            channel.text = (
                f"{bar.channel_name} {PLAYBACK_SEPARATOR} {bar.live_show_name}"
            )
        else:
            channel.text = bar.channel_name

        chip = self.query_one("#expanded-follow", Label)
        followed = bar.live_show_followed
        chip.display = airing and followed is not None
        if chip.display:
            chip.update(_FOLLOWING_CHIP_LABEL if followed else _FOLLOW_CHIP_LABEL)
            chip.set_class(bool(followed), "active")

    def _refresh_seek(self) -> None:
        bar_state = self._bar
        elapsed, duration = format_time_pair(
            bar_state.elapsed_seconds, bar_state.duration_seconds
        ).split("/")
        self.query_one("#expanded-elapsed", Label).update(elapsed)
        self.query_one("#expanded-duration", Label).update(duration)

        seek = self.query_one("#expanded-seek", ProgressBar)
        if bar_state.duration_seconds:
            seek.update(total=float(bar_state.duration_seconds))
            seek.progress = float(bar_state.elapsed_seconds)
        elif bar_state.state == State.LOADING:
            seek.update(total=None)
        else:
            seek.update(total=1.0)
            seek.progress = 0.0

    def _refresh_volume(self) -> None:
        bar = self._bar
        label = self.query_one("#expanded-volume", Label)
        label.update(format_volume_label(bar.volume, muted=bar.muted))
        label.set_class(bar.muted, "muted")
        self.query_one("#expanded-vol-bar", ProgressBar).progress = float(
            0 if bar.muted else bar.volume
        )

    def _request_image(self, url: str | None) -> None:
        self._image_loader.request(
            url, is_relevant=lambda: self.is_open and self._bar.track_image_url == url
        )

    # ── Open / close ─────────────────────────────────────────────

    def open(self) -> None:
        if self.is_open:
            return
        self.is_open = True
        bar = self.app.query_one_optional("#playback-bar")
        if bar is not None:
            bar.display = False
        target = max(
            _PANEL_HEIGHT_MIN, int(self.app.size.height * _PANEL_HEIGHT_FRACTION)
        )
        self.styles.animate(
            "height",
            target,
            duration=ANIMATION_FAST,
            easing="out_sine",
        )

    def close(self) -> None:
        if not self.is_open:
            return
        self.is_open = False
        self.styles.animate(
            "height",
            0,
            duration=ANIMATION_FAST,
            easing="out_sine",
            on_complete=self._on_close_complete,
        )

    def _on_close_complete(self) -> None:
        bar = self.app.query_one_optional("#playback-bar")
        if bar is not None:
            bar.display = True
