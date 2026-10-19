"""The launch check against GitHub Releases: pick the newest published version,
stay silent on every failure. Nothing here touches the network."""

import json
import logging
import unittest

import httpx
from packaging.version import Version

from addictune_cli.src.update import check  # bound before conftest patches it


def _release(tag: str, *, draft: bool = False, pre: bool = False) -> dict:
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": pre,
        "html_url": f"https://github.com/ukw2d/addictune-cli/releases/tag/{tag}",
    }


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serving(payload, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        return httpx.Response(status, content=body)

    return _client(handler)


class CheckTests(unittest.IsolatedAsyncioTestCase):
    async def _check(self, client, current="0.3.0", *, prereleases=True):
        async with client:
            return await check(client, Version(current), prereleases=prereleases)

    async def test_newer_published_release_is_returned(self):
        client = _serving([_release("v0.3.1"), _release("v0.3.0"), _release("v0.2.1")])
        found = await self._check(client)
        self.assertEqual(found.version, Version("0.3.1"))
        self.assertEqual(
            found.html_url, "https://github.com/ukw2d/addictune-cli/releases/tag/v0.3.1"
        )

    async def test_picks_the_maximum_not_the_first(self):
        client = _serving([_release("v0.3.1"), _release("v0.4.0"), _release("v0.3.2")])
        self.assertEqual((await self._check(client)).version, Version("0.4.0"))

    async def test_equal_or_older_is_none(self):
        for tags in (["v0.3.0"], ["v0.2.1", "v0.1.0"], []):
            with self.subTest(tags=tags):
                client = _serving([_release(t) for t in tags])
                self.assertIsNone(await self._check(client))

    async def test_drafts_and_unparsable_tags_are_skipped(self):
        client = _serving(
            [_release("v9.9.9", draft=True), _release("nightly"), _release("v0.3.1")]
        )
        self.assertEqual((await self._check(client)).version, Version("0.3.1"))

    async def test_prerelease_filter(self):
        payload = [_release("v0.4.0b1", pre=True), _release("v0.3.1")]
        self.assertEqual(
            (await self._check(_serving(payload))).version, Version("0.4.0b1")
        )
        self.assertEqual(
            (await self._check(_serving(payload), prereleases=False)).version,
            Version("0.3.1"),
        )

    async def test_request_shape(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=[])

        await self._check(_client(handler))
        (request,) = seen
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.url.host, "api.github.com")
        self.assertEqual(request.url.path, "/repos/ukw2d/addictune-cli/releases")
        self.assertEqual(request.url.params["per_page"], "30")
        self.assertEqual(request.headers["Accept"], "application/vnd.github+json")
        self.assertEqual(request.headers["X-GitHub-Api-Version"], "2022-11-28")
        self.assertTrue(request.headers["User-Agent"].startswith("addictune-cli/"))

    async def test_failures_are_none_with_one_debug_line(self):
        def raising(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline")

        cases = {
            "rate limited": _serving({"message": "API rate limit exceeded"}, 403),
            "server error": _serving("", 500),
            "not json": _serving("<html>"),
            "not a list": _serving({"tag_name": "v9.0.0"}),
            "network": _client(raising),
        }
        for name, client in cases.items():
            with self.subTest(name):
                with self.assertLogs("addictune_cli.update", logging.DEBUG) as logs:
                    self.assertIsNone(await self._check(client))
                self.assertEqual(len(logs.records), 1)
                self.assertEqual(logs.records[0].levelno, logging.DEBUG)

    async def test_failures_do_not_reach_sentry(self):
        import sentry_sdk

        sent: list = []
        sentry_sdk.init(
            dsn="https://k@o0.ingest.sentry.io/0",
            before_send=lambda e, h: sent.append(e),
        )
        try:
            await self._check(_serving("", 500))
            sentry_sdk.flush(timeout=1)
        finally:
            sentry_sdk.get_client().close()
            sentry_sdk.get_global_scope().set_client(None)
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
