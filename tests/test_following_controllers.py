"""`ListFilter` is a value; the controllers only decide how a change is applied."""

import unittest
from types import SimpleNamespace

from addictune_cli.src.tui.services.following import (
    ChannelFollowedController,
    MixshowFollowedController,
    PlaylistFollowedController,
)
from addictune_cli.src.tui.types import MediaStatus
from addictune_cli.src.tui.widgets.mixshow_list import MixshowItem


class ListFilterTests(unittest.TestCase):
    def test_option_groups_reflect_the_current_choice(self) -> None:
        f = ChannelFollowedController.initial
        groups = {g.id: g for g in f.option_groups()}
        self.assertEqual(
            [c.id for c in groups["filter"].choices if c.selected], ["all"]
        )
        self.assertEqual(
            [c.id for c in groups["sort"].choices if c.selected], ["default"]
        )
        self.assertTrue(groups["status"].multiple)
        self.assertEqual(f.label(), "")

        g = f.with_option("filter", "followed", None).with_option(
            "status", "live_now", True
        )
        self.assertEqual(g.label(), "Filter: Favorites + Live now")
        self.assertEqual(g.status, {MediaStatus.LIVE_NOW})
        self.assertIs(
            g.with_option("status", "live_now", None).status == frozenset(), True
        )

    def test_same_choice_gives_an_equal_value(self) -> None:
        f = PlaylistFollowedController.initial
        self.assertEqual(f.with_option("sort", "popular", None), f)
        self.assertEqual(f.with_search(""), f)
        self.assertEqual(
            PlaylistFollowedController.initial.option_groups()[0].choices[1].label,
            "Followed",
        )


class LiveShowIdTests(unittest.TestCase):
    """Only mixshow rows map to an airing show (used to sync the bar's heart)."""

    def test_mixshow_controller_returns_the_shows_id(self) -> None:
        item = MixshowItem(SimpleNamespace(id=20, name="Show", following=False))
        self.assertEqual(MixshowFollowedController(None).live_show_id(item), 20)

    def test_other_controllers_and_foreign_items_give_none(self) -> None:
        item = SimpleNamespace(show=SimpleNamespace(id=20))
        self.assertIsNone(MixshowFollowedController(None).live_show_id(item))
        self.assertIsNone(ChannelFollowedController(None).live_show_id(item))
        self.assertIsNone(PlaylistFollowedController(None).live_show_id(item))


class ItemNameTests(unittest.TestCase):
    def test_name_is_the_rows_label_and_foreign_items_give_empty(self) -> None:
        item = MixshowItem(SimpleNamespace(id=20, name="Show", following=False))
        self.assertEqual(MixshowFollowedController(None).item_name(item), "Show")
        self.assertEqual(ChannelFollowedController(None).item_name(item), "")


if __name__ == "__main__":
    unittest.main()
