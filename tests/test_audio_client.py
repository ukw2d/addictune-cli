"""`PlayerClient` against the real child process.

A null output keeps these tests silent and hardware-free: the child is spawned
with ``ADDICTUNE_NULL_OUTPUT=1`` and a local wav file is played.
"""

import math
import os
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import av
import pytest

from addictune_cli.src.audio import protocol
from addictune_cli.src.audio.client import PlayerClient
from addictune_cli.src.audio.output import OutputConfig
from addictune_cli.src.audio.state import State


def _wav(seconds: float = 0.3) -> str:
    path = os.path.join(tempfile.mkdtemp(), "tone.wav")
    rate = 44100
    n = int(rate * seconds)
    with av.open(path, "w") as container:
        stream = container.add_stream("pcm_s16le", rate=rate, layout="stereo")
        frame = av.AudioFrame(format="s16", layout="stereo", samples=n)
        frame.sample_rate = rate
        frame.planes[0].update(
            struct.pack(
                f"<{n * 2}h", *(int(8000 * math.sin(i / 20)) for i in range(n * 2))
            )
        )
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return path


def _spawn() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "addictune_cli.src.audio.worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "ADDICTUNE_NULL_OUTPUT": "1"},
        cwd=Path(__file__).resolve().parents[1],
    )


class _Sink:
    def __init__(self) -> None:
        self.states: list[State] = []
        self.errors: list[tuple[str, str]] = []
        self.positions: list[float] = []
        self.infos: list[protocol.AudioStreamInfo] = []
        self.titles: list[str] = []
        self.devices: list[list[str]] = []
        self.stopped = threading.Event()
        self.got_devices = threading.Event()

    def on_state(self, state: State) -> None:
        self.states.append(state)
        if state == State.STOPPED:
            self.stopped.set()

    def on_devices(self, names: list[str]) -> None:
        self.devices.append(names)
        self.got_devices.set()


def _client(sink: _Sink, *, dispatch=lambda fn: fn()) -> PlayerClient:
    return PlayerClient(
        dispatch=dispatch,
        on_state=sink.on_state,
        on_error=lambda k, m: sink.errors.append((k, m)),
        on_position=sink.positions.append,
        on_info=sink.infos.append,
        on_title=sink.titles.append,
        config=OutputConfig(),
        spawn=_spawn,
    )


class PlayerClientTests(unittest.TestCase):
    def test_plays_a_file_to_the_end(self) -> None:
        sink = _Sink()
        client = _client(sink)

        client.play(_wav(), live=False, volume=0.5)
        self.assertTrue(sink.stopped.wait(10))
        client.close()

        self.assertEqual(sink.states, [State.PLAYING, State.STOPPED])
        self.assertEqual(sink.errors, [])
        self.assertEqual(sink.infos[0].channels, 2)

    def test_events_from_a_superseded_play_are_dropped(self) -> None:
        sink = _Sink()
        client = _client(sink)

        client.play(_wav(2.0), live=False, volume=0.5)
        client.stop()
        pause = threading.Event()
        pause.wait(0.3)
        client.close()

        self.assertEqual(sink.states, [])

    def test_devices_come_from_the_child(self) -> None:
        sink = _Sink()
        client = _client(sink)

        client.request_devices(sink.on_devices)
        self.assertTrue(sink.got_devices.wait(10))
        client.close()

        self.assertIsInstance(sink.devices[0], list)

    def test_child_exits_when_the_parent_closes_stdin(self) -> None:
        process = _spawn()
        process.stdin.close()
        process.wait(timeout=10)

        self.assertEqual(process.returncode, 0)

    def test_close_terminates_the_child(self) -> None:
        sink = _Sink()
        client = _client(sink)
        client.request_devices(sink.on_devices)
        self.assertTrue(sink.got_devices.wait(10))
        process = client._process

        client.close()

        self.assertIsNotNone(process.returncode)


@pytest.mark.parametrize("retire", [None, "stop", "play"])
@pytest.mark.parametrize(
    ("event", "attribute", "expected"),
    [
        (
            protocol.StateEvent(generation=0, state=State.PLAYING),
            "states",
            State.PLAYING,
        ),
        (
            protocol.Error(generation=0, kind="decode", message="old error"),
            "errors",
            ("decode", "old error"),
        ),
        (protocol.Position(generation=0, seconds=42), "positions", 42),
        (
            protocol.InfoEvent(
                generation=0,
                info=protocol.AudioStreamInfo(channels=2, sample_rate=48000),
            ),
            "infos",
            protocol.AudioStreamInfo(channels=2, sample_rate=48000),
        ),
        (protocol.Title(generation=0, title="old title"), "titles", "old title"),
    ],
)
def test_queued_events_check_generation_when_delivered(
    retire, event, attribute, expected
):
    sink = _Sink()
    queued = []
    client = _client(sink, dispatch=queued.append)
    try:
        client._handle(event)
        callback = queued.pop()
        if retire == "stop":
            client.stop()
        elif retire == "play":
            client.play(_wav(), live=False, volume=0.5)

        callback()

        assert getattr(sink, attribute) == ([expected] if retire is None else [])
    finally:
        client.close()


def test_queued_device_list_survives_stop():
    sink = _Sink()
    queued = []
    received = threading.Event()

    def dispatch(callback):
        queued.append(callback)
        received.set()

    client = _client(sink, dispatch=dispatch)
    try:
        client.request_devices(sink.on_devices)
        assert received.wait(10)
        client.stop()
        for callback in tuple(queued):
            callback()

        assert sink.devices == [[]]
    finally:
        client.close()


@pytest.mark.parametrize("retire", [None, "stop", "play"])
def test_queued_child_loss_checks_generation_when_delivered(retire):
    sink = _Sink()
    queued = []
    client = _client(sink, dispatch=queued.append)
    client._process = process = object()
    try:
        client._child_lost(process)
        callbacks = tuple(queued)
        if retire == "stop":
            client.stop()
        elif retire == "play":
            client.play(_wav(), live=False, volume=0.5)

        for callback in callbacks:
            callback()

        assert sink.errors == (
            [("device", "player process exited")] if retire is None else []
        )
        assert sink.states == ([State.STOPPED] if retire is None else [])
    finally:
        client.close()


def test_child_loss_after_stop_cannot_report_against_retired_playback():
    sink = _Sink()
    queued = []
    client = _client(sink, dispatch=queued.append)
    client._process = process = SimpleNamespace(stdin=BytesIO(), poll=lambda: None)
    client.play("old", live=True, volume=1.0)
    client.stop()

    client._child_lost(process)
    for callback in queued:
        callback()

    assert sink.errors == []
    assert sink.states == []


if __name__ == "__main__":
    unittest.main()
