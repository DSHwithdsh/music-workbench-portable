"""Run on Apple Silicon macOS to build/test/sign an app and create its DMG."""
from pathlib import Path
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import urllib.request
import uuid

BASE = Path(__file__).resolve().parent
RES = BASE / "resources"
APP_NAME = "MusicWorkbench"
DMG_SHA = "22e29d73bdaf6dcb851a03bfe344028e38457c85b21e7378ffac8625a8ed4f12"
DOWNLOADS = BASE / "downloads"


def run(args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_freac():
    image = DOWNLOADS / "freac-1.1.7-macos11.dmg"
    if not image.exists():
        DOWNLOADS.mkdir(exist_ok=True)
        urllib.request.urlretrieve("https://github.com/enzo1982/freac/releases/download/v1.1.7/freac-1.1.7-macos11.dmg", image)
    if sha(image) != DMG_SHA:
        raise ValueError("fre:ac DMG checksum mismatch")
    data = plistlib.loads(subprocess.check_output(["hdiutil", "attach", "-readonly", "-nobrowse", "-plist", str(image)]))
    mounts = [Path(e["mount-point"]) for e in data["system-entities"] if "mount-point" in e]
    try:
        apps = [path for mount in mounts for path in mount.glob("*.app") if (path / "Contents/MacOS/freaccmd").is_file()]
        if len(apps) != 1:
            raise RuntimeError("Expected one freac.app with CLI on DMG")
        destination = RES / "tools/freac.app"
        run(["ditto", apps[0], destination])
        return destination
    finally:
        for mount in mounts:
            run(["hdiutil", "detach", mount])


def executable_paths():
    paths = {}
    for name, prefix in (("ffmpeg", "/opt/homebrew/opt/ffmpeg@6/bin"), ("MP4Box", "/opt/homebrew/bin")):
        path = Path(prefix) / name
        if not path.is_file():
            raise RuntimeError("Missing build prerequisite: " + str(path))
        paths[name] = path
        run(["lipo", "-verify_arch", "arm64", path])
    run(["lipo", "-verify_arch", "arm64", RES / "tools/amdl/downloader"])
    return paths


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SystemExit("This build must run on native Apple Silicon macOS; Windows cannot freeze the Mac Python runtime.")
    freac_app = prepare_freac()
    tools = executable_paths()
    run(["lipo", "-verify_arch", "arm64", freac_app / "Contents/MacOS/freaccmd"])
    env = os.environ.copy()
    env["MUSIC_WORKBENCH_FFMPEG"] = str(tools["ffmpeg"])
    env["MUSIC_WORKBENCH_MP4BOX"] = str(tools["MP4Box"])
    env["MUSIC_WORKBENCH_ROOT"] = str(BASE / "build/source-test-state")
    reports = BASE / "build/reports"
    reports.mkdir(parents=True, exist_ok=True)
    run([sys.executable, BASE / "src/mac_entry.py", "--doctor", reports / "source-doctor.json"], env=env)
    run([sys.executable, BASE / "src/mac_entry.py", "--self-test", reports / "source-tests.json"], env=env)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
               "--target-architecture", "arm64", "--name", APP_NAME, "--osx-bundle-identifier", "io.github.dshwithdsh.musicworkbench",
               "--distpath", str(BASE / "dist"), "--workpath", str(BASE / "build/pyinstaller"), "--specpath", str(BASE / "build"),
               "--collect-submodules", "mutagen", "--copy-metadata", "mutagen", "--codesign-identity", "-"]
    for name, path in tools.items():
        command += ["--add-binary", str(path) + ":tools/bin"]
    command += ["--add-binary", str(RES / "tools/amdl/downloader") + ":tools/amdl",
                "--add-data", str(RES / "tools/amdl/config.yaml") + ":defaults",
                "--add-data", str(RES / "service") + ":service",
                "--add-data", str(BASE / "licenses") + ":licenses", str(BASE / "src/mac_entry.py")]
    run(command, cwd=BASE)
    app = BASE / "dist" / (APP_NAME + ".app")
    helpers = app / "Contents/Helpers"
    helpers.mkdir(exist_ok=True)
    run(["ditto", freac_app, helpers / "freac.app"])
    run(["codesign", "--force", "--deep", "--sign", "-", "--timestamp=none", app])
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    # Reject accidentally retained Homebrew load paths. System /usr/lib paths are fine.
    for path in (app / "Contents").rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
            continue
        dependencies = subprocess.check_output(["otool", "-L", str(path)], text=True)
        for line in dependencies.splitlines()[1:]:
            if line.lstrip().startswith(("/opt/homebrew/", "/usr/local/")):
                raise RuntimeError("Unbundled dependency: " + str(path) + "\n" + line)
    bundled_env = os.environ.copy()
    for name in ("MUSIC_WORKBENCH_FFMPEG", "MUSIC_WORKBENCH_MP4BOX", "MUSIC_WORKBENCH_FREAC", "PYTHONPATH"):
        bundled_env.pop(name, None)
    bundled_env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    bundled_env["MUSIC_WORKBENCH_ROOT"] = str(BASE / "build/frozen-test-state")
    executable = app / "Contents/MacOS" / APP_NAME
    for mode in ("doctor", "self-test", "gui-smoke"):
        run([executable, "--" + mode, reports / ("frozen-" + mode + ".json")], env=bundled_env)
    stage = BASE / "build" / ("dmg-stage-" + uuid.uuid4().hex[:10])
    stage.mkdir()
    run(["ditto", app, stage / app.name])
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", stage / app.name])
    if not (stage / "Applications").exists():
        (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
    shutil.copy2(BASE / "Mac使用说明.txt", stage / "Mac使用说明.txt")
    disk = BASE / "dist/MusicWorkbench-0.2.0-mac-port.1-arm64.dmg"
    run(["hdiutil", "create", "-volname", "MusicWorkbench v0.2 Mac", "-srcfolder", stage, "-ov", "-format", "UDZO", disk])
    disk.with_suffix(".dmg.sha256").write_text(sha(disk) + "  " + disk.name + "\n", encoding="ascii")
    print("Built and tested on " + platform.platform() + ": " + str(disk))


if __name__ == "__main__":
    main()
