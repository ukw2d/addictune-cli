"""Windows System Media Transport Controls through winrt.

Untested by the owner so far (D13): a console process may not receive media
keys without a window; the Windows manual pass in 05 decides.
"""

from .session import CallSoon, Command, MediaInfo, OnCommand, Schedule


class SmtcSession:
    def __init__(self, call_soon: CallSoon) -> None:
        from winrt.windows.media import (
            MediaPlaybackStatus,
            MediaPlaybackType,
            SystemMediaTransportControlsButton as Button,
        )
        from winrt.windows.media.playback import MediaPlayer

        self._status = MediaPlaybackStatus
        self._type = MediaPlaybackType
        self._buttons = {
            Button.PLAY: Command.PLAY,
            Button.PAUSE: Command.PAUSE,
            Button.NEXT: Command.NEXT,
            Button.PREVIOUS: Command.PREVIOUS,
        }
        self._call_soon = call_soon
        self._on_command: OnCommand = lambda c: None
        self._info = MediaInfo()
        self._player = MediaPlayer()
        self._player.command_manager.is_enabled = False
        self._smtc = self._player.system_media_transport_controls
        self._smtc.is_enabled = True
        self._token = None

    def start(self, on_command: OnCommand, schedule: Schedule) -> None:
        self._on_command = on_command
        self._token = self._smtc.add_button_pressed(self._on_button)

    def _on_button(self, _sender, args) -> None:
        command = self._buttons.get(args.button)
        if command is not None:
            self._call_soon(lambda: self._on_command(command))

    def update(self, info: MediaInfo) -> None:
        if info == self._info:
            return
        self._info = info
        smtc = self._smtc
        smtc.is_play_enabled = info.can_play
        smtc.is_pause_enabled = info.can_pause
        smtc.is_next_enabled = info.can_next
        smtc.is_previous_enabled = info.can_previous
        smtc.playback_status = (
            self._status.PLAYING
            if info.playing
            else self._status.PAUSED
            if info.can_play
            else self._status.STOPPED
        )
        updater = smtc.display_updater
        updater.type = self._type.MUSIC
        updater.music_properties.title = info.title
        updater.music_properties.artist = info.artist
        if info.artwork_url:
            from winrt.windows.foundation import Uri
            from winrt.windows.storage.streams import RandomAccessStreamReference

            updater.thumbnail = RandomAccessStreamReference.create_from_uri(
                Uri(info.artwork_url)
            )
        else:
            updater.thumbnail = None
        updater.update()

    def stop(self) -> None:
        if self._token is not None:
            self._smtc.remove_button_pressed(self._token)
            self._token = None
        self._smtc.is_enabled = False
        self._player.close()
