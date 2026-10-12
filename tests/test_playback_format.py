import unittest

from addictune_cli.src.audio.protocol import AudioStreamInfo
from addictune_cli.src.tui.widgets.playback_format import (
    format_stream_quality,
    stream_quality_from_url,
)


class StreamQualityFormatTests(unittest.TestCase):
    def test_live_quality_comes_from_sdk_stream_tier(self) -> None:
        cases = {
            "premium_high": ("MP3 · 320k", "Source: MP3 · 320 kbps"),
            "premium": ("AAC · 128k", "Source: AAC · 128 kbps"),
            "premium_medium": ("AAC · 64k", "Source: AAC · 64 kbps"),
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                url = f"https://listen.di.fm/{path}/trance.pls?listen_key=secret"
                self.assertEqual(stream_quality_from_url(url), expected)

        self.assertIsNone(stream_quality_from_url("https://example.test/audio"))

    def test_compact_label_prioritizes_codec_and_bitrate(self) -> None:
        info = AudioStreamInfo(
            channels=2,
            sample_rate=44_100,
            layout="stereo",
            codec_name="aac",
            bit_rate=127_999,
        )

        label, tooltip = format_stream_quality(info)

        self.assertEqual(label, "AAC · 128k")
        self.assertEqual(tooltip, "Source: AAC · 128 kbps · 44.1 kHz · Stereo")

    def test_sample_rate_is_the_fallback_when_bitrate_is_unknown(self) -> None:
        info = AudioStreamInfo(
            channels=1,
            sample_rate=48_000,
            codec_name="opus",
        )

        label, tooltip = format_stream_quality(info)

        self.assertEqual(label, "OPUS · 48 kHz")
        self.assertEqual(tooltip, "Source: OPUS · 48 kHz · Mono")

    def test_unknown_codec_still_exposes_declared_bitrate(self) -> None:
        info = AudioStreamInfo(
            channels=6,
            sample_rate=48_000,
            bit_rate=320_000,
        )

        label, tooltip = format_stream_quality(info)

        self.assertEqual(label, "320 kbps")
        self.assertEqual(tooltip, "Source: 320 kbps · 48 kHz · 6 channels")


if __name__ == "__main__":
    unittest.main()
