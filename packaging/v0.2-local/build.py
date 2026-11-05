"""Compile v0.2 without modifying the validated local app or v0.1 distribution."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
from prepare import BASE, LOCAL, SRC, PAYLOAD, digest


def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(LOCAL / "portable-build/builddeps"), str(LOCAL / "_vendor")))
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
               "--name", "MusicWorkbench", "--distpath", str(BASE / "build/dist"),
               "--workpath", str(BASE / "build/work"), "--specpath", str(BASE / "build"),
               "--icon", str(PAYLOAD / "app.ico"), "--paths", str(LOCAL / "_vendor"),
               "--collect-submodules", "mutagen", str(SRC / "portable_entry.py")]
    subprocess.run(command, cwd=SRC, env=env, check=True)
    shutil.copytree(BASE / "build/dist/MusicWorkbench", PAYLOAD, dirs_exist_ok=True)
    shutil.copytree(SRC, PAYLOAD / "source", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (PAYLOAD / ".music-workbench-installer").write_text("0.2.0\n", encoding="ascii")
    info = {"name": "Music 工作台", "version": "0.2.0", "platform": "Windows x64", "date": "2026-11-05",
            "bundled": ["CPython 3.14.7", "AMDL downloader", "freac 1.1.7", "FFmpeg", "MP4Box", "Mutagen 1.48.1", "clean Ubuntu Base 22.04.5 + wrapper"],
            "optional_external": ["MusicTag.exe (not bundled)"],
            "source_sha256": {p.name: digest(p) for p in SRC.glob("*.py")},
            "validation": "See separate validation.json alongside installer; new-PC WSL setup not executed on deployed host"}
    (PAYLOAD / "BUILD-INFO.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(LOCAL / "portable-build/release/MusicWorkbench-Portable/licenses/THIRD-PARTY.md", PAYLOAD / "licenses/THIRD-PARTY.md")
    with (PAYLOAD / "licenses/THIRD-PARTY.md").open("a", encoding="utf-8") as stream:
        stream.write("\n\n## v0.2 标签组件\nMutagen 1.48.1，GPL-2.0-or-later；许可证及元数据见 mutagen-1.48.1.dist-info。https://github.com/quodlibet/mutagen\n")
    forbidden = {"settings.json", "service.json", "creds.key", ".bash_history"}
    assert not [p for p in PAYLOAD.rglob("*") if p.is_file() and p.name in forbidden]
    manifest = [digest(p) + "  " + p.relative_to(PAYLOAD).as_posix() for p in sorted(PAYLOAD.rglob("*")) if p.is_file() and p.name != "MANIFEST.sha256"]
    (PAYLOAD / "MANIFEST.sha256").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    baseline = json.loads((BASE / "baseline.json").read_text())
    assert all(digest(path) == expected for path, expected in baseline.items()), "Existing app or v0.1 changed"
    print("v0.2 frozen payload ready", flush=True)


if __name__ == "__main__":
    main()
