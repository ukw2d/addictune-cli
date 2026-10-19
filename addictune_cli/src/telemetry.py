"""Error reports to the maintainer's Sentry project, without the user's secrets.

One client per process: the app and each player child call :func:`init` with
their role. Reports are on by default (``Settings.telemetry``); nothing here
reads or writes the setting, callers pass the decision in.

What leaves the machine: exception type and stack (file paths with the home
directory replaced), the redacted message, recent log lines as breadcrumbs,
app/OS/library versions and the station slug. Local variables, the user, the
hostname and every URL credential are stripped in ``_scrub`` before send.
"""

import logging
import platform
import re
from importlib.metadata import version
from pathlib import Path

from .logging_setup import redact_url
from .subprocess_worker import IS_NUITKA

# The DSN is a public, write-only address: it lets a client send events to
# the project and nothing else, which is why every shipped app embeds it. It
# is the same for every installation and must never be user-editable (a
# changed value would silently send reports elsewhere), so it lives here,
# not in settings.
_DSN = "https://9da8aab8fa5b7a4ab9c6a06e50c61abf@o4512278309699584.ingest.de.sentry.io/4512282194280528"
_ENV = "release" if IS_NUITKA else "source"
TELEMETRY_ENV = "ADDICTUNE_TELEMETRY"
_URL = re.compile(r"https?://[^\s'\"<>]+")
# Not addictune_sdk: it logs the account id at INFO before login registers it
# as a secret.
_LOGGERS = ("addictune_cli", "audio")
_levels: dict[str, int] = {}  # logger levels before init lowered them

# Values the app learns at login (email, password, listen key, account id);
# replaced by *** wherever they appear.
secrets: set[str] = set()


def remember_secrets(*values: object) -> None:
    # An empty value (a missing listen key) would put *** between every character.
    secrets.update(text for value in values if (text := str(value or "")))


def init(role: str, enabled: bool, *, transport=None) -> None:
    """Start (or, when *enabled* is false, stop) reporting for this process."""
    import sentry_sdk

    # close() stops sending but leaves the client bound and is_active();
    # unbinding is what makes "off" visible to the player spawn, and closing
    # first keeps a repeated init from leaking the old transport thread.
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)
    if not enabled:
        for name, level in _levels.items():
            logging.getLogger(name).setLevel(level)
        _levels.clear()
        return
    from sentry_sdk.integrations.atexit import AtexitIntegration
    from sentry_sdk.integrations.dedupe import DedupeIntegration
    from sentry_sdk.integrations.excepthook import ExcepthookIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.threading import ThreadingIntegration

    sentry_sdk.init(
        dsn=_DSN,
        transport=transport,
        release=f"addictune-cli@{version('addictune-cli')}",
        environment=_ENV,
        # Neither send_default_pii nor data_collection: the SDK then collects
        # conservatively (no user, no IP), and _scrub enforces it regardless.
        include_local_variables=False,
        # The source is public; context lines would only repeat it, and they
        # are the one place a frame's literal values still show.
        include_source_context=False,
        server_name="",
        traces_sample_rate=None,
        auto_session_tracking=False,
        # Explicit so a Nuitka build reports like a source run and nothing
        # auto-enables on an installed library.
        default_integrations=False,
        auto_enabling_integrations=False,
        integrations=[
            # Log lines are context, never events by themselves.
            LoggingIntegration(level=logging.INFO, event_level=None),
            ExcepthookIntegration(always_run=True),
            ThreadingIntegration(),
            DedupeIntegration(),
            # The default callback prints to stderr; the player's stdout is a
            # protocol pipe and its stderr is discarded, so stay silent.
            AtexitIntegration(callback=lambda pending, timeout: None),
        ],
        before_send=_scrub,
        # Breadcrumbs are scrubbed when recorded as well as when sent, so a
        # secret learned later cannot be missing from an earlier line.
        before_breadcrumb=lambda crumb, hint: _scrub_value(crumb),
        shutdown_timeout=2,
    )
    sentry_sdk.set_tag("role", role)
    sentry_sdk.set_tag("os", f"{platform.system()} {platform.release()}")
    try:
        import av

        sentry_sdk.set_tag("pyav", av.__version__)
        sentry_sdk.set_tag(
            "ffmpeg", ".".join(map(str, av.library_versions["libavformat"]))
        )
    except Exception:  # noqa: BLE001 -- a tag is not worth failing init over
        pass
    # Breadcrumbs need INFO records; the file handler keeps its own level.
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        _levels.setdefault(name, logger.level)
        if logger.getEffectiveLevel() > logging.INFO:
            logger.setLevel(logging.INFO)


def capture(error: BaseException) -> None:
    import sentry_sdk

    sentry_sdk.capture_exception(error)


def set_network(slug: str) -> None:
    import sentry_sdk

    sentry_sdk.set_tag("network", slug)


def report_playback_failure(*, kind: str, detail: str, content_type: str) -> None:
    """One event per playback failure, grouped by cause rather than by URL.

    *kind* is "resolve" (the playlist fetch) or the player's failure kind.
    """
    import sentry_sdk

    cause = _URL.sub("<url>", detail)
    with sentry_sdk.new_scope() as scope:
        scope.set_context(
            "playback", {"kind": kind, "content_type": content_type, "detail": detail}
        )
        scope.fingerprint = ["playback", kind, cause]
        sentry_sdk.capture_message(f"playback {kind} failed: {detail}", level="error")


def _scrub(event: dict, hint: dict) -> dict:
    for key in ("user", "server_name", "request"):
        event.pop(key, None)
    return _scrub_value(event)


def _scrub_value(value):
    match value:
        case str():
            return _scrub_text(value)
        case dict():
            return {k: _scrub_value(v) for k, v in value.items()}
        case list():
            return [_scrub_value(v) for v in value]
        case _:
            return value


_HOME = str(Path.home())


def _scrub_text(text: str) -> str:
    text = _URL.sub(lambda m: redact_url(m.group(0)), text)
    for secret in tuple(secrets):  # login may add to it from another thread
        text = text.replace(secret, "***")
    return text.replace(_HOME, "~")
