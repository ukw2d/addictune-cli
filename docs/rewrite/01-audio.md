# 01 Audio: KEEP the player subprocess, REWRITE its protocol, device handling and `Player`

Package `addictune_cli/src/audio/` (playback part), `tui/handlers/playback.py`, `tui/controllers/playback.py`, `tui/controllers/clock.py`, the backend region of `tui/widgets/playback_bar.py`, `subprocess_worker.py`, `tui/screens/settings.py` (audio rows). About 1,100 production LOC today. Target about 600 before `07`, about 450 after `07` removes ICY and live retry.

Owner decisions (2026-10-06) that shape this doc:

- The player stays a **separate process**. In-process audio made the UI laggy, and process isolation is the better architecture here (GIL contention, native-crash isolation, clean kill on quit).
- The user **must be able to change audio settings** (device, and the other knobs below).
- The hotplug bug must be fixed.
- Live streams and ICY are going away through `07` (channels as tracklists). `01` does not touch ICY; `07` deletes it. Until then `stream.py` keeps `_IcyAudioSource` unchanged.

## Job

Turn one URL into sound on the device the user chose (or the system default), with pause, resume, volume, stop, position and a clear "it failed, here is why" signal, without ever blocking the UI. When the output device set or the system default changes (headphones in or out), sound follows within about 2 seconds. Changing audio settings takes effect immediately on the current track, with no restart of the app.

## Today

| Finding | Where |
|---|---|
| **Hotplug root cause.** `RawOutputStream(device=None)` resolves the default output once, at open. CoreAudio does not migrate an open stream. Nothing watches for device changes. PortAudio rescans devices only on `Pa_Terminate` + `Pa_Initialize`, which needs no open streams. The TUI-side `sd.query_devices()` list is also frozen at first use, so the settings device picker goes stale too. | `audio/player.py:131-137`, `audio/devices.py` |
| The `devices.py` docstring claims PortAudio "rebuilds whenever hotplugged". That is wrong for a running process. | `audio/devices.py:3-4` |
| A device is stored by name but resolved to an index per open; the index/name mapping is recomputed in two places. | `audio/devices.py`, `settings.py` |
| `config.dtype` is passed to the output stream, but the decoder always emits float32. The dtype setting is already broken. | `audio/player.py:134`, `audio/stream.py` |
| Volume is applied by a per-sample Python generator. numpy is not a dependency. **Likely cause of the in-process lag** (pure-Python work holding the GIL at audio rate); inference, not measured. | `audio/stream.py` |
| An on-demand play opens the URL three times (`_resolve_and_probe`, `probe`, `decode`). | `audio/stream.py`, `tui/handlers/playback.py` |
| `_schedule_audio_warmup` initializes PortAudio in the **TUI** process for nothing. | `tui/app.py:284,317` |
| `handler.play_resolved` uses `model_copy` on config. | `tui/handlers/playback.py:136` |
| Subprocess plumbing is heavier than it needs to be: text protocols on stdin, stdout **and** stderr, a watchdog, signals, three worker groups, duplicate generation counters in handler, controller and bar. About 500 LOC. | `tui/handlers/playback.py` (240), `audio/player.py` (225), `subprocess_worker.py` (30), `__main__.py` (15) |
| `restart_current_with_audio_settings` tears the subprocess down and restarts playback to apply a setting. | `tui/widgets/playback_bar.py:341-344` |
| Controller retry policy (live-only backoff, stop reasons) is sound and tested. | `tui/controllers/playback.py` (150) |
| Volume default `0.3` is duplicated in `settings.py` and `audio/config.py`. | both |

### Hotplug fix options (recorded decision input)

| Option | Verdict |
|---|---|
| **a1.** Keep sounddevice. In the child, poll an OS "output signature" about once a second. On change: `abort`, `close`, `sd._terminate`, `sd._initialize`, re-resolve the configured device, reopen, continue at the current position. | **Chosen.** Cost: a gap of a few hundred ms, per-OS signature code, use of private `sd._terminate/_initialize`. |
| a2. Poll `sd.query_devices()`. | Rejected: does not refresh while a stream is open. |
| b. pyminiaudio. | Unverified (cffi sdist, py3.14 wheels not guaranteed, no AAC decoder so PyAV stays, Nuitka risk). Revisit only if Windows WASAPI proves awkward. |
| c. Parent restarts the child on a change. | Rejected: 1 to 2 s gap. |

Output signature per platform (`output.py`):

| OS | Signature | Note |
|---|---|---|
| macOS | ctypes CoreAudio: default output device id + `kAudioHardwarePropertyDevices` id set | about 30 LOC |
| Linux | ctypes-free: PulseAudio/PipeWire move the `default` device by themselves, so a stream opened on the default sink follows. Signature is a constant for `default`. A **named** device that appears later is not detected until the stream is reopened (limitation; see Open questions). | 0 LOC |
| Windows | PortAudio WASAPI does not follow endpoint changes. Needs `IMMDeviceEnumerator.GetDefaultAudioEndpoint` via ctypes COM (about 40 LOC) or a small dependency. **Unverified; needs a Windows machine.** | gap, see `05` |

## Target shape

```
audio/
  state.py       KEEP   PlaybackState, StoppedReason (8)
  stream.py      KEEP   probe/decode/_packed_audio_bytes (+ ICY until 07); volume via PyAV filter or numpy; one av.open
  output.py      NEW    OutputConfig(device_name|None, sample_rate|None, latency); signature(); resolve(config) -> index|None (~80)
  player.py      REWRITE  Player: decode thread, one generation counter, reopen-on-signature-change (~130)
  worker.py      NEW    child entry: JSON-lines command loop around Player (~60)
  client.py      NEW    parent side: spawn, send, event-reader thread, generation filter (~100)
tui/controllers/
  playback.py    KEEP   retry policy; drop PlayerExit and handler-exit reporting
  clock.py       KEEP
subprocess_worker.py  KEEP only as the Nuitka-safe entry (shrinks)
```

Deleted: `audio/config.py` (clamp lives in `state.py`), `audio/devices.py`, `tui/handlers/playback.py`, `_schedule_audio_warmup`, `restart_current_with_audio_settings`, the stdout/stderr text protocols, the watchdog thread, signal handling, parent-side `model_copy`.

### Process contract

- One child process per app run, started lazily at first play, never restarted for settings.
- One channel, **JSON lines** on stdin/stdout, modelled as a pydantic discriminated union (`TypeAdapter`) used by both sides. stderr goes to the log file only.
- Commands (parent to child): `play{gen,url,live,volume,start_at?}`, `pause`, `resume`, `stop`, `volume{v}`, `configure{device_name,sample_rate,latency}`, `devices{}`, `quit`.
- Events (child to parent): `state{gen,state}`, `error{gen,kind,message}`, `position{gen,seconds}`, `devices{items,default}`, `ready`.
- `configure` makes the child reopen the output at the current frame (same mechanism as the hotplug reopen), so a settings change is instantaneous and does not touch the queue or retry state.
- **Orphan safety on every OS:** the child exits when stdin reaches EOF (the parent died or closed the pipe). No signals and no watchdog, which also works on Windows.
- **Device list comes from the child** (`devices` request). The TUI process never initializes PortAudio, so its picker cannot go stale; the settings screen asks the child each time it opens.
- One `generation` counter for child events, assigned by `audio/client.py` on `play` and echoed by the child on every event; the client drops events whose generation is not current. The bar keeps none. The controller keeps its own user-level counter only to retire async URL resolution that finishes after a newer play.

### Settings kept and removed

| Setting | Verdict | Why |
|---|---|---|
| `audio_device_name` | KEEP; `None` means "System default (follow the OS)" | main user control; stored by name, resolved to an index per open |
| `audio_sample_rate` | KEEP; `None` means auto | some DACs need a fixed rate |
| `audio_latency` | KEEP | buffer size vs dropouts |
| `audio_dtype` | DELETE | already ignored by the decoder, which always emits float32; no listener |

All audio settings are applied through `configure`. Stale keys in `settings.json` are tolerated on load (pydantic ignores extras); add a test. The settings screen (in `03`) renders rows from the child's `devices` reply.

### Behaviour on a missing device

If the configured named device is not present, the child plays on the system default and emits `error{kind="device_missing"}` once (shown as a notice). When the signature changes and the named device is back, it moves back to it. No retry loop.

## Tests

| Action | Tests |
|---|---|
| DELETE | `test_audio_devices`, `test_audio_player_controls`, `test_playback_handler` |
| TRIM | `test_playback_failure_reporting`: delete the `_last_error_line`, `PlayerExit`, `HandlerExitReporting` cases; keep `StoppedReason` and `RetryPolicy` |
| KEEP | `test_playback_clock`, `test_next_event_delay`, the two `_packed_audio_bytes` tests in `test_audio_stream`, the four ICY tests until `07` |
| ADD | `Player` with a fake stream and decoder: pause, stop, stale generation ignored. `output.resolve` with a fake device table: named, missing, default. Watcher: a scripted signature sequence causes exactly one reopen. Protocol: round-trip of every message through the `TypeAdapter`. Client: child EOF on parent close (spawn a real child with a null output). Stale settings keys load |

## Acceptance

- `grep -rn "PlayerExit\|PlaybackHandler\|_schedule_audio_warmup\|restart_current_with_audio_settings\|audio_dtype\|AudioConfig" addictune_cli` is empty.
- `grep -rn "import sounddevice\|import av" addictune_cli/src/tui` is empty (TUI never touches audio libraries).
- `wc -l` of `audio/*.py` is at most about 600 (about 450 after `07`).
- Manual: play; connect headphones; sound moves within about 2 s with no action; unplug and it moves back. Pick a specific device in settings and the sound moves at once. Choose a sample rate and latency; playback continues. Quit returns immediately; `ps` shows no leftover child after killing the parent with `kill -9` (macOS and Linux) or ending the task (Windows).
- An on-demand play opens the URL once.
- UI stays responsive (no visible lag) while a track plays and the volume is changed quickly.

## Tasks

1. Spike (30 min each, macOS and Windows): CoreAudio signature read and `sd._terminate` + `sd._initialize` refreshing the device table while idle; Windows default-endpoint read via ctypes COM. Decide numpy vs PyAV filter for volume by measuring CPU in the child.
2. `output.py` + tests.
3. `Player` + tests.
4. Protocol models, `worker.py`, `client.py` + tests.
5. Switch `PlaybackController` and the bar to `client`; delete handler, config, devices, warmup, text protocols.
6. Settings rows through `configure` and the child's device list; delete dtype; stale-key test.
7. Single `av.open` for on-demand.

## Open questions (proposed default first)

1. Volume implementation: **PyAV `volume` filter** (spike result below). numpy is not added.
2. Linux named devices that appear after start are not detected without a stream reopen. **Accepted by the owner.**
3. Gapless next track: with per-track files from `07` the child could pre-open the next URL. Not in scope here; decide after `07`.
4. Keep `audio_latency` as a free value or three presets (low, default, high)? Default: presets.

## Landed shape (2026-10-06, branch `develop`, epic `add-mk4`)

```
audio/
  state.py        8   unchanged
  output.py     136   OutputConfig; resolve(); output_names(); Output (re-inits PortAudio per open, fell_back); device_names(); signature() (CoreAudio via ctypes on macOS, () elsewhere)
  protocol.py   126   AudioStreamInfo; Command/Event discriminated unions + TypeAdapters
  stream.py     340   Stream (one av.open, resampler, PyAV volume filter with live process_command, seek); _IcyAudioSource kept verbatim until 07 (~170)
  player.py     ~300  Player: one decode thread per generation, one long-lived Output reused across plays, pause/resume/stop/seek/configure/check_output, reopen-in-place keeping position
  worker.py     111   child entry; JSON lines on stdin/stdout; exits on stdin EOF; 1 Hz signature poll; ADDICTUNE_NULL_OUTPUT for tests
  client.py     194   PlayerClient: lazy spawn, generation assigned by the parent, event thread -> dispatch, stale-event filter, request_devices(callback), close()
tui/controllers/playback.py  131   retry policy kept; confirm_playback/STARTUP_GRACE/PlayerExit gone; playing()/backend_exited(). Its generation counter stays: it retires in-flight async URL resolution, which the child never sees. The child-event counter lives in client.py; the two are never compared.
tui/widgets/playback_bar.py  626   UI unchanged; backend region now: _resolve_and_play, _on_player_{state,error,position,info}, apply_audio_settings, request_devices
subprocess_worker.py          30   unchanged except "player" -> audio.worker
```

Deleted: `audio/config.py`, `audio/devices.py`, `tui/handlers/playback.py`, `_schedule_audio_warmup`, `restart_current_with_audio_settings`, `AUDIO_SETTINGS_RESTARTING`, text protocols, watchdog, signals, `audio_dtype`, the bar's `DurationReceived/PlaybackStarted/PlaybackStartFailed/BackendExited/IcyTitleReceived` messages, `_with_listen_key` (SDK has it). Tests deleted: `test_audio_devices`, `test_audio_player_controls`, `test_playback_handler`. Added: `test_audio_output`, `test_audio_player` (12), `test_audio_client` (5, real child with null output), stale-settings-key test; `test_playback_failure_reporting` trimmed to policy.

Also landed in this epic (unplanned, Beads `add-izv0`): SDK 0.4.1 compatibility, because the app did not import against the installed SDK.

Size: `audio/*.py` is 1,178 LOC against the ~600 estimate. ICY (~170) leaves with 07; `protocol.py` (126) and `Output`/null output (~60) were not in the estimate. Realistic floor after 07 is about 900.

Owner test found that opening Settings during playback made the stream reconnect and then go silent while the clock kept counting: `devices` ran `sd._terminate()` on the stdin thread under the decode thread's open stream (PortAudio -9986, then an invalid stream handle). Fixed: the device table is re-read through `Player.devices()`, which re-initialises PortAudio only while no output is open; `Output` opens under the player lock. Regression test `DevicesTests`. `device_missing` is now reported once per session, not on every reopen.

Owner test found a ~0.1 s click/pop on every channel switch. A listening test with silence only (device opened and closed three times, no audio sent) still popped, so the cause is the device open/close itself, not the signal; fades cannot fix it. Fixed by keeping **one output stream open across plays and seeks**; it is closed and reopened only when the format (channels/rate) changes, on `configure`, on a hotplug signature change, or before a device-list refresh while idle. Verified: 12 rapid channel switches opened the device once. Tests `OutputReuseTests`.

Owner test found a ~50 ms burst at full volume on play start: the volume filter was built at gain 1.0 and `set_volume` ran after the first chunk existed. Fixed by passing the volume into `Stream` at open (also covers the hotplug/configure/seek reopens). Verified: first chunk peak 0.17 at volume 0.3 instead of full scale.

Validation: 387 tests green, `ruff check` clean, acceptance greps empty. Manual on macOS: live channel plays with ICY titles; mixshow episode plays with duration and quality, seek +60 s lands at 64 s; pause/resume/stop; settings `configure` to a named device switches during live playback; **hotplug**: default output changed twice via CoreAudio during playback, child reopened within the 1 s poll each time and stayed PLAYING; app exit leaves the child with returncode 0; closing stdin alone makes the child exit 0.

Windows gaps (D13): `signature()` returns a constant, so hotplug on Windows relies on pause/resume or a settings change until the COM default-endpoint read is added and tested on a Windows machine; `CREATE_NO_WINDOW` is passed to the child spawn but untested; the pipe is forced to UTF-8 on both ends so non-ASCII device names survive on Windows (untested).

Out of this epic, recorded for later: `audio_latency` presets (question 4) kept as the existing high/low literal.


## Spike results (2026-10-06, macOS; task `add-3l2`)
| Spike | Result |
|---|---|
| CoreAudio signature via ctypes (`AudioObjectGetPropertyData` on `kAudioHardwarePropertyDefaultOutputDevice` + `kAudioHardwarePropertyDevices` filtered to devices with output streams) | Works, 0.3 ms per read, about 40 LOC. Polling at 1 Hz is free. |
| `sd._terminate()` + `sd._initialize()` while idle | Refreshes the default: `query_devices(kind="output")` went from the old to the new default only after the refresh. Also runs without raising while a stream is open, but the design closes the stream first. |
| Volume: per-sample Python loop vs PyAV `volume` filter, 60 s of 44.1 kHz stereo | Loop 0.16 s (0.27 % CPU), filter 0.007 s (0.01 % CPU). `vol.process_command("volume", "0.5")` changes the gain live without rebuilding the graph. The loop is therefore **not** the in-process lag cause; the cause stays unknown and is moot under D1. |
| Windows default-endpoint read via ctypes COM | **Not run** (no Windows machine). Gap recorded for the Windows manual pass (`05`). Until then `output.signature()` on Windows returns a constant and hotplug relies on a `configure` or pause/resume. |
