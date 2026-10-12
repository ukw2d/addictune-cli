"""Output device selection for the player child.

Devices are stored by name because PortAudio renumbers them on every hotplug;
``resolve`` maps the name to an index right before the stream is opened.
``signature`` is a cheap, hashable snapshot of the OS output configuration; the
player polls it and reopens its stream when it changes (PortAudio itself never
notices a new default while the process runs).
"""

import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OutputConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    device_name: str | None = None
    sample_rate: int | None = Field(default=None, gt=0)
    latency: Literal["high", "low"] = "high"


def output_names(table: Sequence[Mapping[str, Any]]) -> list[str]:
    return [d["name"] for d in table if d["max_output_channels"] > 0]


def resolve(name: str | None, table: Sequence[Mapping[str, Any]]) -> int | None:
    """Index of *name* in *table*, or ``None`` for the system default or a missing device."""
    if name is None:
        return None
    return next(
        (
            i
            for i, d in enumerate(table)
            if d["name"] == name and d["max_output_channels"] > 0
        ),
        None,
    )


class Output:
    """A sounddevice output stream opened against the current device table.

    PortAudio is re-initialised on every open so that the device table and the
    system default reflect hotplug changes made since the last open.
    """

    def __init__(self, config: OutputConfig, channels: int, sample_rate: int) -> None:
        import sounddevice as sd

        refresh_devices()
        index = resolve(config.device_name, sd.query_devices())
        self.fell_back = config.device_name is not None and index is None
        self.channels = channels
        self.sample_rate = sample_rate
        self._stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            latency=config.latency,
            device=index,
        )
        self._stream.start()

    def write(self, data: bytes) -> None:
        self._stream.write(data)

    def close(self) -> None:
        # Abort instead of draining: a reopen must not wait a buffer. Opening
        # and closing the device is what pops on many DACs, so Player keeps
        # one Output across plays and only closes it when the format changes.
        self._stream.abort()
        self._stream.close()


def refresh_devices() -> None:
    """Re-initialise PortAudio so its device table matches the OS.

    Only safe while no stream is open: an open stream's handle is invalidated.
    ``Player`` is the sole caller and serialises it with its output.
    """
    import sounddevice as sd

    sd._terminate()
    sd._initialize()


def device_names() -> list[str]:
    import sounddevice as sd

    return output_names(sd.query_devices())


if sys.platform == "darwin":
    import ctypes
    import ctypes.util

    _ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))
    _SYSTEM_OBJECT = 1
    _SCOPE_GLOBAL, _SCOPE_OUTPUT = 0x676C6F62, 0x6F757470  # 'glob', 'outp'
    _DEFAULT_OUTPUT, _DEVICES, _STREAMS = (
        0x644F7574,
        0x64657623,
        0x73746D23,
    )  # 'dOut' 'dev#' 'stm#'

    class _Address(ctypes.Structure):
        _fields_ = [
            ("selector", ctypes.c_uint32),
            ("scope", ctypes.c_uint32),
            ("element", ctypes.c_uint32),
        ]

    def _property(obj: int, selector: int, scope: int = _SCOPE_GLOBAL) -> bytes:
        addr = _Address(selector, scope, 0)
        size = ctypes.c_uint32()
        if _ca.AudioObjectGetPropertyDataSize(
            obj, ctypes.byref(addr), 0, None, ctypes.byref(size)
        ):
            return b""
        buf = ctypes.create_string_buffer(size.value)
        if _ca.AudioObjectGetPropertyData(
            obj, ctypes.byref(addr), 0, None, ctypes.byref(size), buf
        ):
            return b""
        return buf.raw[: size.value]

    def _ids(raw: bytes) -> list[int]:
        return [int.from_bytes(raw[i : i + 4], "little") for i in range(0, len(raw), 4)]

    def signature() -> tuple[int, ...]:
        """Default output device id followed by every id that has an output stream."""
        default = _ids(_property(_SYSTEM_OBJECT, _DEFAULT_OUTPUT))
        outputs = [
            d
            for d in _ids(_property(_SYSTEM_OBJECT, _DEVICES))
            if _property(d, _STREAMS, _SCOPE_OUTPUT)
        ]
        return (*default, *outputs)

else:

    def signature() -> tuple[int, ...]:
        # Linux: PulseAudio/PipeWire move the ``default`` sink under an open stream,
        # so nothing to watch. Windows: WASAPI does not follow endpoint changes;
        # the default-endpoint read via COM is an open gap (see 01-audio.md).
        return ()
