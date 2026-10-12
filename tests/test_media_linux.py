"""MPRIS backend: pure mapping helpers and the Player interface wiring.

Runs only on Linux with dbus-fast installed; the bus itself is not touched.
"""

import sys
import unittest

if not sys.platform.startswith("linux"):
    raise unittest.SkipTest("MPRIS tests require Linux")
try:
    import dbus_fast  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("MPRIS tests require dbus_fast") from exc

from addictune_cli.src.media.linux import (
    MprisSession,
    _Player,
    metadata,
    playback_status,
)
from addictune_cli.src.media.session import Command, MediaInfo


class MprisTests(unittest.TestCase):
    def test_status_and_metadata_mapping(self) -> None:
        info = MediaInfo(
            title="Track",
            artist="Artist",
            artwork_url="https://a/b.png",
            playing=True,
            can_play=True,
        )
        self.assertEqual(playback_status(info), "Playing")
        self.assertEqual(playback_status(MediaInfo(can_play=True)), "Paused")
        self.assertEqual(playback_status(MediaInfo()), "Stopped")
        data = metadata(info)
        self.assertEqual(data["xesam:title"].value, "Track")
        self.assertEqual(data["xesam:artist"].value, ["Artist"])
        self.assertEqual(data["mpris:artUrl"].value, "https://a/b.png")

    def test_player_methods_emit_commands_and_reflect_info(self) -> None:
        delivered: list[Command] = []
        session = MprisSession(call_soon=lambda fn: fn())
        session.on_command = delivered.append
        player = _Player(session)

        player.Play()
        player.Pause()
        player.PlayPause()
        player.Next()
        player.Previous()

        self.assertEqual(
            delivered,
            [
                Command.PLAY,
                Command.PAUSE,
                Command.TOGGLE,
                Command.NEXT,
                Command.PREVIOUS,
            ],
        )
        self.assertFalse(player.CanGoNext)
        session.update(MediaInfo(can_next=True, can_play=True, playing=True))
        self.assertTrue(player.CanGoNext)
        self.assertEqual(player.PlaybackStatus, "Playing")


if __name__ == "__main__":
    unittest.main()
