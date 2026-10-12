"""`TrackQueue` is a value: every transition builds the next queue."""

import unittest
from types import SimpleNamespace

from addictune_cli.src.tui.services.queue import TrackQueue
from addictune_cli.src.tui.types import ContentType


def _track(id_: int):
    return SimpleNamespace(id=id_, track_id=None)


def _episode(id_: int, track_id: int):
    return SimpleNamespace(id=id_, tracks=[SimpleNamespace(id=track_id)])


class TrackQueueTests(unittest.TestCase):
    def test_playlist_queue_walks_forward_and_back(self) -> None:
        q = TrackQueue.playlist(1, "di", "Mix", (_track(10), _track(11), _track(12)))

        self.assertEqual(
            (q.index, q.current_track_id, q.content_type), (0, 10, ContentType.PLAYLIST)
        )
        self.assertTrue(q.has_more)
        self.assertFalse(q.has_previous)
        n = q.next()
        self.assertEqual((n.index, n.current_track_id), (1, 11))
        self.assertTrue(n.has_previous)
        self.assertEqual(n.previous().index, 0)
        self.assertEqual(n.next().next(), n.next())  # last item: next is a no-op
        self.assertEqual(q.previous(), q)  # first item: previous is a no-op
        self.assertEqual(q.items, n.items)  # values share the item tuple

    def test_mixshow_queue_starts_at_the_selected_episode(self) -> None:
        episodes = (_episode(1, 100), _episode(2, 200), _episode(3, 300))
        q = TrackQueue.mixshow(7, "di", "Show", episodes, start_id=2)

        self.assertEqual((q.index, q.current_track_id, q.current.id), (1, 200, 2))
        self.assertEqual(q.content_type, ContentType.MIXSHOW)
        self.assertEqual(
            TrackQueue.mixshow(7, "di", "Show", episodes, start_id=99).index, 0
        )

    def test_track_queue_is_a_single_or_a_page(self) -> None:
        q = TrackQueue.tracks("di", (_track(5), _track(6)), start_id=6)
        self.assertEqual((q.index, q.current_track_id, q.source_id), (1, 6, 6))
        self.assertEqual(q.content_type, ContentType.TRACK)

    def test_refill_replaces_items_and_restarts(self) -> None:
        q = TrackQueue.playlist(1, "di", "Mix", (_track(10),)).next()
        r = q.refill((_track(20), _track(21)))
        self.assertEqual((r.index, r.current_track_id, r.skip_used), (0, 20, False))
        self.assertTrue(q.with_skip_used(True).refill((_track(20),)).skip_used)
        self.assertEqual((r.source_id, r.network, r.name), (1, "di", "Mix"))

    def test_refill_with_the_same_tracks_is_detected(self) -> None:
        q = TrackQueue.playlist(1, "di", "Mix", (_track(10), _track(11)))
        self.assertTrue(q.same_tracks((_track(10), _track(11))))
        self.assertFalse(q.same_tracks((_track(11), _track(10))))

    def test_playlist_skip_budget_is_a_value_too(self) -> None:
        q = TrackQueue.playlist(1, "di", "Mix", (_track(10),))
        self.assertFalse(q.skip_used)
        used = q.with_skip_used(True)
        self.assertTrue(used.skip_used)
        self.assertFalse(
            used.with_skip_used(False).skip_used
        )  # a natural end resets it
        self.assertTrue(
            used.refill((_track(1),)).skip_used
        )  # a manual boundary crossing is remembered

    def test_repositioned_keeps_the_current_track_across_a_page_reload(self) -> None:
        q = TrackQueue.tracks("di", (_track(5), _track(6)), start_id=6)
        page = (_track(4), _track(5), _track(6), _track(7))
        r = q.repositioned(page)
        self.assertEqual((r.index, r.current_track_id, len(r.items)), (2, 6, 4))
        self.assertEqual(r.next().current_track_id, 7)

    def test_liked_tracks_expose_track_id(self) -> None:
        liked = SimpleNamespace(id=999, track_id=42)
        q = TrackQueue.tracks("di", (liked,), start_id=42)
        self.assertEqual(q.current_track_id, 42)


if __name__ == "__main__":
    unittest.main()
