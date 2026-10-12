"""Spawn this program as a worker subprocess.

A Nuitka-compiled binary cannot re-invoke itself with ``-m`` -- the
self-execution deployment guard aborts with returncode 2. So under Nuitka we
re-exec the binary plainly and select the worker entry point via the
``ADDICTUNE_SUBPROCESS_MODULE`` environment variable (dispatched in
``addictune_cli.__main__``). Running from source we keep the ``-m`` form.
"""

import sys

# Nuitka injects ``__compiled__`` into every compiled module's globals.
IS_NUITKA = "__compiled__" in globals()

ENV_KEY = "ADDICTUNE_SUBPROCESS_MODULE"

_MODULES = {"player": "addictune_cli.src.audio.worker"}


def worker_command(
    key: str, args: list[str] | None = None
) -> tuple[list[str], dict[str, str]]:
    """Return ``(argv, env_overrides)`` to spawn the *key* worker."""
    args = args or []
    if IS_NUITKA:
        return [sys.argv[0], *args], {ENV_KEY: key}
    return [sys.executable, "-m", _MODULES[key], *args], {}
