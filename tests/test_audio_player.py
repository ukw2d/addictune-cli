"""`Player` runs one decode thread per play and reports through callbacks.

The stream and the output are injected so these tests run without a sound card
or network: a fake output records what was written, and a fake stream yields a
scripted number of chunks, optionally gated by the test.
"""

import threading
import unittest

from addictune_cli.src.audio.output import OutputConfig
from addictune_cli.src.audio.player import Player
from addictune_cli.src.audio.protocol import AudioStreamInfo
from addictune_cli.src.audio.state import State

_CHUNK = b"\x00" * 1024
_INFO = AudioStreamInfo(channels=2, sample_rate=48000)


class _FakeOutput:
    instances: list["_FakeOutput"] = []

    def __init__(self, config: OutputConfig, channels: int, sample_rate: int) -> None:
        self.config = config
        self.channels = channels
        self.sample_rate = sample_rate
        self.fell_back = False
        self.written = 0
        self.closed = False
        _FakeOutput.instances.append(self)

    def write(self, data: bytes) -> None:
        self.written += len(data)

    def close(self) -> None:
        self.closed = True


class _FakeStream:
    def __init__(
        self,
        chunks: int,
        gate: threading.Event | None,
        start_at: float,
        stop: threading.Event,
    ) -> None:
        self._chunks = chunks
        self._gate = gate
        self._stop = stop
        self.start_at = start_at
        self.info = _INFO
        self.channels = 2
        self.sample_rate = 48000
        self.volumes: list[float] = []
        self.closed = False

    def set_volume(self, volume: float) -> None:
        self.volumes.append(volume)

    def chunks(self):
        """Yield one chunk at once, then hold at the gate (or until stopped)."""
        pause = threading.Event()
        for i in range(self._chunks):
            while i and self._gate is not None and not self._gate.is_set():
                if self._stop.is_set():
                    return
                pause.wait(0.005)
            if self._stop.is_set():
                return
            yield _CHUNK

    def close(self) -> None:
        self.closed = True


class _Opener:
    """`open_stream` that records every open and serves scripted streams."""

    def __init__(self, chunks: int, gate: threading.Event | None = None) -> None:
        self.chunks = chunks
        self.gate = gate
        self.streams: list[_FakeStream] = []

    def __call__(
        self, url, *, live, start_at, sample_rate, volume, stop, on_title
    ) -> _FakeStream:
        stream = _FakeStream(self.chunks, self.gate, start_at, stop)
        stream.volumes.append(volume)
        self.streams.append(stream)
        return stream


class _Events:
    def __init__(self) -> None:
        self.states: list[tuple[int, State]] = []
        self.errors: list[tuple[int, str, str]] = []
        self.done = threading.Event()

    def on_state(self, gen: int, state: State) -> None:
        self.states.append((gen, state))
        if state == State.STOPPED:
            self.done.set()

    def on_error(self, gen: int, kind: str, message: str) -> None:
        self.errors.append((gen, kind, message))


def _player(
    events: _Events,
    opener,
    *,
    signature=lambda: (),
    open_output=_FakeOutput,
    device_names=lambda: [],
    refresh_devices=lambda: None,
) -> Player:
    return Player(
        open_stream=opener,
        open_output=open_output,
        signature=signature,
        device_names=device_names,
        refresh_devices=refresh_devices,
        on_state=events.on_state,
        on_error=events.on_error,
        on_position=lambda gen, s: None,
        on_info=lambda gen, info: None,
        on_title=lambda gen, title: None,
    )


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    pause = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return True
        pause.wait(0.01)
    return predicate()


class PlayerTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeOutput.instances.clear()

    def test_plays_to_the_end_and_reports_playing_then_stopped(self) -> None:
        events = _Events()
        opener = _Opener(3)
        player = _player(events, opener)

        gen = 1
        player.play(gen, "u", live=False, volume=0.5)
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(events.states, [(gen, State.PLAYING), (gen, State.STOPPED)])
        self.assertEqual(_FakeOutput.instances[0].written, 3 * len(_CHUNK))
        self.assertTrue(_FakeOutput.instances[0].closed)
        self.assertTrue(opener.streams[0].closed)
        self.assertEqual(opener.streams[0].volumes[0], 0.5)

    def test_play_while_playing_retires_the_old_generation_silently(self) -> None:
        events = _Events()
        gate = threading.Event()
        opener = _Opener(100, gate)
        player = _player(events, opener)

        gen1, gen2 = 1, 2
        player.play(gen1, "a", live=False, volume=1.0)
        player.play(gen2, "b", live=False, volume=1.0)
        opener.chunks = 1
        gate.set()
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertNotEqual(gen1, gen2)
        self.assertNotIn((gen1, State.STOPPED), events.states)
        self.assertIn((gen2, State.STOPPED), events.states)
        self.assertTrue(all(s.closed for s in opener.streams))

    def test_pause_blocks_writes_and_resume_continues(self) -> None:
        events = _Events()
        gate = threading.Event()
        player = _player(events, _Opener(4, gate))

        gen = 1
        player.play(gen, "u", live=False, volume=1.0)
        player.pause()
        gate.set()
        self.assertTrue(_wait_until(lambda: (gen, State.PAUSED) in events.states))
        pause = threading.Event()
        pause.wait(0.1)
        written_while_paused = _FakeOutput.instances[0].written
        player.resume()
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertLess(written_while_paused, 4 * len(_CHUNK))
        self.assertEqual(_FakeOutput.instances[0].written, 4 * len(_CHUNK))
        self.assertIn((gen, State.PLAYING), events.states[1:])

    def test_stop_reports_stopped_once(self) -> None:
        events = _Events()
        gate = threading.Event()
        player = _player(events, _Opener(100, gate))

        gen = 1
        player.play(gen, "u", live=False, volume=1.0)
        self.assertTrue(_wait_until(lambda: (gen, State.PLAYING) in events.states))
        player.stop()
        gate.set()
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(events.states.count((gen, State.STOPPED)), 1)

    def test_signature_change_reopens_output_at_the_current_position(self) -> None:
        events = _Events()
        sig = [("a",)]
        gate = threading.Event()
        opener = _Opener(6, gate)
        player = _player(events, opener, signature=lambda: sig[0])

        player.play(1, "u", live=False, volume=1.0)
        self.assertTrue(
            _wait_until(
                lambda: _FakeOutput.instances and _FakeOutput.instances[0].written > 0
            )
        )
        sig[0] = ("b",)
        player.check_output()
        gate.set()
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(len(_FakeOutput.instances), 2)
        self.assertTrue(_FakeOutput.instances[0].closed)
        self.assertEqual(len(opener.streams), 2)
        self.assertGreater(opener.streams[1].start_at, 0.0)
        self.assertEqual(events.states.count((1, State.PLAYING)), 1)

    def test_unchanged_signature_does_not_reopen(self) -> None:
        events = _Events()
        opener = _Opener(3)
        player = _player(events, opener, signature=lambda: ("a",))

        player.play(1, "u", live=False, volume=1.0)
        player.check_output()
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(len(opener.streams), 1)

    def test_configure_reopens_with_the_new_config(self) -> None:
        events = _Events()
        gate = threading.Event()
        player = _player(events, _Opener(6, gate))

        player.play(1, "u", live=False, volume=1.0)
        self.assertTrue(
            _wait_until(
                lambda: _FakeOutput.instances and _FakeOutput.instances[0].written > 0
            )
        )
        player.configure(OutputConfig(device_name="DAC"))
        gate.set()
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(_FakeOutput.instances[-1].config.device_name, "DAC")

    def test_seek_reopens_at_the_new_position_for_on_demand_only(self) -> None:
        events = _Events()
        gate = threading.Event()
        opener = _Opener(6, gate)
        player = _player(events, opener)

        player.play(1, "u", live=False, volume=1.0, start_at=10.0)
        self.assertTrue(_wait_until(lambda: len(opener.streams) == 1))
        player.seek(30.0)
        gate.set()
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(len(opener.streams), 2)
        self.assertGreaterEqual(opener.streams[1].start_at, 40.0)

    def test_seek_is_ignored_for_live(self) -> None:
        events = _Events()
        opener = _Opener(3)
        player = _player(events, opener)

        player.play(1, "u", live=True, volume=1.0)
        player.seek(30.0)
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(len(opener.streams), 1)

    def test_stream_open_failure_reports_decode_error_then_stopped(self) -> None:
        events = _Events()

        def broken(url, **kwargs):
            raise RuntimeError("boom")

        player = _player(events, broken)
        gen = 1
        player.play(gen, "u", live=False, volume=1.0)
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(events.errors, [(gen, "decode", "boom")])
        self.assertEqual(events.states, [(gen, State.STOPPED)])

    def test_a_failure_message_never_carries_the_signed_url_secrets(self) -> None:
        """libav errors quote the URL they failed on, and a stream URL is signed."""
        url = "https://content.example/t.mp3?audio_token=s3cret&auth=s1gn&member_id=42"
        events = _Events()

        def broken(_url, **kwargs):
            raise OSError(5, "Input/output error", url)

        player = _player(events, broken)
        with self.assertLogs("audio.player", level="ERROR") as logs:
            player.play(1, url, live=False, volume=1.0)
            self.assertTrue(events.done.wait(2))
        player.close()

        ((_, _, message),) = events.errors
        for text in (message, "\n".join(logs.output)):
            self.assertIn("content.example/t.mp3", text)
            for secret in ("s3cret", "s1gn", "42"):
                self.assertNotIn(secret, text)

    def test_output_failure_is_a_device_error(self) -> None:
        events = _Events()

        def no_output(config, channels, sample_rate):
            raise OSError("no device")

        opener = _Opener(1)
        player = _player(events, opener, open_output=no_output)
        gen = 1
        player.play(gen, "u", live=False, volume=1.0)
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(events.errors[0][:2], (gen, "device"))
        self.assertTrue(opener.streams[0].closed)

    def test_missing_named_device_is_reported_once_and_playback_continues(self) -> None:
        events = _Events()

        class _Fallback(_FakeOutput):
            def __init__(self, config, channels, sample_rate) -> None:
                super().__init__(config, channels, sample_rate)
                self.fell_back = True

        player = _player(events, _Opener(2), open_output=_Fallback)
        player.configure(OutputConfig(device_name="Gone"))
        gen = 1
        player.play(gen, "u", live=False, volume=1.0)
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(events.errors, [(gen, "device_missing", "Gone")])
        self.assertEqual(events.states, [(gen, State.PLAYING), (gen, State.STOPPED)])


class DevicesTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeOutput.instances.clear()

    def test_devices_refresh_portaudio_only_while_idle(self) -> None:
        # Re-initialising PortAudio under an open stream kills it (owner bug:
        # opening Settings during playback went silent), so the refresh must
        # happen only when no output is open.
        events = _Events()
        refreshes: list[str] = []
        gate = threading.Event()
        player = _player(
            events,
            _Opener(4, gate),
            device_names=lambda: ["A", "B"],
            refresh_devices=lambda: refreshes.append("refresh"),
        )

        self.assertEqual(player.devices(), ["A", "B"])
        self.assertEqual(refreshes, ["refresh"])
        player.play(1, "u", live=False, volume=1.0)
        self.assertTrue(_wait_until(lambda: _FakeOutput.instances))
        self.assertEqual(player.devices(), ["A", "B"])
        self.assertEqual(refreshes, ["refresh"])  # no refresh while playing
        gate.set()
        self.assertTrue(events.done.wait(2))
        player.close()
        self.assertEqual(len(_FakeOutput.instances), 1)  # and no reopen
        self.assertEqual(len(events.errors), 0)

        player.devices()
        self.assertEqual(refreshes, ["refresh", "refresh"])  # idle again


class OutputReuseTests(unittest.TestCase):
    """The device stays open across plays: opening/closing it pops on many DACs."""

    def setUp(self) -> None:
        _FakeOutput.instances.clear()

    def _play_and_wait(
        self, player: Player, events: _Events, gen: int, url: str = "u"
    ) -> None:
        events.done.clear()
        player.play(gen, url, live=True, volume=1.0)
        self.assertTrue(events.done.wait(2))

    def test_switching_channels_reuses_one_output(self) -> None:
        events = _Events()
        player = _player(events, _Opener(3))

        for gen in (1, 2, 3, 4, 5):
            self._play_and_wait(player, events, gen)

        self.assertEqual(len(_FakeOutput.instances), 1)
        self.assertFalse(_FakeOutput.instances[0].closed)
        self.assertEqual(_FakeOutput.instances[0].written, 5 * 3 * len(_CHUNK))
        player.close()
        self.assertTrue(_FakeOutput.instances[0].closed)

    def test_rapid_switching_while_playing_still_uses_one_output(self) -> None:
        events = _Events()
        gate = threading.Event()
        player = _player(events, _Opener(100, gate))

        for gen in range(1, 9):
            player.play(gen, "u", live=True, volume=1.0)
        self.assertTrue(_wait_until(lambda: _FakeOutput.instances))
        gate.set()
        player.stop()
        self.assertTrue(events.done.wait(2))
        player.close()

        self.assertEqual(len(_FakeOutput.instances), 1)

    def test_a_different_format_reopens_the_output(self) -> None:
        events = _Events()
        opener = _Opener(2)
        player = _player(events, opener)

        self._play_and_wait(player, events, 1)
        original = opener.__call__

        def mono_44k(url, **kwargs):
            stream = original(url, **kwargs)
            stream.channels, stream.sample_rate = 1, 44100
            return stream

        player._open_stream = mono_44k
        self._play_and_wait(player, events, 2)
        player.close()

        self.assertEqual(len(_FakeOutput.instances), 2)
        self.assertTrue(_FakeOutput.instances[0].closed)
        self.assertEqual(_FakeOutput.instances[1].channels, 1)

    def test_superseded_stream_open_cannot_replace_the_current_output(self) -> None:
        events = _Events()
        opening = threading.Event()
        release_old = threading.Event()
        release_current = threading.Event()
        opener = _Opener(2, release_current)

        def open_stream(url, **kwargs):
            stream = opener(url, **kwargs)
            if url == "old":
                stream.channels, stream.sample_rate = 1, 44100
                opening.set()
                self.assertTrue(release_old.wait(2))
            return stream

        player = _player(events, open_stream)
        try:
            player.play(1, "old", live=False, volume=1.0)
            self.assertTrue(opening.wait(2))
            player.play(2, "current", live=False, volume=1.0)
            self.assertTrue(
                _wait_until(
                    lambda: (
                        _FakeOutput.instances
                        and _FakeOutput.instances[0].written == len(_CHUNK)
                    )
                )
            )
            current_output = _FakeOutput.instances[0]

            release_old.set()
            self.assertTrue(_wait_until(lambda: opener.streams[0].closed))

            self.assertEqual(len(_FakeOutput.instances), 1)
            self.assertFalse(current_output.closed)
            release_current.set()
            self.assertTrue(events.done.wait(2))
            self.assertEqual(current_output.written, 2 * len(_CHUNK))
            self.assertEqual(events.errors, [])
        finally:
            release_old.set()
            release_current.set()
            player.close()

    def test_configure_and_hotplug_reopen_even_between_plays(self) -> None:
        events = _Events()
        sig = [("a",)]
        player = _player(events, _Opener(2), signature=lambda: sig[0])

        self._play_and_wait(player, events, 1)
        player.configure(OutputConfig(device_name="DAC"))
        self._play_and_wait(player, events, 2)
        sig[0] = ("b",)
        player.check_output()
        self._play_and_wait(player, events, 3)
        player.close()

        self.assertEqual(len(_FakeOutput.instances), 3)
        self.assertEqual(_FakeOutput.instances[1].config.device_name, "DAC")

    def test_device_refresh_closes_an_idle_output_first(self) -> None:
        # devices() re-initialises PortAudio, which invalidates an open stream.
        events = _Events()
        refreshes = []
        player = _player(
            events, _Opener(2), refresh_devices=lambda: refreshes.append("refresh")
        )

        self._play_and_wait(player, events, 1)
        self.assertFalse(_FakeOutput.instances[0].closed)
        player.devices()
        self.assertTrue(_FakeOutput.instances[0].closed)
        self.assertEqual(refreshes, ["refresh"])

        self._play_and_wait(player, events, 2)
        player.close()
        self.assertEqual(len(_FakeOutput.instances), 2)


if __name__ == "__main__":
    unittest.main()
