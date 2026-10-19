"""Is a newer release published on GitHub?

One unauthenticated request per launch; every failure is ``None`` after a
DEBUG line, never a Sentry event. Selecting and installing a build for this
platform is deliberately out of scope (docs/design/auto-update.md).
"""

import logging
from dataclasses import dataclass
from importlib.metadata import version

import httpx
from packaging.version import InvalidVersion, Version

log = logging.getLogger("addictune_cli.update")

_RELEASES = "https://api.github.com/repos/ukw2d/addictune-cli/releases"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": f"addictune-cli/{version('addictune-cli')}",
}


@dataclass(frozen=True)
class Release:
    version: Version
    html_url: str


async def check(
    client: httpx.AsyncClient, current: Version, *, prereleases: bool
) -> Release | None:
    """The newest published release above *current*, or ``None``."""
    try:
        response = await client.get(
            _RELEASES, params={"per_page": 30}, headers=_HEADERS, timeout=5
        )
        response.raise_for_status()
        releases = [
            Release(parsed, item["html_url"])
            for item in response.json()
            if not item["draft"]
            and (parsed := _parse(item["tag_name"])) is not None
            and (prereleases or not parsed.is_prerelease)
        ]
    except Exception as error:  # noqa: BLE001 - the check is best effort
        log.debug("update check failed: %s: %s", type(error).__name__, error)
        return None
    newest = max(releases, key=lambda r: r.version, default=None)
    return newest if newest and newest.version > current else None


def _parse(tag: str) -> Version | None:
    try:
        return Version(tag.removeprefix("v"))
    except InvalidVersion:
        return None
