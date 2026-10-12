# 07 Channels as tracklists: NEW, dedicated branch, dedicated epic

Status: **WITHDRAWN 2026-10-06 (owner).** Per-track playback would tie the CLI to the account's server-side current track and interfere with multi-device listening; channels stay a stream. See [`07b-channels-stream.md`](07b-channels-stream.md). The probe results below are kept for reference.

Original status: probe passed (2026-10-06). Owner decision 2026-10-06: the website plays channels the way it plays playlists (per-track files from the routine, skippable). The CLI should do the same. This removes live streams, ICY, and the ICY-to-routine matcher from the product.

Branch: a dedicated branch off `develop`, created when the epic starts. Epic `add-3uw`: created, parked; it is blocked on the `01`–`05` epics and on SDK R6. Its first task closes the two server-side items at the end of Probe results before building.

## Job

Play a channel as an ordered list of track files taken from the channel routine, starting at the track the station is on now (`offset`), advancing on track end, skipping on demand, refreshing the routine before it expires, and reporting listen and skip events the way the website does. Channel and playlist playback share one queue model.

## Why

| Today | After |
|---|---|
| Live stream URL + `listen_key`, decoded as an endless stream | Per-track asset URLs from `RoutineTrack.assets`, played like playlist tracks |
| `_IcyAudioSource` (about 150 LOC) parses in-band `StreamTitle` | Not needed: the routine says what is playing |
| ICY-to-routine matcher in `services/channels.py` (about 520 LOC, four source dataclasses, boundary timer, `_icy_debug`) | Not needed: track id, artwork, votes come from the queue item |
| Live-only retry/backoff policy in `PlaybackController` | One on-demand policy for everything |
| `ChannelRoutineService` polls for "now" and "Next:" | Queue position is "now"; the next item is "Next:" |
| Channels and playlists are two code paths in `services/playback.py` | One `TrackQueue` with a `source` that knows how to refill (playlist page, routine refresh) |

Estimated deletion: about 900 LOC across audio, services and widgets, on top of the trims already scoped in `01` and `04`.

## What the SDK already gives (verified in the installed 0.3.1)

- `channels.get_routine(channel_id, audio_token, tune_in=True) -> ChannelTracklist{routine_id, channel_id, expires_on, tracks: list[RoutineTrack]}`.
- `RoutineTrack(Track)`: `id, title, display_artist, length, artists, votes, images, assets, offset, content_length, is_current`. `Track._hoist_content` lifts `content.assets[0]` to the top level, so `url` is available if the payload has assets.
- `tracks.skip_track(track_id, channel_id=, skipped_at=, length=)`.
- `channels.add_listen_history(channel_id, track_id)`.
- `channels.get_track_history(channel_id)` for recently played.

## Probe (must run before design is final)

Run against at least five channels across three networks (for example DI `vocaltrance`, `chillout`; RadioTunes `smoothjazz`; RockRadio `classicrock`; ZenRadio `sleep`), as a throwaway `uv run python` script, no code committed. Record answers in this doc under **Probe results**.

1. Do routine tracks carry a playable `url` in `assets`? Does it need `listen_key`, and does `tracks.get_by_id` return the same URL (so no second request is needed)?
2. How many tracks per routine, and how far ahead does `expires_on` sit? Does calling `get_routine` again before expiry return the same routine id?
3. Where is `audio_token` taken from (channel payload? listen key?) and does `tune_in=True` have visible effects (listen history, "now playing" on the site)?
4. Is `offset` accurate enough to seek the current track and stay roughly in sync with the stream? Does PyAV seek on these files (CDN range support)?
5. Is skipping limited (count per hour, premium-only)? What does the site send: `skip_events` only, or also `listen_history`?
6. Does the routine include tracks already played (`offset` only on one item) and are upcoming items stable or reshuffled on refresh?
7. Mixes/shows inside a channel schedule: do routines contain show assets (`is_show_asset`) and are they playable the same way?
8. Rate limits or errors on frequent `get_routine` calls.

If the probe shows that routine tracks are not playable files (question 1 fails), the decision reverts: keep streams, and `01`'s ICY question becomes "keep".

## Probe results (2026-10-06, SDK 0.3.1, logged-in account, 6 channels on 5 networks; no keys or URLs recorded)

Channels: DI `vocaltrance` and `chillout`; RadioTunes, RockRadio, ZenRadio and JazzRadio (one channel each). Three more runs on DI `vocaltrance` tested refresh behaviour.

**Verdict: D12 is feasible. Routine tracks are plain playable files.**

| # | Question | Result |
|---|---|---|
| 1 | Playable URL? | Yes, on every channel: `RoutineTrack.url` on `content.audioaddict.com`, `audio/mpeg`, mp3 44.1 kHz, `HEAD` 200, `Accept-Ranges: bytes`, `Range` request 206, PyAV opens it. |
| 1b | Needs `listen_key`? | **No.** The URL has no `listen_key` placeholder; it is pre-signed (`auth`, `exp`, `member_id`, `routine_id`, `channel_id`, ...). The `url.replace("listen_key", ...)` step in `handlers/playlists.py` is not needed for routine tracks. `exp` is an ISO timestamp about 24 h ahead, equal to the routine's `expires_on`. |
| 1c | Same URL as `tracks.get_by_id`? | Same path, **different query**: `get_by_id` lacks `routine_id` and `channel_id` and may add `fallback`. Use the routine URL; `get_by_id` is not needed for channel tracks (one request less per track). |
| 2 | Tracks per routine, expiry | 5 tracks per fetch, lengths 2 to 30 minutes. `expires_on` about 24 h ahead. |
| 3 | `audio_token` source | `Client.listen_key` works (as in today's `channel_routine_service.py`). |
| 4 | `offset` accuracy, seek | With `tune_in=True` the first item is the current track and `offset` is seconds into it (31, 36, 42 on fetches 5 s apart: it advances in real time). PyAV seek to 274 s in a 445 s file landed at 274.0 s in about 0.85 s over HTTP; open about 0.6 s. Meets the "about 2 s" target. |
| 6 | Shape of the routine | **Not a stable schedule.** `tune_in=True`: item 0 is the current track (same id, growing offset); items 1 to 4 are **re-drawn on every fetch** (zero overlap). `tune_in=False`: no current item and 5 items re-drawn each time, no sliding-window pattern. `routine_id` is constant. |
| 7 | Shows/mixes | `is_show_asset` was 0 everywhere sampled. Mix-flagged and 30-minute items have the same asset shape. Show-asset routines were not seen: untested. |
| 8 | Rate limits | 10 rapid `get_routine` calls: all 200. |

SDK finding for `06` (R6): **`RoutineTrack.offset` and `content_length` can be floats** (for example `445.54`). With `offset: int` the whole `ChannelTracklist` fails validation (seen once in about 12 fetches). Needs `float`. **Blocking for `07`.**

Consequences for the design:

- Upcoming items are random per fetch, so "Next:" exists only once a batch is fetched. Rule: when a track starts, fetch one batch (`tune_in=False`), **hold it**, show its first item as "Next:" and play exactly that item. Never refetch to refresh the upcoming list.
- Expiry (24 h) is handled by re-tuning when the held routine is past `expires_on`.
- Channel tracks need no `get_by_id` and no key rewriting; a queue item is a `Track` with `url`.

**Not determinable from the probe; task 1 of the epic closes these** by watching the website on one channel for about 15 minutes (browser network panel):

1. Does the server move "current" on by itself when the track ends, or only when the client reports `listen_history` or a skip? This decides what to call at track end and whether a fresh `tune_in=True` after a pause resumes mid-way through the next track.
2. Skip limits and which calls the site makes on skip and on track end. Not tested, to keep the account's history clean.

## Target shape (design draft, finalised after the probe)

```
services/
  queue.py          TrackQueue(items, index, source) ; source: PlaylistSource | RoutineSource | EpisodeSource
  routine.py        RoutineSource: fetch(channel) -> items starting at is_current, with start_offset; refresh when
                    the queue has fewer than N items or expires_on is near; report listen/skip
```

- Channel play: `get_routine(tune_in=True)`, build queue from the current item (seek to `offset`), play. When a track starts, fetch one more batch (`tune_in=False`) and hold it; on track end advance into the held batch; on manual next call `skip_track` and advance. Never merge batches: upcoming items are re-drawn on every fetch (see Probe results).
- `NowPlaying` for a channel is the current queue item plus the channel's live show (unchanged from `get_currently_playing`/shows), so the live show badge still works.
- Votes and artwork read from the queue item; no track id matching.
- Deleted: `get_stream_url` usage, `ContentType.LIVE` split in the controller, `_IcyAudioSource`, the matcher half of `services/channels.py`, `ChannelRoutineService`, `MediaStatusService`'s stream path, `debugging-playback.md` live sections.

## Interaction with other epics

- Runs **first** if the probe passes, because it decides what `01`, `03` and `04` must not build (live retry, ICY, matcher). While it runs, `01` can still be scoped but not started. If the owner prefers audio first, `01` keeps ICY untouched and `07` deletes it later; the cost is touching `stream.py` twice.
- `06` (SDK, external agent): ask for `Network`-aware `routine` typing already present; if the probe reveals gaps (for example `audio_token` source), they go on the SDK request list.

## Acceptance

- `grep -rn "get_stream_url\|IcyAudio\|_icy_debug\|StreamTitle" addictune_cli` is empty.
- Playing a channel starts within about 2 s at roughly the same track and position as the website.
- Next skips to the next routine track and the site's listen history reflects it.
- Leaving a channel playing for one hour never stalls: routine refresh happens before expiry.
- Votes, artwork and the live show badge work during channel playback.

## Tasks

1. Done: probe and **Probe results**. Remaining: website observation (how "current" advances, skip events and limits); owner approves the design. SDK R6 (float `offset`) must be released first.
2. `RoutineSource` + queue integration with tests (fixtures from the probe).
3. Channel play path switched; listen and skip events.
4. Delete streams, ICY, matcher, routine service; retarget tests.
5. Manual validation on all three networks.

## Open questions

0. Probe passed. Remaining server-side questions are task 1 (how "current" advances, skip limits and events).
1. Order: **after `01`–`05`** (owner, second round). Skip/advance works like playlists; the site allows skipping channel tracks.
2. Start at `offset` (in sync with the station) or at the start of the current track? Default: at offset.
3. Keep `get_currently_playing` polling for the live show badge only? Default: yes.
4. Previous-track for channels: **disabled** (owner: previous exists only in playlists, D16).
