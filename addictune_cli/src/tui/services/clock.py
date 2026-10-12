"""The playback clock — sole owner of elapsed/duration for the playback bar.

Elapsed time has two representations that must stay consistent: a *base*
offset plus the wall-clock instant the counter last started running. Every
way playback time can change (a fresh stream, a scheduled show, an ICY track
change, a seek, a probe result, a pause) is a named transition here, so
callers cannot invent a fourth combination by assigning the two halves
separately — which is exactly how a live show's remaining time got reset to
zero by an unrelated ICY update.

The clock is deliberately free of Textual: it reads a monotonic source and
answers questions. The widget owns reactive publication.
"""

from time import monotonic
from typing import Callable


class PlaybackClock:
    def __init__(self, now: Callable[[], float] = monotonic) -> None:
        self._now = now
        self._base = 0
        self._started_at: float | None = None
        self._duration: int | None = None

    # ── Queries ──────────────────────────────────────────────────

    @property
    def elapsed(self) -> int:
        if self._started_at is None:
            return self._base
        return self._base + int(self._now() - self._started_at)

    @property
    def duration(self) -> int | None:
        return self._duration

    @property
    def running(self) -> bool:
        return self._started_at is not None

    # ── Transitions ──────────────────────────────────────────────

    def reset(self, *, clear_duration: bool) -> None:
        """A new stream is loading: rewind to zero."""
        self._base = 0
        self._started_at = None
        if clear_duration:
            self._duration = None

    def adopt_schedule(self, position: float, duration: float, *, running: bool) -> None:
        """Follow a scheduled live show, which is already *position* seconds in."""
        self._base = int(position)
        self._started_at = self._now() if running else None
        self._duration = int(duration)

    def adopt_track(self, length: int | None, *, running: bool) -> None:
        """A new track began (per ICY): restart the counter with its length."""
        self._base = 0
        self._started_at = self._now() if running else None
        self._duration = length

    def set_duration(self, duration: int | None) -> None:
        """Attach or clear a total without disturbing the counter."""
        self._duration = duration

    def seek_to(self, target: int, *, running: bool) -> None:
        self._base = max(0, target)
        self._started_at = self._now() if running else None

    def resume(self) -> None:
        """Start counting without moving the position (idempotent)."""
        if self._started_at is None:
            self._started_at = self._now()

    def pause(self) -> None:
        """Freeze the counter, keeping the position reached so far."""
        self._base = self.elapsed
        self._started_at = None

    def clamp_seek_target(self, seconds: int) -> int:
        """Where a relative seek of *seconds* would land, inside the duration."""
        target = max(0, self.elapsed + seconds)
        if self._duration is not None:
            target = min(target, max(0, self._duration - 1))
        return target
