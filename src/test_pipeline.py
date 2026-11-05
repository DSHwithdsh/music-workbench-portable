"""Real local codec tests. No network, account access, or music-library changes."""
import dataclasses
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from music_core import ROOT, Pipeline, Settings, download_command, parse_links, scan_folder


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = ROOT / "test-artifacts" / "pipeline"
        cls.base.mkdir(parents=True, exist_ok=True)
        cls.source = cls.base / "inputs" / "测试艺人" / "测试专辑"
        cls.source.mkdir(parents=True, exist_ok=True)
        cls.settings = Settings(output=str(cls.base / "output"), workers=2)
        cls.settings.check(True)

        def ff(*args):
            result = subprocess.run([str(cls.settings.ffmpeg), "-y", "-v", "error", *map(str, args)],
                                    capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                raise RuntimeError(result.stderr.decode("utf-8", "replace"))

        cls.ff = staticmethod(ff)
        cover = cls.base / "cover.jpg"
        ff("-f", "lavfi", "-i", "color=c=teal:s=64x64", "-frames:v", "1", cover)
        cls.track = cls.source / "01. 中文 曲目.m4a"
        ff("-f", "lavfi", "-i", "sine=frequency=997:sample_rate=96000:duration=2.5",
           "-i", cover, "-map", "0:a", "-map", "1:v", "-ac", "2", "-c:a", "alac",
           "-sample_fmt", "s32p", "-c:v", "copy", "-disposition:v", "attached_pic",
           "-metadata", "title=测试标题", "-metadata", "artist=测试艺人",
           "-metadata", "album=测试专辑", "-metadata", "lyrics=测试歌词", cls.track)
        cls.track.with_suffix(".lrc").write_text("[00:00.00]测试歌词\n", encoding="utf-8")

    def pipeline(self, name):
        output = self.base / name
        # All tests use their own output; don't erase anything from prior runs.
        suffix = 1
        while output.exists():
            output = self.base / f"{name}-{suffix}"
            suffix += 1
        return Pipeline(dataclasses.replace(self.settings, output=str(output)))

    def test_real_alac_to_flac_and_aac_metadata_and_resume(self):
        pipe = self.pipeline("roundtrip")
        pipe.convert([self.track], self.source.parent.parent, ("flac", "aac"))
        self.assertEqual([r.status for r in pipe.results], ["完成", "完成"], [r.detail for r in pipe.results])
        for result in pipe.results:
            output = Path(result.output)
            self.assertTrue(output.with_suffix(".lrc").is_file())
            _, info = pipe.run_process([pipe.settings.ffmpeg, "-hide_banner", "-i", output])
            for text in ("测试标题", "测试艺人", "测试专辑", "测试歌词", "attached pic"):
                self.assertIn(text, info)
        flac = Path(pipe.results[0].output)
        self.assertEqual(pipe.pcm_hash(self.track), pipe.pcm_hash(flac))
        aac = pipe.probe(Path(pipe.results[1].output))
        self.assertEqual((aac.codec, aac.profile, aac.rate), ("aac", "LC", 96000))
        pipe.convert([self.track], self.source.parent.parent, ("flac", "aac"))
        self.assertEqual([r.status for r in pipe.results[-2:]], ["已验证并跳过", "已验证并跳过"])
        report = pipe.finish()
        self.assertEqual(len(report["results"]), 4)
        self.assertTrue(pipe.report_path.is_file())

    def test_corrupt_owned_target_is_not_overwritten(self):
        pipe = self.pipeline("corrupt")
        pipe.convert([self.track], self.source, ("flac",))
        self.assertEqual(pipe.results[0].status, "完成", pipe.results[0].detail)
        target = Path(pipe.results[0].output)
        target.write_bytes(b"broken file")
        pipe.convert([self.track], self.source, ("flac",))
        self.assertEqual(pipe.results[-1].status, "失败")
        self.assertEqual(target.read_bytes(), b"broken file")

    def test_encoder_failure_does_not_publish_partial_output(self):
        pipe = self.pipeline("encoder-failure")
        real_run = pipe.run_process

        def fail_encoder(args, **kwargs):
            if str(args[0]) == pipe.settings.freac:
                path = Path(args[args.index("-o") + 1])
                path.write_bytes(b"partial")
                return 1, "simulated encoder failure"
            return real_run(args, **kwargs)

        with patch.object(pipe, "run_process", side_effect=fail_encoder):
            pipe.convert([self.track], self.source, ("flac",))
        self.assertEqual(pipe.results[0].status, "失败")
        self.assertFalse(list(Path(pipe.settings.output).rglob("*.flac")))
        self.assertFalse(list(Path(pipe.settings.output).rglob(".amdl-stage-*")))

    def test_cancel_does_not_start_encoder(self):
        pipe = self.pipeline("canceled")
        pipe.stop.set()
        pipe.convert([self.track], self.source, ("flac", "aac"))
        self.assertEqual([r.status for r in pipe.results], ["已取消", "已取消"])
        self.assertFalse(Path(pipe.settings.output).exists())

    def test_lossy_input_is_rejected(self):
        source = self.source / "有损.mp3"
        self.ff("-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libmp3lame", source)
        pipe = self.pipeline("lossy")
        pipe.convert([source], self.source, ("flac", "aac"))
        self.assertTrue(all(r.status == "失败" and "有损" in r.detail for r in pipe.results))

    def test_192k_aac_and_corrupt_source(self):
        source = self.source / "192k.wav"
        self.ff("-f", "lavfi", "-i", "sine=sample_rate=192000:duration=1", "-ac", "2", "-c:a", "pcm_s24le", source)
        pipe = self.pipeline("highrate")
        pipe.convert([source], self.source, ("aac",))
        self.assertEqual(pipe.results[0].status, "完成", pipe.results[0].detail)
        self.assertEqual(pipe.probe(pipe.results[0].output).rate, 96000)
        broken = self.source / "broken.m4a"
        broken.write_bytes(b"broken")
        pipe.convert([broken], self.source, ("flac",))
        self.assertEqual(pipe.results[-1].status, "失败")

    def test_collision_detected_before_encoding(self):
        other = self.track.with_suffix(".flac")
        shutil.copyfile(self.track, other)
        pipe = self.pipeline("collision")
        with self.assertRaisesRegex(ValueError, "同名"):
            pipe.convert([self.track, other], self.source, ("flac",))
        self.assertFalse(pipe.results)

    def test_download_command_and_missing_service(self):
        album = "https://music.apple.com/us/album/example/123"
        song = album + "?i=456"
        links = parse_links(album + "\n" + song + "\n" + song)
        self.assertEqual(len(links), 2)
        self.assertNotIn("-song", download_command(self.settings, album, self.base))
        self.assertIn("-song", download_command(self.settings, song, self.base))
        with self.assertRaises(ValueError):
            parse_links("https://music.apple.com.evil.example/album/123")
        pipe = self.pipeline("service")
        with patch("music_core.service_status", return_value={10020: False, 20020: False}):
            with self.assertRaisesRegex(ValueError, "尚未就绪"):
                pipe.download(links, ("flac",))

    def test_scan_excludes_generated_outputs(self):
        pipe = self.pipeline("scan")
        output = Path(pipe.settings.output)
        (output / "FLAC").mkdir(parents=True)
        (output / "FLAC" / "generated.flac").write_bytes(b"x")
        self.assertFalse(scan_folder(output, output))


if __name__ == "__main__":
    unittest.main(verbosity=2)
