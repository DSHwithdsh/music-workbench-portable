"""Platform contracts runnable on the host; these do not claim macOS execution."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile

import mac_runtime as runtime
import mac_service as service
from music_tags import launch_musictag


class MacPortTests(unittest.TestCase):
    def test_coreaudio_command_uses_mac_codec_options(self):
        settings = SimpleNamespace(freac="/Applications/freac.app/Contents/MacOS/freaccmd", aac_encoder="coreaudio")
        command = runtime.encoder_command(settings, "aac", "/tmp/中文 music.m4a", "/tmp/source.m4a", 2)
        self.assertIn("--encoder=coreaudio", command)
        self.assertEqual(command[-5:-1], ["-f", "AAC", "-b", "128"])
        self.assertNotIn("LC", command)
        self.assertIn("/tmp/中文 music.m4a", command)

    def test_flac_command_preserves_level_six(self):
        command = runtime.encoder_command(SimpleNamespace(freac="freaccmd", aac_encoder="coreaudio"), "flac", "out.flac", "in.m4a", 4)
        self.assertIn("--encoder=flac", command)
        self.assertEqual(command[-3:], ["-c", "6", "in.m4a"])

    def test_engine_update_preserves_user_configuration(self):
        with tempfile.TemporaryDirectory(dir=runtime.ROOT) as temp:
            base = Path(temp)
            assets = base / "assets/tools/amdl"
            assets.mkdir(parents=True)
            (assets / "downloader").write_bytes(b"native binary v1")
            (assets / "config.yaml").write_text("fresh default")
            with patch.object(runtime, "ROOT", base / "state"), patch.object(runtime, "RESOURCES", base / "assets"):
                target = runtime.initialize_engine()
                (target / "config.yaml").write_text("user config")
                (assets / "downloader").write_bytes(b"native binary v2")
                runtime.initialize_engine()
                self.assertEqual((target / "downloader").read_bytes(), b"native binary v2")
                self.assertEqual((target / "config.yaml").read_text(), "user config")

    def test_service_plan_runs_no_docker_and_writes_no_service_state(self):
        with tempfile.TemporaryDirectory(dir=runtime.ROOT) as temp, patch.object(service, "ROOT", Path(temp)), patch.object(service, "call", side_effect=AssertionError("No Docker")):
            plan = service.plan()
            self.assertEqual(plan["platform"], "linux/arm64")
            self.assertEqual(plan["host_ports"], ["127.0.0.1:10020:10020", "127.0.0.1:20020:20020"])
            self.assertFalse(list(Path(temp).iterdir()))

    def test_service_state_rejects_foreign_container_name(self):
        with tempfile.TemporaryDirectory(dir=runtime.ROOT) as temp:
            root = Path(temp)
            (root / "service-runtime").mkdir()
            (root / "service-runtime/service.json").write_text(json.dumps({"id": "0" * 32, "name": "someone-else"}))
            with patch.object(service, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "不属于"):
                    service.read_state()

    def test_foreign_container_label_cannot_be_operated(self):
        response = SimpleNamespace(returncode=0, stdout=json.dumps([{"Config": {"Labels": {service.LABEL: "other"}}}]))
        with patch.object(service.subprocess, "run", return_value=response):
            with self.assertRaisesRegex(ValueError, "不属于"):
                service.owned_container({"id": "0" * 32, "name": service.PREFIX + "0" * 12})

    def test_external_mac_app_opens_with_safe_argument_list(self):
        with tempfile.TemporaryDirectory(dir=runtime.ROOT) as temp:
            root = Path(temp)
            app = root / "标签应用.app"
            app.mkdir()
            folder = root / "音乐 folder"
            folder.mkdir()
            with patch("music_tags.subprocess.Popen") as popen:
                launch_musictag(app, folder)
                self.assertEqual(popen.call_args.args[0], ["/usr/bin/open", "-a", str(app), str(folder.resolve())])
            with self.assertRaisesRegex(ValueError, ".app"):
                launch_musictag(root / "MusicTag.exe", folder)

    def test_service_script_quotes_source_path_and_contains_no_credentials(self):
        with tempfile.TemporaryDirectory(dir=runtime.ROOT) as temp, patch.object(runtime, "ROOT", Path(temp)), patch.object(runtime, "FROZEN", False), patch.object(runtime.subprocess, "Popen") as popen:
            runtime.launch_service()
            script = next(Path(temp).glob("*.command"))
            text = script.read_text(encoding="utf-8")
            self.assertIn("--service", text)
            self.assertNotIn("PASSWORD", text)
            self.assertEqual(popen.call_args.args[0], ["/usr/bin/open", "-a", "Terminal", str(script)])

    def test_wrapper_traversal_is_rejected_before_outside_write(self):
        with tempfile.TemporaryDirectory(dir=runtime.ROOT) as temp:
            root = Path(temp)
            assets = root / "assets/service"
            assets.mkdir(parents=True)
            archive = assets / "Wrapper.arm64.latest.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("../escape.txt", "bad")
            expected = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(service, "RESOURCES", root / "assets"), patch.object(service, "WRAPPER_SHA", expected):
                with self.assertRaisesRegex(ValueError, "不安全"):
                    service.unpack_wrapper(root / "output")
            self.assertFalse((root / "escape.txt").exists())

    def test_wrapper_account_material_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=runtime.ROOT) as temp:
            root = Path(temp)
            assets = root / "assets/service"
            assets.mkdir(parents=True)
            archive = assets / "Wrapper.arm64.latest.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("rootfs/data/account.db", "private")
            expected = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(service, "RESOURCES", root / "assets"), patch.object(service, "WRAPPER_SHA", expected):
                with self.assertRaisesRegex(ValueError, "账号"):
                    service.unpack_wrapper(root / "output")

    def test_stop_only_targets_verified_owned_container(self):
        state = {"id": "0" * 32, "name": service.PREFIX + "0" * 12}
        with patch.object(service, "read_state", return_value=state), patch.object(service, "owned_container", return_value={"State": {"Running": True}}), patch.object(service, "call") as call:
            service.stop()
            call.assert_called_once_with("stop", "--time", "10", state["name"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
