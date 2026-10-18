# Debugging playback

Playback spans two processes: the Textual app decides *when* to (re)start
audio, a player subprocess decodes it. Both log to one file, tagged with role
and pid, so a reconnect reads as a single timeline.

```sh
uv run addictune --dev            # DEBUG logging + Textual devtools
uv run textual console            # optional, in another terminal
tail -f ~/Library/Caches/addictune-cli/debug.log   # macOS; ~/.cache/addictune-cli on Linux
```

Normal runs log at `WARNING` and the file is created lazily, so a healthy
session writes nothing; it is capped at 512KB with one previous generation
kept. `ADDICTUNE_LOG_FILE` moves it, `ADDICTUNE_LOG_LEVEL` overrides the level.

## Connection failures

The player child enables libav's log at `ERROR`, so a failed `av.open` carries
the stage that failed after `last error log:` -- `[tcp] Failed to resolve
hostname`, `[tls] Unable to negotiate TLS/SSL session`, `[tls] IO Error`
(macOS: a handshake or first response that outlasted the open timeout).
Without that line, PyAV reports every connection-level failure as a bare
`[Errno 5] Input/output error`. An HTTP rejection is never `EIO`: it arrives
as `HTTPForbiddenError` (`Server returned 403 Forbidden`) and the like.

Stream URLs are signed (`audio_token`, `auth`, `member_id`, the client's
`ip`), so the player redacts them with `redact_url` before any error reaches
the log or the screen. A URL in a report should show `***` for those params.

## Reconnects

A dropped live stream must end the player process — that exit is what triggers
the reconnect. The invariant to check is that a stalled connection produces
**one** `icy stream stalled` warning, then the player exits:

```
player[123] addictune_cli.audio.stream: icy stream stalled for 6s with no data; treating as EOF
app[100] addictune_cli.playback_bar: live playback ended; retry 1/12 in 0.5s
```

The first line carries the `player` role and the child's pid, the second the
`app` role: one timeline for both processes. (`live playback ended` is logged
at INFO; run with `--dev` to see it.)

Repeated stall warnings on one connection mean `_IcyAudioSource._ended` has
regressed: libav retries a short read, so an EOF that does not latch restarts
the countdown forever. The player then stays alive on a dead socket and the UI
keeps showing it as playing, progress bar and all, over silence.
