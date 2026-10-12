"""User preferences: one instance loaded at startup, saved debounced.

``Settings.set(name=value, ...)`` validates through pydantic, applies in place
and schedules one write; a burst of volume ticks writes the file once.
"""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from addictune_sdk import BUILTIN_NETWORKS
from pydantic import BaseModel, Field, PrivateAttr

from .paths import SETTINGS_FILE

_log = logging.getLogger("addictune_cli.settings")
_DEBOUNCE = 0.5

STATION_NAMES = {network.slug: network.name for network in BUILTIN_NETWORKS}


class Settings(BaseModel):
    volume: float = Field(default=0.3, ge=0.0, le=2.0)
    # Devices are stored by name: PortAudio renumbers indices on every hotplug.
    audio_device_name: str | None = None
    audio_sample_rate: int | None = None
    audio_latency: Literal["high", "low"] = "high"
    default_tab: Literal["channels", "mixshows", "playlists"] = "channels"
    station_selected: bool = False
    station_slug: str = next(iter(STATION_NAMES))

    _path: Path = PrivateAttr(default=SETTINGS_FILE)
    _debounce: float = PrivateAttr(default=_DEBOUNCE)
    _pending: asyncio.TimerHandle | None = PrivateAttr(default=None)

    @classmethod
    def load(
        cls, path: Path = SETTINGS_FILE, *, debounce: float = _DEBOUNCE
    ) -> "Settings":
        """Read *path*; unknown keys are ignored, a bad file gives defaults."""
        settings = cls()
        try:
            settings = cls.model_validate_json(path.read_text())
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            _log.warning("settings unreadable, using defaults: %r", exc)
        settings._path = path
        settings._debounce = debounce
        return settings

    def set(self, **values: object) -> None:
        """Apply validated changes and schedule a save; a no-op change writes nothing.

        The whole batch is validated before anything is applied, so a bad value
        leaves every field untouched.
        """
        if unknown := values.keys() - type(self).model_fields.keys():
            raise ValueError(f"unknown settings: {sorted(unknown)}")
        validated = type(self).model_validate({**self.model_dump(), **values})
        changed = {
            name: getattr(validated, name)
            for name in values
            if getattr(validated, name) != getattr(self, name)
        }
        for name, value in changed.items():
            setattr(self, name, value)
        if changed:
            self._schedule_save()

    def flush(self) -> None:
        """Write now if a save is pending (call on exit)."""
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
            self._write()

    def _schedule_save(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._write()
            return
        if self._pending is not None:
            self._pending.cancel()
        self._pending = loop.call_later(self._debounce, self._on_timer)

    def _on_timer(self) -> None:
        self._pending = None
        self._write()

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(self.model_dump_json(indent=2))
