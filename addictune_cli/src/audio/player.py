"""Decode thread with one generation counter and one long-lived output.

``Player`` owns playback inside the child process. Every ``play`` carries the
generation the parent assigned; events echo it so the parent can ignore a
superseded play. The output stream stays open across plays and seeks (opening
and closing the device is what pops on many DACs and headsets); it is reopened
only when the format changes, settings change (``configure``) or the OS output
signature changes (hotplug).
"""

import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from .output import OutputConfig
from .protocol import AudioStreamInfo
from .state import State
from ..logging_setup import redact_url

_log = logging.getLogger("audio.player")
_POSITION_INTERVAL = 1.0


class StreamLike(Protocol):
    info: AudioStreamInfo
    channels: int
    sample_rate: int

    def set_volume(self, volume: float) -> None: ...
    def chunks(self) -> Iterator[bytes]: ...
    def close(self) -> None: ...


class OutputLike(Protocol):
    fell_back: bool
    channels: int
    sample_rate: int

    def write(self, data: bytes) -> None: ...
    def close(self) -> None: ...


OpenStream = Callable[..., StreamLike]
OpenOutput = Callable[[OutputConfig, int, int], OutputLike]
DeviceNames = Callable[[], list[str]]
RefreshDevices = Callable[[], None]


@dataclass
class _Session:
    generation: int
    url: str
    live: bool
    position: float
    stop: threading.Event = field(init=False, default_factory=threading.Event)
    reopen: bool = False
    fell_back: bool = False


class Player:
    def __init__(
        self,
        *,
        open_stream: OpenStream,
        open_output: OpenOutput,
        signature: Callable[[], tuple],
        device_names: DeviceNames = lambda: [],
        refresh_devices: RefreshDevices = lambda: None,
        on_state: Callable[[int, State], None],
        on_error: Callable[[int, str, str], None],
        on_position: Callable[[int, float], None],
        on_info: Callable[[int, AudioStreamInfo], None],
        on_title: Callable[[int, str], None],
    ) -> None:
        self._open_stream = open_stream
        self._open_output = open_output
        self._device_names = device_names
        self._refresh_devices = refresh_devices
        self._signature = signature
        self._on_state = on_state
        self._on_error = on_error
        self._on_position = on_position
        self._on_info = on_info
        self._on_title = on_title
        self._config = OutputConfig()
        self._cond = threading.Condition()
        self._volume = 1.0
        self._paused = False
        self._session: _Session | None = None
        self._threads: list[threading.Thread] = []  # decode threads not yet joined
        self._output: OutputLike | None = None
        self._output_stale = False
        self._last_signature = signature()

    # -- commands (any thread) ------------------------------------------------

    def play(
        self,
        generation: int,
        url: str,
        *,
        live: bool,
        volume: float,
        start_at: float = 0.0,
    ) -> None:
        with self._cond:
            self._volume = volume
            self._paused = False
            self._interrupt()
            session = _Session(generation, url, live, start_at)
            self._session = session
            thread = threading.Thread(target=self._run, args=(session,), daemon=True)
            self._threads = [t for t in self._threads if t.is_alive()] + [thread]
            self._cond.notify_all()
        thread.start()

    def pause(self) -> None:
        with self._cond:
            if self._session is None or self._paused:
                return
            self._paused = True
            self._cond.notify_all()
            generation = self._session.generation
        self._on_state(generation, State.PAUSED)

    def resume(self) -> None:
        with self._cond:
            if self._session is None or not self._paused:
                return
            self._paused = False
            self._cond.notify_all()
            generation = self._session.generation
        self._on_state(generation, State.PLAYING)

    def stop(self) -> None:
        with self._cond:
            session = self._session
            self._interrupt()
            self._cond.notify_all()
        if session is not None:
            self._on_state(session.generation, State.STOPPED)

    def set_volume(self, volume: float) -> None:
        with self._cond:
            self._volume = volume

    def seek(self, seconds: float) -> None:
        with self._cond:
            if self._session is None or self._session.live:
                return
            self._session.position = max(0.0, self._session.position + seconds)
            self._reopen_locked()

    def configure(self, config: OutputConfig) -> None:
        with self._cond:
            self._config = config
            self._output_stale = True
            self._reopen_locked()

    def devices(self) -> list[str]:
        """Current output names. PortAudio is re-read only while idle: a
        re-init under an open stream kills it (the owner-reported bug)."""
        with self._cond:
            if self._session is None and not any(t.is_alive() for t in self._threads):
                self._close_output_locked()
                self._refresh_devices()
            return self._device_names()

    def check_output(self) -> None:
        """Reopen the output when the OS output set or default changed."""
        signature = self._signature()
        with self._cond:
            if signature == self._last_signature:
                return
            self._last_signature = signature
            _log.info("output signature changed; reopening")
            self._output_stale = True
            self._reopen_locked()

    def close(self) -> None:
        self.stop()
        for thread in self._threads:
            thread.join(timeout=2.0)
        with self._cond:
            self._close_output_locked()

    # -- internals ------------------------------------------------------------

    def _interrupt(self) -> None:
        if self._session is not None:
            self._session.reopen = False
            self._session.stop.set()
            self._session = None

    def _reopen_locked(self) -> None:
        if self._session is not None:
            self._session.reopen = True
            self._session.stop.set()
            self._cond.notify_all()

    def _close_output_locked(self) -> None:
        if self._output is not None:
            self._output.close()
            self._output = None
        self._output_stale = False

    def _output_for(self, stream: StreamLike) -> OutputLike:
        """The open output if it still fits *stream*; otherwise reopen. Caller holds the lock."""
        output = self._output
        if (
            output is not None
            and not self._output_stale
            and output.channels == stream.channels
            and output.sample_rate == stream.sample_rate
        ):
            return output
        self._close_output_locked()
        self._output = self._open_output(
            self._config, stream.channels, stream.sample_rate
        )
        return self._output

    def _run(self, session: _Session) -> None:
        gen = session.generation
        first = True
        while True:
            with self._cond:
                if self._session is not session:
                    return
                session.stop = threading.Event()
                session.reopen = False
                stop = session.stop
                config = self._config
                volume = self._volume
            try:
                stream = self._open_stream(
                    session.url,
                    live=session.live,
                    start_at=session.position,
                    sample_rate=config.sample_rate,
                    volume=volume,
                    stop=stop,
                    on_title=lambda title: self._on_title(gen, title),
                )
            except Exception as exc:
                self._end(session, "decode", exc)
                return
            try:
                with self._cond:
                    if self._session is not session:
                        stream.close()
                        return
                    output = self._output_for(stream)
            except Exception as exc:
                stream.close()
                self._end(session, "device", exc)
                return
            if output.fell_back and not session.fell_back:
                self._on_error(gen, "device_missing", config.device_name or "")
            session.fell_back = output.fell_back
            if first:
                self._on_info(gen, stream.info)
                self._on_state(gen, State.PLAYING)
                first = False
            try:
                self._pump(session, stream, output, stop)
            except Exception as exc:
                stream.close()
                self._end(session, "decode", exc)
                return
            stream.close()
            with self._cond:
                if self._session is not session or not session.reopen:
                    break
        self._end(session)

    def _pump(
        self,
        session: _Session,
        stream: StreamLike,
        output: OutputLike,
        stop: threading.Event,
    ) -> None:
        bytes_per_second = stream.channels * 4 * stream.sample_rate
        next_report = session.position + _POSITION_INTERVAL
        for chunk in stream.chunks():
            with self._cond:
                while self._paused and not stop.is_set():
                    self._cond.wait()
                if stop.is_set():
                    return
                volume = self._volume
            stream.set_volume(volume)
            output.write(chunk)
            with self._cond:
                session.position += len(chunk) / bytes_per_second
                position = session.position
            if position >= next_report:
                next_report = position + _POSITION_INTERVAL
                self._on_position(session.generation, position)

    def _end(
        self, session: _Session, kind: str | None = None, exc: Exception | None = None
    ) -> None:
        with self._cond:
            current = self._session is session
            if current:
                self._session = None
        if not current:
            return
        if kind is not None:
            # libav quotes the URL it failed on, and stream URLs are signed.
            message = str(exc).replace(session.url, redact_url(session.url))
            _log.error("%s failed: %s: %s", kind, type(exc).__name__, message)
            self._on_error(session.generation, kind, message)
        self._on_state(session.generation, State.STOPPED)
