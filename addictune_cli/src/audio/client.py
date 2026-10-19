"""Parent side of the player child: spawn, send commands, read events.

Events are delivered through *dispatch*, which the app sets to
``app.call_from_thread`` so callbacks run on the Textual loop. ``play`` assigns
the generation; events from any other generation are dropped here, so no
consumer needs its own counter.
"""

import logging
import os
import subprocess
import threading
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from ..subprocess_worker import worker_command
from . import protocol
from .output import OutputConfig
from .state import State

_log = logging.getLogger("addictune_cli.audio.client")
_QUIT_TIMEOUT = 2.0


class PlayerClient:
    def __init__(
        self,
        *,
        dispatch: Callable[[Callable[[], None]], None],
        on_state: Callable[[State], None],
        on_error: Callable[[str, str], None],
        on_position: Callable[[float], None],
        on_info: Callable[[protocol.AudioStreamInfo], None],
        on_title: Callable[[str], None],
        config: OutputConfig,
        spawn: Callable[[], subprocess.Popen] | None = None,
    ) -> None:
        self._dispatch = dispatch
        self._on_state = on_state
        self._on_error = on_error
        self._on_position = on_position
        self._on_info = on_info
        self._on_title = on_title
        self._device_waiters: list[Callable[[list[str]], None]] = []
        self._config = config
        self._spawn = spawn or _spawn_worker
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._generation = 0
        self._play_generation = 0

    # -- commands -------------------------------------------------------------

    def play(
        self, url: str, *, live: bool, volume: float, start_at: float = 0.0
    ) -> int:
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._play_generation = generation
        self._send(
            protocol.Play(
                generation=generation,
                url=url,
                live=live,
                volume=volume,
                start_at=start_at,
            )
        )
        return generation

    def pause(self) -> None:
        self._send(protocol.Pause())

    def resume(self) -> None:
        self._send(protocol.Resume())

    def stop(self) -> None:
        """Stop and retire the current generation; its late events are dropped."""
        with self._lock:
            self._generation += 1
        if self._process is not None:
            self._send(protocol.Stop())

    def seek(self, seconds: float) -> None:
        self._send(protocol.Seek(seconds=seconds))

    def set_volume(self, volume: float) -> None:
        if self._process is not None:
            self._send(protocol.Volume(volume=volume))

    def configure(self, config: OutputConfig) -> None:
        self._config = config
        if self._process is not None:
            self._send(protocol.Configure(config=config))

    def request_devices(self, on_devices: Callable[[list[str]], None]) -> None:
        """Ask the child for its current output device names (fresh table)."""
        with self._lock:
            self._device_waiters.append(on_devices)
        self._send(protocol.Devices())

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            _write(process, protocol.Quit())
            process.stdin.close()
            process.wait(timeout=_QUIT_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait()

    # -- internals ------------------------------------------------------------

    def _send(self, command: BaseModel) -> None:
        process = self._ensure_process()
        try:
            _write(process, command)
        except (BrokenPipeError, OSError) as exc:
            _log.error("player child gone: %r", exc)
            self._child_lost(process)

    def _ensure_process(self) -> subprocess.Popen:
        if self._process is not None and self._process.poll() is None:
            return self._process
        process = self._spawn()
        self._process = process
        threading.Thread(target=self._read_events, args=(process,), daemon=True).start()
        if self._config != OutputConfig():
            _write(process, protocol.Configure(config=self._config))
        return process

    def _read_events(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            try:
                event = protocol.event_adapter.validate_json(line)
            except ValidationError as exc:
                _log.error("bad event %r: %s", line, exc)
                continue
            self._handle(event)
        self._child_lost(process)

    def _child_lost(self, process: subprocess.Popen) -> None:
        with self._lock:
            if self._process is not process:
                return
            self._process = None
            generation = self._play_generation
            waiters, self._device_waiters = self._device_waiters, []
        for waiter in waiters:
            self._dispatch(lambda w=waiter: w([]))
        _log.error("player child exited unexpectedly")
        self._handle(
            protocol.Error(
                generation=generation, kind="device", message="player process exited"
            )
        )
        self._handle(protocol.StateEvent(generation=generation, state=State.STOPPED))

    def _handle(self, event: protocol.Event) -> None:
        if isinstance(event, protocol.DeviceList):
            with self._lock:
                waiters, self._device_waiters = self._device_waiters, []
            for waiter in waiters:
                self._dispatch(lambda w=waiter: w(event.names))
            return

        def deliver() -> None:
            if event.generation != self._generation:
                return
            match event:
                case protocol.StateEvent(state=state):
                    self._on_state(state)
                case protocol.Error(kind=kind, message=message):
                    self._on_error(kind, message)
                case protocol.Position(seconds=seconds):
                    self._on_position(seconds)
                case protocol.InfoEvent(info=info):
                    self._on_info(info)
                case protocol.Title(title=title):
                    self._on_title(title)

        self._dispatch(deliver)


def _write(process: subprocess.Popen, command: BaseModel) -> None:
    process.stdin.write(command.model_dump_json().encode() + b"\n")
    process.stdin.flush()


def _spawn_worker() -> subprocess.Popen:
    import sentry_sdk

    from ..telemetry import TELEMETRY_ENV

    argv, env = worker_command("player")
    # The child reports iff this process does; the app re-spawns it on toggle.
    env[TELEMETRY_ENV] = "1" if sentry_sdk.get_client().is_active() else "0"
    return subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={**os.environ, **env},
        # Windows: no console window for the child.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
