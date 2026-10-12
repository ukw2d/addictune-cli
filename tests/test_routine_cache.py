from datetime import UTC, datetime, timedelta

from addictune_sdk.models.track import ChannelTracklist

from addictune_cli.src.tui.routine_cache import RoutineCache


def _make_tracklist(
    routine_id: int = 1,
    channel_id: int = 278,
    expires_delta: timedelta = timedelta(minutes=10),
) -> ChannelTracklist:
    expires_on = (datetime.now(UTC) + expires_delta).isoformat()
    return ChannelTracklist(
        routine_id=routine_id,
        channel_id=channel_id,
        expires_on=expires_on,
        tracks=[],
    )


def _expired_tracklist(routine_id: int = 1, channel_id: int = 278) -> ChannelTracklist:
    return _make_tracklist(
        routine_id=routine_id,
        channel_id=channel_id,
        expires_delta=timedelta(seconds=-1),
    )


class TestRoutineCacheGet:
    def test_miss_on_empty_cache(self):
        cache = RoutineCache()
        assert cache.get("di", 278) is None

    def test_hit_within_ttl(self):
        cache = RoutineCache()
        tl = _make_tracklist()
        cache.put("di", 278, tl)
        result = cache.get("di", 278)
        assert result is not None
        assert result is tl

    def test_miss_after_expiry(self):
        cache = RoutineCache()
        cache.put("di", 278, _expired_tracklist())
        assert cache.get("di", 278) is None

    def test_expired_entry_removed_on_get(self):
        cache = RoutineCache()
        cache.put("di", 278, _expired_tracklist())
        cache.get("di", 278)
        # Internal store should be cleared
        assert len(cache._store) == 0

    def test_miss_for_different_network(self):
        cache = RoutineCache()
        cache.put("di", 278, _make_tracklist())
        assert cache.get("rockradio", 278) is None

    def test_miss_for_different_channel(self):
        cache = RoutineCache()
        cache.put("di", 278, _make_tracklist())
        assert cache.get("di", 999) is None


class TestRoutineCachePut:
    def test_put_stores_the_tracklist(self):
        cache = RoutineCache()
        tracklist = _make_tracklist()
        cache.put("di", 278, tracklist)
        assert cache.get("di", 278) is tracklist

    def test_put_overwrites_existing(self):
        cache = RoutineCache()
        tl1 = _make_tracklist(routine_id=1)
        tl2 = _make_tracklist(routine_id=2)
        cache.put("di", 278, tl1)
        cache.put("di", 278, tl2)
        result = cache.get("di", 278)
        assert result is not None
        assert result.routine_id == 2

    def test_lru_eviction_at_capacity(self):
        cache = RoutineCache(max_size=3)
        for ch_id in (1, 2, 3):
            cache.put("di", ch_id, _make_tracklist(channel_id=ch_id))
        # Access channel 1 to make it recently used
        cache.get("di", 1)
        # Add a fourth entry — channel 2 (LRU) should be evicted
        cache.put("di", 4, _make_tracklist(channel_id=4))
        assert cache.get("di", 2) is None
        assert cache.get("di", 1) is not None
        assert cache.get("di", 3) is not None
        assert cache.get("di", 4) is not None

    def test_capacity_not_exceeded(self):
        cache = RoutineCache(max_size=5)
        for ch_id in range(10):
            cache.put("di", ch_id, _make_tracklist(channel_id=ch_id))
        assert len(cache._store) <= 5
