import argparse
import logging
import os

from .logging_setup import setup_logging

# Textual reads this in App.__init__, so it must be set before the app is
# constructed. "devtools" streams self.log to a running `textual console`.
_TEXTUAL_ENV = "TEXTUAL"
_DEV_ENV = "ADDICTUNE_DEV"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="addictune")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="log at DEBUG and stream to a running `textual console`",
    )
    parser.add_argument("--log-level", metavar="LEVEL", help="DEBUG, INFO, WARNING")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="check UI resources and the audio worker without signing in",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    if args.self_test:
        from .diagnostics import run

        run()
        return
    if args.dev or os.environ.get(_DEV_ENV) == "1":
        os.environ[_TEXTUAL_ENV] = "devtools,debug"
        os.environ.setdefault("ADDICTUNE_LOG_LEVEL", "DEBUG")
    if args.log_level:
        os.environ["ADDICTUNE_LOG_LEVEL"] = args.log_level

    path = setup_logging("app")
    log = logging.getLogger("addictune_cli.startup")
    log.info("=== addictune-cli start pid=%s log=%s ===", os.getpid(), path)

    from .telemetry import init as init_telemetry
    from .tui.app import AddictuneApp

    app = AddictuneApp()
    init_telemetry("app", app.settings.telemetry)
    app.run()


if __name__ == "__main__":
    main()
