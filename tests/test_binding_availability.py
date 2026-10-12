"""check_action's enable/disable matrix for toggle-style player bindings."""

import unittest
from types import SimpleNamespace

from textual.widgets import Tabs

from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.services.queue import TrackQueue
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar


class _Tabs:
    active = "channels"


class _Bar:
    def __init__(
        self,
        *,
        live_show_id: int | None,
        live_show_followed: bool | None,
        track_id: int | None = None,
        vote_state: str | None = None,
    ) -> None:
        self.live_show_id = live_show_id
        self.live_show_followed = live_show_followed
        self.track_id = track_id
        self.vote_state = vote_state


class _App:
    def __init__(
        self,
        *,
        content_type: ContentType = ContentType.LIVE,
        user_id: int | None = 1,
        live_show_id: int | None = 42,
        live_show_followed: bool | None = False,
        track_id: int | None = None,
        vote_state: str | None = None,
    ) -> None:
        self.content_type = content_type
        self.user_id = user_id
        self._bar = _Bar(
            live_show_id=live_show_id,
            live_show_followed=live_show_followed,
            track_id=track_id,
            vote_state=vote_state,
        )
        self.screen_stack = [object()]
        self.track_queue = None
        self.playback_active = True
        self._playing_channel_id = None
        self._search = SimpleNamespace(
            local_search_has_focus=lambda: False, local_search_open=False
        )
        self.controller = None

    def query_one(self, selector, *_args):
        if selector is Tabs:
            return _Tabs()
        if selector is PlaybackBar or selector == "#playback-bar":
            return self._bar
        raise AssertionError(f"unexpected query_one({selector!r})")

    def _selected_list_item(self):
        return None

    def _active_followed_controller(self):
        return self.controller


class LiveShowFollowActionAvailabilityTests(unittest.TestCase):
    def _check(self, action: str, **app_kwargs) -> bool | None:
        return AddictuneApp.check_action(_App(**app_kwargs), action, ())

    def test_live_show_toggle_enabled_for_either_resolved_state(self) -> None:
        for followed in (False, True):
            with self.subTest(followed=followed):
                self.assertTrue(
                    self._check(
                        "toggle_live_show_follow",
                        live_show_id=42,
                        live_show_followed=followed,
                    )
                )

    def test_live_show_toggle_disabled_while_state_is_unresolved(self) -> None:
        self.assertFalse(
            self._check(
                "toggle_live_show_follow",
                live_show_id=42,
                live_show_followed=None,
            )
        )

    def test_live_show_toggle_disabled_when_no_show_is_airing(self) -> None:
        self.assertFalse(
            self._check(
                "toggle_live_show_follow",
                live_show_id=None,
                live_show_followed=None,
            )
        )

    def test_both_disabled_during_on_demand_playback(self) -> None:
        # An on-demand mixshow episode has a parent show too -- this is the
        # hard scope boundary: the action must stay disabled there regardless.
        for content_type in (
            ContentType.MIXSHOW,
            ContentType.PLAYLIST,
            ContentType.TRACK,
        ):
            with self.subTest(content_type=content_type):
                self.assertFalse(
                    self._check(
                        "toggle_live_show_follow",
                        content_type=content_type,
                        live_show_id=42,
                        live_show_followed=False,
                    )
                )

    def test_live_show_toggle_disabled_when_logged_out(self) -> None:
        self.assertFalse(
            self._check(
                "toggle_live_show_follow",
                user_id=None,
                live_show_id=42,
                live_show_followed=False,
            )
        )

    def test_vote_action_stays_enabled_to_remove_an_existing_vote(self) -> None:
        self.assertTrue(self._check("vote", track_id=7, vote_state="up"))
        self.assertFalse(self._check("vote", track_id=None, vote_state=None))


class ToggleBindingDescriptionTests(unittest.TestCase):
    def test_keys_panel_gets_one_clear_toggle_binding_per_key(self) -> None:
        expected = {
            "f": "Follow / unfollow selected item",
            "ctrl+l": "Follow / unfollow airing show",
            "l": "Like / unlike current track",
            "d": "Dislike / remove dislike",
        }
        for key, description in expected.items():
            with self.subTest(key=key):
                bindings = [
                    binding
                    for binding in AddictuneApp.BINDINGS
                    if key in binding.key.split(",")
                ]
                self.assertEqual(len(bindings), 1)
                self.assertEqual(bindings[0].description, description)
                self.assertFalse(bindings[0].show)


class PreviousTrackAvailabilityTests(unittest.TestCase):
    """D16: previous works for every queue once it has moved on, never for a channel."""

    def _check(self, queue: TrackQueue | None, **app_kwargs) -> bool | None:
        app = _App(content_type=ContentType.PLAYLIST, **app_kwargs)
        app.track_queue = queue
        return AddictuneApp.check_action(app, "previous_track", ())

    def test_available_for_every_queue_kind_past_the_first_item(self) -> None:
        items = (SimpleNamespace(id=1), SimpleNamespace(id=2))
        for queue in (
            TrackQueue.playlist(1, "di", "P", items).next(),
            TrackQueue.mixshow(1, "di", "M", items, start_id=2),
            TrackQueue.tracks("di", items, start_id=2),
        ):
            with self.subTest(kind=queue.kind):
                self.assertTrue(self._check(queue))

    def test_unavailable_at_the_first_item_and_without_a_queue(self) -> None:
        items = (SimpleNamespace(id=1), SimpleNamespace(id=2))
        self.assertFalse(self._check(TrackQueue.playlist(1, "di", "P", items)))
        self.assertFalse(self._check(None))


class LocalSearchAvailabilityTests(unittest.TestCase):
    def _check(self, controller) -> bool | None:
        app = _App()
        app.controller = controller
        return AddictuneApp.check_action(app, "focus_local_search", ())

    def test_search_needs_a_list_to_search_in(self) -> None:
        self.assertFalse(self._check(None))
        self.assertTrue(self._check(SimpleNamespace(searchable=True)))
        self.assertFalse(self._check(SimpleNamespace(searchable=False)))


if __name__ == "__main__":
    unittest.main()
