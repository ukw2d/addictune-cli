"""Resolving and keeping in step the airing live show's follow state.

get_upcoming() does not personalize MixShow.following, while get_by_id() can
return a stale personalized field from its SDK ETag cache after follow/unfollow.
FollowService therefore checks membership in iter_followed(), the same source
used by the Mixshows list and its media panel, while retaining locally changed
state across quick channel switches.

_sync_live_show_follow_state covers the other direction: a follow/unfollow
made from the Mixshows tab (or, later, the player itself) for the show that
happens to be airing must update the indicator immediately rather than
waiting on a redundant fetch.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from addictune_cli.src.tui.services.follow import FollowService
from addictune_cli.src.tui.types import ContentType


class _Bar:
    def __init__(
        self,
        *,
        live_show_id: int | None,
        live_show_name: str = "Group Therapy",
        live_show_followed: bool | None = None,
    ) -> None:
        self.live_show_id = live_show_id
        self.live_show_name = live_show_name
        self.live_show_followed = live_show_followed


class _Mixshows:
    def __init__(
        self,
        show,
        *,
        followed_ids: set[int] | None = None,
        fail: Exception | None = None,
    ) -> None:
        self._show = show
        self._followed_ids = (
            followed_ids
            if followed_ids is not None
            else ({20} if getattr(show, "following", False) else set())
        )
        self._fail = fail
        self.calls: list[int] = []
        self.get_by_id_calls: list[int] = []
        self.follow_calls: list[tuple[int, int]] = []
        self.unfollow_calls: list[tuple[int, int]] = []

    async def get_by_id(self, show_id: int):
        self.get_by_id_calls.append(show_id)
        return self._show

    def iter_followed(self, user_id: int):
        self.calls.append(user_id)

        async def _items():
            for show_id in self._followed_ids:
                yield SimpleNamespace(id=show_id, following=True)

        return _items()

    async def follow(self, user_id: int, show_id: int) -> None:
        if self._fail:
            raise self._fail
        self.follow_calls.append((user_id, show_id))

    async def unfollow(self, user_id: int, show_id: int) -> None:
        if self._fail:
            raise self._fail
        self.unfollow_calls.append((user_id, show_id))


class _Client:
    def __init__(self, mixshows) -> None:
        self._mixshows = mixshows

    def network(self, _name: str) -> SimpleNamespace:
        return SimpleNamespace(mixshows=self._mixshows)


class _App:
    def __init__(
        self,
        bar: _Bar,
        mixshows: _Mixshows,
        *,
        authenticated: bool = True,
        content_type: ContentType = ContentType.LIVE,
        user_id: int | None = 1,
    ) -> None:
        self.bar = bar
        self.client = _Client(mixshows)
        self.network = "di"
        self.user_id = user_id
        self.content_type = content_type
        self._authenticated = authenticated
        self.ensure_authenticated_session = AsyncMock(return_value=authenticated)
        self.notify = Mock()
        self.refresh_bindings = Mock()
        self.set_live_show_followed = Mock()

    def query_one(self, *_args, **_kwargs) -> _Bar:
        return self.bar


class FetchLiveShowFollowStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_applies_follow_state_when_the_show_is_still_airing(self) -> None:
        bar = _Bar(live_show_id=20)
        mixshows = _Mixshows(SimpleNamespace(following=True))
        service = FollowService(_App(bar, mixshows))

        await service.fetch_live_show_follow_state(20)

        self.assertEqual(bar.live_show_followed, True)
        self.assertEqual(mixshows.calls, [1])
        self.assertEqual(mixshows.get_by_id_calls, [])

    async def test_applies_not_followed_when_show_is_absent_from_followed_items(
        self,
    ) -> None:
        bar = _Bar(live_show_id=20)
        mixshows = _Mixshows(SimpleNamespace(following=True), followed_ids=set())
        service = FollowService(_App(bar, mixshows))

        await service.fetch_live_show_follow_state(20)

        self.assertFalse(bar.live_show_followed)
        self.assertEqual(mixshows.calls, [1])

    async def test_ignores_a_stale_response_after_the_show_changed(self) -> None:
        bar = _Bar(live_show_id=21)  # a different show is airing by the time this lands
        mixshows = _Mixshows(SimpleNamespace(following=True))
        service = FollowService(_App(bar, mixshows))

        await service.fetch_live_show_follow_state(20)

        self.assertIsNone(bar.live_show_followed)

    async def test_no_fetch_result_applied_when_not_authenticated(self) -> None:
        bar = _Bar(live_show_id=20)
        mixshows = _Mixshows(SimpleNamespace(following=True))
        service = FollowService(_App(bar, mixshows, authenticated=False))

        await service.fetch_live_show_follow_state(20)

        self.assertIsNone(bar.live_show_followed)
        self.assertEqual(mixshows.calls, [])

    async def test_fetch_failure_leaves_no_follow_state_rather_than_raising(
        self,
    ) -> None:
        bar = _Bar(live_show_id=20)

        class _FailingMixshows:
            def iter_followed(self, user_id: int):
                async def _items():
                    raise RuntimeError("network error")
                    yield

                return _items()

        app = _App(bar, _Mixshows(SimpleNamespace(following=True)))
        app.client = _Client(_FailingMixshows())
        service = FollowService(app)

        await service.fetch_live_show_follow_state(20)

        self.assertIsNone(bar.live_show_followed)

    async def test_ctrl_l_state_survives_switching_away_and_back(self) -> None:
        for previous, followed in ((False, True), (True, False)):
            with self.subTest(followed=followed):
                stale_ids = set() if followed else {20}
                bar = _Bar(live_show_id=20, live_show_followed=previous)
                mixshows = _Mixshows(
                    SimpleNamespace(following=previous), followed_ids=stale_ids
                )
                app = _App(bar, mixshows)
                service = FollowService(app)

                service.set_live_show_followed(followed)
                bar.live_show_id = None
                bar.live_show_followed = None
                bar.live_show_id = 20
                await service.fetch_live_show_follow_state(20)

                self.assertIs(bar.live_show_followed, followed)
                self.assertEqual(mixshows.calls, [])
                self.assertEqual(mixshows.get_by_id_calls, [])


class SyncLiveShowFollowStateTests(unittest.TestCase):
    """FollowService._sync_live_show_follow_state -- applies a show_id already
    resolved by FollowedController.live_show_id (see test_following_controllers.py
    for that resolution step) against the bar.
    """

    def test_updates_the_indicator_when_the_updated_show_is_airing(self) -> None:
        bar = _Bar(live_show_id=20)
        service = FollowService(_App(bar, _Mixshows(None)))

        service._sync_live_show_follow_state(20, True)

        self.assertEqual(bar.live_show_followed, True)

    def test_leaves_the_indicator_alone_for_a_different_show(self) -> None:
        bar = _Bar(live_show_id=20)
        service = FollowService(_App(bar, _Mixshows(None)))

        service._sync_live_show_follow_state(99, True)

        self.assertIsNone(bar.live_show_followed)

    def test_no_show_id_is_a_no_op(self) -> None:
        # FollowedController.live_show_id's default answer -- channels and
        # playlists updates never reach here with anything else.
        bar = _Bar(live_show_id=20)
        service = FollowService(_App(bar, _Mixshows(None)))

        service._sync_live_show_follow_state(None, True)

        self.assertIsNone(bar.live_show_followed)


class ToggleSelectedFollowTests(unittest.TestCase):
    def test_toggle_inverts_the_selected_items_state(self) -> None:
        item = object()
        controller = SimpleNamespace(
            accepts=lambda candidate: candidate is item,
            followed=lambda candidate: True if candidate is item else None,
        )
        app = _App(_Bar(live_show_id=None), _Mixshows(None))
        app._active_followed_controller = Mock(return_value=controller)
        app._selected_list_item = Mock(return_value=item)
        app.set_item_followed = Mock()

        FollowService(app).toggle_selected()

        app.set_item_followed.assert_called_once_with(controller, item, False, 1, "di")


class SetLiveShowFollowedTests(unittest.TestCase):
    """FollowService's airing-show toggle and explicit persistence target."""

    def test_toggle_inverts_the_resolved_state(self) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=True)
        app = _App(bar, _Mixshows(None))

        FollowService(app).toggle_live_show_follow()

        app.set_live_show_followed.assert_called_once_with(
            20, "Group Therapy", False, True, 1, "di"
        )
        self.assertFalse(bar.live_show_followed)

    def test_toggle_is_a_no_op_while_state_is_unresolved(self) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=None)
        app = _App(bar, _Mixshows(None))

        FollowService(app).toggle_live_show_follow()

        app.set_live_show_followed.assert_not_called()

    def test_dispatches_when_gates_are_satisfied(self) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=False)
        app = _App(bar, _Mixshows(None))

        FollowService(app).set_live_show_followed(True)

        app.set_live_show_followed.assert_called_once_with(
            20, "Group Therapy", True, False, 1, "di"
        )
        self.assertTrue(bar.live_show_followed)

    def test_no_dispatch_when_no_show_is_airing(self) -> None:
        bar = _Bar(live_show_id=None, live_show_followed=None)
        app = _App(bar, _Mixshows(None))

        FollowService(app).set_live_show_followed(True)

        app.set_live_show_followed.assert_not_called()

    def test_no_dispatch_during_on_demand_playback(self) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=False)
        app = _App(bar, _Mixshows(None), content_type=ContentType.TRACK)

        FollowService(app).set_live_show_followed(True)

        app.set_live_show_followed.assert_not_called()

    def test_prompts_login_when_logged_out(self) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=None)
        app = _App(bar, _Mixshows(None), user_id=None)

        FollowService(app).set_live_show_followed(True)

        app.set_live_show_followed.assert_not_called()
        app.notify.assert_called_once()

    def test_no_dispatch_when_already_in_the_requested_state(self) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=True)
        app = _App(bar, _Mixshows(None))

        FollowService(app).set_live_show_followed(True)

        app.set_live_show_followed.assert_not_called()


class RunLiveShowFollowUpdateTests(unittest.IsolatedAsyncioTestCase):
    """The @work body: optimistic update, remote call, rollback on failure."""

    async def test_success_applies_optimistically_and_stays_applied(self) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=False)
        mixshows = _Mixshows(None)
        app = _App(bar, mixshows)

        await FollowService(app).run_live_show_follow_update(
            20, "Group Therapy", True, False, 1, "di"
        )

        self.assertTrue(bar.live_show_followed)
        self.assertEqual(mixshows.follow_calls, [(1, 20)])
        app.refresh_bindings.assert_called_once_with()

    async def test_unfollow_calls_the_unfollow_endpoint(self) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=True)
        mixshows = _Mixshows(None)
        app = _App(bar, mixshows)

        await FollowService(app).run_live_show_follow_update(
            20, "Group Therapy", False, True, 1, "di"
        )

        self.assertFalse(bar.live_show_followed)
        self.assertEqual(mixshows.unfollow_calls, [(1, 20)])

    async def test_failure_rolls_back_the_optimistic_update_and_notifies(self) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=False)
        mixshows = _Mixshows(None, fail=RuntimeError("network error"))
        app = _App(bar, mixshows)

        await FollowService(app).run_live_show_follow_update(
            20, "Group Therapy", True, False, 1, "di"
        )

        self.assertFalse(bar.live_show_followed)  # rolled back to the pre-update value
        app.notify.assert_called_once()
        app.refresh_bindings.assert_not_called()

    async def test_rollback_does_not_clobber_a_show_that_changed_mid_flight(
        self,
    ) -> None:
        bar = _Bar(
            live_show_id=99, live_show_followed=None
        )  # a different show now airing
        mixshows = _Mixshows(None, fail=RuntimeError("network error"))
        app = _App(bar, mixshows)

        await FollowService(app).run_live_show_follow_update(
            20, "Group Therapy", True, False, 1, "di"
        )

        # Whatever fetch_live_show_follow_state already set for show 99 must
        # survive -- not be overwritten by a rollback meant for show 20.
        self.assertIsNone(bar.live_show_followed)

    async def test_not_authenticated_rolls_back_without_calling_the_remote(
        self,
    ) -> None:
        bar = _Bar(live_show_id=20, live_show_followed=False)
        mixshows = _Mixshows(None)
        app = _App(bar, mixshows, authenticated=False)

        await FollowService(app).run_live_show_follow_update(
            20, "Group Therapy", True, False, 1, "di"
        )

        self.assertFalse(bar.live_show_followed)
        self.assertEqual(mixshows.follow_calls, [])


if __name__ == "__main__":
    unittest.main()
