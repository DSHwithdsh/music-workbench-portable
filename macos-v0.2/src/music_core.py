"""Local AMDL + fre:ac pipeline. Python standard library only; no credentials stored."""
from __future__ import annotations

import concurrent.futures
import dataclasses
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from mac_runtime import ROOT, tool, freac, encoder_command, process_env
CONFIG = ROOT / "settings.json"
AUDIO_EXTENSIONS = {".m4a", ".flac", ".wav", ".aiff", ".aif", ".alac", ".mp3", ".aac", ".ogg", ".opus", ".wma"}
LOSSLESS = {"alac", "flac", "wavpack", "ape"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclasses.dataclass
class Settings:
    amdl_root: str = str(ROOT / "tools/amdl")
    freac: str = str(freac())
    aac_encoder: str = "coreaudio" if sys.platform == "darwin" else "fdkaac"
    output: str = str(Path.home() / "Music/MusicWorkbench")
    workers: int = 4
    storefront: str = "us"
    musictag: str = ""

    @property
    def downloader(self):
        return Path(self.amdl_root) / "downloader"

    @property
    def ffmpeg(self):
        return tool("ffmpeg")

    @property
    def service_script(self):
        return ROOT / "打开独立解密服务.command"

    @classmethod
    def load(cls):
        if not CONFIG.exists():
            return cls()
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        for key in ("amdl_root", "freac", "output", "musictag"):
            if data.get(key) and not Path(data[key]).is_absolute():
                data[key] = str(ROOT / data[key])
        return cls(**{f.name: data[f.name] for f in dataclasses.fields(cls) if f.name in data})

    def save(self):
        data = dataclasses.asdict(self)
        for key in ("amdl_root", "freac", "output", "musictag"):
            if not data[key]:
                continue
            path = Path(data[key]).resolve()
            if path.is_relative_to(ROOT):
                data[key] = path.relative_to(ROOT).as_posix()
        atomic_json(CONFIG, data)

    def check(self, download=False):
        if not 1 <= int(self.workers) <= 10:
            raise ValueError("并行曲目数必须在 1–10 之间")
        if not re.fullmatch(r"[a-z]{2}", self.storefront):
            raise ValueError("商店地区须为两位小写字母，例如 us、cn、jp")
        for name, path in [("fre:ac", Path(self.freac)), ("FFmpeg", self.ffmpeg)]:
            if not path.is_file():
                raise ValueError(f"找不到 {name}：{path}")
        if download:
            if not self.downloader.is_file():
                raise ValueError(f"找不到 AMDL 下载引擎：{self.downloader}")
            if not (self.downloader.parent / "config.yaml").is_file():
                raise ValueError("AMDL 引擎旁缺少 config.yaml")
        if not str(self.output).strip() or not Path(self.output).is_absolute():
            raise ValueError("请选择音乐库的绝对路径")


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def redact(text):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[已隐藏令牌]", text)
    if re.search(r"(?i)(?:authorization|media[-_ ]user[-_ ]token|password|passwd|bearer)\s*[:= ]", text):
        return "[含认证信息的日志行已隐藏]"
    return text


def service_status():
    result = {}
    for port in (10020, 20020):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                result[port] = True
        except OSError:
            result[port] = False
    return result


def parse_links(text):
    text = re.sub(r"\[[^\]]*\]\((https://music\.apple\.com/[^\s)]+)\)", r"\1", text)
    links = []
    for value in text.split():
        value = value.strip("\ufeff\"'<>，,；;")
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.netloc.lower() != "music.apple.com":
            raise ValueError(f"请输入完整的 https://music.apple.com/ 链接：{value}")
        if not re.search(r"/(album|playlist|song)/", parts.path):
            raise ValueError("目前支持专辑、歌单和单曲链接；艺人页请使用原 AMDL")
        if value not in links:
            links.append(value)
    if not links:
        raise ValueError("请先粘贴至少一个 Apple Music 链接")
    return links


def download_command(settings, url, folder):
    args = [str(settings.downloader), "-codec-preference", "alac",
            "-alac-save-folder", str(folder), "-storefront", settings.storefront]
    parsed = urlsplit(url)
    if "i" in parse_qs(parsed.query) or "/song/" in parsed.path:
        args.append("-song")
    return args + [url]


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_identity(path):
    path = Path(path).resolve()
    stat = path.stat()
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": file_hash(path)}


@dataclasses.dataclass
class AudioInfo:
    codec: str
    rate: int
    layout: str
    duration: float
    profile: str = ""


@dataclasses.dataclass
class Result:
    source: str
    preset: str
    status: str
    output: str = ""
    detail: str = ""


class Pipeline:
    def __init__(self, settings, emit=None):
        self.settings = settings
        self.emit = emit or (lambda kind, value: None)
        self.stop = threading.Event()
        self.results = []
        self.downloads = []
        self.lock = threading.Lock()
        self.id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.log_dir = ROOT / "logs"
        self.log_dir.mkdir(exist_ok=True)
        self.log_path = self.log_dir / (self.id + ".log")
        self.report_path = self.log_dir / (self.id + ".json")

    def log(self, line):
        line = redact(str(line)).strip()
        if line.startswith("AMDL_PROGRESS::"):
            try:
                self.emit("download_progress", json.loads(line.split("::", 1)[1]))
            except (ValueError, TypeError):
                pass
        if line:
            with self.lock:
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"[{datetime.now():%H:%M:%S}] {line}\n")
            self.emit("log", line)

    def run_process(self, args, cwd=None, stream=False):
        """Never interrupt an active encoder; stop is observed between files."""
        env = process_env(self.settings.ffmpeg)
        proc = subprocess.Popen([str(x) for x in args], cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        chunks = []
        pending = bytearray()
        while True:
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if stream:
                pending.extend(chunk)
                while b"\n" in pending or b"\r" in pending:
                    indices = [p for p in (pending.find(b"\n"), pending.find(b"\r")) if p >= 0]
                    index = min(indices)
                    self.log(pending[:index].decode("utf-8", errors="replace"))
                    del pending[:index + 1]
        if stream and pending:
            self.log(pending.decode("utf-8", errors="replace"))
        code = proc.wait()
        proc.stdout.close()
        return code, b"".join(chunks).decode("utf-8", errors="replace")

    def probe(self, path):
        _, output = self.run_process([self.settings.ffmpeg, "-hide_banner", "-nostdin", "-i", path])
        # Match only stream descriptions, never titles or other metadata.
        audio = re.search(r"^\s*Stream #\S+.*?: Audio: (\w+)(?: \(([^)]*)\))?.*?, (\d+) Hz, ([^,\r\n]+)", output, re.M)
        duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", output)
        if not audio or not duration:
            raise ValueError(f"无法识别完整音频：{Path(path).name}")
        seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
        if seconds <= 0:
            raise ValueError("音频时长为零")
        return AudioInfo(audio[1], int(audio[3]), audio[4], seconds, audio[2] or "")

    def validate_audio(self, path):
        code, output = self.run_process([self.settings.ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
                                         "-xerror", "-err_detect", "explode", "-i", path,
                                         "-map", "0:a:0", "-vn", "-sn", "-dn", "-f", "null", "-"])
        # Cover art is excluded; a real decode error must never be published.
        if code:
            raise ValueError("音频完整性校验失败：" + redact(output[-1200:]))

    def pcm_hash(self, path):
        code, output = self.run_process([self.settings.ffmpeg, "-nostdin", "-v", "error", "-xerror",
                                         "-i", path, "-map", "0:a:0", "-c:a", "pcm_s32le",
                                         "-f", "hash", "-hash", "sha256", "-"])
        match = re.search(r"SHA256=([a-fA-F0-9]{64})", output)
        if code or not match:
            raise ValueError("PCM 校验失败：" + redact(output[-800:]))
        return match[1]

    def record(self, result):
        with self.lock:
            self.results.append(result)
        self.emit("result", dataclasses.asdict(result))
        self.log(f"{result.status} | {result.preset.upper()} | {Path(result.source).name} | {result.detail}")

    def encode(self, source, relative, preset, info, identity, source_pcm):
        ext = ".flac" if preset == "flac" else ".m4a"
        target = Path(self.settings.output) / ("FLAC" if preset == "flac" else "AAC-LC 256k") / relative.with_suffix(ext)
        receipt = target.with_name(target.name + ".amdl.json")
        spec = {"encoder": preset, "profile": "FLAC level 6" if preset == "flac" else "AAC-LC 128kbps/channel", "version": 2, "implementation": "flac" if preset == "flac" else self.settings.aac_encoder}
        if target.exists():
            if not receipt.is_file():
                raise FileExistsError(f"目标已存在且无本工具记录，未覆盖：{target}")
            old = json.loads(receipt.read_text(encoding="utf-8"))
            if old.get("source") != identity or old.get("spec") != spec or old.get("sha256") != file_hash(target):
                raise FileExistsError(f"已有成品或源文件发生变化，未覆盖；请换输出目录或移走旧文件：{target}")
            self.validate_audio(target)
            self.record(Result(str(source), preset, "已验证并跳过", str(target)))
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        stage_dir = target.parent / (".amdl-stage-" + uuid.uuid4().hex)
        stage_dir.mkdir()
        staged = stage_dir / target.name
        try:
            threads = max(1, 10 // int(self.settings.workers))
            args = encoder_command(self.settings, preset, staged, source, threads)
            code, output = self.run_process(args, cwd=Path(self.settings.freac).parent)
            if code or not staged.is_file() or staged.stat().st_size == 0:
                raise RuntimeError("fre:ac 转码失败：" + redact(output[-1800:]))
            self.validate_audio(staged)
            encoded = self.probe(staged)
            expected = "flac" if preset == "flac" else "aac"
            if encoded.codec != expected:
                raise ValueError(f"编码器输出格式不符：{encoded.codec}，期望 {expected}")
            if preset == "aac" and encoded.profile != "LC":
                raise ValueError(f"AAC profile 不符：{encoded.profile}，期望 LC")
            if abs(info.duration - encoded.duration) > max(0.25, 4096 / info.rate):
                raise ValueError("转码前后时长不符")
            if encoded.layout != info.layout:
                raise ValueError(f"转码前后声道不符：{info.layout} → {encoded.layout}")
            if preset == "flac":
                if encoded.rate != info.rate or self.pcm_hash(staged) != source_pcm:
                    raise ValueError("FLAC 解码后的 PCM 与源文件不一致")
            # Reject a source modified by another application during conversion.
            if source_identity(source) != identity:
                raise ValueError("转码期间源文件发生变化，结果未提交")
            record = {"source": identity, "spec": spec, "audio": dataclasses.asdict(encoded),
                      "sha256": file_hash(staged), "created": datetime.now().isoformat()}
            # Hard-link on the same volume gives atomic, no-overwrite publication.
            os.link(staged, target)
            atomic_json(receipt, record)
            for suffix in (".lrc", ".txt"):
                sidecar = source.with_suffix(suffix)
                destination = target.with_suffix(suffix)
                if sidecar.is_file() and not destination.exists():
                    try:
                        with sidecar.open("rb") as src, destination.open("xb") as dst:
                            shutil.copyfileobj(src, dst)
                    except FileExistsError:
                        pass
            self.record(Result(str(source), preset, "完成", str(target),
                               f"{encoded.codec.upper()} {encoded.rate} Hz / {encoded.layout}；音频已校验"))
        finally:
            # Only this uniquely created staging directory can be removed.
            shutil.rmtree(stage_dir)

    def convert_one(self, source, relative, presets):
        if self.stop.is_set():
            for preset in presets:
                self.record(Result(str(source), preset, "已取消", detail="未开始"))
            return
        self.log(f"校验源音频：{source}")
        try:
            info = self.probe(source)
            if info.codec not in LOSSLESS and not info.codec.startswith("pcm_"):
                raise ValueError(f"输入为有损 {info.codec}，已跳过，避免有损转无损或再次有损编码")
            if "aac" in presets and info.layout not in ("mono", "stereo", "1 channels", "2 channels"):
                raise ValueError("AAC 便携预设仅支持单声道／立体声；多声道请单独选择 FLAC")
            self.validate_audio(source)
            identity = source_identity(source)
            source_pcm = self.pcm_hash(source) if "flac" in presets else None
        except Exception as exc:
            for preset in presets:
                self.record(Result(str(source), preset, "失败", detail=redact(str(exc))))
            return
        # Once a track has started, finish its selected presets before stopping.
        for preset in presets:
            try:
                self.encode(source, relative, preset, info, identity, source_pcm)
            except Exception as exc:
                self.record(Result(str(source), preset, "失败", detail=redact(str(exc))))

    def convert(self, files, source_root, presets):
        if not presets or any(p not in ("flac", "aac") for p in presets):
            raise ValueError("请选择至少一种有效的输出格式")
        source_root = Path(source_root).resolve()
        files = sorted({Path(p).resolve() for p in files})
        if not files:
            raise ValueError("没有找到可处理的音频文件")
        planned = []
        targets = set()
        for source in files:
            relative = source.relative_to(source_root)
            for preset in presets:
                key = (preset, str(relative.with_suffix(".flac" if preset == "flac" else ".m4a")).casefold())
                if key in targets:
                    raise ValueError(f"不同输入会产生同名成品，请分开处理：{relative}")
                targets.add(key)
            planned.append((source, relative))
        total = len(planned) * len(presets)
        self.emit("total", total)
        with concurrent.futures.ThreadPoolExecutor(max_workers=int(self.settings.workers)) as pool:
            futures = [pool.submit(self.convert_one, s, r, presets) for s, r in planned]
            for future in concurrent.futures.as_completed(futures):
                future.result()

    def download(self, links, presets):
        self.settings.check(download=True)
        ports = service_status()
        if not all(ports.values()):
            raise ValueError("解密服务尚未就绪。请打开解密服务，等 10020 和 20020 两个端口均就绪后再开始。")
        task_root = Path(self.settings.output) / "ALAC" / self.id
        self.log(f"本次下载目录：{task_root}")
        for index, url in enumerate(links, 1):
            if self.stop.is_set():
                break
            folder = task_root / f"{index:03d}"
            folder.mkdir(parents=True)
            self.emit("phase", f"下载 {index}/{len(links)}：{url}")
            self.log(f"开始下载 {index}/{len(links)}：{url}")
            code, output = self.run_process(download_command(self.settings, url, folder),
                                            cwd=self.settings.downloader.parent, stream=True)
            alerts = [redact(line) for line in output.splitlines()
                      if re.search(r"(?i)Invalid CKC|decryptFragment: EOF|More than one device|(?:failed|error)\s*[:=]|\bFailed to\b|\b(?:failed|error)\s+[1-9]\d*", line)]
            audio = sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXTENSIONS)
            status = "完成" if code == 0 and not alerts and audio else "需检查"
            self.downloads.append({"url": url, "exit_code": code, "status": status,
                                   "audio_files": len(audio), "alerts": alerts, "folder": str(folder)})
            if status != "完成":
                self.log(f"下载需检查：退出码 {code}，发现 {len(audio)} 个音频；详见引擎日志")
        files = sorted(p for p in task_root.rglob("*") if p.suffix.lower() in AUDIO_EXTENSIONS) if task_root.exists() else []
        if not files:
            raise ValueError("本次没有产出音频。请检查日志中的账号区域、解密服务或网络错误。")
        if self.stop.is_set():
            self.log("已按要求停止添加后续步骤；本次已下载文件保留在 ALAC 目录")
            return
        if presets:
            self.emit("phase", "下载阶段结束，开始校验并转码")
            self.convert(files, task_root.parent, presets)
        else:
            self.emit("total", len(files))
            for source in files:
                if self.stop.is_set():
                    self.record(Result(str(source), "alac", "已取消"))
                    continue
                try:
                    info = self.probe(source)
                    if info.codec != "alac":
                        raise ValueError(f"实际编码为 {info.codec}，未得到 ALAC 无损")
                    self.validate_audio(source)
                    self.record(Result(str(source), "alac", "完成", str(source), f"ALAC {info.rate} Hz；音频已校验"))
                except Exception as exc:
                    self.record(Result(str(source), "alac", "失败", detail=redact(str(exc))))

    def finish(self, fatal=""):
        report = {"id": self.id, "stopped": self.stop.is_set(), "fatal": redact(fatal),
                  "downloads": self.downloads, "results": [dataclasses.asdict(r) for r in self.results]}
        atomic_json(self.report_path, report)
        return report


def scan_folder(folder, output):
    folder, output = Path(folder).resolve(), Path(output).resolve()
    if not folder.is_dir():
        raise ValueError("输入文件夹不存在")
    files = []
    for current, directories, names in os.walk(folder, followlinks=False):
        directories[:] = [name for name in directories
                          if not name.startswith(".amdl-stage-") and not (Path(current) / name).is_symlink()
                          and (Path(current) / name).resolve() != output]
        for name in names:
            path = Path(current) / name
            if path.suffix.lower() in AUDIO_EXTENSIONS and not path.is_symlink():
                # When scanning the library itself, exclude generated conversion trees.
                if any(path.is_relative_to(output / sub) and not folder.is_relative_to(output / sub)
                       for sub in ("FLAC", "AAC-LC 256k")):
                    continue
                files.append(path)
    return sorted(files)
