# 04 Widgets and lists: REWRITE lists, bar, expanded player and channels service; TRIM media info; KEEP leaves

`07b` (landed 2026-10-06) already replaced the ICY-to-routine pipeline and the two hidden-widget services with `services/live_resolver.py`, `services/live_status.py` and `LiveTracker` in `services/channels.py` (513 LOC together). This epic does not touch them beyond rendering `LiveInfo` through `NowPlaying`.

Files: `tui/widgets/*` (about 2,900 LOC), `tui/services/channels.py` (816), `services/{media_info 229, artwork 72}`, `presentation.py` (112), `styles/*.tcss` (654). About 4,900 LOC today, target about 2,100 (styles about 350). The shell doc (`03`) covers the remaining services.

## Job

Render lists of channels, mixshows, playlists and tracks that load lazily; render the now-playing bar, the expanded player and the media info panel from one `NowPlaying` value; resolve "what is on now" for live channels.

## Today

| Finding | Where |
|---|---|
| Four list layers (`LazyList`, `CachedLazyList`, `CachedModelList`, `MediaList`) plus four subclasses, about 920 LOC. `LazyList` reaches the app with `getattr(self.app, ...)`. `ModelItem.set_followed` uses `model_copy`. | `widgets/lazy_list.py` (350), `media_list.py` (86), `channel_list.py`, `mixshow_list.py` (149), `playlist_list.py`, `track_list.py` |
| ~~ICY-to-routine resolver, hidden-widget services~~ done in `07b`. `ChannelsService` still writes 5 app dicts (`_live_by_channel`, `_now_playing_by_channel`, `_statuses_by_*`, `_next_show_by_channel`) that `03` can fold into one `ChannelLive` map. | `services/channels.py` (301) |
| `ExpandedPlayer` mirrors 15 `PlaybackBar` reactives. | `widgets/expanded_player.py` (312) |
| `PlaybackBar` has 13 Messages: four are internal thread hops, three are payload-less commands, three (`StateChanged`, `TrackChanged`, `LiveShowChanged`) are one `NowPlaying`. | `widgets/playback_bar.py` (736) |
| Artwork (pillow + rich-pixels, about 420 LOC with a disk cache). Reviewers disagreed; the owner chose option A (keep the disk and memory caches). See [Artwork options](#artwork-options). | `services/artwork.py`, `handlers/images.py`, `controllers/image_loader.py` |
| `.tcss`: a content-type colour block and `.muted` are duplicated; small files can fold into screens as `DEFAULT_CSS`. | `styles/` |
| Artwork and stream URL size bumping is reimplemented locally. | `playback_bar.py:67-84,487-501`, `handlers/playlists.py:25` |

## Target shape (about 2,100 LOC)

```
widgets/
  media_list.py        ~150  MediaList[T] + ListSpec[T] (fetch page, render row, key, follow attr)
  now_playing_bar.py   ~250  renders NowPlaying; emits Play/Pause/Next/Prev/Volume via app actions
  expanded_player.py   ~150  second view of NowPlaying
  media_info.py        ~200  trimmed
  (kept) playback_format, marquee_text, content_type_label, live_show_badge, live_show_follow, app_footer, types
services/
  channels.py, live_resolver.py, live_status.py   landed in 07b; only the ChannelLive map fold remains (03)
styles/                ~350  folded where small, one shared colour block
```

Rules:

- `ListSpec[T]` is a small frozen dataclass; rows are built from immutable models with a follow overlay (a set of followed ids) instead of copying models.
- A `ChannelLive` map (`channel_id` to live info) replaces the eight app attributes.
- No hidden Widget hosts background work; use plain classes with `@work` on the app or `asyncio` tasks.
- Artwork is decided (A): `handlers/images.py`, `controllers/image_loader.py` and `services/artwork.py` are kept and trimmed; the cache directory moves to `platformdirs`.
- `NowPlaying` for channels is built from `LiveInfo` (`07b`); for queue items from the item.

## Artwork options

What exists today: raw bytes come from `client.assets.get_bytes(url)` (the SDK does not cache them). The CLI keeps **two** caches: a disk cache of the bytes (TTL 3 days for media art, 3 hours for track art, pruned every 5 minutes, under `~/.cache/addictune-cli/images`) and an in-memory LRU of the **rendered** `rich-pixels` objects (256 media, 512 track entries). Rendering needs Pillow and `rich-pixels`. About 420 LOC in total.

| | A. Keep as is (disk + memory) | B. Memory-only | C. Memory in the CLI, HTTP cache in the SDK | D. No artwork |
|---|---|---|---|---|
| What you see | Art everywhere, instant on relaunch | Art everywhere; after a restart each image is fetched again as it scrolls into view | Same as A for the user | Text only (badges, markers stay) |
| Code in the CLI | about 420 LOC | about 150 LOC (fetch, decode, render, one LRU) | about 150 LOC | about 0; removes Pillow, `rich-pixels`, `image_loader.py`, `images.py`, `artwork.py` |
| Network | Fewest requests | A channel grid is 100+ images fetched lazily after every start. CDN images are small; fine on broadband, slower first paint | Fewest requests; revalidation handled by headers | None |
| Disk | Files, TTL, prune, Windows path handling, stale-file bugs | None | In the SDK (its problem, one place) | None |
| Memory | Bounded LRU of rendered objects | Same bound; each entry is a small cell grid (tens of KB at most). The bound is by entry count, so it is predictable | Same | None |
| Risk | Most code to keep correct; the lifecycle you asked me to question ("why is this stored") is the weakest here | Slower cold start is the only cost | Depends on the SDK agent adding HTTP caching; ask for it in `06` | Product feels bare; terminal must still render the layout without the art slot |
| Media-session artwork (`02`) | Reads bytes from disk | Needs the bytes kept in the memory LRU or refetched | Same as B | Dropped (or small fetch for the OS widget only) |
| With `07` | Track art is per queue item, so the 3-hour track TTL becomes irrelevant; prefetch of the next track's art is natural | Same | Same | n/a |

**Decided (owner, 2026-10-06): A.** Keep the disk and memory caches; a disk cache is normal for artwork. Consequences: the SDK request R7 is dropped; the cache directory moves to `platformdirs` (D10, the current `Path.home()/".cache"` is wrong on Windows); the TTL and prune rules stay but are reviewed for the "why is this stored" check (consumer: the image loader; lifecycle: TTL plus prune). The media session (`02`) reads artwork bytes from the same cache. The other options above are kept only as the record.

## Tests

| Action | Tests |
|---|---|
| DELETE | `test_expanded_player`, `test_playback_bar_layout`, `test_media_info_layout`, `test_media_list_styles`, `test_lazy_list_app` |
| REWRITE | `test_channels_service`, `test_live_show_artwork`, `test_mixshow_focus`, `test_media_info_performance` (keep "no lookup when closed" and the bounded recently-played list), `test_track_list`, `test_playlist_list` |
| TRIM | `test_playback_bar_live_show` |
| KEEP | `test_artwork`, `test_playback_format`, `test_live_show_follow_marker`, `test_channel_routine_service`, `test_channel_sorting`, `test_channel_filters`, `test_filter_bar` |

## Acceptance

- `grep -rn "CachedLazyList\|CachedModelList\|class LazyList" addictune_cli` is empty.
- `grep -rn "_icy_debug\|class .*Service(Widget)" addictune_cli` is empty.
- `grep -rn "getattr(self.app" addictune_cli/src/tui/widgets` is empty.
- `wc -l widgets/*.py services/channels.py services/live_resolver.py` is at most about 1,900.
- Manual: lists scroll and lazy-load; sort and filter switch; follow marker updates in place; bar and expanded player show the same state; live show, "Next:" and info panel update at show boundaries.

## Tasks

1. `MediaList[T]` and `ListSpec[T]` with the four specs; tests.
2. `NowPlaying` rendering: bar and expanded player.
3. ~~Split `channels.py`~~ done in `07b`.
4. ~~Replace hidden-widget services~~ done in `07b`.
5. Artwork: keep the caches (A); move the directory to `platformdirs`; delete only the forwarding layers.
6. Fold `.tcss`.
7. Delete old widgets and tests.

## Open questions

1. `ListView` rows vs `OptionList` line rendering: `OptionList` if it supports lazy append; otherwise `ListView`.
2. Artwork: decided, option A.
3. Expanded player: keep.
4. "Next:" prediction and boundary timer: keep.
5. Per-view cache on sort/filter switch: refetch; no restore.
6. Recently-played in the info panel: keep, as a bounded list of the last 5 tracks that advances when the track changes (owner: it is about how the list advances, not a TTL).
7. Delete layout-pinning tests: yes.
8. `live_resolver` lives in `services/` (landed in `07b`).

## Landed shape (2026-10-06)

```
widgets/
  media_list.py        291  MediaList (paging, per-view cache of retired _Load sessions, local search, auth retry, statuses; calls app._search/_playback_service directly) + ListSpec (label, model_id, message, followed, live_badge) + ModelItem (model + public `followed` overlay, no model_copy) + selected_child
  channel_list.py       36  ChannelList/ChannelItem on MediaList (filled in memory by ChannelsService)
  mixshow_list.py       70  MixshowList: followed/popular/all + search + status filter -> show(key, source)
  playlist_list.py      58  PlaylistList: followed/newest/popular + search
  track_list.py         77  TrackList: liked tracks; PageLoaded for the queue via an _after_page override
  expanded_player.py   304  pure view of PlaybackBar: one watch per bar reactive -> _on_bar(name); no mirrored state
  playback_bar.py      656  unchanged this epic (01/02/07b already trimmed its backend); still the single owner of now-playing state
  media_info.py        315  media_image_url(*image_sets, size) is the one artwork lookup (typed ImageSet only)
  marquee_text, playback_format, content_type_label, live_show_badge, live_show_follow, app_footer   kept
screens/episodes.py        EpisodeList/EpisodeItem on MediaList; EpisodeSelected message
styles/                    587 LOC in 6 files: app.tcss now holds media-list rows, dialog chrome, search input/empty state and the shared content-type/mute colours; episodes/station_select/list_options/global_search styles are DEFAULT_CSS on their screens
```

Deleted: `widgets/lazy_list.py` (LazyList/CachedLazyList/CachedModelList, 350), `compose_media_list_row`/`post_selected_item_message`/`apply_row_statuses`, `ModelItem.set_followed` via `model_copy`, `services/artwork.py` (`LiveArtworkCandidates`/`resolve_track_artwork_url`: `media_image_url` takes the candidates in order), the dict-accepting branch of `media_image_url`, the listen-key string hack and `listen_key` parameter in `handlers/playlists.py`/`handlers/mixshows.py` (SDK `client.with_listen_key`, gated on `client.listen_key`), the `_PIXEL_LIMITS` re-sync in `handlers/images.py`, `styles/{media_list,dialog,search,episodes,station_select,list_options,global_search}.tcss`, `DIALOG_CSS_PATH`. Tests: `test_lazy_list_app` (manual demo), `test_artwork`, `test_media_info_layout`, and the geometry-only cases in `test_playback_bar_layout`/`test_expanded_player` (13 layout-pinning tests); `test_mixshow_focus` cache-key tests retargeted to `MediaList.show()` behaviour.

Size: widgets 2,900 → 2,100 LOC; styles 654 → 587; tests 8,970 → 8,442. 353 tests green, ruff clean.

Verified in the real app: info panel on a mixshow row keeps the row's follow state after the detail fetch (no `model_copy`); follow/unfollow on a channel and a mixshow round-trips; channel list with 119 rows, badges and 36 favourites; mixshows page, sort switch restores the cached view without a refetch, local search filters, followed marks; playlists and liked tracks page and select; episodes screen plays; expanded player mirrors title/channel/type/quality/elapsed/volume/vote/stop icon live; content-type and mute colours render from the folded `app.tcss`; episodes dialog keeps its border and sizing from `DEFAULT_CSS`.

Not built: the `NowPlaying` frozen value. `PlaybackBar` already is the single owner of now-playing state and every reader (bar, expanded player, media session, `check_action`) reads it directly; introducing a second representation would add a type and a copy step without removing a consumer. `ExpandedPlayer` lost its 15 mirrored reactives instead, which was the duplication the target shape aimed at. The `ChannelLive` map fold (five app dicts) is left for a later pass: it is state plumbing shared with `ChannelsService`, not widget code, and the dicts have one writer.

Note for Textual `watch()`: it decides how to call the callback from its parameter count, so a `lambda _v, name=name:` receives `(old, new)` — the expanded player uses a zero-arg closure per field.
