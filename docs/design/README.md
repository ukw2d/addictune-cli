# Design proposals

Each file is one feature: problem, goal, non-goals, design (data table with
purpose / consumer / lifecycle, wireframes), acceptance, failure/rollback and
validation. A proposal becomes a Beads epic once approved; the epic's
description links back here.

| Proposal | Status | Beads |
|---|---|---|
| [Account tier in the UI](account-tier.md) | implemented | `at-lx2` (children `at-b36` SDK, `at-i33` app) |
| [Sign out](sign-out.md) | implemented | `at-ouf` (after `at-lx2`) |
| [Error telemetry (Sentry)](telemetry-sentry.md) | implemented (on by default) | `at-rl5` |
| [Update notifications](auto-update.md) | implemented (notification only; install is Phase 2) | `at-0dk` |

Shipped without a proposal (hotfix): redaction of signed stream URLs and
libav failure reasons in playback errors -- see
[debugging-playback.md](../debugging-playback.md), Beads `at-9e9`, v0.2.1.
