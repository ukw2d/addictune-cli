"""Track voting: fetch current vote state and cast up/down votes.

The @work-decorated entry points (_fetch_vote_state, _do_vote) live on
AddictuneApp because only Widget/App subclasses can host Textual workers.
The app's wrappers delegate the bodies here.
"""

from typing import TYPE_CHECKING

from ..widgets.playback_bar import PlaybackBar

if TYPE_CHECKING:
    from ..app import AddictuneApp


class VoteService:
    def __init__(self, app: "AddictuneApp") -> None:
        self.app = app

    async def fetch_vote_state(self, track_id: int) -> None:
        bar = self.app.query_one(PlaybackBar)
        try:
            if not await self.app.ensure_authenticated_session(self.app.network):
                return
            track = await self.app.client.network(self.app.network).tracks.get_liked_track(
                self.app.user_id, track_id
            )
            state = _vote_of(track)
        except Exception:
            return
        if bar.track_id == track_id:
            bar.vote_state = state

    async def cast(self, direction: str) -> None:
        bar = self.app.query_one(PlaybackBar)
        track_id = bar.track_id
        if track_id is None:
            return
        try:
            if not await self.app.ensure_authenticated_session(self.app.network):
                return
            bar.vote_state = await self._cast_vote(track_id, direction, bar.vote_state)
        except Exception as exc:
            self.app.notify(f"Vote failed: {exc}", severity="error")

    async def _cast_vote(
        self, track_id: int, direction: str, current: str | None
    ) -> str | None:
        """Vote on a track, toggling off when *direction* matches the current vote."""
        if direction not in ("up", "down"):
            raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")
        tracks = self.app.client.network(self.app.network).tracks
        if direction == current:
            await tracks.vote(track_id, "delete")
            return None
        await tracks.vote(track_id, direction)
        return direction


def _vote_of(track) -> str | None:
    if track is None:
        return None
    return "up" if track.up else ("down" if track.down else None)
