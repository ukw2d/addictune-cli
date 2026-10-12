# 05 Auth, settings and packaging: REWRITE auth and packaging, TRIM settings, KEEP logging and main

Files: `auth/keyring_store.py` (228), `auth/__init__.py` (21), `tui/handlers/auth.py` (88), `tui/services/auth.py` (73), `tui/screens/auth.py` (144), `settings.py` (45), `logging_setup.py` (95), `main.py` (42), `subprocess_worker.py` (30), `__main__.py` (15), `tools/{macos,linux,windows}_pkg.py`, `tools/release.py`, `.github` workflow. About 700 production LOC plus about 900 LOC of tools; target about 350 plus about 200 plus a `justfile`.

## Job

Log in once per machine, restore the session on launch, persist the few user preferences (volume, theme, last network), and ship a working build on the owner's machine (macOS first).

## Today

| Finding | Where |
|---|---|
| The CLI mutates SDK privates: `client._session_keys`, `_credentials`, `_listen_key`. | `tui/handlers/auth.py:26,31,61-63` |
| `keyring_store.py` has legacy migrations and a dead `load_listen_key`. `auth/__init__.py` is dead. `keyring` returns None on macOS by design. | `auth/` |
| `email-validator` is used only in the login form. Direct `httpx` dependency is never imported. `secretstorage` is transitive via keyring. | `screens/auth.py`, `pyproject.toml` |
| `save_settings(model_copy(...))` runs on every volume tick, with a load before it. | `widgets/playback_bar.py:326`, `app.py:621`, `screens/settings.py:171` |
| Volume default `0.3` is duplicated. | `settings.py`, `audio/config.py` |
| Four config/cache locations under two names (`addictune`, `addictune-cli`). | `settings.py`, `keyring_store.py`, image cache, logs |
| `logging_setup._ROOTS` lists `audio`; must match new logger names. | `logging_setup.py` |
| `subprocess_worker.py` and `__main__.py` exist solely for the Nuitka re-exec of child processes. | 45 LOC |
| `tools/{macos,linux,windows}_pkg.py` are about 60% copy-paste; `release.py` is a pure forwarder; dev-install logic uses sudo. | `tools/` |
| `nuitka-crash-report.xml` is stale, untracked and gitignored. **Never read it; it blew a sub-agent's context.** Delete locally. | repo root |

## Target shape

```
auth.py          ~70   Credentials record; ensure_session(client, network); keyring load/save
settings.py      ~60   Settings (volume, theme, network); one in-memory instance; debounced save
logging_setup.py KEEP
main.py          KEEP
tools/package.py ~200  one script, per-OS branches
justfile               test, lint, package, install
```

- Settings keep the three audio fields from `01` (`audio_device_name`, `audio_sample_rate`, `audio_latency`); `audio_dtype` is removed.
- `ensure_session(client, network)` uses only public SDK calls (`06`: `login(network=)`, `set_session`). The per-network session key is stored only if the SDK cannot re-create it cheaply (question 2).
- `Settings` is created once at startup and passed by reference; `save()` is debounced (for example 500 ms) so volume ticks do not write files. No `model_copy`: mutate through a small `set(name, value)` that builds the next frozen value once, or hold a mutable model owned by one place.
- Paths come from `platformdirs` with one app name (D10). Existing files at old locations are not migrated except credentials, if the owner wants (question 7).
- Delete: `email-validator`, direct `httpx`, `secretstorage`, legacy keyring migrations, `load_listen_key`, `auth/__init__.py`. `subprocess_worker.py` and `__main__.py` **stay** (shrunk) because the audio child remains (`01`); they only lose the media-host dispatch (`02`).
- `screens/auth.py` stays; drop `_EmailValidator` (a non-empty check is enough, the server validates).

### Auth waits for the SDK bump (D14)

The auth rewrite (`auth.py`, `ensure_session`) is blocked by the SDK agent's release of the public login and session API (see `06`). Until the owner reports the bumped version, this epic does only **settings, paths, dependency cleanup and packaging**; `tui/handlers/auth.py` stays as it is behind the shell's seam. The auth task is then picked up as its own last epic.

### Windows gaps (D13)

| Area | Gap | Action |
|---|---|---|
| Config and credential paths | `platformdirs` gives `%APPDATA%`/`%LOCALAPPDATA%`; old code builds some paths with `Path.home() / ".cache"` (`handlers/images.py`), wrong on Windows. | All paths through `platformdirs` (D10). |
| Keyring | Windows Credential Locker has a ~2.5 KB value limit; a JSON blob with several network keys can exceed it. | Store one small item per network or credentials only (question 2 default). |
| Packaging | `windows_pkg.py` output is a zip; CI has a `windows-latest` job that runs the suite. Nuitka on Windows needs MSVC or MinGW. | Keep the Windows CI job; Nuitka build for Windows stays (owner) and is verified in the Windows manual pass. |
| Child process | stdin-EOF orphan safety works on Windows; signals do not. | Covered by `01`. |
| Terminal | Windows Terminal needed for true colour and Textual mouse; legacy conhost degrades. | Note in README of the app, no code. |

### Packaging

- Nuitka builds for **all three platforms** (owner): macOS `.pkg` (the `.app` bundle gives Now Playing a bundle identifier), Linux and Windows standalone archives.
- One `tools/package.py` with `macos`, `linux`, `windows` branches and shared helpers; `release.py` and the three per-OS scripts are deleted. The CI workflow is pointed at the new script.
- `uv tool install addictune-cli` (from PyPI or a git URL) is an equally supported install path on every platform; it does not replace the Nuitka artifacts.
- `justfile` recipes: `test`, `lint`, `package`, `install` (`uv tool install --editable .`, no sudo into `/usr/local`; question 6).
- Remove `smoke_test_media_host` (see `02`).

## Tests

| Action | Tests |
|---|---|
| TRIM | keyring tests (drop migrations and `load_listen_key`) |
| REWRITE | auth-handler tests against the public SDK (`ensure_session`) |
| KEEP | `test_auth_error_banner` |
| ADD | settings debounce writes once for many `set` calls; stale keys ignored on load |

## Acceptance

- `grep -rn "\._session_keys\|\._credentials\|\._listen_key" addictune_cli` is empty.
- `grep -n "email-validator\|secretstorage\|^ *\"httpx" pyproject.toml` has no direct entries (unless the owner keeps httpx for a reason).
- `grep -rn "model_copy" addictune_cli/src/settings.py addictune_cli/src/tui` is empty.
- `ls tools` shows `package.py` only; `justfile` exists.
- Manual: fresh config dir, log in, relaunch, session restored; wrong password shows the banner; `just package` builds the macOS `.pkg`; the app shows Now Playing when launched from it.

## Tasks

1. Settings: single instance, debounced save (after `01`, which decides the audio keys).
2. Paths via `platformdirs`; update logging.
3. Remove unused dependencies.
4. `tools/package.py` and `justfile`; update the CI workflow; add a Windows manual pass.
5. Spike: can a runtime-set `CFBundleIdentifier` make Now Playing work without Nuitka? (shared with `02`)
6. **Blocked until the SDK bump:** `auth.py` on the new SDK API; delete the private-attribute access.

## Open questions

1. Drop `keyring` and use a 0600 file on all platforms? **No** (owner): keep keyring; no second store.
2. Persist per-network session keys, or credentials only? Default: credentials only; `ensure_session` logs in per network on demand.
3. Move 422-on-bad-login handling into the SDK? Default: yes (`06`).
4. Packaging: **Nuitka for all three platforms** plus `uv tool install` (owner). Not "PyPI only" for Linux/Windows.
5. Bundle-identifier spike: Now Playing works without Nuitka (02 spike); Nuitka stays for all three artifacts regardless.
6. `just install` uses `uv tool install --editable . --force`: done.
7. Migrate credentials from the old location: **no** (owner); re-login once.

## 05a Landed shape (2026-10-06, settings, paths, dependencies, packaging)

```
settings.py       98   Settings (pydantic): volume, audio_device_name, audio_sample_rate, audio_latency, default_tab, station_selected, station_slug; Settings.load(path) once at startup (app.settings); set(**values) validates the whole batch first (a bad value applies nothing), applies in place, debounces one write (0.5 s); flush() on unmount; STATION_NAMES
paths.py          20   platformdirs under one app name: CONFIG_DIR/CACHE_DIR, SETTINGS_FILE, SESSION_FILE, IMAGE_CACHE_DIR, LOG_FILE. No legacy migration (owner): one re-login after upgrade.
tools/package.py 226   one script: Nuitka build (per-OS flags table), smoke test, macOS .pkg (bundle id set on the staged .app, non-relocatable), Linux .tar.gz, Windows .zip
justfile          30   default (list), lint, test, check, run, install (uv tool install --editable), package, clean
```

Deleted: `load_settings`/`save_settings` and the three `model_copy` save sites (bar volume, settings screen, station select), `AppSettings`, the four hard-coded `~/.config`/`~/.cache` paths, `tools/{macos,linux,windows}_pkg.py` and `tools/release.py` (794 LOC), the old 3-recipe justfile, `email-validator` (replaced by a local `local@domain.tld` check; the server validates) and the never-imported direct `httpx` dependency. `secretstorage` stays: keyring's SecretService backend needs it on Linux. `platformdirs` promoted to a direct dependency.

Tests: `test_settings` (6: debounce writes once, no-op does not write, flush, no-loop immediate write, invalid batch/unknown key applies nothing, stale keys/corrupt/unreadable file), `test_station_settings` trimmed to app-level cases; `test_app_initialization`/`test_settings_layout` patched to `Settings.load`.

Validation: 367 tests green, ruff clean, `just --list` parses. `uv run python tools/package.py --assume-downloads` on macOS built the `.app`, passed the smoke test and produced `addictune-cli-0.2.0-macos-arm64.pkg` (59 MiB) with `CFBundleIdentifier=com.addictune.cli` and the `/usr/local/bin` symlink; the staged binary started with a throwaway HOME and showed the sign-in screen. Linux and Windows builds run in CI only (the Linux dist dir is now `__main__.dist` since `--python-flag=-m` was dropped; unverified off-macOS); the Linux and Windows manual passes (D13) are still owed and tracked with 05b. `PlaybackBar` requires a `Settings`; tests use `support.temp_settings()` so no test writes the user's config.

Task 5 (bundle identifier without Nuitka): answered by the 02 spike. Now Playing registered and showed the title from a plain `uv run` (main bundle `org.python.python`), so no runtime `CFBundleIdentifier` is needed for function; the Nuitka `.app` only improves the name shown by the OS. Nuitka stays for all three platforms per the owner.

## 05b Landed shape (2026-10-07, auth on the public SDK API)

```
auth.py              128  login(client, email, password, network) -> user_id (stores credentials only after the server accepts); sign_in(client, network) -> user_id | None (silent login from the stored record; clears it on a rejection, keeps it on a transient error); is_auth_failure; load_credentials/clear_credentials; keyring (Linux/Windows) or 0600 file (macOS) behind _load/_store
tui/services/auth.py  37  AuthRecoveryService: ensure_authenticated_session (has session and user id -> done, else recover_auth) and recover_auth (sign_in or prompt)
tui/screens/auth.py  122  AuthScreen -> ModalScreen[int | None]: dismisses with the user id, so the app no longer re-reads a store
```

**Decision: only the email and password are persisted.** A probe against the live API showed that logging in again returns the identical session key, listen key and user id, and that an older key stays valid after fresh logins, so a cached session key, listen key or user id has no reader that could not be served by one login (about 0.6 to 0.9 s). The record is `{"email", "password"}`; a file left by an earlier build keeps working because it carries the same two keys (its extra keys are ignored and dropped on the next login that rewrites it). Startup therefore shows the channel list after one silent login; a second network costs one more login on first use.

`sign_in` raises on anything but a rejection (503, dropped connection): `recover_auth` then notifies and returns False **without** prompting, so a flaky server on launch leaves the app open with an empty list and the record intact (the old cached session behaved the same way). The hand-written `STATION_NAMES` table was replaced with the SDK's `BUILTIN_NETWORKS` as a deliberate extra (D9). The login form now rejects an empty email as well as an empty password locally.

Deleted: `auth/keyring_store.py` (225) and `auth/__init__.py` (21) with the per-network session record, the legacy `session_key` field, the file-to-keyring migration and `load_listen_key`; `tui/handlers/auth.py` (81: `restore_sessions`, `has_session`, the `_AUTH_FAIL_STATUS` set, `ensure_session_from_keyring`); the client rebuild and `set_session` restore in `on_mount` (the app builds one `Client()` in `__init__`); `_EmailValidator` (the server validates); the hand-written `STATION_NAMES` table (now `{n.slug: n.name for n in BUILTIN_NETWORKS}`); the direct `secretstorage` dependency (keyring requires it on Linux itself; `tools/package.py` still includes it in the Nuitka build). `is_auth_failure` is now `AddictuneAuthError` (401/403/422 in SDK 0.4) or HTTP 419.

Tests: `test_keyring_store` (24) and `test_auth_handler` (3) replaced by `test_auth` (13: file and keyring stores, 0600, locked keyring, corrupt record, login stores only on acceptance, sign_in success/rejected/transient, failure classification, backend selection); `test_app_initialization` rewritten for the new seams (startup with/without credentials, sign-in before prompt, existing session, recover_auth); `test_playback_bar_key_recovery` fixtures use `AddictuneAuthError` as the SDK raises it. Later in the epic: the transient-failure cases for `sign_in` and `recover_auth`, the empty-email banner, and the `AuthScreen` dismissal / `_on_auth` contract (355 tests after review).

Verified against the real API: relaunch with a stored record signs in silently and loads 119 channels; switching to `rockradio` signs in once more and loads 48; a dead session key is replaced by `recover_auth`. In a throwaway HOME: the sign-in prompt appears, a wrong password shows the banner and stores nothing, the right one loads 119 channels and writes a 0600 file, and a relaunch skips the prompt. 350 tests green, ruff check clean. Acceptance greps empty (`\._session_keys`, `\._credentials`, `\._listen_key`, `load_listen_key`). Linux and Windows keyring backends are untested (D13).

## Aggregate review (2026-10-07, final gate)

Scope `43d58fc..71f3e1b` (whole rewrite, 58 commits). Verdict after one fix round: **APPROVE**. Fixed from the first round: `previous_track` was footer-disabled for mixshow and track queues although the action worked (D16); one surviving `dataclasses.replace` in `services/media_info.py` (D8); a `getattr(widget, "loaded")` probe left from `LazyList`; three service forwarders and three one-line SDK wrappers; bead ids and "extracted from Mixin" history in docstrings; the shared `addictune_cli.icy` logger name; stale `07` wording; README status, size table (before / target / landed) and decision states; `docs/debugging-playback.md` log roles. Judged and kept: the favourite-tracks tab (pre-rewrite, D15; only *listen history* was declined) and the bar's `_hires_artwork_url` regex (threading `ImageSet` through four producers for a 512 px media-widget URL was not worth ~8 files). Cleanliness sweep: empty `tui/mixins`, `tui/loaders`, four empty `__init__.py`, dead `COMING_SOON`, untracked probe files removed; a vulture/AST pass found only framework hooks.

357 tests green, ruff check clean, `uv build --wheel` complete, live API checks (silent login, network switch, dead-key recovery) pass. Still owed: Linux and Windows manual passes (D13).

### Tracks tab: Liked tracks + History placeholder (owner, 2026-10-07)

A first trim removed the favourite-tracks tab and left a History placeholder tab; the owner wanted Liked tracks kept, and the three commits were reverted. Landed instead: the Tracks tab is a regular tab on the shared machinery. `TracksController` (`services/following.py`) gives it the same `^F` options menu as the other tabs with one **View** group (`Liked tracks`, default; `History`) and no Followed filter (`ListFilter.followed_label=None`, `sort_title="View"`). The History view resets the list and `SearchService.active_empty_message` shows "Listening history is coming soon" in the empty-results line; the filter bar reads "View: History". `TrackList.load` takes the same keywords as the other lists so `RemoteListController.load` drives it, and the tracks branch in the lazy-tab loader is gone. The pending next-page queue moved from `app._pending_track_next_queue` to `PlaybackService._pending_track_next` (its only reader).

Also fixed: `get_track_playback_info` applied `with_listen_key` to every track URL, but the API returns signed URLs (`audio_token`/`auth`), which answer 403 once a parameter is added, so playlist, episode and liked-track playback all failed (regression from `04`, probed against the live API). The key is now added only to a bare `listen_key` placeholder.

Live check: 40 liked tracks by default; `^F` shows View; History shows the placeholder and hides the list; switching back reloads; a playlist, the latest mixshow episode and a liked track each reach PLAYING. 360 tests, ruff clean.

