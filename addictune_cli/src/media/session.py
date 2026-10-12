"""OS media session contract: what to show, which keys can arrive.

One frozen ``MediaInfo`` per update; backends drop identical repeats. Commands
are delivered on the Textual loop. ``make_session`` picks the platform backend
and falls back to ``NullSession`` when the platform or its bindings are absent.
"""

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

_log = logging.getLogger("addictune_cli.media")


class Command(StrEnum):
    PLAY = "play"
    PAUSE = "pause"
    TOGGLE = "toggle"
    NEXT = "next"
    PREVIOUS = "previous"


@dataclass(frozen=True, slots=True)
class MediaInfo:
    title: str = ""
    artist: str = ""
    artwork_url: str = ""
    playing: bool = False
    can_play: bool = False
    can_pause: bool = False
    can_next: bool = False
    can_previous: bool = False


OnCommand = Callable[[Command], None]
CallSoon = Callable[[Callable[[], None]], None]
# schedule(seconds, callback): repeat *callback* every *seconds* on the UI loop.
Schedule = Callable[[float, Callable[[], None]], object]


class MediaSession(Protocol):
    def start(self, on_command: OnCommand, schedule: Schedule) -> None: ...
    def update(self, info: MediaInfo) -> None: ...
    def stop(self) -> None: ...


class NullSession:
    def start(self, on_command: OnCommand, schedule: Schedule) -> None:
        pass

    def update(self, info: MediaInfo) -> None:
        pass

    def stop(self) -> None:
        pass


def make_session(call_soon: CallSoon) -> MediaSession:
    """Backend for this platform; *call_soon* schedules work on the Textual loop.

    ``NullSession`` when the platform is unsupported or its bindings are missing,
    so the app runs the same with or without a now-playing integration.
    """
    try:
        if sys.platform == "darwin":
            from .macos import MacSession

            return MacSession(call_soon)
        if sys.platform.startswith("linux"):
            from .linux import MprisSession

            return MprisSession(call_soon)
        if sys.platform == "win32":
            from .windows import SmtcSession

            return SmtcSession(call_soon)
    except Exception as exc:  # missing framework bindings, no session bus
        _log.warning("media session unavailable: %r", exc)
    return NullSession()
