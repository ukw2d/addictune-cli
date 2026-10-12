"""`Settings` is loaded once and shared; writes are debounced and never happen
for a no-op change."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from addictune_cli.src.settings import Settings


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "nested" / "settings.json"

    async def test_many_sets_write_once_after_the_debounce(self) -> None:
        settings = Settings.load(self.path, debounce=0.05)

        for volume in (0.1, 0.2, 0.3, 0.4):
            settings.set(volume=volume)
        self.assertFalse(self.path.exists())  # nothing written yet

        await asyncio.sleep(0.15)

        self.assertEqual(json.loads(self.path.read_text())["volume"], 0.4)
        mtime = self.path.stat().st_mtime_ns
        await asyncio.sleep(0.15)
        self.assertEqual(self.path.stat().st_mtime_ns, mtime)  # one write only

    async def test_setting_the_same_value_does_not_write(self) -> None:
        settings = Settings.load(self.path, debounce=0.01)
        settings.set(volume=settings.volume)
        await asyncio.sleep(0.05)
        self.assertFalse(self.path.exists())

    async def test_flush_writes_pending_changes_immediately(self) -> None:
        settings = Settings.load(self.path, debounce=60)
        settings.set(station_slug="jazzradio", station_selected=True)
        settings.flush()
        self.assertEqual(json.loads(self.path.read_text())["station_slug"], "jazzradio")

    def test_without_a_loop_set_writes_immediately(self) -> None:
        settings = Settings.load(self.path)
        settings.set(default_tab="mixshows")
        self.assertEqual(Settings.load(self.path).default_tab, "mixshows")

    def test_an_invalid_batch_applies_nothing(self) -> None:
        settings = Settings.load(self.path)
        with self.assertRaises(ValidationError):
            settings.set(station_selected=True, volume=5.0)
        self.assertEqual((settings.volume, settings.station_selected), (0.3, False))
        with self.assertRaises(ValueError):
            settings.set(volum=0.5)  # unknown name

    def test_stale_keys_and_corrupt_files_load_as_defaults(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps({"audio_dtype": "int16", "audio_device": 3, "volume": 0.6})
        )
        loaded = Settings.load(self.path)
        self.assertEqual(loaded.volume, 0.6)
        self.assertFalse(hasattr(loaded, "audio_dtype"))

        self.path.write_text("{not json")
        self.assertEqual(Settings.load(self.path).volume, 0.3)
        self.path.chmod(0)
        try:
            self.assertEqual(Settings.load(self.path).volume, 0.3)
        finally:
            self.path.chmod(0o600)


if __name__ == "__main__":
    unittest.main()
