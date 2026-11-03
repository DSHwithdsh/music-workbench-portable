"""Frozen desktop entry point plus local-only verification modes."""
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from music_core import ROOT, Settings, Pipeline, atomic_json


def self_test(report_path):
    folder = ROOT / "diagnostics" / "codec-test"
    folder.mkdir(parents=True, exist_ok=True)
    settings = Settings(output=str(folder / "output"), workers=2)
    settings.check(download=True)
    source = folder / "portable-test.wav"
    result = subprocess.run([str(settings.ffmpeg), "-y", "-nostdin", "-v", "error", "-f", "lavfi",
                             "-i", "sine=frequency=997:sample_rate=96000:duration=2",
                             "-ac", "2", "-c:a", "pcm_s24le", str(source)],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    pipeline = Pipeline(settings)
    pipeline.convert([source], folder, ("flac", "aac"))
    report = pipeline.finish()
    report["portable_root"] = str(ROOT)
    report["python_bundled"] = bool(getattr(sys, "frozen", False))
    report["tools"] = {"downloader": str(settings.downloader), "freac": settings.freac, "ffmpeg": str(settings.ffmpeg)}
    if not all(r.status in ("完成", "已验证并跳过") for r in pipeline.results) or len(pipeline.results) != 2:
        raise RuntimeError("Portable codec test failed: " + json.dumps(report, ensure_ascii=True))
    atomic_json(Path(report_path), report)


def main():
    if "--self-test" in sys.argv:
        self_test(sys.argv[sys.argv.index("--self-test") + 1])
        return
    if "--gui-smoke" in sys.argv:
        import tkinter as tk
        from apple_music_ui import AppleMusicApp
        root = tk.Tk()
        app = AppleMusicApp(root)
        root.update()
        atomic_json(Path(sys.argv[sys.argv.index("--gui-smoke") + 1]),
                    {"root": str(ROOT), "title": root.title(), "pages": list(app.pages), "bundled": bool(getattr(sys, "frozen", False))})
        root.destroy()
        return
    from apple_music_ui import main as ui_main
    ui_main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error = traceback.format_exc()
        folder = ROOT / "diagnostics"
        folder.mkdir(exist_ok=True)
        (folder / "startup-error.log").write_text(error, encoding="utf-8")
        if "--self-test" not in sys.argv and "--gui-smoke" not in sys.argv:
            import tkinter.messagebox
            tkinter.messagebox.showerror("Music 工作台", "启动失败，详见 diagnostics/startup-error.log\n" + error[-1200:])
        sys.exit(1)
