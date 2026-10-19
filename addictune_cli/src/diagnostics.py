"""Account-free startup diagnostics for source installs and standalone releases."""

import asyncio
import os
import subprocess
from pathlib import Path

from textual.app import App

from .audio import protocol
from .subprocess_worker import worker_command
from .tui.app import AddictuneApp
from .tui.screens.about import AboutScreen
from .tui.screens.auth import AuthScreen


async def _check_ui() -> None:
    app = App(css_path=Path(__file__).parent / "tui" / AddictuneApp.CSS_PATH)
    async with app.run_test() as pilot:
        await app.push_screen(AuthScreen())
        await pilot.pause()
        app.pop_screen()
        await app.push_screen(AboutScreen())
        await pilot.pause()


def _check_telemetry() -> None:
    """Error reporting must survive compilation; record in memory, send nothing."""
    import sentry_sdk
    from sentry_sdk.transport import Transport

    from . import telemetry

    class _Recorder(Transport):
        events = 0

        def capture_envelope(self, envelope) -> None:
            _Recorder.events += sum(item.type == "event" for item in envelope.items)

    telemetry.init("app", True, transport=_Recorder())
    sentry_sdk.capture_message("self-test")
    sentry_sdk.flush(timeout=2)
    telemetry.init("app", False)
    if _Recorder.events != 1:
        raise RuntimeError("error reporting did not capture an event")


def run() -> None:
    asyncio.run(_check_ui())
    _check_telemetry()
    argv, worker_env = worker_command("player")
    result = subprocess.run(
        argv,
        input=f"{protocol.Devices().model_dump_json()}\n"
        f"{protocol.Quit().model_dump_json()}\n",
        env={**os.environ, **worker_env},
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )
    if result.returncode:
        raise RuntimeError(
            f"audio worker exited with {result.returncode}:\n{result.stderr}"
        )
    if not isinstance(
        protocol.event_adapter.validate_json(result.stdout), protocol.DeviceList
    ):
        raise RuntimeError("audio worker did not return its device list")
    print("Self-test passed.")
