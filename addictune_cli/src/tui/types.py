from dataclasses import dataclass
from enum import auto, Enum

from addictune_sdk.models.channel import Channel
from addictune_sdk.models.mixshow import ShowEpisode


class ContentType(Enum):
    LIVE = auto()
    MIXSHOW = auto()
    PLAYLIST = auto()
    TRACK = auto()


class ChannelSort(Enum):
    DEFAULT = auto()
    ALPHA = auto()
    POPULAR = auto()


class MixshowSort(Enum):
    DEFAULT = auto()
    POPULAR = auto()


class PlaylistSort(Enum):
    POPULAR = auto()
    NEWEST = auto()


class TracksView(Enum):
    LIKED = auto()
    HISTORY = auto()


class MediaStatus(Enum):
    LIVE_NOW = auto()
    UPCOMING = auto()
    NOW_PLAYING = auto()


@dataclass(frozen=True)
class OptionChoice:
    id: str
    label: str
    selected: bool = False


@dataclass(frozen=True)
class OptionGroup:
    id: str
    title: str
    choices: list[OptionChoice]
    multiple: bool = False


@dataclass(frozen=True)
class MediaStatusState:
    status: MediaStatus
    episode: ShowEpisode | None = None
    now_playing: tuple[str, str] | None = None


@dataclass(frozen=True)
class ChannelView:
    channel: Channel
    favorite: bool = False
