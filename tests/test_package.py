import subprocess
import tarfile
import zipfile
from unittest.mock import Mock

import pytest

from tools import package


@pytest.mark.parametrize("returncode", [1, -9, -15])
def test_smoke_rejects_failed_binary(monkeypatch, tmp_path, returncode):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode, args[0], stderr="startup failed"
        )

    monkeypatch.setattr(package.subprocess, "run", fail)

    with pytest.raises(SystemExit, match="startup failed"):
        package.smoke_test(tmp_path / "app")


def test_smoke_rejects_timeout(monkeypatch, tmp_path):
    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(package.subprocess, "run", hang)

    with pytest.raises(SystemExit, match="smoke test failed"):
        package.smoke_test(tmp_path / "app")


@pytest.mark.parametrize("stdout", ["", "Self-test passed."])
def test_smoke_requires_readiness(monkeypatch, tmp_path, stdout):
    def run(argv, **kwargs):
        assert argv == [str(tmp_path / "app"), "--self-test"]
        assert kwargs["cwd"] != package.ROOT
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(package.subprocess, "run", run)

    if stdout:
        package.smoke_test(tmp_path / "app")
    else:
        with pytest.raises(SystemExit, match="missing readiness"):
            package.smoke_test(tmp_path / "app")


def test_package_rejects_version_mismatch_before_build(monkeypatch, tmp_path):
    monkeypatch.setattr(package, "project_version", lambda: "0.2.0")
    monkeypatch.setattr(package.sys, "argv", ["package.py", "--version", "0.3.0"])
    build = Mock()
    monkeypatch.setattr(package, "build", build)
    monkeypatch.setattr(package, "smoke_test", Mock())
    artifact = tmp_path / "artifact"
    artifact.touch()
    monkeypatch.setattr(package, "package", lambda version: artifact)

    with pytest.raises(SystemExit):
        package.main()
    build.assert_not_called()


@pytest.mark.parametrize("suffix", [".tar.gz", ".zip"])
def test_verify_artifact_checks_extracted_payload(monkeypatch, tmp_path, suffix):
    name = package.NAME + (".exe" if suffix == ".zip" else "")
    payload = tmp_path / package.NAME / name
    payload.parent.mkdir()
    payload.write_text("packaged executable")
    artifact = tmp_path / f"release{suffix}"
    if suffix == ".zip":
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.write(payload, f"{package.NAME}/{name}")
    else:
        with tarfile.open(artifact, "w:gz") as archive:
            archive.add(payload.parent, arcname=package.NAME)

    checked = []

    def smoke(executable):
        assert executable != payload
        assert executable.read_text() == "packaged executable"
        checked.append(executable)

    monkeypatch.setattr(package, "smoke_test", smoke)
    package.verify_artifact(artifact)

    assert len(checked) == 1
    assert not checked[0].exists()
