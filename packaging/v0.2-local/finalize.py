from pathlib import Path
import json
import zipfile
from prepare import BASE, PAYLOAD, digest


def main():
    report = json.loads((BASE / "release/validation.json").read_text(encoding="utf-8"))
    assert report["uninstall_preserved_user_data"] == "passed"
    assert report["frozen_tests"] >= 18
    archive_path = BASE / "release/MusicWorkbench-0.2.0-Portable-Windows-x64.zip"
    temporary = archive_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(PAYLOAD.rglob("*")):
            if path.is_file():
                archive.write(path, "MusicWorkbench/" + path.relative_to(PAYLOAD).as_posix(),
                              compress_type=zipfile.ZIP_STORED if path.suffix in (".zip", ".gz") else zipfile.ZIP_DEFLATED)
    temporary.replace(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        for line in archive.read("MusicWorkbench/MANIFEST.sha256").decode("utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            import hashlib
            assert hashlib.sha256(archive.read("MusicWorkbench/" + relative)).hexdigest() == expected, relative
        forbidden = {"settings.json", "service.json", "creds.key", ".bash_history"}
        assert not [name for name in archive.namelist() if Path(name).name in forbidden]
        assert not any("/.auth/" in name or "/tag-backups/" in name or "/logs/" in name for name in archive.namelist())
    archive_path.with_suffix(".zip.sha256").write_text(digest(archive_path) + "  " + archive_path.name + "\n", encoding="ascii")
    report["portable_zip"] = {"filename": archive_path.name, "bytes": archive_path.stat().st_size, "sha256": digest(archive_path), "archive_integrity": "passed; all manifest entries verified"}
    baseline = json.loads((BASE / "baseline.json").read_text())
    assert all(digest(path) == expected for path, expected in baseline.items())
    report["original_files_unchanged"] = len(baseline)
    (BASE / "release/validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"setup": "MusicWorkbench-0.2.0-Setup-x64.exe", "portable": report["portable_zip"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
