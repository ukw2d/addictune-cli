import unittest
from unittest import mock

import av

from addictune_cli.src.audio import stream as stream_module
from addictune_cli.src.audio.stream import _IcyAudioSource, _packed_audio_bytes


class _FakeSocket:
    def __init__(self, data: bytes) -> None:
        self._data = bytearray(data)
        self.closed = False

    def recv(self, size: int) -> bytes:
        if not self._data:
            return b""
        chunk = bytes(self._data[:size])
        del self._data[:size]
        return chunk

    def close(self) -> None:
        self.closed = True


class PackedAudioBytesTests(unittest.TestCase):
    def test_trims_resampler_alignment_padding(self) -> None:
        """The real-world case: 44100→48000 resampling produces padded planes."""
        frame = av.AudioFrame(format="flt", layout="stereo", samples=1152)
        frame.sample_rate = 44100
        resampler = av.AudioResampler(format="flt", layout="stereo", rate=48000)

        out_frame = resampler.resample(frame)[0]
        logical_size = (
            out_frame.samples * out_frame.layout.nb_channels * out_frame.format.bytes
        )

        self.assertGreater(out_frame.planes[0].buffer_size, logical_size)
        self.assertEqual(len(_packed_audio_bytes(out_frame)), logical_size)

    def test_multichannel(self) -> None:
        frame = av.AudioFrame(format="flt", layout="5.1", samples=100)
        self.assertEqual(len(_packed_audio_bytes(frame)), 100 * 6 * 4)


class IcyAudioSourceTests(unittest.TestCase):
    def test_strips_metadata_and_emits_stream_title(self) -> None:
        titles: list[str] = []
        meta = b"StreamTitle='Artist - Track';"
        padded = meta + b"\x00" * (32 - len(meta))
        data = b"abcd" + bytes([2]) + padded + b"efgh"

        source = _IcyAudioSource(
            _FakeSocket(data), metaint=4, on_metadata=titles.append, stop=None
        )

        self.assertEqual(source.read(8), b"abcdefgh")
        self.assertEqual(titles, ["Artist - Track"])


class _TimeoutSocket:
    """Socket stub simulating a silently stalled connection."""

    def recv(self, size: int) -> bytes:
        raise TimeoutError

    def close(self) -> None:
        pass


class IcyAudioSourceEndOfStreamTests(unittest.TestCase):
    """The end of a stream has to latch.

    libav answers a short read by reading again, so an unlatched EOF restarts
    the stall countdown on every retry: the player then never exits, and the
    app keeps showing a dead stream as playing.
    """

    def test_a_stall_ends_the_stream_for_good(self) -> None:
        # The clock reads 0 while the deadline is set, then jumps past the
        # stall budget, asserting the give-up branch with no real sleeping.
        clock = iter([0.0])
        with mock.patch.object(
            stream_module.time,
            "perf_counter",
            lambda: next(clock, stream_module._ICY_STALL_TIMEOUT + 1.0),
        ):
            source = _IcyAudioSource(
                _TimeoutSocket(), metaint=4, on_metadata=lambda _: None, stop=None
            )
            self.assertEqual(source._recv(8), b"")

        self.assertTrue(source._ended)
        # Without the latch this would burn a whole fresh stall budget.
        self.assertEqual(source._recv(8), b"")
        self.assertEqual(source.read(8), b"")

    def test_a_closed_connection_ends_the_stream_for_good(self) -> None:
        source = _IcyAudioSource(
            _FakeSocket(b""), metaint=4, on_metadata=lambda _: None, stop=None
        )

        self.assertEqual(source.read(8), b"")
        self.assertTrue(source._ended)
        source._sock = None  # a further read must not touch the socket
        self.assertEqual(source.read(8), b"")

    def test_data_still_flows_before_the_stream_ends(self) -> None:
        source = _IcyAudioSource(
            _FakeSocket(b"abcd"), metaint=4, on_metadata=lambda _: None, stop=None
        )

        self.assertEqual(source.read(4), b"abcd")
        self.assertFalse(source._ended)


if __name__ == "__main__":
    unittest.main()
