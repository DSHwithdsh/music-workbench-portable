import dataclasses
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid
from unittest.mock import patch
import io

from music_core import ROOT, Settings, Pipeline, file_hash, source_identity
from music_matching import candidate_score, ranked, lyric_text, PublicClient
from music_tags import TagWriter, proposed_changes, read_track, set_tags


class TagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = ROOT / "test-artifacts" / ("tag-tests-" + uuid.uuid4().hex[:8])
        cls.base.mkdir(parents=True)
        cls.settings = dataclasses.replace(Settings(), output=str(cls.base / "library"))
        cls.fixtures = cls.base / "fixtures"
        cls.fixtures.mkdir()
        ff = cls.settings.ffmpeg
        def run(*args):
            result = subprocess.run([str(ff), "-nostdin", "-y", "-v", "error", *map(str, args)], capture_output=True,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                raise RuntimeError(result.stderr.decode("utf-8", "replace"))
        for extension, encoder in (("m4a", "alac"), ("flac", "flac"), ("mp3", "libmp3lame")):
            run("-f", "lavfi", "-i", "sine=frequency=977:sample_rate=44100:duration=1.5", "-ac", "2", "-c:a", encoder,
                "-metadata", "title=原始歌名", "-metadata", "artist=测试艺人", cls.fixtures / ("track." + extension))
        run("-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", cls.fixtures / "cover.png")
        cls.cover = (cls.fixtures / "cover.png").read_bytes()

    def source(self, extension="m4a"):
        folder = self.base / uuid.uuid4().hex[:8]
        folder.mkdir()
        path = folder / ("01. 测试曲目." + extension)
        shutil.copy2(self.fixtures / ("track." + extension), path)
        return path

    def writer(self):
        with patch("music_tags.ROOT", self.base):
            return TagWriter(self.settings)

    def test_actual_tag_cover_synced_lyrics_roundtrip_and_pcm(self):
        for extension in ("m4a", "flac", "mp3"):
            with self.subTest(extension=extension):
                path = self.source(extension)
                old = path.read_bytes()
                track = read_track(path)
                result = self.writer().write(track, {"title": "新歌名", "album": "测试专辑", "tracknumber": "2/9"},
                    "[00:00.00]集成测试歌词\n[00:01.00]第二行", "同步 LRC", self.cover)
                updated = read_track(path)
                self.assertEqual(updated["title"], "新歌名")
                self.assertEqual(updated["artist"], "测试艺人")
                self.assertTrue(updated["cover"])
                self.assertIn("集成测试歌词", updated["lyrics"])
                self.assertTrue(path.with_suffix(".lrc").is_file())
                self.assertEqual(result["status"], "完成")
                backups = [Path(x["backup"]) for x in result["originals"].values() if x.get("backup")]
                self.assertIn(old, [p.read_bytes() for p in backups])
                self.assertFalse(list(path.parent.glob(".tag-stage-*")))

    def test_fill_only_and_low_confidence_keep_existing(self):
        path = self.source()
        local = read_track(path)
        match = {"metadata": {"title": "另一首歌", "album": "新增专辑", "ready": True},
                 "lyric": {"ready": False, "syncedLyrics": "[00:00.00]不应写入"}}
        fields, text, kind = proposed_changes(local, match)
        self.assertNotIn("title", fields)
        self.assertEqual(fields["album"], "新增专辑")
        self.assertEqual(text, "")
        path.with_suffix(".lrc").write_text("[00:00.00]已有歌词", encoding="utf-8")
        local = read_track(path)
        match["lyric"]["ready"] = True
        _, text, kind = proposed_changes(local, match)
        self.assertIn("已有歌词", text)

    def test_plain_lyrics_are_not_mislabeled_lrc(self):
        path = self.source("flac")
        self.writer().write(read_track(path), {}, "这是纯文本歌词", "纯文本")
        self.assertTrue(path.with_suffix(".txt").is_file())
        self.assertFalse(path.with_suffix(".lrc").exists())

    def test_stale_preview_refuses_to_write(self):
        path = self.source()
        track = read_track(path)
        set_tags(path, {"title": "外部编辑"})
        updated_hash = file_hash(path)
        with self.assertRaisesRegex(ValueError, "预览后发生变化"):
            self.writer().write(track, {"title": "不应覆盖"})
        self.assertEqual(file_hash(path), updated_hash)

    def test_audio_verification_failure_preserves_original(self):
        path = self.source()
        track = read_track(path)
        writer = self.writer()
        with patch.object(writer.pipeline, "pcm_hash", side_effect=["original", "different"]):
            with self.assertRaisesRegex(ValueError, "改变了音频"):
                writer.write(track, {"title": "错误"})
        self.assertEqual(file_hash(path), track["identity"]["sha256"])
        self.assertFalse(path.with_name(path.name + ".tag-lock").exists())

    def test_receipts_follow_tag_only_changes_and_resume(self):
        source = self.source()
        pipe = Pipeline(self.settings)
        pipe.convert([source], source.parent, ("flac", "aac"))
        self.assertEqual([x.status for x in pipe.results], ["完成", "完成"])
        self.writer().write(read_track(source), {"album": "补全专辑"})
        for result in pipe.results:
            receipt = json.loads(Path(result.output + ".amdl.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["source"], source_identity(source))
        flac = Path(pipe.results[0].output)
        self.writer().write(read_track(flac), {"genre": "测试风格"})
        pipe.convert([source], source.parent, ("flac", "aac"))
        self.assertEqual([x.status for x in pipe.results[-2:]], ["已验证并跳过", "已验证并跳过"])

    def test_transaction_rolls_back_if_receipt_commit_fails(self):
        path = self.source("flac")
        track = read_track(path)
        receipt = path.with_name(path.name + ".amdl.json")
        receipt.write_text(json.dumps({"sha256": file_hash(path), "source": {}}), encoding="utf-8")
        receipt_original = receipt.read_bytes()
        import music_tags
        real_replace = music_tags.os.replace
        def fail_receipt(src, dst):
            if Path(dst) == receipt and Path(src).name.startswith(".tag-stage-"):
                raise OSError("injected receipt commit failure")
            return real_replace(src, dst)
        with patch("music_tags.os.replace", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "injected"):
                self.writer().write(track, {"title": "必须回滚"}, "[00:00.00]测试", "同步 LRC")
        self.assertEqual(file_hash(path), track["identity"]["sha256"])
        self.assertEqual(receipt.read_bytes(), receipt_original)
        self.assertFalse(path.with_suffix(".lrc").exists())

    def test_wrong_version_and_ambiguous_results_require_review(self):
        local = {"title": "Song", "artist": "Artist", "album": "", "duration": 180}
        live = {"title": "Song", "artist": "Artist", "album": "Live", "duration": 250}
        self.assertFalse(candidate_score(local, live)[1])
        choices = ranked(local, [dict(live, duration=180, album="A"), dict(live, duration=180, album="B")])
        self.assertFalse(choices[0]["ready"])
        self.assertEqual(lyric_text({"instrumental": True})[1], "纯音乐")

    def test_apple_javascript_content_type_can_carry_json(self):
        class Response(io.BytesIO):
            headers = {"Content-Type": "text/javascript; charset=utf-8"}
        client = PublicClient()
        with patch("music_matching.urlopen", return_value=Response(b'{"results": []}')):
            self.assertEqual(client.get("https://itunes.apple.com", "/search", {"term": "test"}), {"results": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
