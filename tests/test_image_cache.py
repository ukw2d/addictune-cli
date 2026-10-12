import asyncio
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from addictune_cli.src.tui.services import images


class ImageCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        images._pixels["media"].clear()
        images._pixels["track"].clear()

    def test_scoped_disk_cache_uses_different_ttls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            with patch.object(images, "IMAGE_CACHE_DIR", cache_dir):
                images._cache_set("media.png", b"media", "media")
                images._cache_set("track.png", b"track", "track")

                old = time.time() - (4 * 3600)
                media_path = images._cache_path("media.png", "media")
                track_path = images._cache_path("track.png", "track")
                os.utime(media_path, (old, old))
                os.utime(track_path, (old, old))

                self.assertEqual(images._cache_get("media.png", "media"), b"media")
                self.assertIsNone(images._cache_get("track.png", "track"))
                self.assertTrue(media_path.exists())
                self.assertFalse(track_path.exists())

    def test_scoped_disk_cache_prunes_expired_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            with patch.object(images, "IMAGE_CACHE_DIR", cache_dir):
                images._cache_set("fresh.png", b"fresh", "track")
                images._cache_set("expired.png", b"expired", "track")

                expired = images._cache_path("expired.png", "track")
                old = time.time() - (4 * 3600)
                os.utime(expired, (old, old))

                images._cache_prune("track")

                self.assertTrue(images._cache_path("fresh.png", "track").exists())
                self.assertFalse(expired.exists())

    def test_track_pixel_cache_is_bounded_lru(self) -> None:
        with patch.dict(images._pixels, {"track": images.LRUCache(2)}):
            images._pixels_set(("one", 16, 16), "one", "track")
            images._pixels_set(("two", 16, 16), "two", "track")
            self.assertEqual(images._pixels_get(("one", 16, 16), "track"), "one")
            images._pixels_set(("three", 16, 16), "three", "track")

            self.assertIn(("one", 16, 16), images._pixels["track"])
            self.assertIn(("three", 16, 16), images._pixels["track"])
            self.assertNotIn(("two", 16, 16), images._pixels["track"])

    def test_decode_center_crops_instead_of_stretching_source(self) -> None:
        from PIL import Image

        source = Image.new("RGB", (4, 2))
        source.paste((255, 0, 0), (0, 0, 1, 2))
        source.paste((0, 255, 0), (1, 0, 3, 2))
        source.paste((0, 0, 255), (3, 0, 4, 2))
        raw = io.BytesIO()
        source.save(raw, format="PNG")

        with patch("rich_pixels.Pixels.from_image", side_effect=lambda image: image):
            decoded = images._decode(raw.getvalue(), 2, 2)

        self.assertEqual(decoded.size, (2, 2))
        self.assertEqual(set(decoded.get_flattened_data()), {(0, 255, 0)})


class FetchPixelsTests(unittest.TestCase):
    def setUp(self) -> None:
        images._pixels["media"].clear()
        images._pixels["track"].clear()
        images._last_prune["media"] = 0.0
        images._last_prune["track"] = 0.0

    def test_pixel_cache_hit_skips_disk_scan_and_client(self) -> None:
        images._pixels_set(("cached.png", 8, 8), "cached-pixels", "track")
        client = Mock()
        client.assets.get_bytes = AsyncMock(
            side_effect=AssertionError("should not fetch")
        )

        with patch.object(images, "_maybe_prune") as maybe_prune:
            result = asyncio.run(
                images.fetch_pixels("cached.png", 8, 8, client, scope="track")
            )

        self.assertEqual(result, "cached-pixels")
        maybe_prune.assert_not_called()
        client.assets.get_bytes.assert_not_called()

    def test_cache_miss_fetches_decodes_and_populates_both_caches(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(images, "IMAGE_CACHE_DIR", Path(tmp)),
        ):
            client = Mock()
            client.assets.get_bytes = AsyncMock(return_value=b"raw-bytes")
            with patch.object(images, "_decode", return_value="decoded-pixels"):
                result = asyncio.run(
                    images.fetch_pixels("new.png", 8, 8, client, scope="media")
                )

            client.assets.get_bytes.assert_awaited_once_with("new.png")
            self.assertEqual(result, "decoded-pixels")
            self.assertTrue(images._cache_path("new.png", "media").exists())
            self.assertEqual(
                images._pixels_get(("new.png", 8, 8), "media"), "decoded-pixels"
            )

    def test_decode_failure_returns_none_logs_and_is_not_cached(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(images, "IMAGE_CACHE_DIR", Path(tmp)),
        ):
            client = Mock()
            client.assets.get_bytes = AsyncMock(return_value=b"not-an-image")

            with self.assertLogs("addictune_cli.images", level="WARNING") as log:
                result = asyncio.run(
                    images.fetch_pixels("bad.png", 8, 8, client, scope="media")
                )

            self.assertIsNone(result)
            self.assertIsNone(images._pixels_get(("bad.png", 8, 8), "media"))
            self.assertTrue(any("decode failed" in msg for msg in log.output))

    def test_fetch_failure_returns_none_and_logs(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(images, "IMAGE_CACHE_DIR", Path(tmp)),
        ):
            client = Mock()
            client.assets.get_bytes = AsyncMock(
                side_effect=RuntimeError("network down")
            )

            with self.assertLogs("addictune_cli.images", level="WARNING") as log:
                result = asyncio.run(
                    images.fetch_pixels("unreachable.png", 8, 8, client, scope="media")
                )

            self.assertIsNone(result)
            self.assertTrue(any("fetch failed" in msg for msg in log.output))

    def test_prune_is_throttled_across_back_to_back_cache_misses(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(images, "IMAGE_CACHE_DIR", Path(tmp)),
        ):
            client = Mock()
            client.assets.get_bytes = AsyncMock(return_value=b"raw-bytes")
            with (
                patch.object(images, "_decode", side_effect=["one", "two"]),
                patch.object(images, "_cache_prune") as prune,
            ):
                asyncio.run(
                    images.fetch_pixels("first.png", 8, 8, client, scope="track")
                )
                asyncio.run(
                    images.fetch_pixels("second.png", 8, 8, client, scope="track")
                )

            prune.assert_called_once_with("track")


def test_image_decode_works_without_os_nice(monkeypatch, tmp_path):
    from PIL import Image
    from rich_pixels import Pixels

    raw = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(raw, format="PNG")
    client = Mock()
    client.assets.get_bytes = AsyncMock(return_value=raw.getvalue())
    monkeypatch.delattr(os, "nice", raising=False)
    monkeypatch.setattr(images, "IMAGE_CACHE_DIR", tmp_path)
    monkeypatch.setattr(images, "_image_executor", None)
    monkeypatch.setitem(images._pixels, "media", images.LRUCache(2))
    executor = images._executor()
    try:
        result = asyncio.run(images.fetch_pixels("windows.png", 8, 8, client))
        assert isinstance(result, Pixels)
    finally:
        executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
