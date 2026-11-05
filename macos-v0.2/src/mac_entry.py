"""Source and frozen entry point, including target-Mac acceptance checks."""
import argparse
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback

from mac_runtime import ROOT, RESOURCES, initialize_engine


def doctor(report):
    from music_core import Settings
    settings = Settings.load()
    settings.check(download=True)
    probes = {}
    commands = {"ffmpeg": [str(settings.ffmpeg), "-version"],
                "freac_coreaudio": [settings.freac, "--help=coreaudio"],
                "downloader_flags": [str(settings.downloader), "-h"]}
    from mac_runtime import tool, process_env
    commands["MP4Box"] = [str(tool("MP4Box")), "-version"]
    for name, command in commands.items():
        result = subprocess.run(command, capture_output=True, timeout=60, env=process_env(settings.ffmpeg))
        output = (result.stdout + result.stderr).decode("utf-8", "replace")
        probes[name] = {"executable": str(Path(command[0]).resolve()), "exit_code": result.returncode, "output": output[-12000:]}
        if getattr(sys, "frozen", False) and name != "downloader_flags":
            app_root = Path(sys.executable).resolve().parents[2]
            assert Path(command[0]).resolve().is_relative_to(app_root), "Tool escaped app bundle: " + name
        if name == "downloader_flags":
            assert all(flag in output for flag in ("codec-preference", "alac-save-folder", "storefront", "song"))
        else:
            assert result.returncode == 0, name + " probe failed"
        if name == "freac_coreaudio":
            assert "AAC" in output and "bitrate" in output.lower(), "CoreAudio AAC support not reported"
    data = {"platform": sys.platform, "machine": platform.machine(), "macOS": platform.mac_ver()[0],
            "frozen": bool(getattr(sys, "frozen", False)), "probes": probes, "status": "passed"}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doctor", type=Path)
    parser.add_argument("--self-test", type=Path)
    parser.add_argument("--gui-smoke", type=Path)
    parser.add_argument("--service", action="store_true")
    options, remaining = parser.parse_known_args()
    if options.service:
        from mac_service import main as service_main
        service_main(remaining)
        return
    if remaining:
        parser.error("unknown arguments: " + " ".join(remaining))
    initialize_engine()
    if options.doctor:
        doctor(options.doctor)
    elif options.self_test:
        import unittest
        import test_music_tags
        import test_pipeline
        import test_mac_port
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_music_tags, test_pipeline, test_mac_port))
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        options.self_test.parent.mkdir(parents=True, exist_ok=True)
        options.self_test.write_text(json.dumps({"tests": result.testsRun, "success": result.wasSuccessful(),
             "host": platform.platform(), "machine": platform.machine(), "output": stream.getvalue()}, ensure_ascii=False, indent=2), encoding="utf-8")
        if not result.wasSuccessful():
            raise RuntimeError(stream.getvalue())
    elif options.gui_smoke:
        import tkinter as tk
        from apple_music_ui import AppleMusicApp
        root = tk.Tk()
        app = AppleMusicApp(root)
        root.update()
        options.gui_smoke.write_text(json.dumps({"title": root.title(), "pages": list(app.pages), "host": platform.platform()}), encoding="utf-8")
        root.destroy()
    else:
        from apple_music_ui import main as ui_main
        ui_main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error = traceback.format_exc()
        (ROOT / "startup-error.log").write_text(error, encoding="utf-8")
        if len(sys.argv) == 1:
            from tkinter import messagebox
            messagebox.showerror("Music 工作台 Mac", "启动失败，详见 " + str(ROOT / "startup-error.log") + "\n" + error[-1000:])
        else:
            print(error, file=sys.stderr)
        raise SystemExit(1)
