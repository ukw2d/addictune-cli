"""Player child process: JSON-lines commands on stdin, events on stdout.

The child exits when stdin reaches EOF, which is what happens when the parent
dies or closes the pipe. That is the only orphan protection and it works on
every OS. stderr is not read by the parent; logging goes to the shared file.
"""

import logging
import os
import sys
import threading
import time

import av.logging
from pydantic import BaseModel, ValidationError

from ..logging_setup import setup_logging
from ..telemetry import TELEMETRY_ENV
from ..telemetry import init as init_telemetry
from . import output, protocol
from .player import Player
from .stream import Stream

_log = logging.getLogger("audio.worker")
_OUTPUT_CHECK_INTERVAL = 1.0


class _NullOutput:
    """Discards audio at real-time pace; used by tests (``ADDICTUNE_NULL_OUTPUT=1``)."""

    fell_back = False

    def __init__(
        self, config: output.OutputConfig, channels: int, sample_rate: int
    ) -> None:
        self.channels = channels
        self.sample_rate = sample_rate
        self._bytes_per_second = channels * 4 * sample_rate

    def write(self, data: bytes) -> None:
        time.sleep(len(data) / self._bytes_per_second)

    def close(self) -> None:
        pass


def main() -> None:
    setup_logging("player")
    init_telemetry("player", os.environ.get(TELEMETRY_ENV) == "1")
    # PyAV discards libav's log by default, which leaves a connection failure as
    # a bare "[Errno 5] Input/output error". With a level set, the exception
    # carries the reason ("[tls] ...", "[tcp] Failed to resolve hostname ...").
    av.logging.set_level(av.logging.ERROR)
    # Device names may be non-ASCII; the pipe must not depend on the locale (Windows).
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    write_lock = threading.Lock()
    null = os.environ.get("ADDICTUNE_NULL_OUTPUT") == "1"

    def emit(event: BaseModel) -> None:
        with write_lock:
            try:
                sys.stdout.write(event.model_dump_json() + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, OSError):
                pass

    player = Player(
        open_stream=Stream,
        open_output=_NullOutput if null else output.Output,
        signature=(lambda: ()) if null else output.signature,
        device_names=(lambda: []) if null else output.device_names,
        refresh_devices=(lambda: None) if null else output.refresh_devices,
        on_state=lambda g, s: emit(protocol.StateEvent(generation=g, state=s)),
        on_error=lambda g, k, m: emit(protocol.Error(generation=g, kind=k, message=m)),
        on_position=lambda g, s: emit(protocol.Position(generation=g, seconds=s)),
        on_info=lambda g, i: emit(protocol.InfoEvent(generation=g, info=i)),
        on_title=lambda g, t: emit(protocol.Title(generation=g, title=t)),
    )
    stop_watch = threading.Event()

    def watch_output() -> None:
        while not stop_watch.wait(_OUTPUT_CHECK_INTERVAL):
            player.check_output()

    threading.Thread(target=watch_output, daemon=True).start()

    for line in sys.stdin:
        try:
            command = protocol.command_adapter.validate_json(line)
        except ValidationError as exc:
            _log.error("bad command %r: %s", line, exc)
            continue
        match command:
            case protocol.Play(
                generation=generation,
                url=url,
                live=live,
                volume=volume,
                start_at=start_at,
            ):
                player.play(
                    generation, url, live=live, volume=volume, start_at=start_at
                )
            case protocol.Pause():
                player.pause()
            case protocol.Resume():
                player.resume()
            case protocol.Stop():
                player.stop()
            case protocol.Seek(seconds=seconds):
                player.seek(seconds)
            case protocol.Volume(volume=volume):
                player.set_volume(volume)
            case protocol.Configure(config=config):
                player.configure(config)
            case protocol.Devices():
                emit(protocol.DeviceList(names=player.devices()))
            case protocol.Quit():
                break
    stop_watch.set()
    player.close()


if __name__ == "__main__":
    main()
