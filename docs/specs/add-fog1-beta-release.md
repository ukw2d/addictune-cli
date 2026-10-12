# Public beta release preparation

Status: current
Task: add-fog1
Version: 0.2.0

## Evidence and purpose

The repository is private and has no GitHub Actions runs or releases as of
2026-10-12. Existing release documentation, artwork, credential-storage and About
changes are staged; recent reviewed UI/copy edits are unstaged. The current
package smoke test accepts exit code 1 and a timeout-killed process as success.
It also runs before final packaging. Build version overrides can disagree with
the installed distribution version used by About. Linux PortAudio is documented
only for source installs. The user requested sequential release preparation and
a clear beta notice.

The first native rebuild also exposed missing Nuitka metadata mapping in an
editable installation and a worker launch path that referenced a nonexistent
Python executable. Packaging now builds from a fresh isolated wheel installation;
compiled workers relaunch the native executable through `sys.argv[0]`.

## Scope and acceptance

- R1: Identify the project as beta near the top of the README.
- R2: Replace the permissive smoke test with a bounded, account-free check of
  packaged UI resources and the real audio worker, run outside the checkout.
  Crashes, timeouts and missing readiness must fail. No sound is played.
- R3: Reject build version overrides that disagree with project metadata before
  building; tag and manual workflow inputs use the same check.
- R4: Document Linux binary PortAudio requirements and install them in Linux CI.
- R5: Prepare draft prereleases with four platform assets and SHA-256 checksums.
  Published releases are not overwritten. Publication remains manual.
- R6: Integrate and independently review the complete final local release tree,
  including prior staged release changes and reviewed UI/copy edits.

Non-goals: PyPI publication, code signing/notarization, new services, repo
deletion, history rewriting, remote pushes, tags, GitHub workflow execution,
repo renaming/creation, visibility changes and release publication in this local
preparation task. External actions require approval against the final candidate.
Cross-platform installation, real account playback and OS media controls remain
external validation requirements, not claims of the automated check.

## Ownership and contracts

| Boundary | Owner | Contract |
|---|---|---|
| Diagnostic CLI | existing entry point | `--self-test` checks imports/UI/worker and exits without reading credentials |
| UI resources | Textual/Rich | mount sign-in and About with shipped CSS and distribution metadata in headless mode |
| Audio worker | existing worker dispatch and Pydantic protocol | request device list, receive a valid response, then quit normally |
| Timeout/process cleanup | Python subprocess | bounded execution; kill and reap on timeout; preserve actionable diagnostics |
| Packaging/version | tools/package.py | requested version equals pyproject version; verify final packaged payload |
| Release files | GitHub workflow | branch runs upload test artifacts; tags prepare a draft prerelease and checksums |

The self-test reuses existing UI widgets and worker messages. It introduces no
alternate application state, networking client, credential storage or audio
output. Temporary extraction/log files are consumed during validation and
deleted afterward; release assets/checksums are read by downloaders and replaced
only while the release is a draft. No dependency or abstraction is added.

## Failure and rollback

Failed validation blocks the local candidate; no GitHub action is performed.
Timeouts and nonzero exits are failures, not successful shutdowns. Keep the
current private repository/history intact. Revert only changes for this release
task to roll back locally. A published tag/assets are never silently replaced.

## Validation

Use focused failing regressions for smoke failures, worker readiness and version
agreement, then the affected tests and project `just check` gate. Verify an
account-free source self-test, wheel resources, README links and workflow syntax.
Build and extract the current macOS ARM64 package locally when practical. Require
one independent read-only review of the final staged/unstaged/untracked task
scope. All four GitHub builds and real platform installation/playback checks
remain pending until their required external actions are approved.
