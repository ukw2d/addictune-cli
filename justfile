set shell := ["bash", "-euo", "pipefail", "-c"]
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

default:
    @just --list

# Lint with ruff (check + format check)
lint:
    uv run ruff check .
    uv run ruff format --check addictune_cli/src/audio addictune_cli/src/media addictune_cli/src/settings.py addictune_cli/src/paths.py tools

# Run the test suite; extra args go to pytest
test *args:
    uv run pytest {{ args }}

# Full gate: lint then tests
check: lint test

# Run the app from source (pass --dev for debug logging)
run *args:
    uv run addictune {{ args }}

# Install the app for this user with uv (editable, from this checkout)
install:
    uv tool install --editable . --force

# Build the Nuitka standalone binary and package it for this OS (build/artifacts)
package *args:
    uv run python tools/package.py --assume-downloads {{ args }}

# Record the README demo (needs resvg, ffmpeg and Fira Code; plays audio): build/demo/demo.mp4 and docs/assets/demo.gif
demo *args:
    uv run python tools/record_demo.py {{ args }}

# Remove build output
[confirm("Delete build/?")]
clean:
    uv run python -c "import shutil; shutil.rmtree('build', ignore_errors=True)"
