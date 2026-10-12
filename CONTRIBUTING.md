# Contributing

Thanks for taking a look! Bug reports and focused pull requests are welcome.

## Setup

You need [uv](https://docs.astral.sh/uv/) and [just](https://just.systems/).

```sh
git clone https://github.com/ukw2d/addictune-cli
cd addictune-cli
uv sync --group dev
just run --dev
```

## Before opening a PR

```sh
just check      # ruff + the full test suite
```

- Keep changes small and focused; one behaviour change per PR.
- Add or update a test for behaviour changes (`tests/`).
- Don't commit credentials, tokens or logs. Redact them in bug reports too.

## Reporting bugs

Open an issue with the bug template. For playback problems, attach the log from `addictune --dev`; see [`docs/debugging-playback.md`](docs/debugging-playback.md) for where it lives. **Remove your email and any stream URLs containing keys first.**

## Scope

addictune is a terminal client for DI.FM and the other AudioAddict networks. Features that need a server component, other music services, or account management beyond signing in are out of scope.
