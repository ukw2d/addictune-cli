from collections.abc import Iterable
from datetime import UTC, datetime
import re

# ICY feeds, channel routines and show tracklists all spell the same track
# differently — "Artist — Track", "Artist - Track", "Artist-Track", and in
# whatever casing the station happens to use. Matching is only meaningful
# against a single canonical form.
_DASHES = str.maketrans({"—": "-", "–": "-", "‒": "-", "―": "-"})
_AROUND_DASH = re.compile(r"\s*-\s*")


def next_event_delay(
    events: Iterable[datetime],
    *,
    max_delay: float = 60.0,
    min_delay: float = 10.0,
) -> float:
    """Return seconds until the nearest future event, clamped to [min_delay, max_delay].

    Events in the past are ignored. If no future events exist, returns max_delay.
    All datetime objects must be timezone-aware.
    """
    now = datetime.now(UTC)
    future = [e for e in events if e > now]
    if not future:
        return max_delay
    secs = (min(future) - now).total_seconds()
    return max(min(secs, max_delay), min_delay)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_artist_title(artist: str | None, title: str | None) -> str:
    artist_text = (artist or "").strip()
    title_text = (title or "").strip()
    if artist_text and title_text:
        return f"{artist_text} — {title_text}"
    return artist_text or title_text


def normalize_title(value: str) -> str:
    """Return the comparison key for a broadcast/scheduled track title.

    Case, surrounding whitespace and dash style are all discarded, so the
    routine matcher and the live-episode matcher can never disagree about
    whether two spellings name the same track.
    """
    collapsed = " ".join(value.translate(_DASHES).casefold().split())
    return _AROUND_DASH.sub("-", collapsed)


def mark_playing(scope, item, *, suspended: bool = False) -> None:
    scope.query(".playing").remove_class("playing")
    scope.query(".suspended").remove_class("suspended")
    if item is not None:
        item.add_class("suspended" if suspended else "playing")


def replace_modifier_class(widget, class_names, active_class: str | None) -> None:
    widget.remove_class(*class_names)
    if active_class is not None:
        widget.add_class(active_class)
