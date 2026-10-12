"""Followed/not-followed marker for the airing live show -- add-d6m.3.

apply_live_show_follow_marker is a pure function so the render logic is
tested without mounting a widget; test_playback_bar_live_show.py covers the
reactive wiring that calls it.
"""

import unittest

from textual.widgets import Label

from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.live_show_follow import apply_live_show_follow_marker


def _apply(**kwargs):
    label = Label()
    apply_live_show_follow_marker(label, **kwargs)
    return label


class ApplyLiveShowFollowMarkerTests(unittest.TestCase):
    def test_followed_and_not_followed_are_visually_distinct(self) -> None:
        followed = _apply(
            show_id=42,
            show_name="Group Therapy",
            followed=True,
            content_type=ContentType.LIVE,
        )
        not_followed = _apply(
            show_id=42,
            show_name="Group Therapy",
            followed=False,
            content_type=ContentType.LIVE,
        )

        self.assertNotEqual(str(followed.render()), str(not_followed.render()))
        self.assertNotEqual(followed.classes, not_followed.classes)
        self.assertIn("live-show-follow--followed", followed.classes)
        self.assertIn("live-show-follow--unfollowed", not_followed.classes)

    def test_show_name_is_reachable_as_a_tooltip(self) -> None:
        label = _apply(
            show_id=42,
            show_name="Group Therapy",
            followed=True,
            content_type=ContentType.LIVE,
        )

        self.assertEqual(label.tooltip, "Group Therapy")

    def test_hidden_when_no_show_is_airing(self) -> None:
        label = _apply(
            show_id=None, show_name="", followed=None, content_type=ContentType.LIVE
        )

        self.assertEqual(str(label.render()), "")
        self.assertEqual(label.tooltip, None)

    def test_hidden_when_content_type_is_not_live(self) -> None:
        for content_type in (
            ContentType.MIXSHOW,
            ContentType.PLAYLIST,
            ContentType.TRACK,
        ):
            with self.subTest(content_type=content_type):
                label = _apply(
                    show_id=42,
                    show_name="Group Therapy",
                    followed=True,
                    content_type=content_type,
                )

                self.assertEqual(str(label.render()), "")

    def test_hidden_while_follow_state_is_not_yet_known(self) -> None:
        # Covers both a logged-out session (never fetched) and the brief
        # window before a fresh fetch resolves -- neither has anything true
        # to assert yet.
        label = _apply(
            show_id=42,
            show_name="Group Therapy",
            followed=None,
            content_type=ContentType.LIVE,
        )

        self.assertEqual(str(label.render()), "")
        self.assertEqual(label.tooltip, None)

    def test_switching_to_hidden_clears_the_previous_css_class(self) -> None:
        label = _apply(
            show_id=42,
            show_name="Group Therapy",
            followed=True,
            content_type=ContentType.LIVE,
        )

        apply_live_show_follow_marker(
            label,
            show_id=None,
            show_name="",
            followed=None,
            content_type=ContentType.LIVE,
        )

        self.assertNotIn("live-show-follow--followed", label.classes)
        self.assertNotIn("live-show-follow--unfollowed", label.classes)


if __name__ == "__main__":
    unittest.main()
