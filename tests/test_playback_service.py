import unittest
from types import SimpleNamespace

from addictune_sdk.models.channel import Channel
from addictune_sdk.models.mixshow import MixShow
from addictune_sdk.models.playlist import Playlist
from textual.css.query import NoMatches

from addictune_cli.src.tui.presentation import PLAYLIST_SKIP_UNAVAILABLE
from addictune_cli.src.tui.services.playback import PlaybackService
from addictune_cli.src.tui.services.queue import TrackQueue
from addictune_cli.src.tui.widgets.channel_list import ChannelItem
from addictune_cli.src.tui.widgets.mixshow_list import MixshowItem
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar
from addictune_cli.src.tui.widgets.playlist_list import PlaylistItem
from addictune_cli.src.tui.widgets.track_list import TrackItem, TrackList
from addictune_cli.src.tui.types import ChannelView


def _track(track_id: int):
    return SimpleNamespace(id=track_id, track_id=None)


class _Routine:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


class _TrackList:
    def __init__(self, tracks=(), *, can_request_more: bool = False) -> None:
        self.loaded_tracks = tuple(tracks)
        self.can_request_more = can_request_more
        self.request_more_calls = 0

    def request_more(self) -> bool:
        self.request_more_calls += 1
        return self.can_request_more


class _List:
    def __init__(self, children=()) -> None:
        self.children = list(children)


class _Bar:
    def __init__(self, *, state, url, title="") -> None:
        self.state = state
        self.current_url = url
        self.now_playing = title
        self.play_calls: list[tuple[str, str]] = []

    def play(self, url: str, *, title: str = "") -> None:
        self.play_calls.append((url, title))


class _PlaybackApp:
    def __init__(self) -> None:
        self.track_queue = None
        self.playing_episode_id = None
        self._playing_channel_id = None
        self.play_track_queue_item_calls = []
        self.load_next_playlist_window_calls = []
        self.notify_calls = []
        self.playlist_event_calls = []
        self._bar = SimpleNamespace(state=None, elapsed_seconds=12)
        self.routine = _Routine()
        self._channels_service = SimpleNamespace(live=self.routine)
        self.track_list = _TrackList()
        self.lists = {
            "#channel-list": _List(),
            "#mixshows-list": _List(),
            "#playlists-list": _List(),
            "#tracks-list": self.track_list,
        }
        self._playback_service = PlaybackService(self)

    def notify(self, message, **_kwargs) -> None:
        self.notify_calls.append(message)

    def query_one(self, selector, *_args):
        if selector == "#playback-bar" or selector is PlaybackBar:
            return self._bar
        try:
            return self.lists[selector]
        except KeyError:
            raise NoMatches(f"no node matches {selector!r}") from None

    def play_track_queue_item(self, queue) -> None:
        self.play_track_queue_item_calls.append(queue)

    def load_next_playlist_window(self, queue) -> None:
        self.load_next_playlist_window_calls.append(queue)

    def record_playlist_event(self, *args, **kwargs) -> None:
        self.playlist_event_calls.append((args, kwargs))

    def _playing_id_for(self, kind: str) -> int | None:
        return self._playback_service._playing_id_for(kind)


class PlaybackServiceTests(unittest.TestCase):
    def test_next_and_previous_track_stay_inside_queue_bounds(self) -> None:
        app = _PlaybackApp()
        service = app._playback_service
        app.track_queue = TrackQueue(
            "track", 10, "di", "Q", (_track(10), _track(20), _track(30))
        )

        service.action_previous_track()
        self.assertEqual(app.track_queue.index, 0)
        self.assertEqual(app.play_track_queue_item_calls, [])

        service.action_next_track()
        self.assertEqual(app.track_queue.index, 1)
        self.assertEqual(app.play_track_queue_item_calls[-1].current.id, 20)

        service.action_next_track()
        service.action_next_track()
        self.assertEqual(app.track_queue.index, 2)
        self.assertEqual(app.play_track_queue_item_calls[-1].current.id, 30)

        service.action_previous_track()
        self.assertEqual(app.track_queue.index, 1)
        self.assertEqual(app.play_track_queue_item_calls[-1].current.id, 20)

    def test_first_manual_playlist_window_advance_is_latched(self) -> None:
        app = _PlaybackApp()
        service = app._playback_service
        queue = TrackQueue("playlist", 99, "di", "Q", (_track(10), _track(20)), 1)
        app.track_queue = queue

        service.action_next_track()

        requested = app.load_next_playlist_window_calls[0]
        self.assertTrue(requested.skip_used)
        self.assertEqual(
            app.playlist_event_calls,
            [(("di", 99, 20), {"skipped": True, "length": 12})],
        )
        self.assertIs(app.track_queue, requested)
        self.assertEqual(app.play_track_queue_item_calls, [])

    def test_rapid_manual_playlist_window_advance_is_latched(self) -> None:
        app = _PlaybackApp()
        service = app._playback_service
        app.track_queue = TrackQueue(
            "playlist", 99, "di", "Q", (_track(10), _track(20)), 1
        )

        service.action_next_track()
        service.action_next_track()

        self.assertEqual(len(app.load_next_playlist_window_calls), 1)
        self.assertTrue(app.load_next_playlist_window_calls[0].skip_used)
        self.assertEqual(len(app.playlist_event_calls), 1)
        self.assertEqual(app.notify_calls, [PLAYLIST_SKIP_UNAVAILABLE])

    def test_natural_playlist_completion_advances_and_resets_allowance(self) -> None:
        app = _PlaybackApp()
        service = app._playback_service
        queue = TrackQueue("playlist", 99, "di", "Q", (_track(10), _track(20)), 0, True)
        app.track_queue = queue

        service.on_playback_bar_stopped(PlaybackBar.Stopped(natural=True))

        self.assertEqual(app.track_queue.index, 1)
        self.assertTrue(app.track_queue.skip_used)
        self.assertEqual(
            app.playlist_event_calls[0],
            (("di", 99, 10), {"skipped": False, "length": None}),
        )
        self.assertEqual(app.play_track_queue_item_calls, [app.track_queue])

        service.on_playback_bar_stopped(PlaybackBar.Stopped(natural=True))

        requested = app.load_next_playlist_window_calls[0]
        self.assertFalse(requested.skip_used)
        self.assertEqual(
            app.playlist_event_calls[1],
            (("di", 99, 20), {"skipped": False, "length": None}),
        )

    def test_explicit_playlist_stop_does_not_advance(self) -> None:
        app = _PlaybackApp()
        service = app._playback_service
        queue = TrackQueue("playlist", 99, "di", "Q", (_track(10), _track(20)), 1, True)
        app.track_queue = queue
        service._notify_playback_changed = lambda: None

        service.on_playback_bar_stopped(PlaybackBar.Stopped())

        self.assertIs(app.track_queue, queue)
        self.assertEqual(app.load_next_playlist_window_calls, [])
        self.assertEqual(app.playlist_event_calls, [])

    def test_track_page_load_advances_pending_queue_once_new_track_exists(
        self,
    ) -> None:
        app = _PlaybackApp()
        service = app._playback_service
        current_tracks = (_track(10), _track(20))
        queue = TrackQueue("track", 10, "di", "Q", current_tracks, 1)
        app.track_queue = queue
        app.track_list = _TrackList(current_tracks, can_request_more=True)
        app.lists["#tracks-list"] = app.track_list

        service.action_next_track()

        self.assertEqual(service._pending_track_next, queue)
        self.assertEqual(app.track_list.request_more_calls, 1)
        self.assertEqual(app.play_track_queue_item_calls, [])

        app.track_list.loaded_tracks = (*current_tracks, _track(30))
        service.on_track_list_page_loaded(TrackList.PageLoaded())

        self.assertIsNone(service._pending_track_next)
        self.assertEqual(app.track_queue.index, 2)
        self.assertEqual(app.play_track_queue_item_calls[-1].current.id, 30)

    def test_playing_id_for_uses_live_channel_or_active_queue(self) -> None:
        app = _PlaybackApp()
        service = app._playback_service
        app._playing_channel_id = 7

        self.assertEqual(service._playing_id_for("channel"), 7)
        self.assertIsNone(service._playing_id_for("mixshow"))

        app.track_queue = TrackQueue(
            "mixshow",
            42,
            "di",
            "Q",
            (SimpleNamespace(id=100, tracks=[SimpleNamespace(id=500)]),),
        )
        self.assertEqual(service._playing_id_for("mixshow"), 42)
        self.assertIsNone(service._playing_id_for("playlist"))

        app.track_queue = TrackQueue(
            "track", 10, "di", "Q", (SimpleNamespace(id=123, track_id=None),)
        )
        self.assertEqual(service._playing_id_for("track"), 123)

    def test_find_playing_item_matches_current_source(self) -> None:
        app = _PlaybackApp()
        service = app._playback_service
        channel = Channel(id=1, key="trance", name="Trance")
        show = MixShow(id=42, name="Show", slug="show")
        playlist = Playlist(id=9, name="Playlist", track_count=1)
        track = _track(77)
        matching_show = MixshowItem(show)
        app.lists = {
            "#channel-list": _List([ChannelItem(ChannelView(channel))]),
            "#mixshows-list": _List([matching_show]),
            "#playlists-list": _List([PlaylistItem(playlist)]),
            "#tracks-list": _List([TrackItem(track)]),
        }
        app.track_queue = TrackQueue(
            "mixshow",
            42,
            "di",
            "Q",
            (SimpleNamespace(id=100, tracks=[SimpleNamespace(id=77)]),),
        )

        self.assertIs(service._find_playing_item(), matching_show)

    def test_start_queue_clears_live_channel_state_and_starts_queue(self) -> None:
        app = _PlaybackApp()
        service = app._playback_service
        service._notify_playback_changed = lambda: None
        app._playing_channel_id = 7
        queue = TrackQueue("track", 10, "di", "Q", (_track(10),))

        service._start_queue(queue, episode_id=99)

        self.assertIs(app.track_queue, queue)
        self.assertEqual(app.playing_episode_id, 99)
        self.assertIsNone(app._playing_channel_id)
        self.assertEqual(app.routine.stop_calls, 1)
        self.assertEqual(app.play_track_queue_item_calls, [queue])

    def test_a_channel_source_retires_the_queue_and_vice_versa(self) -> None:
        app = _PlaybackApp()
        service = PlaybackService(app)
        queue = TrackQueue("playlist", 7, "di", "Q", (_track(1),))

        service._set_source(queue=queue, episode_id=42)
        self.assertIs(app.track_queue, queue)
        self.assertIsNone(app._playing_channel_id)

        # Switching to live radio must not leave the queue behind, or the
        # highlight and the next/previous bindings keep pointing at it.
        service._set_source(channel_id=5)
        self.assertIsNone(app.track_queue)
        self.assertIsNone(app.playing_episode_id)
        self.assertEqual(app._playing_channel_id, 5)

    def test_a_channel_source_leaves_the_routine_running(self) -> None:
        app = _PlaybackApp()
        service = PlaybackService(app)

        service._set_source(channel_id=5)

        self.assertEqual(app.routine.stop_calls, 0)

    def test_a_source_cannot_be_both_a_channel_and_a_queue(self) -> None:
        app = _PlaybackApp()
        service = PlaybackService(app)
        queue = TrackQueue("playlist", 7, "di", "Q", (_track(1),))

        with self.assertRaises(AssertionError):
            service._set_source(channel_id=5, queue=queue)


if __name__ == "__main__":
    unittest.main()
