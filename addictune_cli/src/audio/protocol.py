"""Messages between the TUI and the player child, as JSON lines.

Both sides validate with the same two ``TypeAdapter`` unions. ``generation`` is
assigned by the parent on ``play`` and echoed on every playback event so the
parent can drop events from a superseded play.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from .output import OutputConfig
from .state import State


class AudioStreamInfo(BaseModel):
    channels: int
    sample_rate: int
    layout: str | None = None
    duration: float | None = None
    codec_name: str | None = None
    bit_rate: int | None = None


# Commands: parent -> child


class Play(BaseModel):
    type: Literal["play"] = "play"
    generation: int
    url: str
    live: bool
    volume: float = Field(ge=0.0, le=2.0)
    start_at: float = 0.0


class Pause(BaseModel):
    type: Literal["pause"] = "pause"


class Resume(BaseModel):
    type: Literal["resume"] = "resume"


class Stop(BaseModel):
    type: Literal["stop"] = "stop"


class Seek(BaseModel):
    type: Literal["seek"] = "seek"
    seconds: float


class Volume(BaseModel):
    type: Literal["volume"] = "volume"
    volume: float = Field(ge=0.0, le=2.0)


class Configure(BaseModel):
    type: Literal["configure"] = "configure"
    config: OutputConfig


class Devices(BaseModel):
    type: Literal["devices"] = "devices"


class Quit(BaseModel):
    type: Literal["quit"] = "quit"


Command = Annotated[
    Play | Pause | Resume | Stop | Seek | Volume | Configure | Devices | Quit,
    Field(discriminator="type"),
]
command_adapter: TypeAdapter[Command] = TypeAdapter(Command)


# Events: child -> parent


class StateEvent(BaseModel):
    type: Literal["state"] = "state"
    generation: int
    state: State


class InfoEvent(BaseModel):
    type: Literal["info"] = "info"
    generation: int
    info: AudioStreamInfo


class Error(BaseModel):
    type: Literal["error"] = "error"
    generation: int
    kind: Literal["decode", "device", "device_missing"]
    message: str


class Position(BaseModel):
    type: Literal["position"] = "position"
    generation: int
    seconds: float


class Title(BaseModel):
    """ICY stream title (live streams only)."""

    type: Literal["title"] = "title"
    generation: int
    title: str


class DeviceList(BaseModel):
    type: Literal["device_list"] = "device_list"
    names: list[str]


Event = Annotated[
    StateEvent | InfoEvent | Error | Position | Title | DeviceList,
    Field(discriminator="type"),
]
event_adapter: TypeAdapter[Event] = TypeAdapter(Event)
