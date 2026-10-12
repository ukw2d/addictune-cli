from dataclasses import dataclass
from datetime import UTC, datetime

from addictune_sdk.models.channel import Channel
from addictune_sdk.models.common import ImageSet
from addictune_sdk.models.mixshow import MixShow
from addictune_sdk.models.playlist import Playlist
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.scalar import ScalarOffset
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static

from ..services.image_loader import DebouncedImageLoader
from ..presentation import (
    ANIMATION_SLOW,
    MEDIA_LIVE_STATUS,
    MEDIA_METADATA_EPISODES,
    MEDIA_METADATA_SCHEDULE,
    MEDIA_NOW_PLAYING_STATUS,
    MEDIA_UPCOMING_STATUS,
)
from ..typed_nodes import AppNode
from ..types import MediaStatus, MediaStatusState
from ..utils import parse_iso_datetime

_PANEL_WIDTH = 40
_INLINE_FOLLOWED_BADGE_MIN_WIDTH = 30
_MEDIA_IMAGE_VARIANTS = ("compact", "square", "default")


@dataclass(frozen=True)
class MediaInfo:
    """A browsable channel/show/playlist's own summary and artwork."""

    title: str
    description: str = ""
    image_url: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()
    recently_played: tuple[str, ...] = ()
    status: MediaStatusState | None = None
    followed: bool = False


class MediaInfoPanel(AppNode, Widget):
    can_focus = False

    media: reactive[MediaInfo | None] = reactive(None, init=False)
    is_open: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._is_opening = False
        self._rendered_status: tuple[str, str] | None = None
        self._rendered_metadata: str | None = None
        self._rendered_recent_tracks: tuple[str, ...] | None = None
        # MediaInfoPanel only ever shows channel/show/playlist artwork (see
        # channel_media_info/mixshow_media_info/playlist_media_info below),
        # never a per-track image, so scope="media" (the default) is correct
        # here — unlike ExpandedPlayer, which shows the live track's artwork
        # and explicitly requests scope="track".
        self._image_loader = DebouncedImageLoader(
            self,
            width=38,
            height=19,
            image_selector="#info-image",
        )

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="media-info--scroll", can_focus=False):
            with Vertical(classes="media-info--content"):
                yield Static("", id="info-image", classes="info--image")
                with Horizontal(classes="info--title-row"):
                    yield Label("", id="info-title", classes="info--title")
                    yield Label(
                        "\u2605 Followed",
                        id="info-followed-badge",
                        classes="info--followed-badge",
                    )
                yield Static("", id="info-status", classes="info--status")
                with Vertical(id="info-recent", classes="info--recent"):
                    yield Label("RECENTLY PLAYED", classes="info--recent-title")
                    yield VerticalScroll(
                        id="info-recent-tracks",
                        classes="info--recent-tracks",
                    )
                yield Label("", id="info-metadata", classes="info--metadata")
                yield Label("", id="info-description", classes="info--description")

    def on_mount(self) -> None:
        self._sync_layout_class()

    def watch_media(self, media: MediaInfo | None) -> None:
        if media is None:
            return
        self.query_one("#info-title", Label).update(media.title)
        self.query_one("#info-followed-badge", Label).display = media.followed
        self.query_one("#info-description", Label).update(media.description)
        metadata = _format_metadata(media)
        if metadata != self._rendered_metadata:
            self.query_one("#info-metadata", Label).update(metadata)
            self._rendered_metadata = metadata
        self._update_status(media)
        self._update_recent_tracks(media.recently_played)
        if self.is_open and not self._is_opening:
            self._request_image(media.image_url)

    def _update_status(self, media: MediaInfo) -> None:
        widget = self.query_one("#info-status", Static)
        text, modifier = _format_status(media)
        rendered_status = (text, modifier) if text else None
        if rendered_status == self._rendered_status:
            if rendered_status is None and widget.display:
                widget.display = False
            return
        self._rendered_status = rendered_status
        if text:
            widget.update(text)
            widget.set_classes(f"info--status info--status--{modifier}")
            widget.display = True
        else:
            widget.display = False

    def _update_recent_tracks(self, tracks: tuple[str, ...]) -> None:
        section = self.query_one("#info-recent", Vertical)
        if tracks == self._rendered_recent_tracks:
            section.display = bool(tracks)
            return
        self._rendered_recent_tracks = tracks
        section.display = bool(tracks)
        container = self.query_one("#info-recent-tracks", VerticalScroll)
        container.remove_children()
        if tracks:
            container.mount(
                *[
                    Label(f"\u25b8 {track}", classes="info--recent-track")
                    for track in tracks
                ]
            )

    def watch_is_open(self, is_open: bool) -> None:
        if is_open and self.media is not None:
            self.set_timer(ANIMATION_SLOW, self._load_current_image)

    def on_resize(self) -> None:
        self._sync_layout_class()
        if self.is_open:
            self._sync_image_size(self.size.width)
            if self.media is not None:
                self._request_image(self.media.image_url)

    def _sync_layout_class(self) -> None:
        self.set_class(
            self.size.width < _INLINE_FOLLOWED_BADGE_MIN_WIDTH,
            "-narrow",
        )

    def _load_current_image(self) -> None:
        self._is_opening = False
        if self.is_open and self.media is not None:
            self._request_image(self.media.image_url)

    def _request_image(self, url: str | None) -> None:
        self._image_loader.request(
            url,
            is_relevant=lambda: (
                self.is_open and self.media is not None and self.media.image_url == url
            ),
        )

    def _effective_width(self) -> int:
        return min(_PANEL_WIDTH, max(1, self.screen.size.width // 2))

    def _sync_image_size(self, panel_width: int) -> None:
        image_width = max(1, panel_width - 2)
        self._image_loader.set_size(image_width, max(1, image_width // 2))

    def open(self, media: MediaInfo) -> None:
        self.media = media
        if self.is_open:
            return
        self._is_opening = True
        width = self._effective_width()
        self._sync_image_size(width)
        self.offset = (width, 0)
        self.styles.width = "50%"
        self.is_open = True
        self.styles.animate(
            "offset",
            ScalarOffset.from_offset((0, 0)),
            duration=ANIMATION_SLOW,
            easing="out_cubic",
        )

    def close(self) -> None:
        if not self.is_open:
            return
        self._is_opening = False
        self.is_open = False
        self.offset = (0, 0)
        self.styles.animate(
            "width",
            0,
            duration=ANIMATION_SLOW,
            easing="out_cubic",
        )


def channel_media_info(
    channel: Channel,
    followed: bool = False,
    status: MediaStatusState | None = None,
    recently_played: tuple[str, ...] = (),
) -> MediaInfo:
    return MediaInfo(
        title=channel.name,
        description=channel.description_short or channel.description or "",
        image_url=media_image_url(channel.images, size=200),
        status=status,
        followed=followed,
        recently_played=recently_played,
    )


def mixshow_media_info(
    show: MixShow,
    followed: bool | None,
    status: MediaStatusState | None = None,
) -> MediaInfo:
    channel_names = ", ".join(channel.name for channel in show.channels)
    return MediaInfo(
        title=show.name,
        description=show.description or "",
        image_url=media_image_url(show.images, size=200),
        metadata=(
            ("Channel", channel_names),
            (MEDIA_METADATA_EPISODES, str(show.ondemand_episode_count or 0)),
            (MEDIA_METADATA_SCHEDULE, ", ".join(show.human_readable_schedule)),
        ),
        status=status,
        followed=followed,
    )


def playlist_media_info(playlist: Playlist) -> MediaInfo:
    tags = ", ".join(tag.name for tag in playlist.tags)
    return MediaInfo(
        title=playlist.name,
        description=playlist.description or "",
        image_url=media_image_url(playlist.images, size=200),
        metadata=(
            ("Tracks", str(playlist.track_count or 0)),
            ("Duration", playlist.duration or ""),
            ("Followers", str(playlist.follow_count) if playlist.follow_count else ""),
            ("Tags", tags),
        ),
        followed=playlist.following,
    )


def media_image_url(*image_sets: ImageSet | None, size: int) -> str | None:
    """CDN URL of the first available image, trying each set in order and the
    compact/square/default variants within it."""
    for images in image_sets:
        if images is None:
            continue
        for variant in _MEDIA_IMAGE_VARIANTS:
            if url := images.url(variant, size=size):
                return url
    return None



def _format_metadata(media: MediaInfo) -> str:
    return "\n".join(f"{label}: {value}" for label, value in media.metadata if value)


def _format_status(media: MediaInfo) -> tuple[str, str]:
    """Return formatted media status content, or ('', '') when no status applies."""
    if media.status is None:
        return "", ""

    if media.status.status in (MediaStatus.LIVE_NOW, MediaStatus.UPCOMING):
        episode = media.status.episode
        if episode is None:
            return "", ""
        show = episode.show
        line1 = (show.name if show else "") or episode.name
        line2 = episode.name if line1 != episode.name else ""
        if media.status.status == MediaStatus.LIVE_NOW:
            status = MEDIA_LIVE_STATUS
            label = status.label
        else:
            minutes = _minutes_until(episode.start_at)
            suffix = f" · in {minutes}m" if minutes is not None else ""
            status = MEDIA_UPCOMING_STATUS
            label = status.label.format(suffix=suffix)
        lines = [label, line1] + ([line2] if line2 else [])
        return "\n".join(lines), status.modifier

    if media.status.status == MediaStatus.NOW_PLAYING and media.status.now_playing:
        artist, title = media.status.now_playing
        if artist or title:
            lines = [MEDIA_NOW_PLAYING_STATUS.label, artist or title] + (
                [title] if artist and title else []
            )
            return "\n".join(lines), MEDIA_NOW_PLAYING_STATUS.modifier

    return "", ""


def _minutes_until(start_at: str | None) -> int | None:
    dt = parse_iso_datetime(start_at)
    if dt is None:
        return None
    seconds = (dt - datetime.now(UTC)).total_seconds()
    return max(1, int(seconds / 60)) if seconds > 0 else None
