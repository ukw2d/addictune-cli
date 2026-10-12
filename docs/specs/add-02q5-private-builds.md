# Private beta build validation

Status: current
Task: add-02q5

## Evidence and scope

The user approved renaming the current private repository to
`addictune-cli-private`, creating an independent private `addictune-cli`, pushing
a clean `main`, and running four native builds within the included allowance.
The existing `main` must first contain the latest `develop` code. Both local
branches were advanced to reviewed candidate `775197c` before validation began.

Review of the full outgoing `main` range reproduced five stale-work races and
identified a Unix permission assertion that blocks Windows CI. Resolve those
findings before any remote push. Keep the existing architecture and libraries.
Do not publish, change visibility, tag, delete history, force-push or enable
paid usage in this phase.

## Requirements and ownership

| ID | Owner | Contract and acceptance |
|---|---|---|
| R1 | Player | A superseded stream open closes its own stream without replacing the current output. |
| R2 | PlaybackBar | A retired retry cannot start a resolver or cancel the current selection's resolver. |
| R3 | PlayerClient and PlaybackBar | Selecting new playback retires old events immediately; queued events are checked when delivered to the UI. |
| R4 | LiveTracker | Changing channels permits the new routine fetch; completion of an old fetch cannot clear the current fetch's state. |
| R5 | MediaList | A page finishing during local search retains its models without appending unfiltered rows. Keep paging paused while restoring search results and preserve earlier models before late arrivals. |
| R6 | Credential tests | Round-trip assertions run on every platform; Unix mode assertions apply only where supported. |
| R7 | Native Git/GitHub workflow | Original remote main contains current code before rename; the new main has no old ancestry and matches the final reviewed tree. |
| R8 | Release workflow | All four platform jobs pass tests, package their payloads, and pass extracted-payload diagnostics. Record artifact hashes and remaining manual playback checks. |
| R9 | Image executor | Apply Unix scheduling priority only where supported; Windows image decoding must retain a usable executor. |
| R10 | Platform tests | Read Python sources as UTF-8, access D-Bus properties through their actual descriptors, and wait for worker/render completion before asserting UI state. |

No new persisted state, protocol or dependency is needed. Reuse existing session
ownership, generation checks and list/fetch state; retain the last submitted play
generation to identify a child-process loss after playback has been retired.
New repository Git history
is independent; old history remains accessible only through the private archive
and original local checkout. Build artifacts are temporary validation outputs,
downloaded for verification rather than published releases.

## Failure and rollback

Failed tests or review block pushes. Material fixes require fresh validation and
review. Keep both repositories private, preserve the original checkout/history,
and stop or cancel builds before approaching the included allowance. Do not
change billing settings. A failed platform build is evidence to fix and rerun,
not permission to skip its diagnostic. Roll back only this task's code if needed;
never overwrite a published release.

## Validation

Use deterministic, account-free regressions for each stale-work race and the
smallest affected tests. Run the full project checks after the batch stabilizes.
Review the complete outgoing archive range and new snapshot. Verify tree identity,
single-root ancestry, noreply author/committer, clean state, exact destinations
and private visibility before pushes. Inspect actual Actions job results and
downloaded artifacts, check hashes, and run the macOS ARM64 payload locally.
Real account playback and OS media controls remain manual platform checks.
