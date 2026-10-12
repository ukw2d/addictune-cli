from datetime import UTC, datetime

from addictune_sdk.models.track import ChannelTracklist

from .lru_cache import LRUCache
from .utils import parse_iso_datetime

_MAX_SIZE = 10

_Key = tuple[str, int]  # (network, channel_id)


class RoutineCache:
    """LRU cache for channel routine responses.

    Keyed by (network, channel_id). Entries are valid while their
    routine_id matches and expires_on has not passed.
    """

    def __init__(self, max_size: int = _MAX_SIZE) -> None:
        self._store: LRUCache[_Key, ChannelTracklist] = LRUCache(max_size)

    def get(self, network: str, channel_id: int) -> ChannelTracklist | None:
        """Return the cached routine if it is still valid, else None."""
        key: _Key = (network, channel_id)
        tracklist = self._store.get(key)
        if tracklist is None:
            return None
        if not self._is_valid(tracklist):
            self._store.discard(key)
            return None
        return tracklist

    def put(self, network: str, channel_id: int, tracklist: ChannelTracklist) -> None:
        """Store a routine, evicting the LRU entry if at capacity."""
        self._store.put((network, channel_id), tracklist)

    @staticmethod
    def _is_valid(tracklist: ChannelTracklist) -> bool:
        if tracklist.expires_on is None:
            return False
        expiry = parse_iso_datetime(tracklist.expires_on)
        return expiry is not None and expiry > datetime.now(UTC)
