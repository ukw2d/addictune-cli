# 06 SDK (`~/Development/addictune-sdk`, PyPI `addictune-sdk`): REQUEST LIST for the separate SDK agent

**Status 2026-10-06: 0.4.1 released and installed.** R1 (public `login`/`set_session`/`has_session`, 422 raises `AddictuneAuthError`), R2 (`Client.with_listen_key(url)`), R3 (typed `Track` in `ShowEpisode.tracks`/`PlaylistTracks.tracks`), R4 (`Network.name` matches `STATION_NAMES`) are done; `playlists.add_listen_history` was removed. R6: `content_length` is now `float`; `offset` is still `int` (recheck when `07` starts). The CLI was made import-clean against 0.4.x in Beads `add-izv0` (minimal swaps; the real auth rewrite stays in `05b`). **D15 exception:** natural-end playlist telemetry (`playlists.add_listen_history`) was removed by the SDK and is no longer reported; skips still are. No visible effect in the CLI.

Owner decision D14: SDK changes are made by a **separate agent**; this repo's agents do not edit the SDK. This file is the list of what the CLI needs. The owner will announce the bumped version; CLI work that depends on it (auth, `stream_url` use, typed tracks) waits for that. CLI work that does not depend on it goes ahead.

Written against SDK HEAD `97adbb4` (matches installed 0.3.1), 3,416 production LOC, 4,099 test LOC.

## Priority for the CLI

| # | Request | Needed by | Blocking |
|---|---|---|---|
| R1 | Public `Client.login(network=...)`, `set_session(slug, key)`, `refresh_listen_key()`; typed error for 422-on-bad-login | `05` auth | yes |
| R2 | `Client.stream_url(...)` / track URL with the listen key appended (CLI currently does `url.replace("listen_key", ...)` in `handlers/playlists.py:25`) | `05`, `07` | yes for `07` if routine URLs need the key |
| R3 | Typed `Track`/`Artist` for `ShowEpisode.tracks`, `PlaylistTracks.tracks`, `MixShow.artists` (today `list[dict]`) | `03`, `07` | no |
| R4 | `Network.display_name` ("Rock Radio" vs "RockRadio") so the CLI deletes `STATION_NAMES` | `03` | no |
| R5 | Per-show follow lookup, if the SDK has none | `03` | decide while writing `03` |
| R6 | **From the `07` probe:** `RoutineTrack.offset` and `content_length` must be `float` (the API returns values like `445.54`; with `int` the whole `ChannelTracklist` fails validation intermittently). Possibly more after the website observation (skip/listen-event helper) | `07` | yes |
| R7 | ~~HTTP cache for `assets.get_bytes`~~ dropped: artwork option A chosen, caches stay in the CLI | n/a | no |
| R9 | `TrackHistoryEntry.track_id` is `None` for `currently_playing`, where the API nests the id as `track.id`; read it so channel badges carry the track id (`07b` probe) | `07b`/`04` | no |
| R8 | Optional feature-availability check so the CLI can hide tabs without probing three endpoints | `03` | no |

## Cleanup the SDK agent may do (owner's call, not required by the CLI)

The CLI does not use: the `AddictuneClient` alias, `config.py` (JSON I/O, env discovery; contradicts the SDK's own "no env vars" rule), `RetryConfig`, `CircuitConfig`, `load_config`, any `cache.*`, channels `add_listen_history`/`get_listen_history` pair (**exception: `07` may use `add_listen_history`**), `get_favorite`, playlists `get_featured`/`get_by_id`/`get_listen_history`, the tracks qualities trio, `api/user.py` + `models/user.py` (146 LOC). Internals noted in review: module-global ETag cache mutated in `Client.__init__`, a hand-rolled retry/breaker in `transport.py` that httpx `retries=` partly covers, stale README, `tests/integration/*` (about 1.1k LOC) not run by pytest, no versioning policy. These are suggestions only; the CLI pins whatever range the owner announces.

## What the CLI will do when the version arrives

1. Pin `addictune-sdk` to the announced range in `pyproject.toml`.
2. Replace private-attribute access in `tui/handlers/auth.py` (`05`, last epic).
3. Delete URL/listen-key and artwork-size helpers in the CLI that R2 and existing `ImageSet.url(size=)` cover.
4. Delete `STATION_NAMES` (R4).

## Original review notes (kept for the SDK agent)

Finding table and phase A/B details follow.

3,416 production LOC, 4,099 test LOC, HEAD `97adbb4` (matches the installed 0.3.1). Two phases: **A** additive and non-breaking, needed by `03` and `05`; **B** breaking cuts for a 0.4 release, only if the owner chooses.

## Job

Give the CLI a typed, public, async view of the AudioAddict API: networks, channels, shows, playlists, tracks, votes, follows, search, listen-history, stream URLs with the listen key.

## Today

| Finding | Where |
|---|---|
| The CLI pokes `Client` privates because there is no public per-network login or session setter. | CLI `tui/handlers/auth.py:26,31,61-63` |
| The CLI re-implements stream-URL and listen-key handling and artwork size bumping, though the SDK has `ImageSet.url(size=)` and `resolve_stream_url`. | CLI `playback_bar.py:67-84,487-501`, `handlers/playlists.py:25` |
| `list[dict]` payloads: `ShowEpisode.tracks`, `PlaylistTracks.tracks`, `MixShow.artists` are untyped. | `models/` |
| `config.py` (181 LOC) has JSON I/O and env discovery, contradicting the SDK's own "no env vars" rule in CONTRIBUTING.md. The CLI uses none of it. | `config.py` |
| The ETag cache (`cache.py`) is module-global SQLite state mutated in `Client.__init__`; an `index_list` layer has unclear use. | `cache.py` |
| `transport.py` is a hand-rolled retry/breaker that httpx `retries=` partly covers. | `transport.py` |
| `STATION_NAMES` in the CLI duplicates `BUILTIN_NETWORKS` (display names differ: "Rock Radio" vs "RockRadio"). | CLI, SDK |
| The README is stale; `tests/integration/*` (about 1.1k LOC) is not run by pytest; no versioning or deprecation policy (Beta, no git tags). | repo |
| Public but unused by the CLI: `AddictuneClient` alias, channels listen-history pair, `get_favorite`, playlists `get_featured`/`get_by_id`/`get_listen_history`, tracks qualities trio, `api/user.py` + `models/user.py` (146 LOC), `RetryConfig`, `CircuitConfig`, `load_config`, all `cache.*`. | SDK |

(Phase A/B plans, SDK tests and acceptance belong to the SDK agent and are not tracked here. The request table above replaces them.)
