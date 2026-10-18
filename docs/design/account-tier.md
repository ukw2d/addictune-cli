# Account tier in the UI

Status: approved. Beads: at-lx2.

## Problem

The app plays `premium_high` streams only. A free account logs in fine, lists
channels fine, and then every stream fails -- today with a 403 that reads like
a bug. Nothing in the UI tells the user which kind of account they signed in
with, and nothing in the app knows it either. Support cannot tell a free-tier
user from a broken network without asking.

Evidence: `/members/authenticate` and `/member_sessions` responses carry
`subscriptions[]` with `status`, `expires_on`, `plan.name`,
`plan.key`; the SDK's `AuthResponse` drops everything except `user_id`,
`api_key`, `listen_key` (`addictune_sdk/models/auth.py`). A free account has
no `active` subscription.

## Goal

The user can see at a glance whether the signed-in account is Premium or Free,
and a free account gets a clear message instead of a generic playback error.

## Non-goals

- Upselling, purchase links, trial handling.
- Playing free-tier (`public3`) streams. That is a separate decision: the free
  public streams exist (`listen.di.fm/public3/<key>.pls` resolves without a
  key) but carry ads and 64k AAC; whether the client should offer them is a
  product call, not part of this change.
- Showing billing details (price, renewal date).

## Design

### Data

| Datum | Purpose | Producer | Consumer | Lifecycle |
|---|---|---|---|---|
| `AccountTier` = `premium` / `free` | tell the user, and gate the free-tier message | derived once from the login response: any `subscriptions[]` entry with `status == "active"` and `expires_on` >= today => `premium` | Settings > General "Account" row; `PlaybackBar` free-tier notice | in-memory on `AddictuneApp`, replaced on every successful login; never persisted |

The SDK gains `AuthResponse.premium: bool` (or `subscriptions: list[Subscription]`
and a derived property), filled by the existing `_normalize` validator for
both auth endpoints. This is a change in `addictune-sdk` (sibling repo
`~/Development/addictune-sdk`), released as 0.4.2 and pinned here. The app
stores only the boolean on `app.account_tier`.

No new settings key: the tier is server truth and changes when the account
changes, so caching it would be wrong after a renewal or lapse.

### Where it shows

One place, Settings > General, as a read-only row, next to the new Sign out
button (see `sign-out.md`). Reasons for not putting it in About: About is the
app's identity, not the user's; and Settings is already where account actions
live after sign-out lands. Reasons for not putting it in the playback bar:
permanent chrome for a fact that changes once a year.

```
┌─ Settings ───────────────────────────────────────────────────────────────┐
│ ┌──────────────┐ ┌────────────────────────────────────────────────────┐  │
│ │ General      │ │                                                    │  │
│ │ Audio Output │ │  Startup Tab                                       │  │
│ │ Playback     │ │  ▾ Channels                                        │  │
│ │              │ │                                                    │  │
│ │              │ │  Account                                           │  │
│ │              │ │  user@example.com · DI.FM · Premium                │  │
│ │              │ │  [ Sign out ]                                      │  │
│ │              │ │                                                    │  │
│ │              │ │  Telemetry                                         │  │
│ │              │ │  [x] Send anonymous error reports (Sentry)         │  │
│ │              │ │                                                    │  │
│ └──────────────┘ └────────────────────────────────────────────────────┘  │
│  Esc Back                                                                │
└──────────────────────────────────────────────────────────────────────────┘
```

Free variant of the Account row:

```
│ │              │ │  Account                                           │  │
│ │              │ │  user@example.com · DI.FM · Free                   │  │
│ │              │ │  Premium streams need a subscription; see di.fm    │  │
│ │              │ │  [ Sign out ]                                      │  │
```

The email comes from the stored credentials (`auth.load_credentials()`); it
is already on disk and the user typed it, so showing it is not a new
disclosure. The network name comes from `STATION_NAMES[app.network]`.

### Free-tier playback message

When `app.account_tier == "free"` and a stream resolution or the player
child fails with an auth error (`HTTPForbiddenError`, `AddictuneAuthError`),
`PlaybackBar._notify_playback_failure` shows
`"This channel needs a Premium subscription (signed in as Free)"` instead of
the raw error. One string in `presentation.py`; one branch where
`_failure_detail` is formatted. Everything else stays as is -- the retry
policy already stops on fatal errors.

## Acceptance

- After login with a premium account, Settings > General shows `Premium`;
  with a free account, `Free` plus the one-line hint.
- A free account selecting a channel gets the Premium-needed toast, not
  `Playback failed: HTTPForbiddenError ...`.
- A premium account's behavior is unchanged (no new requests, no new state
  besides the boolean).
- `addictune-sdk` test covers both auth payload shapes with and without an
  active subscription.

## Failure / rollback

- Missing or unparsable `subscriptions` => `free` is NOT assumed; tier becomes
  `unknown` and the row shows nothing after the network name. Playback
  messaging falls back to today's behavior. Fail open, never block a paying
  user on a parsing bug.
- Rollback: revert the app commit; the SDK field is additive.

## Validation

- SDK: unit tests on `AuthResponse` with real (redacted) payloads.
- App: `tests/test_settings_screen.py` renders General with each tier;
  `tests/test_playback_failure_reporting.py` gets a free-tier case.
- `just check`.
