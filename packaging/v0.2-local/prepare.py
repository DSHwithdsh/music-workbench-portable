"""Snapshot validated local v0.2 into a separate, credential-free distribution."""
from pathlib import Path
import hashlib
import json
import shutil

BASE = Path(__file__).resolve().parent
LOCAL = BASE.parent
OLD = LOCAL / "portable-build/release/MusicWorkbench-Portable"
SRC = BASE / "src"
PAYLOAD = BASE / "payload/MusicWorkbench"
MODULES = ("music_core.py", "music_app.py", "apple_music_ui.py", "music_catalog.py",
           "music_matching.py", "music_tags.py", "music_tags_ui.py")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def replace_once(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new, 1)


def main():
    SRC.mkdir(parents=True, exist_ok=True)
    PAYLOAD.mkdir(parents=True, exist_ok=True)
    baseline = {str(LOCAL / name): digest(LOCAL / name) for name in (*MODULES, "settings.json", "LOCAL-VERSION.json", "使用说明.md")}
    old_zip = LOCAL / "portable-build/release/MusicWorkbench-Portable-Windows-x64.zip"
    baseline[str(old_zip)] = digest(old_zip)
    (BASE / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    for name in MODULES:
        shutil.copy2(LOCAL / name, SRC / name)
    core = (SRC / "music_core.py").read_text(encoding="utf-8")
    core = replace_once(core, "import subprocess\n", "import subprocess\nimport sys\n")
    core = replace_once(core, "ROOT = Path(__file__).resolve().parent", 'ROOT = Path(os.environ.get("MUSIC_WORKBENCH_ROOT", str(Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent))).resolve()')
    core = replace_once(core, 'amdl_root: str = r"D:\\System\\Music\\Music Zone\\AMDL-Offline"', 'amdl_root: str = str(ROOT / "tools/amdl")')
    core = replace_once(core, 'freac: str = r"D:\\Program Files\\freac\\freaccmd.exe"', 'freac: str = str(ROOT / "tools/freac/freaccmd.exe")')
    core = replace_once(core, 'output: str = str(ROOT / "音乐库")', 'output: str = str(ROOT / "Music")')
    core = replace_once(core, 'musictag: str = r"D:\\System\\Music\\Music Zone\\MusicTag v1.0.9.0\\MusicTag.exe"', 'musictag: str = ""')
    core = replace_once(core, '        return cls(**{f.name: data[f.name] for f in dataclasses.fields(cls) if f.name in data})', '''        for key in ("amdl_root", "freac", "output", "musictag"):
            if data.get(key) and not Path(data[key]).is_absolute():
                data[key] = str(ROOT / data[key])
        return cls(**{f.name: data[f.name] for f in dataclasses.fields(cls) if f.name in data})''')
    core = replace_once(core, '        atomic_json(CONFIG, dataclasses.asdict(self))', '''        data = dataclasses.asdict(self)
        for key in ("amdl_root", "freac", "output", "musictag"):
            if not data[key]:
                continue
            path = Path(data[key]).resolve()
            if path.is_relative_to(ROOT):
                data[key] = path.relative_to(ROOT).as_posix()
        atomic_json(CONFIG, data)''')
    (SRC / "music_core.py").write_text(core, encoding="utf-8")
    app = (SRC / "music_app.py").read_text(encoding="utf-8")
    app = replace_once(app, 'tk.StringVar(value=r"D:\\System\\Music\\Music Zone\\AM-DL downloads")', 'tk.StringVar(value=str(ROOT / "Music/ALAC"))')
    # Keep the proven isolated service launcher from v0.1, all other UI is v0.2.
    previous = (LOCAL / "portable-build/src/music_app.py").read_text(encoding="utf-8")
    start, end = '    def open_service(self):', '    def '
    a = app.index(start)
    b = app.index(end, a + len(start))
    c = previous.index(start)
    d = previous.index(end, c + len(start))
    app = app[:a] + previous[c:d].replace("便携包", "安装包").replace("便携版", "安装版") + app[b:]
    (SRC / "music_app.py").write_text(app, encoding="utf-8")
    ui = (SRC / "apple_music_ui.py").read_text(encoding="utf-8")
    ui = replace_once(ui, 'self.root.title("Music 工作台 v0.2 本地版 · 标签与歌词")', 'self.root.title("Music 工作台 v0.2 · 标签与歌词")\n        self.root.iconbitmap(str(ROOT / "app.ico"))')
    ui = ui.replace("继续使用本机已经安装的 AMDL、fre:ac 与 FFmpeg。", "AMDL、fre:ac 与标签组件已内置；外部 MusicTag 可选。")
    ui = ui.replace("原 AMDL 的 config.yaml 继续生效。歌曲下载、校验和转码均在本机完成。", "配置保存在安装目录；解密服务使用独立 WSL 环境。")
    (SRC / "apple_music_ui.py").write_text(ui, encoding="utf-8")
    for name in ("service_manager.py", "portable_entry.py"):
        shutil.copy2(LOCAL / "portable-build/src" / name, SRC / name)
    entry = (SRC / "portable_entry.py").read_text(encoding="utf-8")
    entry = replace_once(entry, 'def main():\n', '''def main():
    if "--tag-self-test" in sys.argv or "--online-match-test" in sys.argv:
        from frozen_checks import run
        run()
        return
''')
    entry = entry.replace('if "--self-test" not in sys.argv and "--gui-smoke" not in sys.argv:',
                          'if not any(flag in sys.argv for flag in ("--self-test", "--gui-smoke", "--tag-self-test", "--online-match-test")):')
    (SRC / "portable_entry.py").write_text(entry, encoding="utf-8")
    shutil.copy2(BASE / "frozen_checks.py", SRC / "frozen_checks.py")
    for name in ("test_music_tags.py", "test_pipeline.py"):
        shutil.copy2(LOCAL / name, SRC / name)
    for folder in ("tools", "service", "service-tools", "licenses"):
        shutil.copytree(OLD / folder, PAYLOAD / folder, dirs_exist_ok=True)
    for name in ("app.ico", "一键准备解密服务.cmd", "启动独立解密服务.cmd"):
        shutil.copy2(OLD / name, PAYLOAD / name)
    # Public, tested v0.1 dependencies only: never copy local user settings or tokens.
    config = PAYLOAD / "tools/amdl/GUI-downloader/_internal/src/core/config.yaml"
    assert "media-user-token: your-media-user-token" in config.read_text(encoding="utf-8")
    shutil.copytree(LOCAL / "_vendor/mutagen-1.48.1.dist-info", PAYLOAD / "licenses/mutagen-1.48.1.dist-info", dirs_exist_ok=True)
    shutil.copy2(BASE / "使用说明.md", PAYLOAD / "使用说明.md")
    print("v0.2 snapshot and clean assets ready", flush=True)


if __name__ == "__main__":
    main()
