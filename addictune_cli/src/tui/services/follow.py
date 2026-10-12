"""Follow / unfollow management.

Gates the follow action on the selected item
and login state, then runs the remote update. The @work-decorated
AddictuneApp.set_item_followed stays on the app (only Widget/App can host
workers); its body delegates to FollowService.run_followed_update.
"""

from typing import TYPE_CHECKING

from textual.worker import get_current_worker

from ..types import ContentType
from ..widgets.playback_bar import PlaybackBar

if TYPE_CHECKING:
    from ..app import AddictuneApp
    from .following import FollowedController


class FollowService:
    def __init__(self, app: "AddictuneApp") -> None:
        self.app = app
        self._live_show_follow_states: dict[tuple[str, int, int], bool] = {}

    def toggle_selected(self) -> None:
        app = self.app
        controller = app._active_followed_controller()
        item = app._selected_list_item()
        followed = controller.followed(item) if controller is not None else None
        if followed is not None:
            self.set_selected(not followed)

    def set_selected(self, followed: bool) -> None:
        app = self.app
        controller = app._active_followed_controller()
        item = app._selected_list_item()
        if controller is None or not controller.accepts(item):
            return
        if app.user_id is None:
            app.notify("Log in to manage followed items.", severity="warning")
            return
        if controller.followed(item) == followed:
            return
        app.set_item_followed(controller, item, followed, app.user_id, app.network)

    def toggle_live_show_follow(self) -> None:
        followed = self.app.query_one(PlaybackBar).live_show_followed
        if followed is not None:
            self.set_live_show_followed(not followed)

    def set_live_show_followed(self, followed: bool) -> None:
        """Follow/unfollow the AIRING show, not a selected row.

        There is no list item or controller here -- a live show need not
        appear in any currently-loaded list -- so the target is PlaybackBar's
        own airing-show fields instead of _active_followed_controller /
        _selected_list_item.
        """
        app = self.app
        bar = app.query_one(PlaybackBar)
        show_id = bar.live_show_id
        if show_id is None or app.content_type != ContentType.LIVE:
            return
        if app.user_id is None:
            app.notify("Log in to manage followed items.", severity="warning")
            return
        if bar.live_show_followed == followed:
            return
        previous = bar.live_show_followed
        self._store_live_show_follow_state(
            app.network, app.user_id, show_id, followed
        )
        bar.live_show_followed = followed
        app.set_live_show_followed(
            show_id,
            bar.live_show_name,
            followed,
            previous,
            app.user_id,
            app.network,
        )

    async def run_followed_update(
        self,
        controller: "FollowedController",
        item: object,
        followed: bool,
        user_id: int,
        network: str,
    ) -> None:
        """Body of the @work-decorated AddictuneApp.set_item_followed."""
        app = self.app
        worker = get_current_worker()
        item_name = controller.item_name(item)
        try:
            if not await app.ensure_authenticated_session(network):
                return
            await controller.update_remote(item, followed, user_id, network)
        except Exception as error:
            app.notify(
                f"Unable to update follow state for {item_name}: {error}",
                severity="error",
            )
            return
        if worker.is_cancelled or network != app.network or user_id != app.user_id:
            return
        await controller.apply_update(item, followed)
        app._media_info.sync_open_media_info()
        app.refresh_bindings()
        self._sync_live_show_follow_state(controller.live_show_id(item), followed)

    def _sync_live_show_follow_state(self, show_id: int | None, followed: bool) -> None:
        """Keep the player's airing-show indicator in step with a follow/unfollow
        made elsewhere (the Mixshows tab today) for the same show,
        without waiting on a redundant fetch of state this update already gave us.

        *show_id* is None for every controller but mixshows' (see
        FollowedController.live_show_id) -- channels/playlists updates are
        simply not this indicator's concern, so there is nothing to check.
        """
        app = self.app
        if show_id is None or app.user_id is None:
            return
        self._store_live_show_follow_state(
            app.network, app.user_id, show_id, followed
        )
        bar = app.query_one(PlaybackBar)
        if bar.live_show_id == show_id:
            bar.live_show_followed = followed

    async def fetch_live_show_follow_state(self, show_id: int) -> None:
        """Resolve whether the airing live show is followed.

        ``get_by_id()`` cannot be used here: its ETag cache may keep the
        personalized ``following`` field stale after follow/unfollow. Membership
        in ``iter_followed()`` is the same source used by the Mixshows list and
        media panel. A state changed in this session is kept locally so a quick
        channel switch cannot race the remote update and overwrite optimism.
        """
        app = self.app
        bar = app.query_one(PlaybackBar)
        network = app.network
        user_id = app.user_id
        if user_id is None:
            return

        key = self._live_show_key(network, user_id, show_id)
        if key in self._live_show_follow_states:
            self._apply_if_still_airing(
                bar, show_id, self._live_show_follow_states[key]
            )
            return

        try:
            if not await app.ensure_authenticated_session(network):
                return
            followed = False
            shows = app.client.network(network).mixshows.iter_followed(user_id)
            async for show in shows:
                if show.id == show_id:
                    followed = True
                    break
        except Exception:
            return
        if network != app.network or user_id != app.user_id:
            return
        self._store_live_show_follow_state(network, user_id, show_id, followed)
        # The airing show may have moved on while the fetch was in flight;
        # a stale answer must not overwrite whatever is current now.
        self._apply_if_still_airing(bar, show_id, followed)

    async def run_live_show_follow_update(
        self,
        show_id: int,
        name: str,
        followed: bool,
        previous: bool | None,
        user_id: int,
        network: str,
    ) -> None:
        """Persist the synchronous optimistic update, rolling it back on failure.

        Every bar write is guarded because the worker may finish after a show
        boundary. The remote call still runs for the original show: changing
        channels does not cancel the user's follow/unfollow intent.
        """
        app = self.app
        bar = app.query_one(PlaybackBar)
        self._store_live_show_follow_state(network, user_id, show_id, followed)
        self._apply_if_still_airing(bar, show_id, followed)

        try:
            if not await app.ensure_authenticated_session(network):
                self._store_live_show_follow_state(
                    network, user_id, show_id, previous
                )
                self._apply_if_still_airing(bar, show_id, previous)
                return
            api = app.client.network(network).mixshows
            if followed:
                await api.follow(user_id, show_id)
            else:
                await api.unfollow(user_id, show_id)
        except Exception as error:
            self._store_live_show_follow_state(network, user_id, show_id, previous)
            self._apply_if_still_airing(bar, show_id, previous)
            app.notify(
                f"Unable to update follow state for {name}: {error}",
                severity="error",
            )
            return
        if network == app.network and user_id == app.user_id:
            self._apply_if_still_airing(bar, show_id, followed)
            app.refresh_bindings()

    @staticmethod
    def _live_show_key(network: str, user_id: int, show_id: int) -> tuple[str, int, int]:
        return network, user_id, show_id

    def _store_live_show_follow_state(
        self,
        network: str,
        user_id: int,
        show_id: int,
        followed: bool | None,
    ) -> None:
        key = self._live_show_key(network, user_id, show_id)
        if followed is None:
            self._live_show_follow_states.pop(key, None)
        else:
            self._live_show_follow_states[key] = followed

    @staticmethod
    def _apply_if_still_airing(bar: PlaybackBar, show_id: int, value: bool | None) -> None:
        if bar.live_show_id == show_id:
            bar.live_show_followed = value
