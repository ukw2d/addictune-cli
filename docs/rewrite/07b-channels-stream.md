# 07b Channels stay streams: TRIM the ICY-to-routine matcher, KEEP the stream

Status: **landed 2026-10-06 on branch `07b-channels-stream`** (see Landed shape). Replaces `07`. Owner decision: channels keep playing the m3u/ICY live stream. Playing channels as per-track files (the website's way, `07`) would tie playback to the account's server-side "current track" and interfere with listening on several devices at once; the stream is also what any ordinary audio player gets, so staying on it keeps the CLI a plain client. `07` is withdrawn; its probe results stay in `07-channels-as-tracklists.md` for reference.

Branch: `07b-channels-stream` off `develop`. Epic: new; blocks `03` and `04`.

## Job

Play a channel's live stream, show what is playing now (from the in-band ICY title, which is the only timely signal), and enrich it with the track id, length, position and artwork from the channel routine so that voting, the elapsed counter and the artwork work. Show the airing live show and the next one from the show schedule. Everything else about channels (list, favorites, filters) is untouched.

## Probe (2026-10-06, `di`/`trance`, 4 minutes)

| Question | Result |
|---|---|
| Can `currently_playing` replace ICY as the "now" signal? | **No.** It changed 76 s after the ICY title did. The CLI already polls it every 60 s for the channel-list badges; it is fine for badges, not for the bar. |
| Does `currently_playing` carry the track id? | The API does (`track.id`), the SDK's `TrackHistoryEntry` reads `track_id` and gets `None`. SDK request **R9**. Not needed if the routine stays the id source. |
| Does the routine have what the bar needs? | Yes: `id`, `display_artist`, `display_title`, `length`, `content.offset` (only on the current track), `images`, `votes`. Titles match the ICY `Artist - Title` after `normalize_title`. |
| Is `track_history` useful? | It is the recently-played list the info panel shows; keep that use. |

Conclusion: the shape stays **ICY title drives, routine enriches, schedule overlays**. What goes is the machinery around it, not the idea.

## Today (about 1,330 LOC across five files)

| Finding | Where |
|---|---|
| `ChannelsService` is 814 LOC; about 520 is the reconcile pipeline: three stages, four `_IcySource` dataclasses, an ICY-override map keyed by `(network, channel_id)`, a boundary timer, a "promote next episode" path, and `_icy_debug` logging on every branch. | `services/channels.py:77-108, 286-620` |
| Three flags thread through the pipeline (`seed_new_track`, `seed_offset`, `refresh_on_miss`) and decide how the clock moves. They exist because the same function is called from five places with different intent. | `_reconcile_icy` callers |
| `ChannelRoutineService` and `MediaStatusService` are hidden `Widget`s used as services (`display: none`) so they can own `@work` and timers. | `widgets/channel_routine_service.py` (130), `widgets/media_status_service.py` (106) |
| `ChannelLiveState` resolves precedence between the schedule, `currently_playing` and the ICY override. The override exists so a live show whose tracklist does not match the ICY title is treated as not live. | `services/live_state.py` (84) |
| Routine fetch is cached by `expires_on` with a 60 s floor (`RoutineCache`, 43). Good, keep. | `routine_cache.py` |
| `PlaybackBar` exposes four clock entry points for this code: `set_live_position`, `start_new_track`, `set_track_duration`, `apply_track`. | `widgets/playback_bar.py` |
| Tests pin the pipeline: `test_channels_service` (633), `test_live_media_resume_metadata` (294), `test_live_show_artwork` (346), `test_playback_bar_live_show` (210). | `tests/` |

## Target shape (about 450 LOC)

```
services/
  live_resolver.py   ~200  LiveResolver: holds routine + schedule for the playing channel; resolve(icy_title) -> LiveInfo
  channels.py        ~130  channel list, favorites, sort/filter only
  live_state.py      KEEP  ChannelLiveState (drop icy_override_episode_id if the override goes; see question 1)
routine_cache.py     KEEP
widgets/
  media_status_service.py  -> plain class on the app with one asyncio task (60 s / next boundary); no Widget
  channel_routine_service.py  DELETE (folded into LiveResolver)
```

```python
@dataclass(frozen=True, slots=True)
class LiveInfo:
    title: str                      # ICY title, verbatim
    track_id: int | None
    length: int | None
    offset: int | None              # routine offset, only when the ICY title is the routine's current track
    image_url: str | None
    show_id: int | None
    show_name: str
    next_show: str                  # "" or "Next: X"

class LiveResolver:
    def __init__(self, client, network, channel_id, *, schedule: ChannelLiveState) -> None
    async def start(self) -> None          # fetch routine (cached), nothing else
    def resolve(self, icy_title: str | None) -> LiveInfo
    async def refresh(self) -> None        # routine miss -> refetch once, then resolve again
    def stop(self) -> None
```

Rules:

- One function, `resolve(icy_title)`, returns one frozen value. The bar applies the value; the resolver never touches the bar. This removes the three flags: the caller knows whether the title changed (new track: restart clock at `offset` or 0) or not (resync: only update duration).
- Precedence inside `resolve`: scheduled live show whose tracklist contains the title, or any scheduled live show if the title matches nothing in the routine; else routine track; else title only. "Next: X" comes from the schedule when the next show starts before the current one ends. This is the current behaviour minus the override map (question 1).
- The boundary timer becomes one `asyncio` sleep until the next show start/end inside `MediaStatusService` (already computes `_next_refresh_delay`); the resolver is rebuilt from the refreshed schedule. No second timer.
- `_icy_debug` goes; one `log.debug` per resolve with the outcome.
- ICY source in `stream.py` stays as is. The `title` event on the player protocol stays.
- Clock entry points on the bar collapse to two: `apply_live(info, *, new_track: bool)` and the existing `apply_track`.

## What `03`/`04` inherit

- `03` ports the queue for playlists/mixshows only; channels stay the `ContentType.LIVE` path with `LiveResolver`. The live-retry branch of `PlaybackController` stays.
- `04` builds `NowPlaying` from `LiveInfo` for channels and from the queue item for the rest. The ICY matcher no longer needs porting.
- `README` §2 row "Channels as tracklists removes about 900" becomes "07b removes about 880 (1,330 to 450)".

## Tests

| Action | Tests |
|---|---|
| REWRITE | `test_channels_service` into `test_live_resolver` (pure: scripted routine + schedule + title sequence -> `LiveInfo`), keep the list/favorites cases |
| TRIM | `test_live_media_resume_metadata`, `test_live_show_artwork`, `test_playback_bar_live_show` to the bar's two entry points |
| KEEP | `test_routine_cache`, `test_live_state`, `test_audio_stream` ICY cases |

## Acceptance

- `grep -rn "_icy_debug\|_IcySource\|_icy_live_overrides\|seed_new_track\|refresh_on_miss\|class .*Service(.*Widget)" addictune_cli` is empty.
- `wc -l services/channels.py services/live_resolver.py services/live_status.py` is at most about 550 (the list/statuses half of `channels.py`, about 160 LOC, was not in the original 350 estimate).
- Manual, one hour on `di/trance` and one show-boundary on a channel with a scheduled show: title follows ICY within a second; vote works on every matched track; elapsed starts at the routine offset on first play and at 0 on each new track; artwork follows; the live-show badge and "Next:" appear and clear at the boundary; a routine miss refetches once and does not restart the clock.

## Tasks

1. Observe one show boundary with the current code and record the exact sequence (ICY title vs schedule) so `resolve` precedence is settled by evidence, not by the old code.
2. `LiveResolver` + `LiveInfo` with tests.
3. `MediaStatusService` as a plain class with one task; delete `ChannelRoutineService`.
4. Switch `services/playback.py` and the bar to `LiveResolver`; collapse the clock entry points.
5. Delete the pipeline, `_icy_debug`, override map, boundary timer; retarget tests.
6. Landed shape, review, owner buy-in.

## Open questions (proposed default first)

1. **ICY override map**: today a non-matching ICY title during a scheduled show hides the show (treated as "not actually live"). Keep that rule inside `resolve` (default), or trust the schedule and always show the live show? Default: keep, but as one `if`, not a map.
2. **"Promote next episode"** when the next show has already started but the schedule poll has not caught up: keep (default, it is three lines in `resolve`) or rely on the boundary refresh?
3. SDK **R9**: `TrackHistoryEntry.id` from `track.id`, so `currently_playing` carries the track id for the channel-list badges. Not blocking.
4. Routine refetch on miss: once per title (default) or never (wait for `expires_on`)?

## Probe, task 1 (2026-10-06, `di/progressive`, 12:51–14:12 UTC)

- `get_routine(..., tune_in=False)` returns a routine **without** the current track and without `offset`; `tune_in=True` returns the current track first with its `offset`. The CLI keeps `tune_in=True`.
- The routine rolls over roughly every track: a new ICY title missed the cached routine (`MISS`) and the next fetch had it as track 0 with `offset` ≈ seconds since the ICY change (59 s after a 60 s poll gap). So "refetch once on an unknown title" is the right rule (open question 4: once).
- `currently_playing` lagged the ICY title by 14–76 s. Fine for badges, not for the bar.
- Show boundary at 14:00 UTC ("Days Like Nights", `di/progressive`), as recorded:
  - 14:00:02 schedule flips to LIVE_NOW (poll fired at the boundary). ICY still carries the previous routine track (`Ranj Kaler`) and the routine still matches it with its offset, so the bar keeps showing the track; the show appears on the list badges only.
  - 14:00:07 to 14:05:40 the server flaps: `currently_playing` says show, then a routine track (`Daniel Testas`, with routine offset 68), then show again, then `Ursarix` (routine), then show again. The ICY title changes only once in that window (14:05:40 to the show's title). So the stream played ordinary routine tracks for about five minutes **inside** the scheduled show slot.
  - Rule confirmed by this: *the ICY title is the truth; the schedule is an overlay.* A routine match in the ICY title must demote the show (the owner would otherwise see "Days Like Nights" with a 60-minute clock while a 7-minute track plays), and a title in the show's tracklist must keep the show even though the routine also lists it. Both are in `LiveResolver.resolve` and `test_live_resolver`.
  - `currently_playing` is **not** a usable "now" source even at boundaries: it changed 5 times while ICY changed once.

Open questions settled: 1 keep the override rule as one branch in `resolve` (routine match beats a scheduled show); 2 keep promote-next (three lines); 3 R9 recorded in `06`; 4 refetch once per title.

## Landed shape (2026-10-06)

```
services/
  live_resolver.py   119  LiveInfo (frozen); LiveResolver(routine, live_episode, next_episode, channel_images).resolve(icy_title)
  live_status.py      85  LiveStatuses; LiveStatusPoller: one worker + one timer (60 s or next show start/end)
  channels.py        301  ChannelsService: watch_network, load_channels_body, render, statuses, _on_statuses; LiveTracker: start/stop/title_changed/resync, cached routine fetch, refetch-once on miss, applies LiveInfo to the bar
widgets/playback_bar.py  apply_live(info, *, new_track, seed_offset) replaces set_live_position/start_new_track; set_track_duration kept for on-demand info
```

Deleted: `widgets/channel_routine_service.py`, `widgets/media_status_service.py`, `services/live_state.py` (`ChannelLiveState`, override map), the 3-stage `_reconcile_icy` pipeline, four `_IcySource` dataclasses, the boundary timer, `_icy_debug`, `app.start_channel_routine/sync_playing_channel_details/_rebuild_channel_statuses` forwarders and the two message handlers. Tests: `test_channels_service` cut to list/statuses (2), new `test_live_resolver` (13, pure), `test_live_show_statuses` (3, schedule selection), `test_live_media_resume_metadata` rewritten against `LiveTracker` (7); deleted `test_channel_routine_service`, `test_live_state`, the artwork half of `test_live_show_artwork`.

Size: 1,330 → 513 LOC (`channels.py` 301 of which about 160 is the untouched list/statuses half; `live_resolver.py` 127; `live_status.py` 85). Acceptance greps empty. 353 tests green, ruff clean.

Behaviour kept: ICY title verbatim, routine match attaches track id/length/artwork, counter starts at the routine offset on the first match and at 0 on each new title, resync never moves the counter, routine miss refetches once, scheduled show overlays id/clock/artwork, a plain routine track in the ICY title demotes a stale show, next show already started is promoted before the poll catches up. Verified in the real app: `di/trance` matched within 1 s of play with offset 152/491 and artwork; statuses for 101 channels and 2 live shows, 2 badges visible.

Behaviour added (owner request after test): "Next: X" is shown whenever the next show is UPCOMING in the list's sense (starts within the 1-hour window), also while regular tracks play; during a live show it is additionally shown for a back-to-back show that starts before the current one ends. Verified live: `di/trance` with the UPCOMING badge showed "Next: Ronski Speed Sessions".

Behaviour changed (accepted): (1) list badges and the LIVE_NOW status filter no longer hide a scheduled show that the playing channel's ICY title has demoted; only the bar follows the ICY evidence. The old override map did this for one channel at a time and was the main source of complexity. (2) The local boundary timer is gone; at a show boundary the poller fires at the boundary time (its delay is computed from the schedule), so the switch happens on the next poll instead of a second local timer. Worst case is one poll interval if the schedule changed since.
