import pytest

from addictune_cli.src import subprocess_worker


@pytest.mark.parametrize("compiled", [False, True])
def test_worker_launches_native_binary_or_python_module(monkeypatch, compiled):
    monkeypatch.setattr(subprocess_worker, "IS_NUITKA", compiled)
    monkeypatch.setattr(subprocess_worker.sys, "executable", "/runtime/python")
    monkeypatch.setattr(subprocess_worker.sys, "argv", ["/installed/addictune-cli"])

    argv, env = subprocess_worker.worker_command("player")

    if compiled:
        assert argv == ["/installed/addictune-cli"]
        assert env == {subprocess_worker.ENV_KEY: "player"}
    else:
        assert argv == ["/runtime/python", "-m", "addictune_cli.src.audio.worker"]
        assert env == {}
