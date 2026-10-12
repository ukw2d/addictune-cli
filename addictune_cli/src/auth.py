"""Login credentials and the auth-failure test.

The only thing persisted is the email and password: logging in again returns
the same session and listen keys, so there is no session cache to go stale.
The record lives in the OS keyring: Windows Credential Manager, Secret Service
on Linux, and the login keychain on macOS. A system without a usable keyring
falls back to a 0600 file.
"""

import functools
import json
import logging
import os
import subprocess
import sys

from addictune_sdk import AddictuneAPIError, AddictuneAuthError, AddictuneError, Client

from .paths import SESSION_FILE

_log = logging.getLogger("addictune_cli.auth")
_SERVICE = "addictune-cli"
_KEYRING_KEY = "credentials"
# The API's "session expired"; 401, 403 and 422 already arrive as AddictuneAuthError.
_SESSION_EXPIRED = 419
_SECURITY = "/usr/bin/security"
_KEYCHAIN_NOT_FOUND = 44  # errSecItemNotFound
_KEYCHAIN_TIMEOUT = (
    10  # a locked keychain waits on a dialog; bound how long it can block
)


class _MacKeychain:
    """The login keychain through Apple's signed `security` tool.

    Keychain ACLs are per calling binary, so an item written through the
    keyring library's C API is owned by that Python (or Nuitka) executable and
    every access from a new build prompts for the login password. Items that
    `security` creates are owned by `security`, which never changes, so reads
    stay silent across rebuilds. The secret travels hex-encoded on stdin, never
    in argv. `security -w` prints hex for non-ASCII data, so values must be
    ASCII; `json.dumps` output always is.
    """

    viable = os.path.exists(_SECURITY)

    def _run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [_SECURITY, *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_KEYCHAIN_TIMEOUT,
        )

    def get_password(self, service: str, username: str) -> str | None:
        result = self._run("find-generic-password", "-s", service, "-a", username, "-w")
        if result.returncode == _KEYCHAIN_NOT_FOUND:
            return None
        result.check_returncode()
        return result.stdout.rstrip("\n")

    def set_password(self, service: str, username: str, password: str) -> None:
        # service/username go in unquoted: callers pass fixed identifiers, never input.
        command = f"add-generic-password -U -s {service} -a {username} -X {password.encode().hex()}\n"
        self._run("-i", stdin=command).check_returncode()

    def delete_password(self, service: str, username: str) -> None:
        result = self._run("delete-generic-password", "-s", service, "-a", username)
        if result.returncode != _KEYCHAIN_NOT_FOUND:
            result.check_returncode()


def is_auth_failure(exc: Exception) -> bool:
    """True when *exc* signals invalid credentials or an expired session."""
    return isinstance(exc, AddictuneAuthError) or (
        isinstance(exc, AddictuneAPIError) and exc.status_code == _SESSION_EXPIRED
    )


async def login(client: Client, email: str, password: str, network: str) -> int:
    """Log in from the login form, then remember the credentials. Returns the user id.

    The write happens only after the server accepts the login, so invalid
    credentials are never stored.
    """
    auth = await client.login(email, password, network=network)
    _store(json.dumps({"email": email, "password": password}))
    return auth.user_id


async def sign_in(client: Client, network: str) -> int | None:
    """Log in to *network* with the stored credentials. Returns the user id.

    None when nothing is stored or the server rejects them (the stale record
    is cleared, so the next launch goes straight to the prompt). Any other
    failure, such as a dropped connection or a 503, propagates with the
    record untouched.
    """
    if (credentials := load_credentials()) is None:
        return None
    try:
        return (await client.login(*credentials, network=network)).user_id
    except AddictuneError as exc:
        if not is_auth_failure(exc):
            raise
        clear_credentials()
        return None


def load_credentials() -> tuple[str, str] | None:
    try:
        data = json.loads(_load() or "{}")
        return data["email"], data["password"]
    except (KeyError, TypeError, ValueError):
        return None


def clear_credentials() -> None:
    SESSION_FILE.unlink(missing_ok=True)  # also a pre-keychain build's plaintext copy
    if backend := _keyring_backend():
        try:
            backend.delete_password(_SERVICE, _KEYRING_KEY)
        except Exception as exc:  # already absent, or the keyring is locked
            _log.warning("keyring delete failed: %r", exc)


@functools.cache
def _keyring_backend():
    """A viable OS keyring backend, or None to use the 0600 file.

    The backend is imported directly rather than through keyring's entry-point
    discovery, so the choice is deterministic and survives Nuitka compilation
    (which doesn't bundle entry-point metadata).
    """
    try:
        match sys.platform:
            case "win32":
                from keyring.backends import Windows

                backend = Windows.WinVaultKeyring()
            case "linux":
                from keyring.backends import SecretService

                backend = SecretService.Keyring()
            case "darwin":
                backend = _MacKeychain()
            case _:
                return None
        if backend.viable:
            return backend
        _log.warning("keyring backend not viable; using file store")
    except Exception as exc:
        _log.warning("keyring backend unavailable (%r); using file store", exc)
    return None


def _load() -> str | None:
    if backend := _keyring_backend():
        try:
            return backend.get_password(_SERVICE, _KEYRING_KEY)
        except Exception as exc:  # a locked keyring behaves like a missing record
            _log.warning("keyring get failed: %r", exc)
            return None
    return SESSION_FILE.read_text() if SESSION_FILE.exists() else None


def _store(raw: str) -> None:
    if backend := _keyring_backend():
        try:
            backend.set_password(_SERVICE, _KEYRING_KEY, raw)
        except Exception as exc:
            _log.warning("keyring set failed: %r", exc)
        else:
            SESSION_FILE.unlink(
                missing_ok=True
            )  # a pre-keychain macOS build's plaintext copy
        return
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(raw)
    os.chmod(SESSION_FILE, 0o600)
