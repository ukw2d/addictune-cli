import unittest
from unittest.mock import patch

from addictune_cli.src.settings import STATION_NAMES, Settings
from addictune_cli.src.tui.app import AddictuneApp


class StationSettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        s = Settings()
        self.assertEqual(s.station_slug, "di")
        self.assertFalse(s.station_selected)

    def test_app_uses_saved_slug_on_init(self) -> None:
        with patch.object(
            Settings, "load", return_value=Settings(station_slug="rockradio")
        ):
            app = AddictuneApp()
        self.assertEqual(app.network, "rockradio")

    def test_app_defaults_to_di_when_no_settings(self) -> None:
        with patch.object(Settings, "load", return_value=Settings()):
            app = AddictuneApp()
        self.assertEqual(app.network, "di")

    def test_all_station_names_present(self) -> None:
        self.assertIn("di", STATION_NAMES)
        self.assertTrue(all(isinstance(v, str) for v in STATION_NAMES.values()))


if __name__ == "__main__":
    unittest.main()
