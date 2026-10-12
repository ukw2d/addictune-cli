# ruff: noqa: F722,F821  (dbus-fast uses D-Bus signature strings as annotations)
"""MPRIS2 over dbus-fast, on the Textual asyncio loop (no thread).

Minimal ``org.mpris.MediaPlayer2`` root plus the ``Player`` interface GNOME and
KDE need for the media keys and the now-playing widget.
"""

import asyncio
import logging

from dbus_fast import Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType, PropertyAccess
from dbus_fast.service import ServiceInterface, dbus_property, method

from .session import CallSoon, Command, MediaInfo, OnCommand, Schedule

_log = logging.getLogger("addictune_cli.media")
_PATH = "/org/mpris/MediaPlayer2"
_NAME = "org.mpris.MediaPlayer2.addictune"


def playback_status(info: MediaInfo) -> str:
    return "Playing" if info.playing else "Paused" if info.can_play else "Stopped"


def metadata(info: MediaInfo) -> dict[str, Variant]:
    data = {
        "mpris:trackid": Variant("o", f"{_PATH}/Track/Current"),
        "xesam:title": Variant("s", info.title),
    }
    if info.artist:
        data["xesam:artist"] = Variant("as", [info.artist])
    if info.artwork_url:
        data["mpris:artUrl"] = Variant("s", info.artwork_url)
    return data


class _Root(ServiceInterface):
    def __init__(self) -> None:
        super().__init__("org.mpris.MediaPlayer2")

    @method()
    def Raise(self) -> None:
        pass

    @method()
    def Quit(self) -> None:
        pass

    @dbus_property(access=PropertyAccess.READ)
    def CanQuit(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def CanRaise(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def HasTrackList(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> "s":
        return "Addictune"

    @dbus_property(access=PropertyAccess.READ)
    def SupportedUriSchemes(self) -> "as":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def SupportedMimeTypes(self) -> "as":
        return []


class _Player(ServiceInterface):
    def __init__(self, session: "MprisSession") -> None:
        super().__init__("org.mpris.MediaPlayer2.Player")
        self._s = session

    @method()
    def Next(self) -> None:
        self._s.emit(Command.NEXT)

    @method()
    def Previous(self) -> None:
        self._s.emit(Command.PREVIOUS)

    @method()
    def Pause(self) -> None:
        self._s.emit(Command.PAUSE)

    @method()
    def PlayPause(self) -> None:
        self._s.emit(Command.TOGGLE)

    @method()
    def Stop(self) -> None:
        self._s.emit(Command.PAUSE)

    @method()
    def Play(self) -> None:
        self._s.emit(Command.PLAY)

    @method()
    def Seek(self, offset: "x") -> None:
        pass

    @method()
    def SetPosition(self, track_id: "o", position: "x") -> None:
        pass

    @method()
    def OpenUri(self, uri: "s") -> None:
        pass

    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> "s":
        return playback_status(self._s.info)

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":
        return metadata(self._s.info)

    @dbus_property(access=PropertyAccess.READ)
    def Volume(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "x":
        return 0

    @dbus_property(access=PropertyAccess.READ)
    def Rate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MinimumRate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MaximumRate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def CanGoNext(self) -> "b":
        return self._s.info.can_next

    @dbus_property(access=PropertyAccess.READ)
    def CanGoPrevious(self) -> "b":
        return self._s.info.can_previous

    @dbus_property(access=PropertyAccess.READ)
    def CanPlay(self) -> "b":
        return self._s.info.can_play

    @dbus_property(access=PropertyAccess.READ)
    def CanPause(self) -> "b":
        return self._s.info.can_pause

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def CanControl(self) -> "b":
        return True


class MprisSession:
    def __init__(self, call_soon: CallSoon) -> None:
        self._call_soon = call_soon
        self.on_command: OnCommand = lambda c: None
        self.info = MediaInfo()
        self._player = _Player(self)
        self._bus: MessageBus | None = None
        self._task: asyncio.Task | None = None

    def start(self, on_command: OnCommand, schedule: Schedule) -> None:
        self.on_command = on_command
        self._task = asyncio.get_running_loop().create_task(self._connect())

    async def _connect(self) -> None:
        try:
            self._bus = bus = await MessageBus(bus_type=BusType.SESSION).connect()
            bus.export(_PATH, _Root())
            bus.export(_PATH, self._player)
            await bus.request_name(_NAME)
        except Exception as exc:
            _log.warning("MPRIS unavailable: %r", exc)

    def update(self, info: MediaInfo) -> None:
        if info == self.info:
            return
        self.info = info
        if self._bus is not None:
            self._player.emit_properties_changed(
                {
                    "PlaybackStatus": playback_status(info),
                    "Metadata": metadata(info),
                    "CanPlay": info.can_play,
                    "CanPause": info.can_pause,
                    "CanGoNext": info.can_next,
                    "CanGoPrevious": info.can_previous,
                }
            )

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None

    def emit(self, command: Command) -> None:
        self._call_soon(lambda: self.on_command(command))
