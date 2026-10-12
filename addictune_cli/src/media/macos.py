"""macOS Now Playing and media keys, in-process.

``MPRemoteCommandCenter`` delivers callbacks on the main thread's run loop,
which Textual's asyncio loop never services; ``pump`` runs it for one pass and
is scheduled on the UI loop every 50 ms (spike 02.1 confirmed callbacks keep
arriving after long idle this way). Artwork is fetched off-thread and applied
on the next ``update``.
"""

import logging
import threading
import time
import urllib.request

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSImage,
    NSWorkspace,
    NSWorkspaceDidWakeNotification,
)
from CoreFoundation import CFRunLoopRunInMode, kCFRunLoopDefaultMode
from Foundation import NSData
from MediaPlayer import (
    MPMediaItemArtwork,
    MPMediaItemPropertyArtist,
    MPMediaItemPropertyArtwork,
    MPMediaItemPropertyTitle,
    MPNowPlayingInfoCenter,
    MPNowPlayingInfoPropertyElapsedPlaybackTime,
    MPNowPlayingInfoPropertyPlaybackRate,
    MPNowPlayingPlaybackStatePaused,
    MPNowPlayingPlaybackStatePlaying,
    MPNowPlayingPlaybackStateStopped,
    MPRemoteCommandCenter,
    MPRemoteCommandHandlerStatusSuccess,
)

from .session import CallSoon, Command, MediaInfo, OnCommand, Schedule

_log = logging.getLogger("addictune_cli.media")
PUMP_INTERVAL = 0.05


class MacSession:
    def __init__(self, call_soon: CallSoon) -> None:
        self._call_soon = call_soon
        self._on_command: OnCommand = lambda c: None
        self._info = MediaInfo()
        self._elapsed = 0.0  # seconds played before the current run of playing
        self._playing_since: float | None = None
        self._artwork: tuple[str, object] | None = None  # (url, MPMediaItemArtwork)
        self._fetching: str | None = None
        self._wake_observer = None
        self._center = MPNowPlayingInfoCenter.defaultCenter()
        self._commands = MPRemoteCommandCenter.sharedCommandCenter()
        self._handlers: list = []  # keep the blocks alive for the command center

    def start(self, on_command: OnCommand, schedule: Schedule) -> None:
        self._on_command = on_command
        schedule(PUMP_INTERVAL, self.pump)
        # Accessory policy: the system routes media keys to us without a Dock
        # icon or focus change.
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        app.finishLaunching()
        for getter, command in (
            (self._commands.playCommand, Command.PLAY),
            (self._commands.pauseCommand, Command.PAUSE),
            (self._commands.togglePlayPauseCommand, Command.TOGGLE),
            (self._commands.nextTrackCommand, Command.NEXT),
            (self._commands.previousTrackCommand, Command.PREVIOUS),
        ):
            handler = self._handler(command)
            self._handlers.append(handler)
            getter().addTargetWithHandler_(handler)
        # The widget goes blank after sleep; republish when the machine wakes.
        self._wake_observer = (
            NSWorkspace.sharedWorkspace()
            .notificationCenter()
            .addObserverForName_object_queue_usingBlock_(
                NSWorkspaceDidWakeNotification, None, None, lambda _n: self._publish()
            )
        )

    def _handler(self, command: Command):
        def handle(_event):
            self._call_soon(lambda: self._on_command(command))
            return MPRemoteCommandHandlerStatusSuccess

        return handle

    def pump(self) -> None:
        """Run the main run loop for one pass (scheduled in ``start``)."""
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0, True)

    def update(self, info: MediaInfo) -> None:
        if info == self._info:
            return
        now = time.monotonic()
        if info.title != self._info.title:
            self._elapsed, self._playing_since = 0.0, None
        if self._playing_since is not None:
            self._elapsed += now - self._playing_since
            self._playing_since = None
        if info.playing:
            self._playing_since = now
        self._info = info
        self._publish()

    def _publish(self) -> None:
        info = self._info
        self._commands.playCommand().setEnabled_(info.can_play)
        self._commands.pauseCommand().setEnabled_(info.can_pause)
        self._commands.togglePlayPauseCommand().setEnabled_(
            info.can_play or info.can_pause
        )
        self._commands.nextTrackCommand().setEnabled_(info.can_next)
        self._commands.previousTrackCommand().setEnabled_(info.can_previous)
        state = (
            MPNowPlayingPlaybackStatePlaying
            if info.playing
            else MPNowPlayingPlaybackStatePaused
            if info.can_play
            else MPNowPlayingPlaybackStateStopped
        )
        elapsed = self._elapsed + (
            time.monotonic() - self._playing_since if self._playing_since else 0.0
        )
        payload = {
            MPMediaItemPropertyTitle: info.title,
            MPMediaItemPropertyArtist: info.artist,
            MPNowPlayingInfoPropertyPlaybackRate: 1.0 if info.playing else 0.0,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: elapsed,
        }
        artwork = self._artwork_for(info.artwork_url)
        if artwork is not None:
            payload[MPMediaItemPropertyArtwork] = artwork
        self._center.setPlaybackState_(state)
        self._center.setNowPlayingInfo_(payload)

    def _artwork_for(self, url: str):
        if not url:
            return None
        if self._artwork is not None and self._artwork[0] == url:
            return self._artwork[1]
        if self._fetching != url:
            self._fetching = url
            threading.Thread(target=self._fetch, args=(url,), daemon=True).start()
        return None

    def _fetch(self, url: str) -> None:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                data = response.read()
        except Exception as exc:
            _log.debug("artwork fetch failed: %r", exc)
            self._call_soon(lambda: self._fetch_failed(url))
            return
        self._call_soon(lambda: self._apply_artwork(url, data))

    def _fetch_failed(self, url: str) -> None:
        if self._fetching == url:  # a newer URL may already be in flight
            self._fetching = None  # allow a retry

    def _apply_artwork(self, url: str, data: bytes) -> None:
        if url != self._info.artwork_url:
            return
        image = NSImage.alloc().initWithData_(
            NSData.dataWithBytes_length_(data, len(data))
        )
        if image is None:
            return
        artwork = MPMediaItemArtwork.alloc().initWithBoundsSize_requestHandler_(
            image.size(), lambda _size: image
        )
        self._artwork = (url, artwork)
        self._fetching = None
        self._publish()

    def stop(self) -> None:
        if self._wake_observer is not None:
            NSWorkspace.sharedWorkspace().notificationCenter().removeObserver_(
                self._wake_observer
            )
            self._wake_observer = None
        self._center.setNowPlayingInfo_(None)
        self._center.setPlaybackState_(MPNowPlayingPlaybackStateStopped)
