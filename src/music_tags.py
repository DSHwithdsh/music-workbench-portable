"""Transactional metadata updates, audio verification, and MusicTag handoff."""
from __future__ import annotations

import dataclasses
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from music_core import ROOT, Settings, Pipeline, atomic_json, file_hash, source_identity
from music_matching import lyric_text, is_synced

sys.path.insert(0, str(ROOT / "_vendor"))
try:
    import mutagen
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, TALB, TDRC, TIT2, TPE1, TPE2, TCON, TRCK, TPOS, USLT
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4, MP4Cover
except ImportError as exc:
    raise RuntimeError("标签组件缺失，请保留工作台目录中的 _vendor 文件夹") from exc

SUPPORTED = {".m4a", ".mp4", ".flac", ".mp3"}
FIELDS = ("title", "artist", "album", "albumartist", "date", "genre", "tracknumber", "discnumber")
MP4_KEYS = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "albumartist": "aART", "date": "\xa9day", "genre": "\xa9gen", "lyrics": "\xa9lyr"}
ID3_KEYS = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2", "date": "TDRC", "genre": "TCON", "tracknumber": "TRCK", "discnumber": "TPOS"}
ID3_CLASSES = {"title": TIT2, "artist": TPE1, "album": TALB, "albumartist": TPE2, "date": TDRC, "genre": TCON, "tracknumber": TRCK, "discnumber": TPOS}


def first(value):
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value or "")


def sidecar_signature(path):
    return {suffix: file_hash(Path(path).with_suffix(suffix)) if Path(path).with_suffix(suffix).is_file() else None
            for suffix in (".lrc", ".txt")}


def read_track(path, fingerprint=True):
    path = Path(path).resolve()
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("标签功能目前支持 M4A／ALAC／AAC、FLAC 和 MP3")
    audio = mutagen.File(path)
    if not isinstance(audio, (FLAC, MP4, MP3)):
        raise ValueError("无法识别受支持的音频格式")
    tags = audio.tags or {}
    result = {"path": str(path), "duration": float(audio.info.length), "cover": False,
              "lyrics": "", "sidecar_lyrics": "", **{key: "" for key in FIELDS}}
    if isinstance(audio, MP4):
        for key, atom in MP4_KEYS.items():
            result[key] = first(tags.get(atom, []))
        for key, atom in (("tracknumber", "trkn"), ("discnumber", "disk")):
            pair = tags.get(atom, [(0, 0)])[0]
            result[key] = (str(pair[0]) + ("/" + str(pair[1]) if pair[1] else "")) if pair[0] else ""
        result["cover"] = bool(tags.get("covr"))
    elif isinstance(audio, FLAC):
        for key in (*FIELDS, "lyrics"):
            result[key] = first(tags.get(key, tags.get("unsyncedlyrics", []) if key == "lyrics" else []))
        result["cover"] = bool(audio.pictures)
    else:
        for key, frame in ID3_KEYS.items():
            value = tags.get(frame)
            result[key] = first(value.text) if value else ""
        frames = tags.getall("USLT") if audio.tags is not None else []
        result["lyrics"] = frames[0].text if frames else ""
        result["cover"] = bool(tags.getall("APIC")) if audio.tags is not None else False
    result["tag_title"] = result["title"]
    result["title"] = result["title"] or re.sub(r"^\s*\d+[.\-_ ]+", "", path.stem)
    result["identity"] = source_identity(path) if fingerprint else None
    result["sidecars"] = sidecar_signature(path)
    lrc = path.with_suffix(".lrc")
    if lrc.is_file():
        try:
            result["sidecar_lyrics"] = lrc.read_text(encoding="utf-8-sig")
        except UnicodeError:
            result["sidecar_lyrics"] = lrc.read_text(encoding="gb18030", errors="replace")
    return result


def set_tags(path, fields, lyrics="", cover=None):
    """Used only on a staging copy. Unselected fields are preserved."""
    audio = mutagen.File(path)
    if audio.tags is None:
        audio.add_tags()
    if isinstance(audio, MP4):
        for key, value in fields.items():
            if key in MP4_KEYS:
                audio.tags[MP4_KEYS[key]] = [str(value)]
            elif key in ("tracknumber", "discnumber"):
                pair = str(value).split("/", 1)
                audio.tags["trkn" if key == "tracknumber" else "disk"] = [(int(pair[0]), int(pair[1]) if len(pair) == 2 else 0)]
        if lyrics:
            audio.tags["\xa9lyr"] = [lyrics]
        if cover:
            audio.tags["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_PNG if cover.startswith(b"\x89PNG") else MP4Cover.FORMAT_JPEG)]
    elif isinstance(audio, FLAC):
        for key, value in fields.items():
            audio[key] = [str(value)]
        if lyrics:
            audio["lyrics"] = [lyrics]
        if cover:
            picture = Picture()
            picture.type, picture.data = 3, cover
            picture.mime = "image/png" if cover.startswith(b"\x89PNG") else "image/jpeg"
            if cover.startswith(b"\x89PNG"):
                import struct
                picture.width, picture.height = struct.unpack(">II", cover[16:24])
            audio.clear_pictures()
            audio.add_picture(picture)
    elif isinstance(audio, MP3):
        for key, value in fields.items():
            audio.tags.setall(ID3_KEYS[key], [ID3_CLASSES[key](encoding=3, text=[str(value)])])
        if lyrics:
            audio.tags.setall("USLT", [USLT(encoding=3, lang="und", desc="", text=lyrics)])
        if cover:
            audio.tags.setall("APIC", [APIC(encoding=3, mime="image/png" if cover.startswith(b"\x89PNG") else "image/jpeg", type=3, desc="Cover", data=cover)])
    else:
        raise ValueError("格式不支持写入")
    audio.save()


def proposed_changes(track, match, overwrite=False, replace_lyrics=False, only_confident=True):
    metadata = match.get("metadata")
    fields = {}
    if metadata and (not only_confident or metadata.get("ready") or metadata.get("accepted")):
        for key in FIELDS:
            before = track.get("tag_title", "") if key == "title" else track.get(key, "")
            after = str(metadata.get(key) or "")
            if after and after != before and (overwrite or not before):
                fields[key] = after
    lyric = match.get("lyric")
    text, kind = lyric_text(lyric)
    if lyric and only_confident and not lyric.get("ready") and not lyric.get("accepted"):
        text = ""
    if (track.get("lyrics") and not replace_lyrics) or text == track.get("lyrics"):
        # Keep the text to allow a missing external LRC to be created, but never replace an existing lyric tag.
        text = track.get("lyrics") or text
    if not replace_lyrics and not track.get("lyrics") and track.get("sidecar_lyrics"):
        text = track["sidecar_lyrics"]
    if text:
        kind = "同步 LRC" if is_synced(text) else "纯文本"
    return fields, text, kind


class TagWriter:
    def __init__(self, settings):
        self.settings = settings
        self.pipeline = Pipeline(settings)
        self.id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.backup_root = ROOT / "tag-backups" / self.id
        self._receipt_sources = None

    def receipts(self, path, before, after_hash, after_stat, audio_hash, metadata):
        own = path.with_name(path.name + ".amdl.json")
        candidates = {own} if own.is_file() else set()
        if self._receipt_sources is None:
            self._receipt_sources = {}
            library = Path(self.settings.output)
            if library.is_dir():
                for receipt in library.rglob("*.amdl.json"):
                    try:
                        data = json.loads(receipt.read_text(encoding="utf-8"))
                        source = data.get("source", {}).get("path")
                        if source:
                            self._receipt_sources.setdefault(Path(source).resolve(), set()).add(receipt)
                    except (ValueError, OSError, TypeError):
                        continue
        candidates.update(self._receipt_sources.get(path, set()))
        updates = {}
        identity_after = {"path": str(path), "size": after_stat.st_size, "mtime_ns": after_stat.st_mtime_ns, "sha256": after_hash}
        for receipt in candidates:
            try:
                data = json.loads(receipt.read_text(encoding="utf-8"))
                changed = False
                if receipt == own and data.get("sha256") == before["sha256"]:
                    data["sha256"] = after_hash
                    data.setdefault("tag_history", []).append({"id": self.id, "before_sha256": before["sha256"],
                        "audio_sha256": audio_hash, "providers": metadata})
                    changed = True
                source = data.get("source", {})
                if source.get("path") and Path(source["path"]).resolve() == path and source.get("sha256") == before["sha256"]:
                    data["source"] = identity_after
                    changed = True
                if changed:
                    updates[receipt] = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            except (ValueError, OSError, TypeError):
                continue
        return updates

    def write(self, track, fields, lyrics="", kind="", cover=None, replace_lyrics=False, providers=None):
        path = Path(track["path"]).resolve()
        before = track["identity"]
        if not before or source_identity(path) != before or sidecar_signature(path) != track["sidecars"]:
            raise ValueError("文件或歌词在预览后发生变化，请重新扫描和匹配")
        if path.is_symlink():
            raise ValueError("请直接选择真实音频文件")
        lock = path.with_name(path.name + ".tag-lock")
        try:
            handle = lock.open("x")
        except FileExistsError as exc:
            raise ValueError("该文件正在进行标签写入；若上次异常退出，请先检查 .tag-lock") from exc
        handle.close()
        stage = path.with_name(".tag-stage-" + uuid.uuid4().hex + path.suffix)
        temporary = []
        backup = self.backup_root / (hashlib.sha256(str(path).encode()).hexdigest()[:12] + "-" + path.stem[:50])
        changes = []
        applied = []
        try:
            backup.mkdir(parents=True, exist_ok=True)
            required = path.stat().st_size * 2 + 4 * 1024 * 1024
            if shutil.disk_usage(backup).free < required or shutil.disk_usage(path.parent).free < path.stat().st_size + 1024 * 1024:
                raise OSError("剩余空间不足以备份和校验该音频")
            audio_hash = self.pipeline.pcm_hash(path)
            shutil.copy2(path, stage)
            tag_lyric = lyrics if replace_lyrics or not track.get("lyrics") else ""
            if fields or tag_lyric and tag_lyric != track.get("lyrics") or cover:
                set_tags(stage, fields, tag_lyric, cover)
            self.pipeline.validate_audio(stage)
            if self.pipeline.pcm_hash(stage) != audio_hash:
                raise ValueError("标签修改改变了音频 PCM，结果未提交")
            after_hash = file_hash(stage)
            changed_audio_file = after_hash != before["sha256"]
            if changed_audio_file:
                changes.append((path, stage))
            if lyrics:
                suffix = ".lrc" if kind == "同步 LRC" else ".txt"
                target = path.with_suffix(suffix)
                data = (lyrics.rstrip() + "\n").encode("utf-8")
                if not target.exists() or (replace_lyrics and target.read_bytes() != data):
                    temp = target.with_name(".tag-stage-" + uuid.uuid4().hex + suffix)
                    temp.write_bytes(data)
                    temporary.append(temp)
                    changes.append((target, temp))
            if changed_audio_file:
                updates = self.receipts(path, before, after_hash, stage.stat(), audio_hash, providers or [])
                for target, data in updates.items():
                    temp = target.with_name(".tag-stage-" + uuid.uuid4().hex + ".json")
                    temp.write_bytes(data)
                    temporary.append(temp)
                    changes.append((target, temp))
            originals = {}
            expected = {}
            for index, (target, temp) in enumerate(changes):
                old_hash = file_hash(target) if target.exists() else None
                saved = backup / (str(index).zfill(3) + "-" + target.name)
                if target.exists():
                    shutil.copy2(target, saved)
                originals[str(target)] = {"sha256": old_hash, "backup": str(saved) if old_hash else None}
                expected[str(target)] = file_hash(temp)
            if source_identity(path) != before:
                raise ValueError("校验期间源文件变化，结果未提交")
            for target, temp in changes:
                previous = originals[str(target)]["sha256"]
                if (file_hash(target) if target.exists() else None) != previous:
                    raise ValueError("待写入文件被其他程序修改，已停止")
                os.replace(temp, target)
                applied.append(target)
            result = {"id": self.id, "path": str(path), "status": "完成" if changes else "无变化",
                      "fields": list(fields), "lyrics": kind if lyrics else "保留已有／无匹配",
                      "cover": bool(cover), "audio_sha256": audio_hash, "originals": originals,
                      "after_sha256": expected, "providers": providers or [], "backup": str(backup)}
            atomic_json(backup / "manifest.json", result)
            return result
        except Exception:
            for target in reversed(applied):
                if file_hash(target) != expected[str(target)]:
                    raise RuntimeError("回滚时发现外部修改，请从标签备份手工恢复：" + str(backup))
                original = originals[str(target)]
                if original["backup"]:
                    restore = target.with_name(".tag-restore-" + uuid.uuid4().hex)
                    shutil.copy2(original["backup"], restore)
                    os.replace(restore, target)
                else:
                    target.unlink()
            raise
        finally:
            stage.unlink(missing_ok=True)
            for temp in temporary:
                temp.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)


def launch_musictag(executable, folder):
    executable, folder = Path(executable), Path(folder).resolve()
    if not executable.is_file():
        raise ValueError("找不到 MusicTag.exe，请在设置中指定路径")
    if not folder.is_dir():
        raise ValueError("选择的音乐文件夹不存在")
    return subprocess.Popen([str(executable), str(folder)], cwd=executable.parent)
