# 02 OS media session: REWRITE macOS, TRIM session and Linux, KEEP Windows, DELETE the host

Files today (all under `addictune_cli/src/audio/`): `media_session.py` (207), `media_host.py` (127), `macos_mediaplayer.py` (222), `linux_mpris.py` (246), `windows_smtc.py` (91). Total 893. Target about 350, moved to `addictune_cli/src/media/`.

## Job

Show title, artist and artwork in the OS now-playing widget and receive play, pause, next and previous from media keys and the OS widget. Nothing else.

## Today

| Finding | Where |
|---|---|
| The session runs in a **child process** (`media_host`) with a JSON-lines wire protocol, reader threads, a queue and a 100 ms drain timer. | `media_session.py`, `media_host.py` |
| Git history shows the process boundary was adopted after macOS flakiness with a background `NSRunLoop` thread (commits `e8cfb74`, `4e5a1f3`, `c2cbb85`, `a737020`). The root cause was never isolated. | git log |
| macOS `MPRemoteCommandCenter` needs the main-thread run loop. Proposed in-process approach: `set_interval(0.05, lambda: CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0, True))` on the Textual loop. **Unproven.** | `macos_mediaplayer.py` |
| macOS Now Playing needs a bundle identifier. `uv tool` installs have none (`NSBundle.mainBundle().bundleIdentifier()` is None). Only the Nuitka `.app` has one. | `tools/macos_pkg.py` |
| Linux `dbus-fast` is asyncio-native. It can run on the Textual loop with no thread and no `serve()`. | `linux_mpris.py` |
| Windows SMTC needs no pump. `serve()` exists only for the child process. | `windows_smtc.py` |
| `smoke_test_media_host` code in the packaging scripts. | `tools/*_pkg.py` |

## Target shape (about 350 LOC)

```
media/
  session.py     ~45   MediaInfo (frozen), Command enum, MediaSession Protocol, NullSession, make_session()
  macos.py       ~100  in-process MPNowPlayingInfoCenter and MPRemoteCommandCenter, runloop pump timer
  linux.py       ~130  MPRIS over dbus-fast; async start(); minimal Player interface
  windows.py     ~75   SMTC; start() only
```

Contract:

```python
class MediaSession(Protocol):
    async def start(self, on_command: Callable[[Command], None]) -> None
    def update(self, info: MediaInfo) -> None      # idempotent, cheap
    async def stop(self) -> None
```

`update` is called from the `NowPlaying` reactive watcher (`03`). Commands are delivered on the Textual loop; the macOS pump runs there.

Deleted: wire protocol, `SubprocessMediaSession`, `media_host.py`, reader threads, queue and drain timer, `smoke_test_media_host` in packaging.

### Fallback if the spike fails

If pumped run-loop callbacks do not survive idle on macOS, keep a **macOS-only** child process using the same `MediaSession` Protocol (small `multiprocessing` pipe, not JSON lines). Linux and Windows stay in-process. Even then the wire protocol and reader threads are rewritten smaller.

## Windows and Linux gaps (D13)

| Area | Gap | Action |
|---|---|---|
| Windows SMTC | Never tested by the owner. Needs a window handle or a `MediaPlayer` with `CommandManager` disabled; a console app may not get media-key focus. Unknown. | Windows pass in the acceptance below; if keys do not arrive, record it here and decide on a fix (hidden window via `winrt` or `pywin32`). |
| Windows artwork | `RandomAccessStreamReference` from bytes needs `InMemoryRandomAccessStream` writes; the current code uses a URI. URI only works for http(s), which is fine for CDN art. | Keep the URI path; test. |
| Linux MPRIS | Works under GNOME/KDE; headless CI has no session bus. | Test skips without a session bus. |
| Linux without `dbus-fast` session | `make_session()` must return `NullSession`, not raise. | Covered by the factory test. |

## Tests

- DELETE: `test_macos_mediaplayer`, `test_windows_smtc` (zero signal), all wire-protocol tests.
- KEEP: `test_linux_mpris`.
- ADD: `make_session()` returns `NullSession` on unsupported platforms or import failure; `update` ignores identical info.
- Tests go from about 277 LOC to about 150.

## Acceptance

- `grep -rn "media_host\|SubprocessMediaSession\|serve(" addictune_cli tools` is empty.
- `grep -rn "Popen\|subprocess" addictune_cli/src/media` is empty (unless the fallback is taken, then only in `macos.py`).
- Manual: start playback, leave the app idle 30 minutes, press the media key; it responds. Now-playing shows title and artist. Repeat on Linux (GNOME or KDE) and Windows (see gaps).

## Tasks

1. **Spike (30 min, macOS, owner-approved):** pump `CFRunLoopRunInMode` from a Textual interval; verify commands still arrive after 30 minutes idle and after sleep/wake. Also test whether a runtime-set `CFBundleIdentifier` makes Now Playing work under `uv tool` (shared with `05`).
1a. **Windows check:** run the existing SMTC code on Windows and record whether media keys arrive from a console process.
2. Write `session.py` and `linux.py` (async start).
3. Write `macos.py` in-process (or the fallback child).
4. Trim `windows.py`.
5. Wire into the shell through the `NowPlaying` watcher; delete the host and tests.
6. Remove host smoke tests from packaging (coordinate with `05`).

## Open questions

1. Spike result decides in-process vs macOS-only child. Default: in-process. With `01` keeping the audio child process, the Nuitka re-exec in `subprocess_worker.py` stays; it just no longer serves the media host.
2. OS-widget artwork required? Dropping it saves about 40 LOC. Default: keep, reusing bytes from the image cache in `04`.
3. Full MPRIS root interface, or the minimal `Player` interface only? Default: minimal.

## Spike results (2026-10-06, macOS, task `add-fc3`)

- **Pumped run loop keeps delivering callbacks.** A standalone script registered `MPRemoteCommandCenter` handlers and ran `CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0, True)` every 50 ms from an asyncio task on the main thread. Synthetic play/pause media keys (Quartz `NX_KEYTYPE_PLAY`) were delivered in a first run at 0:46, 5:00 and 12:00, and in a full 32-minute run at exactly 10, 20 and 30 minutes, each after 600 s of idle (`COMMAND toggle (idle for 600s)` ×3). No fallback child process is needed. The historical flakiness came from running the run loop on a *background* thread; pumping it on the main thread from the UI loop is what works.
- **Bundle identifier under `uv tool`:** `NSBundle.mainBundle().infoDictionary()["CFBundleIdentifier"] = ...` changes `bundleIdentifier()` at runtime (from `org.python.python` to the set value). Whether Now Playing then shows the right app name outside the Nuitka `.app` is left to the `05` packaging pass; the session works either way (verified from a plain `uv run`).
- Sleep/wake: not tested in the spike. The `NSWorkspaceDidWakeNotification` re-publish from the old backend is kept (the bar does not call `update` on every tick, and `MacSession.update` drops identical info, so without it the widget could stay blank after wake).

## Landed shape (2026-10-06)

```
media/
  session.py    82   Command (StrEnum: play/pause/toggle/next/previous), MediaInfo (frozen), MediaSession Protocol with start(on_command, schedule)/update/stop, NullSession, make_session(call_soon)
  macos.py    ~185   MacSession: in-process MPNowPlayingInfoCenter + MPRemoteCommandCenter; pump() scheduled every 50 ms through `schedule`; wake re-publish; artwork fetched off-thread, applied on the loop (failed fetch may retry); elapsed accumulates across pause/resume, resets on title change
  linux.py    ~218   MprisSession: dbus-fast on the Textual loop (no thread, no serve()); minimal root + Player interface; next/previous exposed
  windows.py   ~83   SmtcSession: SMTC with play/pause/next/previous buttons; URI thumbnail; untested (D13)
```

Deleted: `audio/media_session.py` (wire protocol, `SubprocessMediaSession`), `audio/media_host.py`, `audio/macos_mediaplayer.py`, `audio/linux_mpris.py`, `audio/windows_smtc.py`, the `media_host` entry in `subprocess_worker.py`/`__main__.py`, `smoke_test_media_host` in the three `tools/*_pkg.py`. Tests deleted: `test_macos_mediaplayer`, `test_linux_mpris`, `test_windows_smtc`; `test_media_session` rewritten against the new contract (3), added `test_media_session_factory` (5), `test_media_linux` (2, skip off-Linux).

Bar wiring: `PlaybackBar._ensure_media_session()` starts the backend once on first playback and falls back to `NullSession` if `start()` raises, so a broken binding never crashes the app; `_sync_media_session` builds one `MediaInfo` (title, artist, hi-res artwork URL, playing, can_play/pause/next/previous) and the session starts lazily on first playback with `self.set_interval` as the scheduler. Commands route back through the bar's existing `PlayRequested`/`PauseRequested`/`TogglePlayRequested` messages; `NEXT`/`PREVIOUS` call `app.action_next_track`/`action_previous_track`, so OS keys behave exactly like the keyboard bindings. `can_previous` is true only for playlists (D16).

Size: 893 → ~570 LOC (target ~350; the MPRIS interface boilerplate is ~120 LOC of required D-Bus properties). Acceptance greps empty. 364 tests green.

Residual risk: `NSApplication.sharedApplication()`/`finishLaunching()` now run inside the TUI process; AppKit diagnostics would land on the terminal. In the macOS real-app check stderr stayed empty (0 bytes). Elapsed time is published as a snapshot plus rate, which is how Now Playing extrapolates; verified across pause/resume (held at 3.1 s while paused, resumed from 3.1 s).

Verified in the real app on macOS: `MacSession` created, Now Playing shows the ICY title with playback state Playing; a synthetic media key stopped the live channel, a second one resumed it.

Windows (D13): `SmtcSession` written against the same winrt calls as before plus next/previous; still untested until the Windows pass in `05`.
