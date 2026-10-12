# 03 App shell: REWRITE `app.py`, services, handlers, controllers, two screens

Depends on `07` (channels as tracklists) only in the future: `07` is deferred, so this epic ports the live/on-demand split, `ContentType.LIVE` handling and the `check_action` live branches unchanged, and `07` later deletes them. The queue is built so that `07` only adds a `RoutineSource` (D16).

Depends on the SDK bump (D14) only for auth; until then the shell keeps `handlers/auth.py` behind one function so the later swap touches one file.

Files: `tui/app.py` (935), `tui/services/{playback 715, bindings 177, search 248, follow 237, features 85, media_info 229, artwork 72, votes 53, auth 73}` (live_resolver, live_status, channels landed in `07b`), `tui/handlers/*` (images 167, live_shows 116, auth 88, channels 40, mixshows 37, playlists 31, votes 34), `tui/controllers/{following 472, image_loader 178}`, `tui/screens/{global_search 277, list_options 143, settings 177}`. About 5,300 LOC today, target about 2,000. The channels service and routine/status services belong to `04`; do not double count.

## Job

Own the app lifecycle: compose tabs, switch networks, hold the single `NowPlaying` value and the playback queue, decide which actions are available (`check_action`), and connect the SDK, the `Player` (`01`), the media session (`02`) and auth (`05`) to the widgets (`04`).

## Today

| Finding | Where |
|---|---|
| About 60 one-line forwarders in `app.py`; services forward again to `PlaybackBar`. Services hold `self.app` and reach into its privates. | `app.py:357-599,735-746` |
| `controllers/following.py` repeats one shape three times. The Playlists "Followed" filter is wired to nothing, although the SDK has `playlists.iter_followed(user_id, ...)` and `Playlist.following`. `RemoteListController.update_remote/apply_update` are empty. | `controllers/following.py` |
| `dataclasses.replace` on `TrackQueue` in 7 places. | `services/playback.py:339,359,383,655,673,679,715` |
| `model_copy` on settings at volume tick, plus a load before it. | `app.py:621`, `screens/settings.py:171`, `widgets/playback_bar.py:326` |
| `check_action` is an 80-line `match`. | `services/bindings.py` |
| `services/features.py` probes 3 endpoints on every network switch. | `services/features.py` |
| Dead code: `COMING_SOON`, `NetworkFeatures.none()` (one use), `_media_info_from_item` (tests only). | `app.py`, `services/features.py`, `services/media_info.py` |
| Favourite-tracks tab works and is kept (D15); listen history `add-frv`/`add-cav` is unbuilt and **not wanted now** (owner). | `widgets/track_list.py` |
| `screens/list_options.py` and `screens/global_search.py` carry their own filter and result plumbing. | 143 and 277 LOC |

## Target shape (about 2,000 LOC)

```
app.py                     ~250  compose, network switch, NowPlaying reactive, check_action, bindings
services/
  queue.py                 ~250  TrackQueue (immutable, new value per transition) + sources: PlaylistSource, EpisodeSource; one queue for every tab (D16)
  features.py              ~40   lazy: probe on first open of a tab, hide tab if empty
  follow.py                ~120  one follow/unfollow path through a ListFilter-aware helper; Playlists "Followed" via iter_followed
  votes.py, media_info.py, search.py  trimmed
controllers/
  following.py             ~150  ListFilter dataclass; three list kinds share it
  image_loader.py          trimmed per 04
screens/
  global_search.py         ~150
  list_options.py          ~70
  settings.py              trimmed to volume/theme/network
handlers/                  merged into services where they are a single call
```

Rules:

- `app.py` holds state and composes. It has no method whose body is one call to another object.
- `NowPlaying` (frozen dataclass: item, status, live show, position, state) is a Textual reactive on the app; widgets and the media session watch it. Defined here, rendered in `04`.
- `TrackQueue` is immutable; every transition builds a new value (no `replace`). It is the **one** player queue: playlists and mixshow episodes fill it today, channel routines (`07`) later. *Next* is the same operation for every source; *previous* is offered for every queue once it has moved past its first item (never for a live channel).
- `check_action` lives on the app and screens using Textual's hook; the footer reads it. No separate `bindings` service.
- One `Settings` instance in memory; saved debounced on change (see `05`).
- Services get what they need as constructor arguments (client, player, callbacks), never `self.app`.

### Suggested rebuild order inside the epic

1. Leaf modules and pure services (`queue`, `features`, `follow`, `votes`).
2. Image handlers and loader (with `04`'s decision on artwork).
3. New `app.py` with `check_action` and the `NowPlaying` reactive.
4. Screens.
5. Delete old code.

## Tests

| Action | Tests |
|---|---|
| KEEP | `test_live_resolver`, `test_live_show_statuses`, `test_routine_cache`, `test_image_cache`, `test_image_loader`, `test_command_palette`, `test_station_settings` |
| RETARGET | `test_auth_handler`, `test_mixshow_playback` |
| REWRITE | `test_follow_service`, `test_feature_availability`, `test_playback_service`, `test_playlist_playback`, `test_binding_availability`, `test_global_search`, `test_app_initialization` |
| DELETE | `test_following_controllers`, `test_dialog_layout`, `test_settings_layout`, `test_lazy_list_app`, `tests/support.py` |

## Acceptance

- `wc -l addictune_cli/src/tui/app.py` is at most about 300.
- `grep -rn "dataclasses import replace\|replace(queue\|model_copy" addictune_cli` is empty.
- `grep -rn "self\.app\._" addictune_cli/src/tui/services` is empty.
- `grep -rn "COMING_SOON\|NetworkFeatures.none" addictune_cli` is empty.
- Manual: switch networks, play channel/mixshow/playlist, next (all), previous (any queue), vote, follow, Playlists "Followed" filter shows followed playlists, search, settings; the footer only shows actions that work.

## Tasks

1. `TrackQueue` immutable and `services/queue.py` with tests (one queue for all tabs; shape must allow a refillable source per `07`).
2. `features.py` lazy.
3. `ListFilter` and `controllers/following.py`; Playlists "Followed" through `playlists.iter_followed`.
4. New `app.py` with `NowPlaying`, `check_action`.
5. Rewrite `global_search` and `list_options`; trim `settings` screen (needs `01` for audio rows).
6. Delete `handlers/*` folded into services, old bindings service, old tests.

## Open questions

All answered by the owner, 2026-10-06.

1. Listen history: not now. The Tracks tab keeps Liked tracks (default) and a History view that is a placeholder (see 05 doc, 2026-10-07).
2. Playlists "Followed" filter: **keep and make it work** via `iter_followed`.
3. Global search stays a screen: yes.
4. SDK per-show follow lookup available? If not, `06` adds it.
5. Lazy tab hiding instead of probing: yes.
6. Footer via Textual `check_action`: yes.
7. `TrackQueue` immutable, new value per transition, shared by all tabs: yes.
8. Previous track: any queue, never a live channel (corrected during 03; see Behaviour changes).

## Landed shape (2026-10-06)

```
tui/app.py                   772  (632 before ruff wrapped long lines) bindings (21), compose, on_mount/auth bootstrap, 14 @work shells (Textual needs a DOM node), 21 message handlers, 22 actions, check_action + the two footer hooks, tab availability/lazy loading, selection helpers
tui/services/
  queue.py                   139  TrackQueue value: playlist/mixshow/tracks constructors; next/previous/refill/repositioned/with_skip_used; current_track_id, has_more, has_previous, same_tracks
  features.py                 68  NetworkFeatures, NONE, FeatureCache (per-network, remembered for the session once a logged-in probe ran)
  playback.py                615  queue playback, live channel start, advance/skip policy; no dataclasses.replace
  channels.py, live_resolver.py, live_status.py   from 07b
  search.py 245, follow.py 237, media_info.py 229, votes.py 53, auth.py 73, artwork.py 72
tui/controllers/
  following.py               385  ListFilter (frozen: sorts, statuses, followed_label, followed_only, sort, status, search; option_groups/label/with_option/with_search) + FollowedController with three subclasses that only decide how a change is applied (in-memory channels vs API reload)
  playback.py 131, clock.py 86, image_loader.py 178
tui/screens/
  global_search.py           213  one submit path; apply_playing_highlight by kind map
  list_options.py 143, settings.py 171, auth.py 140, episodes.py 82, station_select.py 49, dialog.py 17
tui/handlers/                506  kept: pure SDK adapters (channels, mixshows, playlists, votes, live_shows, images, auth); none is a forwarder
```

Behaviour changes (recorded): (1) the login veto for a "Followed/Favorites" filter now applies to every tab, not only playlists: anonymous users get a "Log in to view …" notice instead of an empty channel list or a `ValueError` on mixshows. (2) `previous_track` works for every queue (playlist, mixshow episodes, tracks) and never for a live channel; the README's D16 wording was corrected to match (the earlier "playlists only" wording contradicted the existing mixshow/track behaviour). (3) Anonymous feature probes are not cached, so the Tracks tab appears after login without a restart (before, the anonymous result stuck for the session).

Kept against the spec's DELETE list: `tests/support.py` (the doubles still need the shared service surface) and `tests/test_lazy_list_app.py` (it tests behaviour, not layout). New `tests/test_app_surface.py` asserts every `app.<name>` used by the TUI exists on the real `AddictuneApp`, because the test doubles stand in for the app and had hidden two removed call sites (`play_episode` in the Episodes screen, `play_track` in the playback service), both fixed in review.

Deleted: `services/bindings.py` (`check_action`/footer hooks live on the app), the 60 one-line forwarders in `app.py` (tests that borrowed them now call the service directly), `_schedule`-style module-level lazy-tab helpers (now `_load_lazy_tab_if_needed` on the app), `TrackQueue` in `types.py`, `detect_network_features`/`NetworkFeatures.none`, the old `FollowedController` hook ladder (`_filter_choices`/`_apply_*`), `tests/test_dialog_layout`, `tests/test_settings_layout`; `test_following_controllers` rewritten around `ListFilter`; `test_queue` added (8).

Verified live (real account): channels Favorites + A-Z + Live-now + Popular filters with correct labels; **Playlists "Followed" returns the followed playlist** (`iter_followed`); Mixshows Followed; footer shows only valid actions per state (idle, live channel, mixshow playing/paused, modal open); `ctrl+f`/`ctrl+g` open the right screens; mixshow queue advances/pauses; 370 tests green, ruff clean.

Acceptance vs. spec: `dataclasses.replace|model_copy` in `addictune_cli` — only `media_info.py:146` and `media_list.py:46` remain (both are `04` widget-layer items: `ModelItem.set_followed` and the show status overlay). `self.app._` in services: 20 reads of app state dicts (`_channels`, `_live_by_channel`, `_statuses_by_*`, `_playing_channel_id`, `_followed_controllers`), to be folded into `ChannelLive`/`NowPlaying` in `04`. `app.py` is 772 formatted LOC (632 unwrapped) against the ~300 estimate: 300 of it is Textual plumbing that cannot move (bindings, `@work` shells, message dispatch, actions); the estimate did not count those.

Not built on purpose: the `NowPlaying` frozen reactive. With `07b` the live path still writes the bar's reactives directly (`apply_live`, `apply_track`), and `04` is where the bar and expanded player are rebuilt around one value; introducing it here would have meant touching every widget twice.

Also fixed on the way: `Player` kept only the newest decode thread, so an old thread from a rapid play/play could outlive `close()` (flaky `test_play_while_playing_retires...`); it now joins every live thread.
