import sys
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows bindings")
class SmtcBindingTests(unittest.TestCase):
    def test_native_media_projections_are_available(self) -> None:
        from winrt.windows.foundation import EventRegistrationToken, Uri
        from winrt.windows.media import (
            MediaPlaybackStatus,
            MediaPlaybackType,
            SystemMediaTransportControlsButton,
        )
        from winrt.windows.media.playback import MediaPlayer
        from winrt.windows.storage.streams import RandomAccessStreamReference

        self.assertTrue(
            all(
                callable(binding)
                for binding in (
                    EventRegistrationToken,
                    MediaPlaybackStatus,
                    MediaPlaybackType,
                    SystemMediaTransportControlsButton,
                    MediaPlayer,
                    RandomAccessStreamReference,
                )
            )
        )
        self.assertEqual(
            Uri("https://example.test/artwork.png").absolute_uri,
            "https://example.test/artwork.png",
        )
