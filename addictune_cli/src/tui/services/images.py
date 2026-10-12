import asyncio
import hashlib
import io
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ...paths import IMAGE_CACHE_DIR
from ..lru_cache import LRUCache

if TYPE_CHECKING:
    from addictune_sdk import Client

ImageCacheScope = Literal["media", "track"]

_log = logging.getLogger("addictune_cli.images")

# Per-scope disk-TTL / in-memory-LRU-limit table.
#
# Track artwork (per-track cover art matched via ICY/channel-routine) rotates
# faster and is requested far more often per session than show/media artwork,
# so it gets a *larger* in-memory LRU (more distinct tracks stay warm) but a
# *shorter* disk TTL (album art cycles in and out of rotation quickly, so
# long-lived disk entries are more likely to go stale/unused). Media/channel
# artwork is the opposite: fewer distinct images, requested less often, but
# each one stays valid for much longer.
_MEDIA_DISK_TTL = 3 * 24 * 3600  # 3 days
_TRACK_DISK_TTL = 3 * 3600  # 3 hours
_DISK_TTLS: dict[ImageCacheScope, int] = {
    "media": _MEDIA_DISK_TTL,
    "track": _TRACK_DISK_TTL,
}
_PIXEL_LIMITS: dict[ImageCacheScope, int] = {
    "media": 256,
    "track": 512,
}
_pixels: dict[ImageCacheScope, LRUCache[tuple[str, int, int], Any]] = {
    "media": LRUCache(_PIXEL_LIMITS["media"]),
    "track": LRUCache(_PIXEL_LIMITS["track"]),
}
_image_executor: Any = None

# A full directory scan+stat on every single fetch_pixels cache-miss is
# wasted I/O once the disk cache is warm; only actually prune once per
# interval per scope.
_PRUNE_INTERVAL_SECONDS = 300
_last_prune: dict[ImageCacheScope, float] = {"media": 0.0, "track": 0.0}


def _cache_dir(scope: ImageCacheScope) -> Path:
    return IMAGE_CACHE_DIR / scope


def _cache_path(url: str, scope: ImageCacheScope) -> Path:
    return _cache_dir(scope) / hashlib.sha256(url.encode()).hexdigest()


def _cache_get(url: str, scope: ImageCacheScope) -> bytes | None:
    path = _cache_path(url, scope)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > _DISK_TTLS[scope]:
        path.unlink(missing_ok=True)
        return None
    return path.read_bytes()


def _cache_set(url: str, data: bytes, scope: ImageCacheScope) -> None:
    _cache_dir(scope).mkdir(parents=True, exist_ok=True)
    _cache_path(url, scope).write_bytes(data)


def _cache_prune(scope: ImageCacheScope) -> None:
    directory = _cache_dir(scope)
    if not directory.exists():
        return
    now = time.time()
    ttl = _DISK_TTLS[scope]
    for path in directory.iterdir():
        try:
            if path.is_file() and now - path.stat().st_mtime > ttl:
                path.unlink(missing_ok=True)
        except OSError:
            continue


def _maybe_prune(scope: ImageCacheScope) -> None:
    """Throttled wrapper around `_cache_prune` (see `_PRUNE_INTERVAL_SECONDS`)."""
    now = time.time()
    if now - _last_prune[scope] < _PRUNE_INTERVAL_SECONDS:
        return
    _last_prune[scope] = now
    _cache_prune(scope)


def _pixels_get(cache_key: tuple[str, int, int], scope: ImageCacheScope) -> Any:
    return _pixels[scope].get(cache_key)


def _pixels_set(cache_key: tuple[str, int, int], value: Any, scope: ImageCacheScope) -> None:
    _pixels[scope].put(cache_key, value)


def _executor() -> Any:
    global _image_executor
    if _image_executor is None:
        import concurrent.futures

        # Decode images on one thread, lowering its priority where supported.
        _image_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            initializer=(lambda: os.nice(10)) if hasattr(os, "nice") else None,
        )
    return _image_executor


def _decode(raw: bytes, w: int, h: int) -> Any:
    try:
        from PIL import Image, ImageOps
        from rich_pixels import Pixels

        with Image.open(io.BytesIO(raw)) as img:
            fitted = ImageOps.fit(img.convert("RGB"), (w, h))
            return Pixels.from_image(fitted)
    except Exception:
        _log.warning(
            "image decode failed (%d bytes, target %dx%d)", len(raw), w, h, exc_info=True
        )
        return None


async def fetch_pixels(
    url: str,
    w: int,
    h: int,
    client: "Client",
    *,
    scope: ImageCacheScope = "media",
) -> Any:
    cache_key = (url, w, h)
    if (p := _pixels_get(cache_key, scope)) is not None:
        return p

    _maybe_prune(scope)
    raw = _cache_get(url, scope)
    if raw is None:
        try:
            raw = await client.assets.get_bytes(url)
            _cache_set(url, raw, scope)
        except Exception:
            _log.warning("image fetch failed url=%r scope=%r", url, scope, exc_info=True)
            return None

    p = await asyncio.get_running_loop().run_in_executor(
        _executor(), _decode, raw, w, h
    )
    if p is not None:
        _pixels_set(cache_key, p, scope)
    return p
