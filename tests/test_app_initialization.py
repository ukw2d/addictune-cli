import unittest
from unittest.mock import Mock, patch

from addictune_sdk import AddictuneAPIError

from addictune_cli.src.media.session import NullSession
from addictune_cli.src.settings import Settings
from addictune_cli.src.tui.app import AddictuneApp
from addictune_cli.src.tui.services.features import NetworkFeatures
from addictune_cli.src.tui.types import ContentType
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar


class AppInitializationTests(unittest.IsolatedAsyncioTestCase):
    def test_channel_status_state_exists_before_network_watcher_runs(self) -> None:
        app = AddictuneApp()

        app._channels_service._rebuild_channel_statuses()

        self.assertEqual(app._statuses_by_channel, {})
        self.assertEqual(app._live_by_channel, {})
        self.assertEqual(app._now_playing_by_channel, {})

    async def test_startup_with_stored_credentials_loads_channels(self) -> None:
        with (
            patch.object(
                Settings, "load", return_value=Settings(station_selected=True)
            ),
            patch.object(AddictuneApp, "load_channels", return_value=None) as load,
            patch(
                "addictune_cli.src.tui.widgets.playback_bar.make_session",
                return_value=NullSession(),
            ),
            patch(
                "addictune_cli.src.tui.app.load_credentials",
                return_value=("a@b.c", "secret"),
            ),
            patch.object(
                AddictuneApp, "refresh_feature_availability", return_value=None
            ),
        ):
            app = AddictuneApp()
            async with app.run_test() as pilot:
                await pilot.pause()

        load.assert_called_once()

    async def test_startup_without_credentials_prompts_login(self) -> None:
        with (
            patch.object(
                Settings, "load", return_value=Settings(station_selected=True)
            ),
            patch.object(AddictuneApp, "_prompt_login") as prompt,
            patch(
                "addictune_cli.src.tui.widgets.playback_bar.make_session",
                return_value=NullSession(),
            ),
            patch("addictune_cli.src.tui.app.load_credentials", return_value=None),
        ):
            app = AddictuneApp()
            async with app.run_test() as pilot:
                await pilot.pause()

        prompt.assert_called_once()

    async def test_live_playback_toggle_remains_available_after_stop(self) -> None:
        with (
            patch.object(
                Settings, "load", return_value=Settings(station_selected=True)
            ),
            patch.object(AddictuneApp, "load_channels", return_value=None),
            patch(
                "addictune_cli.src.tui.widgets.playback_bar.make_session",
                return_value=NullSession(),
            ),
            patch(
                "addictune_cli.src.tui.app.load_credentials",
                return_value=("a@b.c", "x"),
            ),
            patch.object(
                AddictuneApp, "refresh_feature_availability", return_value=None
            ),
        ):
            app = AddictuneApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                bar = app.query_one("#playback-bar", PlaybackBar)
                bar._controller.play(
                    "https://example.invalid/stream",
                    "Channel",
                    ContentType.LIVE,
                )
                app.content_type = ContentType.LIVE
                app._playing_channel_id = 1
                # The bar itself was never started, so playback is inactive —
                # a resumable live URL must still enable the toggle.
                self.assertFalse(app.playback_active)

                self.assertTrue(app.check_action("toggle_playback", ()))

    async def test_stale_feature_probe_does_not_update_current_network(self) -> None:
        app = AddictuneApp()
        app.set_reactive(AddictuneApp.network, "di")
        stale_features = NetworkFeatures(mixshows=False, playlists=False, tracks=False)
        app._sync_feature_tabs = Mock()  # type: ignore[method-assign]

        async def detect(_client, network: str, *, user_id: int | None):
            self.assertEqual(network, "di")
            self.assertIsNone(user_id)
            app.set_reactive(AddictuneApp.network, "rockradio")
            return stale_features

        with patch.object(app._feature_cache, "detect", side_effect=detect):
            await AddictuneApp.refresh_feature_availability.__wrapped__(app)

        self.assertEqual(app._feature_availability, NetworkFeatures())
        app._sync_feature_tabs.assert_not_called()

    async def test_missing_network_session_signs_in_before_prompting(self) -> None:
        app = AddictuneApp()
        app.client = Mock()
        app.client.has_session = Mock(return_value=False)
        app._prompt_login = Mock()  # type: ignore[method-assign]

        with patch(
            "addictune_cli.src.tui.services.auth.sign_in", return_value=42
        ) as sign_in:
            result = await app.ensure_authenticated_session("rockradio")

        self.assertTrue(result)
        self.assertEqual(app.user_id, 42)
        sign_in.assert_awaited_once_with(app.client, "rockradio")
        app._prompt_login.assert_not_called()

    async def test_missing_network_session_prompts_after_sign_in_fails(self) -> None:
        app = AddictuneApp()
        app.client = Mock()
        app.client.has_session = Mock(return_value=False)
        app._prompt_login = Mock()  # type: ignore[method-assign]

        with patch("addictune_cli.src.tui.services.auth.sign_in", return_value=None):
            result = await app.ensure_authenticated_session("rockradio")

        self.assertFalse(result)
        app._prompt_login.assert_called_once()

    async def test_existing_session_needs_no_sign_in(self) -> None:
        app = AddictuneApp()
        app.client = Mock()
        app.client.has_session = Mock(return_value=True)
        app.user_id = 42
        app._prompt_login = Mock()  # type: ignore[method-assign]

        with patch("addictune_cli.src.tui.services.auth.sign_in") as sign_in:
            result = await app.ensure_authenticated_session("rockradio")

        self.assertTrue(result)
        sign_in.assert_not_called()
        app._prompt_login.assert_not_called()

    async def test_recover_auth_replaces_a_dead_session(self) -> None:
        app = AddictuneApp()
        app.client = Mock()
        app._prompt_login = Mock()  # type: ignore[method-assign]

        with patch("addictune_cli.src.tui.services.auth.sign_in", return_value=7):
            self.assertTrue(await app.recover_auth("di"))
        self.assertEqual(app.user_id, 7)

        with patch("addictune_cli.src.tui.services.auth.sign_in", return_value=None):
            self.assertFalse(await app.recover_auth("di"))
        app._prompt_login.assert_called_once()

    async def test_recover_auth_reports_a_transient_failure_without_prompting(
        self,
    ) -> None:
        app = AddictuneApp()
        app.client = Mock()
        app._prompt_login = Mock()  # type: ignore[method-assign]
        app.notify = Mock()  # type: ignore[method-assign]

        with patch(
            "addictune_cli.src.tui.services.auth.sign_in",
            side_effect=AddictuneAPIError(503, "down"),
        ):
            self.assertFalse(await app.recover_auth("di"))

        app._prompt_login.assert_not_called()
        app.notify.assert_called_once()

    def test_successful_login_sets_the_user_and_loads_channels(self) -> None:
        app = AddictuneApp()
        app.load_channels = Mock()  # type: ignore[method-assign]
        app.call_after_refresh = lambda fn, *a: fn(*a)  # type: ignore[method-assign]
        app._prompt_station_selection_if_needed = Mock()  # type: ignore[method-assign]

        app._on_auth(42)

        self.assertEqual(app.user_id, 42)
        app.load_channels.assert_called_once()

    def test_dismissed_login_without_a_session_exits(self) -> None:
        app = AddictuneApp()
        app.exit = Mock()  # type: ignore[method-assign]

        app._on_auth(None)

        app.exit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
