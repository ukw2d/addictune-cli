"""Which optional tabs a network has, probed with one-page requests.

Results are remembered per network for the session once a logged-in probe ran;
an anonymous probe cannot see the Tracks tab, so it is repeated after login.

Mixshows and playlists exist when their first page has an item; the Tracks tab
is the user's favourites, so it exists for any logged-in user whose network
answers the endpoint (even with zero items).
"""

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass

from addictune_sdk import Client
from addictune_sdk.exceptions import AddictuneNotFoundError

_log = logging.getLogger("addictune_cli.features")


@dataclass(frozen=True, slots=True)
class NetworkFeatures:
    mixshows: bool = True
    playlists: bool = True
    tracks: bool = True

    def available(self, tab_id: str) -> bool:
        return tab_id == "channels" or getattr(self, tab_id, False)


NONE = NetworkFeatures(False, False, False)


class FeatureCache:
    """Per-network results, kept for the app's lifetime (a network's catalog does not change mid-session)."""

    def __init__(self) -> None:
        self._known: dict[str, NetworkFeatures] = {}

    def get(self, network: str) -> NetworkFeatures | None:
        return self._known.get(network)

    def remember(self, network: str, features: NetworkFeatures) -> None:
        self._known[network] = features

    async def detect(
        self, client: Client, network: str, *, user_id: int | None
    ) -> NetworkFeatures:
        if (known := self._known.get(network)) is not None:
            return known
        api = client.network(network)
        probes = {
            "mixshows": _exists(anext(api.mixshows.iter_shows(per_page=1, end_page=1))),
            "playlists": _exists(
                anext(api.playlists.iter_playlists(per_page=1, end_page=1))
            ),
        }
        if user_id is not None:
            probes["tracks"] = _exists(
                api.tracks.get_liked_tracks(user_id, per_page=1, page=1)
            )
        results = dict(zip(probes, await asyncio.gather(*probes.values())))
        features = NetworkFeatures(**results)
        if user_id is not None:  # anonymous probes are provisional: tracks is unknown
            self.remember(network, features)
        return features


async def _exists(probe: Awaitable[object]) -> bool:
    try:
        await probe
    except (StopAsyncIteration, AddictuneNotFoundError):
        return False
    except Exception as exc:  # transient: assume the tab exists rather than hide it
        _log.debug("feature probe failed: %r", exc)
    return True
