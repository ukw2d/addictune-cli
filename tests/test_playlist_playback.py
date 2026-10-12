import asyncio
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from addictune_sdk.models.common import ImageSet
from addictune_sdk.models.mixshow import MixShow, ShowEpisode
from addictune_sdk.models.playlist import Playlist
from addictune_sdk.models.track import LikedTrack
from textual.app import App, ComposeResult
from textual.widgets import Static, Tab, Tabs

from addictune_cli.src.audio.state import State
from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.presentation import (
    PLAYLIST_NO_NEW_TRACKS,
    PLAYLIST_SKIP_UNAVAILABLE,
)
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.channel_list import ChannelList
from addictune_cli.src.tui.widgets.media_info import MediaInfoPanel
from addictune_cli.src.tui.widgets.mixshow_list import MixshowItem, MixshowList
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar
from addictune_cli.src.tui.widgets.playlist_list import PlaylistItem, PlaylistList
from addictune_cli.src.tui.widgets.track_list import TrackItem, TrackList

from support import install_services, temp_settings


def _at_last(queue):
    while queue.has_more:
        queue = queue.next()
    return queue


def _t(track_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=track_id, track_id=None)


class _Playlists:
    def __init__(self) -> None:
        self.windows = [
            [_t(1), _t(2), _t(3), _t(4), _t(5)],
            [_t(6), _t(7), _t(8), _t(9), _t(10)],
            [_t(11), _t(12), _t(13), _t(14), _t(15)],
        ]
        self.calls: list[int] = []

    async def get_content(self, playlist_id: int):
        self.calls.append(playlist_id)
        index = min(len(self.calls) - 1, len(self.windows) - 1)
        return SimpleNamespace(tracks=self.windows[index])


class _Tracks:
    def __init__(self) -> None:
        self.requested: list[int] = []
        self.skipped: list[tuple[int, dict]] = []

    async def skip_track(self, track_id: int, **kwargs) -> None:
        self.skipped.append((track_id, kwargs))

    async def get_by_id(self, track_id: int):
        self.requested.append(track_id)
        return SimpleNamespace(
            url=f"https://example.test/listen_key/track-{track_id}.mp3",
            display_artist="Artist",
            title=f"Track {track_id}",
            images=ImageSet(square=f"https://example.test/track-{track_id}.png"),
        )


class _Mixshows:
    def __init__(self) -> None:
        self.episodes: list[ShowEpisode] = []
        self.requested: list[int] = []

    async def iter_episodes(self, show_id: int):
        self.requested.append(show_id)
        for episode in self.episodes:
            yield episode


class _Network:
    def __init__(self) -> None:
        self.mixshows = _Mixshows()
        self.playlists = _Playlists()
        self.tracks = _Tracks()


class _Client:
    def __init__(self) -> None:
        self.listen_key = "abc"
        self.di = _Network()

    def network(self, _network: str):
        return self.di

    def with_listen_key(self, url: str) -> str:
        return url.replace("listen_key", f"listen_key={self.listen_key}")


class _App(App):
    def __init__(self) -> None:
        super().__init__()
        self.client = _Client()
        self.network = "di"
        self.user_id = None
        self.content_type = ContentType.LIVE
        self.playback_active = False
        self.track_queue = None
        self.playing_episode_id = None
        self._playing_channel_id = None
        self._statuses_by_channel = {}
        self._statuses_by_show = {}
        self._followed_controllers = {}
        self.played: list[tuple[str, str]] = []
        self.notifications: list[str] = []
        # Services used by the copied AddictuneApp methods below.
        from addictune_cli.src.tui.services.media_info import MediaInfoService
        from addictune_cli.src.tui.services.playback import PlaybackService

        self._media_info = MediaInfoService(self)
        self._playback_service = PlaybackService(self)
        install_services(self)

    def compose(self) -> ComposeResult:
        yield Tabs(
            Tab("Channels", id="channels"),
            Tab("Mixshows", id="mixshows"),
            Tab("Playlists", id="playlists"),
            Tab("Tracks", id="tracks"),
        )
        yield Static("", id="filter-bar")
        yield ChannelList(id="channel-list")
        yield MixshowList(id="mixshows-list")
        yield PlaylistList(id="playlists-list")
        yield TrackList(id="tracks-list")
        yield MediaInfoPanel()
        yield PlaybackBar(temp_settings(), id="playback-bar")

    def notify(self, message: str, **_kwargs) -> None:
        self.notifications.append(message)

    async def on_mount(self) -> None:
        bar = self.query_one(PlaybackBar)

        def play(url: str, *, title: str = "") -> None:
            self.played.append((url, title))

        bar.play = play
        bar.state = State.PLAYING

    play_playlist = AddictuneApp.play_playlist
    on_playlist_list_playlist_selected = AddictuneApp.on_playlist_list_playlist_selected
    action_toggle_playback = AddictuneApp.action_toggle_playback

    play_latest_mixshow_episode = AddictuneApp.play_latest_mixshow_episode

    def play_track(self, track, network):
        self._playback_service.play_track(track, network)

    play_track_queue_item = AddictuneApp.play_track_queue_item

    def _playing_id_for(self, kind):
        return self._playback_service._playing_id_for(kind)

    record_playlist_event = AddictuneApp.record_playlist_event
    load_next_playlist_window = AddictuneApp.load_next_playlist_window

    on_track_list_page_loaded = AddictuneApp.on_track_list_page_loaded
    action_previous_track = AddictuneApp.action_previous_track
    action_next_track = AddictuneApp.action_next_track

    _list_item = AddictuneApp._list_item

    def _media_info_from_item(self, item):
        return self._media_info.media_info_from_item(item)


def _liked_track(track_id: int) -> LikedTrack:
    return LikedTrack.model_validate(
        {
            "id": track_id + 1000,
            "track_id": track_id,
            "channel_id": 1,
            "network_id": 1,
            "position": 1,
            "created_at": "2026-07-17T11:00:00Z",
            "updated_at": "2026-07-17T11:00:00Z",
            "up": True,
            "down": False,
            "display_artist": "Artist",
            "title": f"Track {track_id}",
        }
    )


async def _iter_tracks(*tracks):
    for track in tracks:
        yield track


class PlaylistPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_selecting_playlist_starts_first_track(self) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=10)

        async with app.run_test() as pilot:
            playlists = app.query_one(PlaylistList)
            await playlists.append(PlaylistItem(playlist))

            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99])
            self.assertEqual(app.client.di.tracks.requested, [1])
            self.assertEqual(app.content_type, ContentType.PLAYLIST)
            self.assertEqual(
                app.played,
                [
                    (
                        "https://example.test/listen_key=abc/track-1.mp3",
                        "Artist — Track 1",
                    )
                ],
            )
            self.assertEqual(
                app.query_one(PlaybackBar).track_image_url,
                "https://example.test/track-1.png?size=200",
            )
            self.assertTrue(playlists.children[0].has_class("playing"))

    async def test_reselecting_active_playlist_does_not_fetch_new_window(self) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=10)

        async with app.run_test() as pilot:
            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()

            app.play_playlist(playlist, "di")
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99])
            self.assertEqual(app.client.di.tracks.requested, [1])

    async def test_channel_round_trip_restores_playlist_session(self) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=10)

        async with app.run_test() as pilot:
            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()
            assert app.track_queue is not None
            cached = app.track_queue.next().next().next().with_skip_used(True)
            app.track_queue = cached

            app._playback_service._set_source(channel_id=7)
            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99])
            self.assertEqual(app.track_queue, cached)
            self.assertEqual(app.client.di.tracks.requested, [1, 4])

    async def test_switching_playlists_restores_each_session_independently(
        self,
    ) -> None:
        app = _App()
        first = Playlist(id=99, name="First", track_count=10)
        second = Playlist(id=100, name="Second", track_count=10)

        async with app.run_test() as pilot:
            app.play_playlist(first, "di")
            await pilot.pause()
            await pilot.pause()
            assert app.track_queue is not None
            first_queue = app.track_queue.next().with_skip_used(True)
            app.track_queue = first_queue

            app.play_playlist(second, "di")
            await pilot.pause()
            await pilot.pause()
            app.play_playlist(first, "di")
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99, 100])
            self.assertEqual(app.track_queue, first_queue)
            self.assertEqual(app.client.di.tracks.requested, [1, 6, 2])

    async def test_reselecting_stopped_playlist_replays_current_track(self) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=10)

        async with app.run_test() as pilot:
            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()
            app.query_one(PlaybackBar).state = State.STOPPED

            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99])
            self.assertEqual(app.client.di.tracks.requested, [1, 1])

    async def test_rapid_playlist_reselection_starts_one_request(self) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=10)

        async with app.run_test() as pilot:
            app.on_playlist_list_playlist_selected(
                PlaylistList.PlaylistSelected(playlist)
            )
            app.on_playlist_list_playlist_selected(
                PlaylistList.PlaylistSelected(playlist)
            )
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99])

    async def test_playlist_sessions_are_scoped_by_network(self) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=10)

        async with app.run_test() as pilot:
            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()
            assert app.track_queue is not None
            app._playback_service._set_source(channel_id=7)

            app.network = "rockradio"
            app.play_playlist(playlist, "rockradio")
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99, 99])
            self.assertEqual(app.track_queue.network, "rockradio")

    async def test_playlist_selected_event_starts_playlist_without_property_write(
        self,
    ) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=10)

        async with app.run_test() as pilot:
            app.on_playlist_list_playlist_selected(
                PlaylistList.PlaylistSelected(playlist)
            )
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99])
            self.assertEqual(app.client.di.tracks.requested, [1])
            self.assertEqual(app._playing_id_for("playlist"), 99)

    async def test_space_on_focused_mixshow_plays_latest_available_episode(
        self,
    ) -> None:
        app = _App()
        show = MixShow(id=5, name="Show", slug="show")
        app.client.di.mixshows.episodes = [
            ShowEpisode(
                id=7, name="Episode", show_id=5, tracks=[{"id": 11, "title": "A"}]
            )
        ]

        async with app.run_test() as pilot:
            mixshows = app.query_one(MixshowList)
            await mixshows.append(MixshowItem(show))
            mixshows.index = 0
            app.query_one(PlaybackBar).state = State.STOPPED

            app.action_toggle_playback()
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.mixshows.requested, [5])
            self.assertEqual(app.client.di.tracks.requested, [11])
            self.assertEqual(app.content_type, ContentType.MIXSHOW)
            self.assertEqual(
                app.played,
                [
                    (
                        "https://example.test/listen_key=abc/track-11.mp3",
                        "Artist — Track 11",
                    )
                ],
            )

    async def test_next_on_last_track_fetches_new_window(self) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=10)

        async with app.run_test() as pilot:
            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()
            app.played.clear()

            assert app.track_queue is not None
            app.track_queue = _at_last(app.track_queue)

            app.action_next_track()
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99, 99])
            self.assertEqual(app.client.di.tracks.requested, [1, 6])
            self.assertEqual(app.track_queue.index, 0)
            self.assertEqual(app.track_queue.items[0].id, 6)
            self.assertTrue(app.track_queue.skip_used)
            self.assertEqual(
                app.played,
                [
                    (
                        "https://example.test/listen_key=abc/track-6.mp3",
                        "Artist — Track 6",
                    )
                ],
            )

    async def test_second_manual_window_advance_is_denied_with_toast(self) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=15)

        async with app.run_test() as pilot:
            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()
            assert app.track_queue is not None
            app.track_queue = _at_last(app.track_queue)
            app.action_next_track()
            await pilot.pause()
            await pilot.pause()

            assert app.track_queue is not None
            app.track_queue = _at_last(app.track_queue)
            app.action_next_track()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99, 99])
            self.assertEqual(app.notifications, [PLAYLIST_SKIP_UNAVAILABLE])

    async def test_natural_window_completion_restores_manual_advance(self) -> None:
        app = _App()
        playlist = Playlist(id=99, name="Playlist", track_count=15)

        async with app.run_test() as pilot:
            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()
            assert app.track_queue is not None
            app.track_queue = _at_last(app.track_queue)
            app.action_next_track()
            await pilot.pause()
            await pilot.pause()

            assert app.track_queue is not None
            app.track_queue = _at_last(app.track_queue)
            app._playback_service.on_playback_bar_stopped(
                PlaybackBar.Stopped(natural=True)
            )
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99, 99, 99])
            self.assertEqual(app.client.di.tracks.requested[-1], 11)
            self.assertFalse(app.track_queue.skip_used)

    async def test_repeated_server_window_stops_safely(self) -> None:
        app = _App()
        app.client.di.playlists.windows[1] = app.client.di.playlists.windows[0]
        playlist = Playlist(id=99, name="Playlist", track_count=10)

        async with app.run_test() as pilot:
            app.play_playlist(playlist, "di")
            await pilot.pause()
            await pilot.pause()
            assert app.track_queue is not None
            app.track_queue = _at_last(app.track_queue)

            app.action_next_track()
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.playlists.calls, [99, 99])
            self.assertEqual(app.client.di.tracks.requested, [1])
            self.assertEqual(app.notifications, [PLAYLIST_NO_NEW_TRACKS])

    async def test_playlist_event_body_calls_sdk(self) -> None:
        app = _App()

        async with app.run_test():
            await app._playback_service.record_playlist_event_body(
                "di", 99, 5, skipped=True, length=12
            )
            await app._playback_service.record_playlist_event_body(
                "di", 99, 10, skipped=False, length=None
            )

            skipped_id, skip_data = app.client.di.tracks.skipped[0]
            self.assertEqual(skipped_id, 5)
            self.assertEqual(skip_data["playlist_id"], 99)
            self.assertEqual(skip_data["length"], 12)
            self.assertIsInstance(skip_data["skipped_at"], int)

    async def test_playlist_event_body_ignores_sdk_failures(self) -> None:
        app = _App()
        attempted: list[str] = []

        async def fail_skip(*_args, **_kwargs) -> None:
            attempted.append("skip")
            raise RuntimeError("skip failed")

        app.client.di.tracks.skip_track = fail_skip

        async with app.run_test():
            await app._playback_service.record_playlist_event_body(
                "di", 99, 5, skipped=True, length=12
            )
            await app._playback_service.record_playlist_event_body(
                "di", 99, 10, skipped=False, length=None
            )

        self.assertEqual(attempted, ["skip"])

    async def test_selecting_liked_track_plays_single_track(self) -> None:
        app = _App()
        track = _liked_track(42)

        async with app.run_test() as pilot:
            tracks = app.query_one(TrackList)
            await tracks.append(TrackItem(track))

            app.play_track(track, "di")
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.tracks.requested, [42])
            self.assertEqual(app.content_type, ContentType.TRACK)
            self.assertEqual(
                app.played,
                [
                    (
                        "https://example.test/listen_key=abc/track-42.mp3",
                        "Artist — Track 42",
                    )
                ],
            )
            self.assertTrue(tracks.children[0].has_class("playing"))

    async def test_liked_tracks_support_next_and_previous_loaded_rows(self) -> None:
        app = _App()
        first = _liked_track(1)
        second = _liked_track(2)

        async with app.run_test() as pilot:
            tracks = app.query_one(TrackList)
            await tracks.append(TrackItem(first))
            await tracks.append(TrackItem(second))

            app.play_track(first, "di")
            await pilot.pause()
            await pilot.pause()
            app.played.clear()

            app.action_next_track()
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.tracks.requested, [1, 2])
            self.assertEqual(app.track_queue.index, 1)
            self.assertEqual(
                app.played,
                [
                    (
                        "https://example.test/listen_key=abc/track-2.mp3",
                        "Artist — Track 2",
                    )
                ],
            )

            app.played.clear()
            app.action_previous_track()
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.client.di.tracks.requested, [1, 2, 1])
            self.assertEqual(app.track_queue.index, 0)
            self.assertEqual(
                app.played,
                [
                    (
                        "https://example.test/listen_key=abc/track-1.mp3",
                        "Artist — Track 1",
                    )
                ],
            )

    async def test_liked_track_next_loads_next_tracklist_page(self) -> None:
        app = _App()
        first = _liked_track(1)
        second = _liked_track(2)

        async with app.run_test() as pilot:
            tracks = app.query_one(TrackList)
            # `second` sits on a page the server has not delivered yet.
            gate = asyncio.Event()

            async def slow_source():
                yield first
                await gate.wait()
                yield second

            with patch("addictune_cli.src.tui.widgets.media_list._PAGE", 1):
                tracks.show("favorites", slow_source())
                await pilot.pause()
                await pilot.pause()
                self.assertEqual(len(tracks.children), 1)

                app.play_track(first, "di")
                await pilot.pause()
                await pilot.pause()
                app.played.clear()

                app.action_next_track()  # last loaded row: asks for the next page
                gate.set()
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

            self.assertEqual(len(tracks.children), 2)
            self.assertEqual(app.client.di.tracks.requested, [1, 2])
            self.assertEqual(app.track_queue.index, 1)
            self.assertEqual(
                app.played,
                [
                    (
                        "https://example.test/listen_key=abc/track-2.mp3",
                        "Artist — Track 2",
                    )
                ],
            )

    async def test_playlist_media_info_uses_playlist_metadata(self) -> None:
        app = _App()
        playlist = Playlist(
            id=99,
            name="Playlist",
            description="Description",
            images=ImageSet(square="https://example.test/square.png"),
            track_count=10,
            duration="42:00",
            follow_count=7,
            following=True,
        )

        async with app.run_test():
            info = app._media_info_from_item(PlaylistItem(playlist))

            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(info.title, "Playlist")
            self.assertEqual(info.description, "Description")
            self.assertEqual(info.image_url, "https://example.test/square.png?size=200")
            self.assertIn(("Tracks", "10"), info.metadata)
            self.assertIn(("Duration", "42:00"), info.metadata)
            self.assertIn(("Followers", "7"), info.metadata)


if __name__ == "__main__":
    unittest.main()
