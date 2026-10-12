"""Build a standalone addictune-cli with Nuitka and package it for this OS.

    uv run python tools/package.py [--version X] [--skip-build] [--skip-smoke] [--assume-downloads]

macOS: `.app` bundle (Now Playing needs a bundle identifier) wrapped in a `.pkg`
that installs to /usr/local. Linux: standalone dir as `.tar.gz`. Windows:
standalone dir as `.zip`. Artifacts land in build/artifacts.
"""

import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
NUITKA_OUT = BUILD / "nuitka"
ARTIFACTS = BUILD / "artifacts"
NAME = "addictune-cli"
BUNDLE_ID = "com.addictune.cli"
ENTRY = "addictune_cli/__main__.py"

NUITKA_FLAGS = {
    "darwin": [
        "--mode=app",
        f"--macos-app-name={NAME}",
        # PyObjC frameworks for media/macos.py; the static imports usually
        # suffice, these are insurance.
        *(
            f"--include-package={p}"
            for p in ("objc", "Foundation", "AppKit", "CoreFoundation", "MediaPlayer")
        ),
    ],
    "linux": [
        "--mode=standalone",
        # keyring's SecretService backend needs these; jeepney's tests pull pytest.
        "--include-package=secretstorage",
        "--include-package=jeepney",
        "--nofollow-import-to=jeepney.tests",
    ],
    "win32": ["--mode=standalone", "--include-package=winrt"],
}


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, cwd=ROOT, **kwargs)


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def dist_dir() -> Path:
    """The Nuitka output: `<entry>.app` on macOS (named after __main__.py), `<entry>.dist` elsewhere."""
    pattern = "*.app" if sys.platform == "darwin" else "*.dist"
    found = sorted(NUITKA_OUT.glob(pattern))
    if len(found) != 1:
        raise SystemExit(f"expected one {pattern} in {NUITKA_OUT}, found {found}")
    return found[0]


def build(*, assume_downloads: bool) -> None:
    shutil.rmtree(BUILD, ignore_errors=True)
    cmd = [
        "uv",
        "run",
        "--isolated",
        "--no-editable",
        "--reinstall-package",
        "addictune-cli",
        "--locked",
        "--python",
        f"{sys.version_info.major}.{sys.version_info.minor}",
        "python",
        "-m",
        "nuitka",
        f"--output-dir={NUITKA_OUT}",
        f"--output-filename={NAME}",
        "--include-package-data=addictune_cli",
        "--include-distribution-metadata=addictune-cli",  # About screen reads the version
        *NUITKA_FLAGS[sys.platform if sys.platform in NUITKA_FLAGS else "linux"],
        *(["--assume-yes-for-downloads"] if assume_downloads else []),
        ENTRY,
    ]
    run(
        cmd,
        env={
            **os.environ,
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(BUILD / "uv-cache")),
        },
    )


def set_bundle_identifier() -> None:
    """Now Playing ignores a process whose main bundle has no identifier."""
    plist = dist_dir() / "Contents" / "Info.plist"
    info = plistlib.loads(plist.read_bytes())
    info["CFBundleIdentifier"] = BUNDLE_ID
    plist.write_bytes(plistlib.dumps(info))


def smoke_test(executable: Path) -> None:
    """Check the packaged UI and real worker from outside the checkout."""
    print("+ smoke test", flush=True)
    with tempfile.TemporaryDirectory(prefix="addictune-smoke-") as temp_dir:
        try:
            result = subprocess.run(
                [str(executable), "--self-test"],
                cwd=temp_dir,
                env={
                    **os.environ,
                    "ADDICTUNE_LOG_FILE": str(Path(temp_dir) / "smoke.log"),
                },
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise SystemExit(f"smoke test failed: {exc.stderr or exc}") from exc
        if "Self-test passed." not in result.stdout:
            raise SystemExit("smoke test failed: missing readiness response")
    print("+ smoke test ok", flush=True)


def verify_artifact(artifact: Path) -> None:
    """Extract the final installer/archive and check its payload without installing."""
    with tempfile.TemporaryDirectory(prefix="addictune-package-") as temp_dir:
        root = Path(temp_dir)
        if artifact.suffix == ".pkg":
            run(["pkgutil", "--expand-full", str(artifact), str(root / "pkg")])
            executable = next(root.rglob(f"Contents/MacOS/{NAME}"))
        elif artifact.suffix == ".zip":
            with zipfile.ZipFile(artifact) as archive:
                archive.extractall(root)
            executable = root / NAME / f"{NAME}.exe"
        else:
            with tarfile.open(artifact) as archive:
                archive.extractall(root, filter="data")
            executable = root / NAME / NAME
        smoke_test(executable)


def package(version: str) -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    arch = platform.machine().lower()
    if sys.platform == "darwin":
        set_bundle_identifier()
        return build_pkg(version, arch)
    if sys.platform == "win32":
        artifact = ARTIFACTS / f"{NAME}-{version}-windows-{arch}.zip"
        with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in dist_dir().rglob("*"):
                if path.is_file():
                    zf.write(path, Path(NAME) / path.relative_to(dist_dir()))
        return artifact
    artifact = ARTIFACTS / f"{NAME}-{version}-linux-{arch}.tar.gz"
    with tarfile.open(artifact, "w:gz") as tar:
        tar.add(dist_dir(), arcname=NAME)
    return artifact


def build_pkg(version: str, arch: str) -> Path:
    """Stage /usr/local/lib/<name>/<name>.app plus a /usr/local/bin symlink, then pkgbuild."""
    root = BUILD / "pkg-root"
    shutil.rmtree(root, ignore_errors=True)
    lib = root / "usr/local/lib" / NAME
    lib.mkdir(parents=True)
    (root / "usr/local/bin").mkdir(parents=True)
    run(["ditto", "--norsrc", "--noextattr", str(dist_dir()), str(lib / f"{NAME}.app")])
    (root / "usr/local/bin" / NAME).symlink_to(
        Path("../lib") / NAME / f"{NAME}.app" / "Contents" / "MacOS" / NAME
    )
    run(["xattr", "-rc", str(root)])
    components = BUILD / "component.plist"
    run(["pkgbuild", "--analyze", "--root", str(root), str(components)])
    plist = plistlib.loads(components.read_bytes())
    for component in plist:
        component["BundleIsRelocatable"] = False  # keep the .app out of /Applications
    components.write_bytes(plistlib.dumps(plist))
    artifact = ARTIFACTS / f"{NAME}-{version}-macos-{arch}.pkg"
    run(
        [
            "pkgbuild",
            "--root",
            str(root),
            "--component-plist",
            str(components),
            "--identifier",
            BUNDLE_ID,
            "--version",
            version,
            "--install-location",
            "/",
            "--filter",
            r"(^|/)\._",
            str(artifact),
        ],
        env={**os.environ, "COPYFILE_DISABLE": "1"},
    )
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", default=project_version())
    parser.add_argument("--skip-build", action="store_true", help="reuse build/nuitka")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument(
        "--assume-downloads",
        action="store_true",
        help="let Nuitka download its toolchain (CI)",
    )
    args = parser.parse_args()
    if args.version != project_version():
        parser.error("--version must match the version in pyproject.toml")
    if not args.skip_build:
        build(assume_downloads=args.assume_downloads)
    artifact = package(args.version)
    if not args.skip_smoke:
        verify_artifact(artifact)
    print(
        f"artifact: {artifact} ({artifact.stat().st_size / 1024 / 1024:.1f} MiB)",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
