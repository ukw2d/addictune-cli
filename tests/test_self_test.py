import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from addictune_cli.src import diagnostics
from addictune_cli.src.audio import protocol
from addictune_cli.src.audio.state import State


def test_self_test_runs_outside_checkout_without_account(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "addictune_cli", "--self-test"],
        cwd=tmp_path,
        env={**os.environ, "ADDICTUNE_LOG_FILE": str(tmp_path / "self-test.log")},
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "Self-test passed." in result.stdout


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected_error"),
    [
        (1, "", RuntimeError),
        (0, "", ValidationError),
        (
            0,
            protocol.StateEvent(generation=0, state=State.STOPPED).model_dump_json(),
            RuntimeError,
        ),
    ],
)
def test_self_test_rejects_worker_failure(
    monkeypatch, returncode, stdout, expected_error
):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, returncode, stdout=stdout, stderr="worker startup failed"
        )

    monkeypatch.setattr(diagnostics.subprocess, "run", run)

    with pytest.raises(expected_error):
        diagnostics.run()
