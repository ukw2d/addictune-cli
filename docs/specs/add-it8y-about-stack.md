# add-it8y — About dependency strip

## Goal and evidence

Replace the About screen's hardcoded four-library credit with a restrained moving strip of direct runtime dependencies. `about.py` already uses installed distribution metadata for its version; `tools/package.py` includes `addictune-cli` distribution metadata in Nuitka artifacts.

## Scope and contract

- Keep the existing logo, version, links, disclaimer, and Escape dismissal.
- Stationary “Built with” label above a muted single-line ticker; advance one terminal cell every 250 ms, wrapping continuously.
- Read `Requires-Dist` via `importlib.metadata`; parse names and platform markers with `packaging.Requirement`. Display canonical package names, not a separate curated branding table.
- Include direct runtime requirements applicable to the running platform, not development tools or transitive dependencies. Declare `packaging` directly because production now imports it.
- No runtime TOML access, network requests, generated dependency manifest, persisted state, or new settings.
- With Textual animations disabled, show the full wrapped list and do not start decorative timers. Only move the ticker while About is current; Textual owns timer cleanup on dismissal.

## Non-goals

No About redesign, dependency links, package version inventory, build-tool credits, or new animation framework.

## Failure and rollback

Use existing installed-metadata ownership (already required for the version); missing requirements produce empty credits, not invented names. Standard requirement parsing owns marker evaluation. Roll back the About, test, and dependency changes together.

## Acceptance and validation

Focused tests cover metadata-driven names, applicable markers, exclusion of inactive extras/platforms, timer-driven motion, seamless wrap, static rendering when animation is disabled, resize, and dismissal. Run About tests during development, then repository lint/format checks and full pytest once stable. Inspect a wheel's metadata and run UI self-test; a new Nuitka build is not required for this UI-only change but frozen validation remains limited to the established metadata inclusion contract.
