"""Generic bounded LRU cache.

Before this existed, RoutineCache (routine_cache.py) and the in-memory
pixel cache (services/images.py) each independently reimplemented the same
OrderedDict move-to-end-on-access, evict-oldest-over-capacity pattern.
This is the one place that pattern lives now; both call sites compose it
rather than re-deriving it.
"""

from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(Generic[K, V]):
    def __init__(self, max_size: int) -> None:
        self.max_size = max_size
        self._store: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, key: K, value: V) -> None:
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def discard(self, key: K) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def __contains__(self, key: K) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)
