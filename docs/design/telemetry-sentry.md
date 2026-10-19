# Error telemetry (Sentry)

Status: approved (on by default, per the maintainer). Beads: at-rl5.

## Problem

The first public bug report arrived as a screenshot of a toast: no stack,
no OS, no version, no failing stage, and the only log sat on the user's
machine. Every future report will look the same unless errors reach the
maintainer on their own.

## Goal

Errors in the app and in the player child reach the Sentry project
`addictune-cli` (org `ukw2d`) with what troubleshooting needs -- app
version, OS, Python/PyAV/FFmpeg versions, the failing stage and libav
reason, the redacted stream URL and the log lines leading up to it --
and never the user's email, password, listen key, tokens or IP.

## Non-goals

Tracing, profiling, logs product, metrics, session tracking, usage
analytics. Sentry's Logging/Tracing products were deliberately not enabled.

## Decision: on by default

The maintainer chose on-by-default. The mitigations: reports carry no
personal data (below), the toggle is one row in Settings > General with a
plain description, and the README privacy section says it is on and how to
turn it off. No consent prompt.

## Design

### Data

| Datum | Purpose | Consumer | Lifecycle |
|---|---|---|---|
| `Settings.telemetry: bool = True` | the user's opt-out | `telemetry.init()` at app start and on toggle; the player child via `ADDICTUNE_TELEMETRY` on spawn | replaced on toggle |
| Sentry events (remote) | the maintainer's debugging | Sentry UI | Sentry retention |

### Module `addictune_cli/src/telemetry.py`

`init(role, enabled)` -- closes and unbinds any client, then `sentry_sdk.init`
only when enabled. Options: neither `send_default_pii` nor `data_collection`
(the SDK's conservative defaults), `include_local_variables=False`,
`include_source_context=False`,
`server_name=""`, `traces_sample_rate=None`, `auto_session_tracking=False`,
explicit integrations only (`default_integrations=False` plus Logging,
Excepthook, Threading, Dedupe, Atexit) so a Nuitka build behaves like a
source run and nothing auto-enables. `release=addictune-cli@<version>`,
`environment=release|source`. Tags: `role` (app/player), `pyav`, `ffmpeg`,
`network` (station slug, set by the app).

`before_send` scrubber, applied to every string in the event (messages,
exception values, breadcrumbs, extra, contexts, frame paths):
1. every URL through `redact_url`;
2. the signed-in email, password, listen key and account id replaced by
   `***` wherever they occur (registered at login via `remember_secrets`;
   INFO lines no longer log the account id);
3. the home directory replaced by `~`;
4. `user`, `server_name`, `request` dropped.
A scrubber exception drops the event rather than sending it raw.

Volume (5,000 errors/month on the free plan):
- The logging integration records breadcrumbs only (`event_level=None`); log
  lines never become events by themselves.
- A playback failure becomes **one** event when playback finally stops
  (`PlaybackBar._notify_playback_failure`), not one per retry. Free-account
  Premium refusals are not reported (expected, not a bug).
- Playback events are fingerprinted by `kind` + the detail with URLs
  stripped, so one root cause is one Sentry issue (errno and TLS codes stay
  distinct).

Breadcrumbs: Sentry gets INFO+ records through its own hook on
`Logger.callHandlers`, but our loggers sit at WARNING by default; `init`
lowers the logger levels to INFO (restored when reporting is turned off)
while the file handler carries the configured level itself, so `debug.log`
is unchanged.

### Hooks

- App: `AddictuneApp._handle_exception` (Textual's private funnel for
  unhandled exceptions; re-check its signature on a Textual upgrade)
  captures, then delegates.
- Player child: the excepthook/threading integrations cover crashes;
  `Player._end` already logs failures at ERROR, which become breadcrumbs.
  The app sends the user-visible playback event (it knows the stage,
  retry outcome and account tier).

### IP addresses

The SDK sends no user or IP. A toggle switched off mid-playback applies to
the running player child at its next stop (it re-spawns with the new
setting).


Sentry sees the connecting IP at transport level and derives a geography
from it (seen on the first test event: "Frankfurt"). The SDK cannot hide
that. Maintainer action: Sentry > Project Settings > Security & Privacy >
**Prevent Storing of IP Addresses** = on.

## Acceptance

See Beads at-rl5. Proven end to end before release: a forced real playback
failure in the running app arrives in Sentry with release, OS, versions,
stage, libav reason, redacted URL and breadcrumbs, and without email, keys
or a user/IP context.

## Failure / rollback

Sentry unreachable: the SDK drops events in its background thread; the app
is unaffected (2 s shutdown drain). Rollback: set the default to False or
remove the dependency; unknown settings keys are ignored on load.

## Validation

`tests/test_telemetry.py` (recording transport, never the network):
scrubber contract on a synthetic event with every secret class; disabled
means no client; one event per final playback failure; free refusal not
reported; fingerprint stable across URLs; default True; debug.log level
unaffected; the player child inherits the decision. Manual: one real event per role to the project before tagging.
