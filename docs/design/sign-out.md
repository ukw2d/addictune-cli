# Sign out

Status: implemented. Beads: at-ouf.

**Implemented as** (deviations from the text below):
- Beyond the listed resets, the stream URL is forgotten
  (`PlaybackController.forget`): it carries the listen key, so Space would
  otherwise resume the signed-out account's stream.
- `ConfirmScreen` opens with **Cancel** focused (Enter backs out); Esc and a
  click outside answer no.
- If a copy of the login cannot be removed (`clear_credentials()` returns False: locked keychain, read-only config dir), the notice says so
  and tells the user to delete it by hand; a wrongly "signed out" state would
  silently log the old account back in on the next launch.
- Workers of the old account (default group, `features`, `live-status`) are
  cancelled before the session is torn down, the old client is closed last,
  and open modals are dismissed (not popped) so Settings still applies a
  changed audio device.
- The palette entry shows while a session *or* a stored login exists, so an
  offline start can still remove the login.
- The per-network reset was split out of `ChannelsService.watch_network` as
  `reset_views()` and reused.
- Tests: `tests/test_sign_out.py` (each reset is individually mutation-checked).

## Problem

There is no way to leave an account inside the app. The README tells the user
to delete a Keychain / Secret Service / Credential Manager item by hand and to
remove `session.json`. That is unacceptable for switching between a premium
and a free account (the maintainer needs this today to reproduce the Reddit
report), for shared machines, and for the "my token leaked, start over" case
the first bug report created.

What exists: `auth.clear_credentials()` already removes both the keyring
record and the legacy file; `AuthScreen` is already pushed by
`app._prompt_login()`; `AuthRecoveryService` already routes every expired
session through the same prompt. Sign out is wiring, not new machinery.

## Goal

One action that forgets the stored credentials, drops the in-memory session,
stops playback, and lands the user on the login screen -- in the running app,
without a restart.

## Non-goals

- Server-side session revocation (the API offers none that the SDK exposes;
  listen keys are rotated on the website).
- Multi-account switching with remembered accounts.
- Clearing settings, image cache, or the log. Those are not account data.

## Design

### Entry points

1. Command palette entry `Sign out` (primary), placed directly above `Quit`
   in `COMMAND_PALETTE_ORDER` -- the two account/session-ending actions sit
   together at the bottom, both behind a confirmation.
2. Settings > General > Account > `[ Sign out ]` button, same callback, so the
   action is also where the account is shown (see `account-tier.md`).

No key binding: it is a rare, destructive-ish action and the footer is full.

### Flow

```
Command palette (^p)                        Confirm (modal)
┌────────────────────────────────┐          ┌───────────────────────────────┐
│ > ▏                            │          │  Sign out of DI.FM?           │
│   Choose radio station         │          │                               │
│   Settings                     │          │  Your saved login is removed  │
│   …                            │          │  from this computer and the   │
│   About                        │   ──▶    │  login screen opens.          │
│ ▸ Sign out  ◀── Enter          │          │                               │
│   Quit                         │          │     [ Cancel ]  [ Sign out ]  │
└────────────────────────────────┘          └───────────────────────────────┘
                                                          │
                                                          ▼
                                   AuthScreen (existing) with a one-line notice
                                   ┌───────────────────────────────────────┐
                                   │            addictune                  │
                                   │   DI.FM in your terminal              │
                                   │                                       │
                                   │   Signed out.                         │
                                   │                                       │
                                   │   Email                               │
                                   │   [                                 ] │
                                   │   Password                            │
                                   │   [                                 ] │
                                   │            [ Log in ]                 │
                                   │   Esc quits                           │
                                   └───────────────────────────────────────┘
```

`app.action_sign_out()`:

1. `push_screen(ConfirmScreen(...))`; on cancel, nothing happens.
2. `PlaybackBar.stop()` -- the player child keeps running (device handle), the
   stream ends.
3. `auth.clear_credentials()`.
4. `app.client` is replaced with a fresh `Client()` (the SDK keeps
   `_credentials`, `_session_keys` and `_listen_key` privately with no public
   reset; constructing a new client is the documented way to drop them and
   costs nothing). `app.user_id = None`, `app.account_tier = None`, followed
   channels / favorites caches cleared through the existing services' reset
   paths (`FollowService`, `VoteService`, `FeatureCache`).
5. Pop every modal (`app.pop_screen()` until the base screen), then
   `app._prompt_login()`. `AuthScreen` gets an optional `notice` argument to
   render "Signed out." in its existing `#auth-error` slot (neutral style).
6. Login success runs the existing `_on_auth` path: channels reload, station
   prompt if needed. Dismissing the prompt exits the app, as today.

### Confirm dialog

`ConfirmScreen(title, body, confirm_label) -> bool` under `screens/dialog.py`
next to `DialogScreen`. Textual has no stock confirm modal; the project
already has the modal CSS and `DialogScreen` click-out semantics, so this is
~40 lines. It will be reused by telemetry (no) and by any future destructive
action; it is justified by this feature alone.

### Data

| Datum | Purpose | Consumer | Lifecycle |
|---|---|---|---|
| none new | | | credentials record deleted; in-memory session dropped |

README "Accounts and privacy" paragraph changes from the manual deletion
recipe to "Settings > Sign out".

## Acceptance

- Sign out from the palette or Settings, confirm: playback stops, the login
  screen appears with "Signed out.", `load_credentials()` returns `None`, and
  the OS credential store no longer has the `addictune-cli` item.
- `Sign out` appears in the palette discovery list directly above `Quit`.
- Logging in again with a different account shows that account's tier and
  favorites; nothing from the previous account remains (follows, likes,
  liked-tracks tab).
- Cancel leaves everything untouched.
- Dismissing the login screen after sign out exits the app cleanly.

## Failure / rollback

- Keyring deletion failure is already logged and swallowed by
  `clear_credentials`; the in-app sign out still proceeds (session dropped),
  and the notice says "Signed out. Could not remove the saved login from the
  system keychain." so the user can act.
- Rollback: revert; no persisted format changes.

## Validation

- `tests/test_auth.py`: unchanged API, so the existing clear tests stand.
- New `tests/test_sign_out.py`: drives `action_sign_out` on the app double
  from `tests/support.py`, asserts the five effects above with the fake
  backend from `test_auth.py`.
- `just check`.
