"""Exercise the actual setup EXE in an isolated directory, then its frozen app."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import time
from prepare import BASE, PAYLOAD, digest

INSTALL = BASE / "build/便携安装验证 中文 path/MusicWorkbench"
REPORTS = BASE / "build/reports"
SETUP = BASE / "release/MusicWorkbench-0.2.0-Setup-x64.exe"


def environment():
    env = os.environ.copy()
    temp = BASE / "build/temp"
    temp.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = env["TMP"] = str(temp)
    env["PATH"] = str(Path(env.get("SystemRoot", r"C:\Windows")) / "System32")
    env.pop("PYTHONPATH", None)
    env.pop("MUSIC_WORKBENCH_ROOT", None)
    return env


def call(args, timeout=180):
    result = subprocess.run(list(map(str, args)), env=environment(), cwd=BASE,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Exit {result.returncode}: {args[0]}\n" + result.stderr.decode("utf-8", "replace")[-1200:])
    return result


def setup(log):
    call([SETUP, "/PORTABLE=1", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/SP-", "/NORESTART", "/NOICONS", "/TASKS=",
          "/LANG=chinesesimp", f"/DIR={INSTALL}", f"/LOG={REPORTS / log}"])


def baseline():
    saved = json.loads((BASE / "baseline.json").read_text())
    assert all(digest(path) == value for path, value in saved.items()), "Original app or v0.1 changed"
    return len(saved)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("install", "finish"))
    phase = parser.parse_args().phase
    REPORTS.mkdir(parents=True, exist_ok=True)
    report_path = BASE / "release/validation.json"
    if phase == "install":
        assert not INSTALL.exists(), "Test installation already exists; inspect before restarting"
        setup("install.log")
        count = 0
        for line in (PAYLOAD / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            assert digest(INSTALL / relative) == expected, relative
            count += 1
        exe = INSTALL / "MusicWorkbench.exe"
        started = time.monotonic()
        # Run each diagnostic on the installed frozen EXE, no Python/tool paths on PATH.
        for mode in ("self-test", "tag-self-test", "gui-smoke", "online-match-test"):
            call([exe, "--" + mode, REPORTS / (mode + ".json")], timeout=180)
        tags = json.loads((REPORTS / "tag-self-test.json").read_text(encoding="utf-8"))
        assert tags["success"] and tags["tests"] >= 18, tags
        gui = json.loads((REPORTS / "gui-smoke.json").read_text(encoding="utf-8"))
        assert "tags" in gui["pages"] and gui["bundled"], gui
        online = json.loads((REPORTS / "online-match-test.json").read_text(encoding="utf-8"))
        assert online["success"], online
        service = call([INSTALL / "service-tools/ServiceManager.exe", "--plan"])
        (REPORTS / "service-plan.json").write_bytes(service.stdout)
        assert b"u22-amdl" not in service.stdout
        # Existing user configuration, music and backup must survive an actual reinstall.
        core_config = INSTALL / "tools/amdl/GUI-downloader/_internal/src/core/config.yaml"
        core_config.write_text(core_config.read_text(encoding="utf-8") + "\n# validation: preserve user configuration\n", encoding="utf-8")
        settings = {"amdl_root": "tools/amdl", "freac": "tools/freac/freaccmd.exe", "output": "Music",
                    "musictag": "", "workers": 2, "storefront": "gb"}
        (INSTALL / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        preserved = [core_config, INSTALL / "settings.json"]
        for name in ("Music/keep-user-data.txt", "tag-backups/keep-backup.txt", "service-runtime/keep-state.txt"):
            path = INSTALL / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("v0.2 validation sentinel", encoding="utf-8")
            preserved.append(path)
        hashes = {str(p): digest(p) for p in preserved}
        setup("upgrade.log")
        assert all(digest(path) == value for path, value in hashes.items()), "Upgrade overwrote user data"
        report = {"version": "0.2.0", "date": "2026-11-05", "install_dir": str(INSTALL),
                  "installation_mode": "actual setup EXE /PORTABLE=1 (no registry or shortcuts)",
                  "standard_install_registration": "not verified: execution host denied HKCU uninstall key and Start Menu writes; initial setup rolled back",
                  "installed_manifest_files": count, "frozen_tests": tags["tests"],
                  "flac_and_aac": "passed", "gui_tags_page": "passed", "online_match": online,
                  "PATH_without_Python_or_installed_tools": "passed", "Chinese_and_space_path": "passed",
                  "reinstall_preserved_user_data": hashes, "service_plan": "passed; no WSL changes",
                  "original_files_unchanged": baseline(), "elapsed_seconds": round(time.monotonic() - started),
                  "fresh_PC_WSL_setup": "not executed on deployed host", "signature": "unsigned"}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "installed checks and upgrade passed", "tests": tags["tests"], "report": str(report_path)}, ensure_ascii=False), flush=True)
    else:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        call([INSTALL / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={REPORTS / 'uninstall.log'}"])
        # The uninstaller can have a short-lived child process; no user files are removed.
        deadline = time.monotonic() + 20
        while (INSTALL / "MusicWorkbench.exe").exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not (INSTALL / "MusicWorkbench.exe").exists(), "Uninstall did not remove installed program"
        assert all(digest(path) == value for path, value in report["reinstall_preserved_user_data"].items()), "Uninstall removed user data"
        report["uninstall_preserved_user_data"] = "passed"
        report["original_files_unchanged"] = baseline()
        report["installer_sha256"] = digest(SETUP)
        report["installer_bytes"] = SETUP.stat().st_size
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        SETUP.with_suffix(".exe.sha256").write_text(digest(SETUP) + "  " + SETUP.name + "\n", encoding="ascii")
        print(json.dumps({"status": "uninstall and preservation passed", "bytes": SETUP.stat().st_size, "sha256": digest(SETUP)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
