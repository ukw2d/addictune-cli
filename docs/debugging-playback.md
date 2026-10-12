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
