import unittest
from types import SimpleNamespace

from addictune_sdk.models.mixshow import ShowEpisode

from addictune_cli.src.tui.services.playback import (
    get_episode_playback_info,
    get_track_playback_info,
)


class _Tracks:
    def __init__(self) -> None:
        self.requested: list[int] = []
        self.url = "https://example.test/listen_key/track.mp3"

    async def get_by_id(self, track_id: int):
        self.requested.append(track_id)
        return SimpleNamespace(
            url=self.url,
            display_artist="Artist",
            title=f"Track {track_id}",
            images=None,
        )


class _Client:
    def __init__(self) -> None:
        self.tracks = _Tracks()
        self.listen_key = "abc"

    def network(self, _network: str):
        return SimpleNamespace(tracks=self.tracks)

    def with_listen_key(self, url: str) -> str:
        return url.replace("listen_key", "listen_key=abc")


class MixshowPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_episode_playback_uses_first_track_and_listen_key(self) -> None:
        client = _Client()
        episode = ShowEpisode(
            id=7,
            name="Episode",
            tracks=[{"id": 11, "title": "A"}, {"id": 12, "title": "B"}],
        )

        info = await get_episode_playback_info(client, "di", episode)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(client.tracks.requested, [11])
        self.assertEqual(info.url, "https://example.test/listen_key=abc/track.mp3")
        self.assertEqual(info.title, "Artist \u2014 Track 11")

    async def test_signed_track_url_is_left_untouched(self) -> None:
        """The API signs track URLs (audio_token/auth); an added parameter is a 403."""
        signed = "https://example.test/t.mp3?audio_token=a&exp=2026&auth=sig"
        client = _Client()
        client.tracks.url = signed

        info = await get_track_playback_info(client, "di", 5)

        self.assertEqual(info.url, signed)


if __name__ == "__main__":
    unittest.main()
