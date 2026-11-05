"""macOS resources are read-only; all mutable state lives outside the .app."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import uuid

SOURCE = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))
RESOURCES = Path(getattr(sys, "_MEIPASS", SOURCE.parent / "resources"))
ROOT = Path(os.environ.get("MUSIC_WORKBENCH_ROOT", str(Path.home() / "Library/Application Support/MusicWorkbenchMac-v0.2"))).expanduser().resolve()
ROOT.mkdir(parents=True, exist_ok=True)


def tool(name):
    if FROZEN:
        # A frozen app must not silently depend on the builder's Homebrew install.
        return RESOURCES / "tools/bin" / name
    override = os.environ.get("MUSIC_WORKBENCH_" + name.upper())
    candidates = [Path(override)] if override else []
    candidates += [RESOURCES / "tools/bin" / name, Path("/opt/homebrew/bin") / name,
                   Path("/opt/homebrew/opt/ffmpeg@6/bin") / name, Path("/usr/local/bin") / name]
    candidates += [Path(found)] if (found := shutil.which(name)) else []
    return next((p for p in candidates if p.is_file()), candidates[0])


def freac():
    if FROZEN:
        return Path(sys.executable).resolve().parent.parent / "Helpers/freac.app/Contents/MacOS/freaccmd"
    override = os.environ.get("MUSIC_WORKBENCH_FREAC")
    if override:
        return Path(override)
    apps = [RESOURCES / "tools/freac.app", Path("/Applications/freac.app"), Path.home() / "Applications/freac.app"]
    paths = [p / "Contents/MacOS/freaccmd" for p in apps]
    return next((p for p in paths if p.is_file()), paths[0])


def initialize_engine():
    target = ROOT / "tools/amdl"
    target.mkdir(parents=True, exist_ok=True)
    binary = RESOURCES / "tools/amdl/downloader"
    if FROZEN and not binary.is_file():
        raise RuntimeError("Mac 应用缺少内置 ARM64 下载器，请重新完整安装")
    if binary.is_file():
        import hashlib
        def sha(path):
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
        installed = target / "downloader"
        if not installed.exists() or sha(installed) != sha(binary):
            staged = target / (".downloader-" + uuid.uuid4().hex)
            shutil.copy2(binary, staged)
            staged.chmod(0o755)
            os.replace(staged, installed)
    config = next((p for p in (RESOURCES / "defaults/config.yaml", RESOURCES / "tools/amdl/config.yaml") if p.is_file()), None)
    if config and not (target / "config.yaml").exists():
        # Exclusive create preserves a user's config across launches and upgrades.
        try:
            with (target / "config.yaml").open("xb") as stream:
                stream.write(config.read_bytes())
        except FileExistsError:
            pass
    return target


def encoder_command(settings, preset, staged, source, threads):
    command = [settings.freac, "--encoder=" + ("flac" if preset == "flac" else settings.aac_encoder),
               "--superfast", f"--threads={threads}", "-o", str(staged), "--"]
    if preset == "flac":
        command += ["-c", "6"]
    elif settings.aac_encoder == "coreaudio":
        command += ["-f", "AAC", "-b", "128"]
    elif settings.aac_encoder == "fdkaac":
        command += ["-m", "LC", "-b", "128"]
    else:
        raise ValueError("AAC 编码器须为 coreaudio 或 fdkaac")
    return command + [str(source)]


def process_env(ffmpeg):
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(Path(ffmpeg).parent), str(tool("MP4Box").parent),
                                    "/opt/homebrew/bin", "/usr/local/bin", env.get("PATH", "")))
    return env


def open_folder(path):
    return subprocess.Popen(["/usr/bin/open", str(Path(path).resolve())])


def launch_service():
    import shlex
    args = [sys.executable, "--service"] if FROZEN else [sys.executable, str(SOURCE / "mac_entry.py"), "--service"]
    command = ROOT / "打开独立解密服务.command"
    command.write_text("#!/bin/zsh\n" + " ".join(shlex.quote(a) for a in args) + '\nresult=$?\nprintf "\\n按回车关闭…"\nread -r _\nexit "$result"\n', encoding="utf-8", newline="\n")
    command.chmod(0o700)
    return subprocess.Popen(["/usr/bin/open", "-a", "Terminal", str(command)])


def configure_window(root):
    width = max(900, min(1320, root.winfo_screenwidth() - 80))
    height = max(650, min(900, root.winfo_screenheight() - 120))
    root.geometry(f"{width}x{height}")
