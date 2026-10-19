"""Error reports reach the maintainer without the user's secrets.

Every test records events in memory through a custom transport; nothing is
sent anywhere.
"""

import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import sentry_sdk
from sentry_sdk.transport import Transport
from textual.app import App, ComposeResult

from addictune_cli.src import telemetry
from addictune_cli.src.audio import client as audio_client
from addictune_cli.src.audio.state import State
from addictune_cli.src.media.session import NullSession
from addictune_cli.src.settings import Settings
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar

from support import temp_settings


class _Recorder(Transport):
    def __init__(self, options=None) -> None:
        super().__init__(options)
        self.events: list[dict] = []

    def capture_envelope(self, envelope) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


class _TelemetryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.recorder = _Recorder()
        telemetry.init("app", True, transport=self.recorder)
        sentry_sdk.get_isolation_scope().clear_breadcrumbs()
        self.addCleanup(telemetry.init, "app", False)
        self.addCleanup(telemetry.secrets.clear)

    def flush(self) -> list[dict]:
        sentry_sdk.flush(timeout=2)
        return self.recorder.events


class InitTests(unittest.TestCase):
    def test_reports_are_on_by_default(self) -> None:
        self.assertTrue(Settings().telemetry)

    def test_the_player_child_inherits_the_decision(self) -> None:
        self.addCleanup(telemetry.init, "app", False)
        for enabled, expected in ((True, "1"), (False, "0")):
            telemetry.init("app", enabled, transport=_Recorder())
            with mock.patch.object(audio_client.subprocess, "Popen") as popen:
                audio_client._spawn_worker()
            env = popen.call_args.kwargs["env"]
            self.assertEqual(env[telemetry.TELEMETRY_ENV], expected)
            self.assertIn("PATH", env)  # still the parent's environment
        self.assertEqual(os.environ.get(telemetry.TELEMETRY_ENV), None)

    def test_disabled_means_no_client(self) -> None:
        telemetry.init("app", False)
        self.assertFalse(sentry_sdk.get_client().is_active())

    def test_enabled_tags_the_role_and_versions(self) -> None:
        recorder = _Recorder()
        telemetry.init("player", True, transport=recorder)
        self.addCleanup(telemetry.init, "app", False)
        sentry_sdk.capture_message("x")
        sentry_sdk.flush(timeout=2)

        (event,) = recorder.events
        self.assertEqual(event["tags"]["role"], "player")
        self.assertIn("pyav", event["tags"])
        self.assertTrue(event["release"].startswith("addictune-cli@"))


class ScrubberTests(_TelemetryCase):
    def test_no_secret_reaches_an_event(self) -> None:
        telemetry.remember_secrets(
            "[EMAIL_REDACTED]", "pa55word", "fceffbccd2", 13716939, "", None
        )
        home = str(Path.home())
        logging.getLogger("addictune_cli.test").warning(
            "login as [EMAIL_REDACTED] with fceffbccd2, GET /di/members/13716939/favorites"
        )
        try:
            raise OSError(
                f"failed: 'https://content.example/t.mp3?audio_token=TOK&auth=SIG'"
                f" 'http://prem2.di.fm:80/x_hi?fceffbccd2' pa55word {home}/x"
            )
        except OSError as exc:
            sentry_sdk.capture_exception(exc)

        telemetry.secrets.clear()  # a later event must not re-expose an old breadcrumb
        (event,) = self.flush()
        text = repr(event)
        for secret in (
            "[EMAIL_REDACTED]",
            "pa55word",
            "fceffbccd2",
            "13716939",
            "TOK",
            "SIG",
            home,
        ):
            self.assertNotIn(secret, text)
        # An empty value is not a secret: replacing "" would garble every string.
        self.assertNotIn("", telemetry.secrets)
        self.assertNotIn("user", event)
        self.assertNotIn("server_name", event)
        self.assertIn("content.example/t.mp3", text)

    def test_local_variables_are_never_sent(self) -> None:
        local_secret = "only-in-a-frame-local"  # noqa: F841 -- the SDK could capture it
        try:
            raise ValueError("boom")
        except ValueError as exc:
            sentry_sdk.capture_exception(exc)

        (event,) = self.flush()
        frames = event["exception"]["values"][0]["stacktrace"]["frames"]
        self.assertTrue(all("vars" not in frame for frame in frames))
        self.assertNotIn("only-in-a-frame-local", repr(event))

    def test_log_lines_are_breadcrumbs_not_events(self) -> None:
        logging.getLogger("addictune_cli.test").error("a routine failure")
        sentry_sdk.capture_message("the real event")

        (event,) = self.flush()
        crumbs = [b["message"] for b in event["breadcrumbs"]["values"]]
        self.assertIn("a routine failure", crumbs)


class LogFileTests(unittest.TestCase):
    def test_reporting_does_not_make_debug_log_chattier(self) -> None:
        """Breadcrumbs need INFO records; the user's log file keeps its level."""
        from addictune_cli.src import logging_setup

        path = Path(tempfile.mkdtemp()) / "debug.log"
        handler = logging_setup.file_handler(path, "app", logging.WARNING)
        logger = logging.getLogger("addictune_cli.logfile_test")
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        telemetry.init("app", True, transport=_Recorder())
        self.addCleanup(telemetry.init, "app", False)

        logger.info("breadcrumb only")
        logger.warning("worth a log line")
        handler.flush()

        text = path.read_text()
        self.assertNotIn("breadcrumb only", text)
        self.assertIn("worth a log line", text)


class PlaybackFailureTests(_TelemetryCase):
    def test_different_failures_are_different_issues(self) -> None:
        for errno in (5, 111):
            telemetry.report_playback_failure(
                kind="decode",
                detail=f"[Errno {errno}] x: 'http://h/p'",
                content_type="live",
            )

        first, second = self.flush()
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_one_issue_per_root_cause_whatever_the_url(self) -> None:
        for url in ("http://prem1.di.fm/a_hi?k1", "http://prem4.di.fm/b_hi?k2"):
            telemetry.report_playback_failure(
                kind="decode",
                detail=f"[Errno 5] Input/output error: '{url}'; last error log: [tls] IO Error: -9806",
                content_type="live",
            )

        first, second = self.flush()
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["contexts"]["playback"]["kind"], "decode")
        self.assertIn("[tls] IO Error", first["message"])
        self.assertNotIn("k1", repr(first))


class _BarApp(App):
    CSS_PATH = "../addictune_cli/src/tui/styles/app.tcss"

    def __init__(self, premium: bool | None) -> None:
        super().__init__()
        self.client = SimpleNamespace(premium=premium, listen_key=None)
        self.network = "di"

    def compose(self) -> ComposeResult:
        yield PlaybackBar(temp_settings(), media_session=NullSession())


class PlaybackBarReportingTests(_TelemetryCase, unittest.IsolatedAsyncioTestCase):
    """The user-visible failure is reported once, after the retries, from the app."""

    async def _fail_live_stream(self, premium: bool | None, times: int) -> list[dict]:
        app = _BarApp(premium)
        async with app.run_test():
            app.notify = lambda *a, **kw: None
            bar = app.query_one(PlaybackBar)
            bar._player.play = mock.Mock()
            bar._player.stop = mock.Mock()
            bar._controller.play("http://s", "Trance", ContentType.LIVE)
            for _ in range(times):
                bar._on_player_error(
                    "decode",
                    "[Errno 5] Input/output error: 'http://prem2.di.fm/x_hi?k'",
                )
                bar._on_player_state(State.STOPPED)
            return self.flush()

    async def test_a_dropped_live_stream_is_one_report_after_the_retries(self) -> None:
        from addictune_cli.src.tui.services.playback_policy import MAX_RETRY_ATTEMPTS

        events = await self._fail_live_stream(True, MAX_RETRY_ATTEMPTS + 1)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["contexts"]["playback"]["kind"], "decode")
        self.assertEqual(events[0]["contexts"]["playback"]["content_type"], "live")
        self.assertNotIn("?k", repr(events[0]))

    async def test_a_free_account_refusal_is_not_a_bug_report(self) -> None:
        app = _BarApp(False)
        async with app.run_test():
            app.notify = lambda *a, **kw: None
            bar = app.query_one(PlaybackBar)
            bar._player.stop = mock.Mock()
            bar._controller.play("http://s", "Trance", ContentType.LIVE)
            bar._on_player_error(
                "decode", "Server returned 401 Unauthorized: 'http://x'"
            )
            bar._on_player_state(State.STOPPED)

        self.assertEqual(self.flush(), [])


if __name__ == "__main__":
    unittest.main()
