import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from addictune_sdk import AddictuneAPIError, AddictuneAuthError

from addictune_cli.src import auth


class _FakeBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def _client(login: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(login=login)


class _StoreTestCase(unittest.IsolatedAsyncioTestCase):
    backend = None

    def setUp(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.enterContext(patch.object(auth, "SESSION_FILE", tmp / "session.json"))
        self.enterContext(patch.object(auth, "_keyring_backend", lambda: self.backend))


class FileStoreTests(_StoreTestCase):
    """Systems without a usable keyring: a 0600 file."""

    async def test_login_stores_credentials_only_after_the_server_accepts(self) -> None:
        ok = AsyncMock(return_value=SimpleNamespace(user_id=42))
        self.assertEqual(await auth.login(_client(ok), "a@b.c", "pw", "rockradio"), 42)
        ok.assert_awaited_once_with("a@b.c", "pw", network="rockradio")
        self.assertEqual(auth.load_credentials(), ("a@b.c", "pw"))
        if os.name == "posix":
            self.assertEqual(oct(auth.SESSION_FILE.stat().st_mode)[-3:], "600")

    async def test_rejected_login_stores_nothing(self) -> None:
        bad = AsyncMock(side_effect=AddictuneAuthError("no"))
        with self.assertRaises(AddictuneAuthError):
            await auth.login(_client(bad), "a@b.c", "pw", "di")
        self.assertIsNone(auth.load_credentials())

    def test_clear_removes_the_file(self) -> None:
        auth._store('{"email": "a@b.c", "password": "pw"}')
        auth.clear_credentials()
        self.assertIsNone(auth.load_credentials())

    def test_corrupt_record_behaves_like_missing(self) -> None:
        auth._store("not json")
        self.assertIsNone(auth.load_credentials())


class KeyringStoreTests(_StoreTestCase):
    def setUp(self) -> None:
        self.backend = _FakeBackend()
        super().setUp()

    def test_roundtrip_and_clear(self) -> None:
        auth._store('{"email": "a@b.c", "password": "pw"}')
        self.assertIn(("addictune-cli", "credentials"), self.backend.values)
        self.assertEqual(auth.load_credentials(), ("a@b.c", "pw"))
        auth.clear_credentials()
        self.assertIsNone(auth.load_credentials())
        self.assertFalse(auth.SESSION_FILE.exists())

    def test_storing_in_the_keyring_removes_a_stale_plaintext_file(self) -> None:
        auth.SESSION_FILE.write_text('{"email": "a@b.c", "password": "old"}')
        auth._store('{"email": "a@b.c", "password": "new"}')
        self.assertFalse(auth.SESSION_FILE.exists())

    def test_clearing_also_removes_a_stale_plaintext_file(self) -> None:
        auth.SESSION_FILE.write_text('{"email": "a@b.c", "password": "old"}')
        auth.clear_credentials()
        self.assertFalse(auth.SESSION_FILE.exists())

    def test_clearing_reports_whether_the_login_is_really_gone(self) -> None:
        auth._store('{"email": "a@b.c", "password": "pw"}')
        self.assertTrue(auth.clear_credentials())

        class _Locked(_FakeBackend):
            def delete_password(self, service, username):
                raise RuntimeError("keyring locked")

        self.backend = _Locked()
        self.assertFalse(auth.clear_credentials())

    def test_an_unremovable_plaintext_file_is_reported_not_raised(self) -> None:
        with patch.object(Path, "unlink", side_effect=PermissionError):
            self.assertFalse(auth.clear_credentials())

    def test_locked_keyring_behaves_like_missing(self) -> None:
        class _Denied(_FakeBackend):
            def get_password(self, service, username):
                raise RuntimeError("keyring locked")

        self.backend = _Denied()
        self.assertIsNone(auth.load_credentials())


class SignInTests(_StoreTestCase):
    async def test_without_stored_credentials_returns_none(self) -> None:
        login = AsyncMock()
        self.assertIsNone(await auth.sign_in(_client(login), "di"))
        login.assert_not_awaited()

    async def test_logs_in_to_the_requested_network(self) -> None:
        auth._store('{"email": "a@b.c", "password": "pw"}')
        login = AsyncMock(return_value=SimpleNamespace(user_id=7))
        self.assertEqual(await auth.sign_in(_client(login), "jazzradio"), 7)
        login.assert_awaited_once_with("a@b.c", "pw", network="jazzradio")

    async def test_rejected_credentials_are_cleared(self) -> None:
        auth._store('{"email": "a@b.c", "password": "pw"}')
        login = AsyncMock(side_effect=AddictuneAuthError("no"))
        self.assertIsNone(await auth.sign_in(_client(login), "di"))
        self.assertIsNone(auth.load_credentials())

    async def test_transient_failure_propagates_and_keeps_the_credentials(self) -> None:
        auth._store('{"email": "a@b.c", "password": "pw"}')
        for error in (AddictuneAPIError(503, "down"), OSError("offline")):
            login = AsyncMock(side_effect=error)
            with self.assertRaises(type(error)):
                await auth.sign_in(_client(login), "di")
            self.assertEqual(auth.load_credentials(), ("a@b.c", "pw"))


class AuthFailureTests(unittest.TestCase):
    def test_classifies_session_errors(self) -> None:
        self.assertTrue(auth.is_auth_failure(AddictuneAuthError("x")))
        self.assertTrue(auth.is_auth_failure(AddictuneAPIError(419, "expired")))
        self.assertFalse(auth.is_auth_failure(AddictuneAPIError(500, "boom")))
        self.assertFalse(auth.is_auth_failure(OSError("down")))


def _done(returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["security"], returncode, stdout, "")


class MacKeychainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = self.enterContext(patch.object(auth.subprocess, "run"))

    def test_set_sends_the_secret_hex_encoded_on_stdin_not_in_argv(self) -> None:
        self.run.return_value = _done()
        secret = 's3"cr\\et $x \u00fc\u2603'
        auth._MacKeychain().set_password("svc", "acct", secret)
        self.assertEqual(self.run.call_args.args[0], ["/usr/bin/security", "-i"])
        self.assertEqual(
            self.run.call_args.kwargs["input"],
            f"add-generic-password -U -s svc -a acct -X {secret.encode().hex()}\n",
        )

    def test_get_returns_the_stored_value(self) -> None:
        self.run.return_value = _done(stdout="secret\n")
        self.assertEqual(auth._MacKeychain().get_password("svc", "acct"), "secret")
        self.assertEqual(
            self.run.call_args.args[0],
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                "svc",
                "-a",
                "acct",
                "-w",
            ],
        )

    def test_missing_item_is_none_and_deleting_it_is_a_no_op(self) -> None:
        self.run.return_value = _done(returncode=44)
        keychain = auth._MacKeychain()
        self.assertIsNone(keychain.get_password("svc", "acct"))
        keychain.delete_password("svc", "acct")

    def test_every_call_is_bounded_by_a_timeout(self) -> None:
        self.run.return_value = _done(stdout="x")
        keychain = auth._MacKeychain()
        keychain.get_password("svc", "acct")
        keychain.set_password("svc", "acct", "x")
        keychain.delete_password("svc", "acct")
        self.assertEqual(self.run.call_count, 3)
        for call in self.run.call_args_list:
            self.assertEqual(call.kwargs["timeout"], auth._KEYCHAIN_TIMEOUT)

    def test_a_hung_keychain_reads_as_missing_credentials(self) -> None:
        self.run.side_effect = subprocess.TimeoutExpired("security", 10)
        with patch.object(auth, "_keyring_backend", lambda: auth._MacKeychain()):
            self.assertIsNone(auth.load_credentials())

    def test_other_failures_raise(self) -> None:
        self.run.return_value = _done(returncode=51)
        keychain = auth._MacKeychain()
        for call in (
            lambda: keychain.get_password("svc", "acct"),
            lambda: keychain.set_password("svc", "acct", "x"),
            lambda: keychain.delete_password("svc", "acct"),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                call()


@unittest.skipUnless(
    sys.platform == "darwin" and not os.environ.get("CI"),
    "touches the real login keychain; local macOS runs only",
)
class RealMacKeychainTests(unittest.TestCase):
    def test_roundtrip_update_and_delete(self) -> None:
        keychain, service = auth._MacKeychain(), f"addictune-test-{uuid.uuid4().hex}"
        self.addCleanup(keychain.delete_password, service, "credentials")
        value = json.dumps({"email": "a@b.c", "password": "p\"w ' $x `y` \u00fc\u2603"})
        keychain.set_password(service, "credentials", value)
        self.assertEqual(keychain.get_password(service, "credentials"), value)
        keychain.set_password(service, "credentials", "second")
        self.assertEqual(keychain.get_password(service, "credentials"), "second")
        keychain.delete_password(service, "credentials")
        self.assertIsNone(keychain.get_password(service, "credentials"))


class BackendSelectionTests(unittest.TestCase):
    def tearDown(self) -> None:
        auth._keyring_backend.cache_clear()

    def test_macos_uses_the_security_tool(self) -> None:
        auth._keyring_backend.cache_clear()
        with (
            patch.object(auth.sys, "platform", "darwin"),
            patch.object(auth._MacKeychain, "viable", True),
        ):
            self.assertIsInstance(auth._keyring_backend(), auth._MacKeychain)

    def test_macos_without_the_security_tool_falls_back_to_the_file(self) -> None:
        auth._keyring_backend.cache_clear()
        with (
            patch.object(auth.sys, "platform", "darwin"),
            patch.object(auth._MacKeychain, "viable", False),
        ):
            self.assertIsNone(auth._keyring_backend())

    def test_unknown_platform_falls_back_to_the_file(self) -> None:
        auth._keyring_backend.cache_clear()
        with patch.object(auth.sys, "platform", "freebsd14"):
            self.assertIsNone(auth._keyring_backend())


if __name__ == "__main__":
    unittest.main()
