"""Logging shared by the app process and its worker subprocesses.

Playback spans two processes: the app decides *when* to (re)start audio, and
the player subprocess decodes it. Diagnosing a dropped stream needs both halves
on one timeline, so both write to the same file and every record carries its
role and pid. The player configured no logging at all before, which discarded
everything ``audio.stream`` had to say about why a stream ended.
"""

import logging
import os
from logging.handlers import WatchedFileHandler
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .paths import LOG_FILE

_FORMAT = "%(asctime)s %(levelname)-7s %(role)s[%(process)d] %(name)s: %(message)s"
_LOG_FILE_ENV = "ADDICTUNE_LOG_FILE"
_LOG_LEVEL_ENV = "ADDICTUNE_LOG_LEVEL"
# "audio" is not under the "addictune_cli" prefix, so it needs its own handler.
_ROOTS = ("addictune_cli", "audio")
# Signed stream URLs (content.audioaddict.com) carry the account's token,
# signature and the address the signature is bound to, next to the listen key.
_SECRET_PARAMS = frozenset(
    {
        "listen_key",
        "token",
        "password",
        "audio_token",
        "auth",
        "member_id",
        "ip",
        "masked_ipv6",
    }
)
# Normal runs record only what a bug report would need; --dev opts into the
# running commentary. Keeps an ordinary listening session writing nothing.
_DEFAULT_LEVEL = "WARNING"
# Checked once per app start, so players never rotate the file out from under
# each other. One previous generation is kept, bounding the cache at 2x.
_MAX_BYTES = 512 * 1024

_configured = False


def log_path() -> Path:
    return Path(os.environ.get(_LOG_FILE_ENV, LOG_FILE))


def redact_url(url: str | None) -> str:
    """Return *url* with credential query params masked, for safe logging."""
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.query:
        return url
    query = [
        (key, "***" if key.lower() in _SECRET_PARAMS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(query, safe="*")))


def setup_logging(role: str) -> Path:
    """Attach a file handler for *role* ("app" or "player"); idempotent."""
    global _configured
    path = log_path()
    if _configured:
        return path
    _configured = True

    path.parent.mkdir(parents=True, exist_ok=True)
    if role == "app":
        _roll_if_oversized(path)
    # delay=True: a healthy session that never warns creates no file at all.
    handler = WatchedFileHandler(path, delay=True)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(_tag_role(role))

    level = os.environ.get(_LOG_LEVEL_ENV, _DEFAULT_LEVEL).upper()
    for name in _ROOTS:
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, level, logging.WARNING))
        logger.addHandler(handler)
        # The player writes ICY titles on stdout; a record escaping to a root
        # StreamHandler would corrupt that protocol.
        logger.propagate = False
    return path


def _roll_if_oversized(path: Path) -> None:
    """Keep the log from growing without bound across many sessions."""
    try:
        if path.stat().st_size > _MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass


def _tag_role(role: str):
    def filter_(record: logging.LogRecord) -> bool:
        record.role = role
        return True

    return filter_
