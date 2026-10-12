"""`make_session` never raises: unsupported platform or missing bindings fall
back to `NullSession`; backends ignore repeated identical info."""

import sys
import unittest
from unittest.mock import patch

from addictune_cli.src.media.session import (
    Command,
    MediaInfo,
    NullSession,
    make_session,
)


class MakeSessionTests(unittest.TestCase):
    def test_unsupported_platform_gives_null_session(self) -> None:
        with patch.object(sys, "platform", "freebsd14"):
            self.assertIsInstance(make_session(lambda fn: fn()), NullSession)

    def test_missing_bindings_give_null_session(self) -> None:
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(sys.modules, {"addictune_cli.src.media.linux": None}),
        ):
            self.assertIsInstance(make_session(lambda fn: fn()), NullSession)

    def test_backend_constructor_failure_gives_null_session(self) -> None:
        class Broken:
            def __init__(self, call_soon) -> None:
                raise RuntimeError("no session bus")

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(
                sys.modules, {"addictune_cli.src.media.linux": type(sys)("linux")}
            ),
        ):
            sys.modules["addictune_cli.src.media.linux"].MprisSession = Broken
            self.assertIsInstance(make_session(lambda fn: fn()), NullSession)

    def test_null_session_accepts_the_whole_protocol(self) -> None:
        null = NullSession()
        null.start(lambda command: None, lambda seconds, fn: None)
        null.update(MediaInfo(title="x", playing=True))
        null.stop()

    def test_media_info_is_a_value(self) -> None:
        self.assertEqual(MediaInfo(title="a"), MediaInfo(title="a"))
        self.assertEqual(set(Command), {"play", "pause", "toggle", "next", "previous"})


if __name__ == "__main__":
    unittest.main()
