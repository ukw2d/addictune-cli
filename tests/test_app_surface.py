"""Every `app.<name>` the TUI code uses must exist on the real AddictuneApp.

Test doubles elsewhere stand in for the app, so a method removed from the app
while production code still calls it would otherwise pass the suite.
"""

import re
import unittest
from pathlib import Path

from textual.app import App

from addictune_cli.src.tui.app import AddictuneApp

_TUI = Path(__file__).resolve().parents[1] / "addictune_cli" / "src" / "tui"
_ATTR = re.compile(r"\b(?:self\.)?app\.([A-Za-z_][A-Za-z_0-9]*)")
# Plain instance state set in AddictuneApp.__init__/on_mount (not class attributes).
_INSTANCE_STATE = {
    "settings",
    "animation_level",  # Textual sets this on the App instance at runtime.
    "client",
    "user_id",
    "playing_episode_id",
    "_playing_channel_id",
    "_channels",
    "_statuses_by_channel",
    "_statuses_by_show",
    "_live_by_channel",
    "_now_playing_by_channel",
    "_next_show_by_channel",
    "_feature_availability",
    "_feature_cache",
    "_followed_controllers",
    "_search",
    "_votes",
    "_auth_service",
    "_media_info",
    "_follow",
    "_channels_service",
    "_playback_service",
}


class AppSurfaceTests(unittest.TestCase):
    def test_every_app_attribute_used_by_the_tui_exists(self) -> None:
        used: dict[str, set[str]] = {}
        for path in _TUI.rglob("*.py"):
            if path.name == "app.py":
                continue
            for name in _ATTR.findall(path.read_text(encoding="utf-8")):
                used.setdefault(name, set()).add(path.name)
        missing = {
            name: sorted(files)
            for name, files in used.items()
            if name not in _INSTANCE_STATE
            and not hasattr(AddictuneApp, name)
            and not hasattr(App, name)
        }
        self.assertEqual(missing, {})


if __name__ == "__main__":
    unittest.main()
