"""Acquire pinned clean upstream materials and compile the ARM64 downloader."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

BASE = Path(__file__).resolve().parent
COMMIT = "5e17b686ca4a01b0c0397f28061788b7c36d07d5"
ASSETS = {
    "apmyx-source.zip": ("https://codeload.github.com/rwnk-12/apmyx-gui/zip/" + COMMIT, "6770339006732ff00189e55216c1c3dec6d9d999676d4b83595e71f4b128fde8"),
    "Wrapper.arm64.latest.zip": ("https://github.com/WorldObservationLog/wrapper/releases/download/wrapper.arm64.latest/Wrapper.arm64.latest.zip", "8de5da67e375038ff5a08761c71ccaf90ac5ec711a6d0924ba7328b5e116e0a6"),
    "freac-1.1.7-macos11.dmg": ("https://github.com/enzo1982/freac/releases/download/v1.1.7/freac-1.1.7-macos11.dmg", "22e29d73bdaf6dcb851a03bfe344028e38457c85b21e7378ffac8625a8ed4f12")}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    downloads = BASE / "downloads"
    downloads.mkdir(exist_ok=True)
    for name, (url, expected) in ASSETS.items():
        target = downloads / name
        if not target.exists():
            urllib.request.urlretrieve(url, target)
        if sha(target) != expected:
            raise ValueError("Upstream asset checksum mismatch: " + name)
    shutil.copy2(downloads / "Wrapper.arm64.latest.zip", BASE / "resources/service/Wrapper.arm64.latest.zip")
    source = BASE / "upstream"
    source.mkdir(exist_ok=True)
    with zipfile.ZipFile(downloads / "apmyx-source.zip") as archive:
        for name in archive.namelist():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Unsafe source path")
        archive.extractall(source)
    project = source / ("apmyx-gui-" + COMMIT) / "backend/providers/legacy"
    assert (project / "go-mp4tag/go.mod").is_file(), "Pinned source replacement missing"
    environment = os.environ.copy()
    cache = BASE / ".cache"
    for part in ("go-build", "go-mod", "temp"):
        (cache / part).mkdir(parents=True, exist_ok=True)
    environment.update(GOOS="darwin", GOARCH="arm64", CGO_ENABLED="0", GOTOOLCHAIN="local",
                       GOCACHE=str(cache / "go-build"), GOMODCACHE=str(cache / "go-mod"), GOTMPDIR=str(cache / "temp"))
    binary = BASE / "resources/tools/amdl/downloader"
    binary.parent.mkdir(parents=True, exist_ok=True)
    go = shutil.which("go")
    if not go:
        raise RuntimeError("Install the Go toolchain before preparing Mac assets")
    subprocess.run([go, "build", "-trimpath", "-buildvcs=false", "-o", str(binary), "."], cwd=project, env=environment, check=True)
    binary.chmod(0o755)
    manifest = {"source_commit": COMMIT, "source_archive_sha256": ASSETS["apmyx-source.zip"][1],
                "downloader_sha256": sha(binary), "GOOS": "darwin", "GOARCH": "arm64", "CGO_ENABLED": "0",
                "go_version": subprocess.check_output([go, "version"], text=True).strip(),
                "host": platform.platform(), "runtime_test": "not established by cross-compilation"}
    (BASE / "BUILD-PROVENANCE.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
