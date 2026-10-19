"""Test-wide guards.

Every ``AddictuneApp`` mounts a launch update check; keep the suite offline by
answering "no update" unless a test replaces the checker itself.
"""

from unittest.mock import patch

import pytest

from addictune_cli.src import update


async def _offline(client, current, *, prereleases: bool):
    return None


@pytest.fixture(autouse=True)
def _no_update_requests():
    with patch.object(update, "check", _offline):
        yield
