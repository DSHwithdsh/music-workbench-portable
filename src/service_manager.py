"""Independent WSL1 service setup. Never modifies an existing distribution."""
from __future__ import annotations

import argparse
import ctypes
import getpass
import gzip
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
PREFIX = "MusicWorkbench-Portable-"


def read_state():
    path = ROOT / "service-runtime/service.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    identifier = data["id"]
    if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
        raise ValueError("服务记录 ID 无效，未执行 WSL 操作")
    if data["name"] != PREFIX + identifier[:12]:
        raise ValueError("服务名称不属于本便携版，未执行 WSL 操作")
    expected = (ROOT / "service-runtime/distro").resolve()
    if Path(data["install_dir"]).resolve() != expected:
        raise ValueError("服务环境安装后移动过目录。请移回安装时的位置；主程序和转码仍可便携运行。")
    return data


def write_state(data):
    path = ROOT / "service-runtime/service.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def call(args, **kwargs):
    return subprocess.run([str(a) for a in args], **kwargs)


def list_distributions():
    try:
        result = call(["wsl.exe", "--list", "--quiet"], capture_output=True)
    except FileNotFoundError:
        return -1, []
    output = result.stdout.decode("utf-16-le", "replace").replace("\x00", "")
    return result.returncode, [line.strip() for line in output.splitlines() if line.strip()]


def plan():
    return {"root": str(ROOT), "operation": "plan-only; no WSL or OS changes",
            "distro_name": PREFIX + "<new-random-id>",
            "install_dir": str(ROOT / "service-runtime/distro"),
            "rootfs": str(ROOT / "service/clean-rootfs.tar.gz"),
            "import": ["wsl.exe", "--import", PREFIX + "<new-random-id>", "<portable-root>/service-runtime/distro", "<portable-root>/service-runtime/import.tar", "--version", "1"],
            "existing_distributions": "never shutdown, convert, overwrite or unregister"}


def enable_wsl():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("启用 WSL 组件需要管理员权限")
    print("仅启用 WSL 1 Windows 组件；不安装默认发行版、不更改现有发行版。", flush=True)
    code = call(["dism.exe", "/online", "/enable-feature", "/featurename:Microsoft-Windows-Subsystem-Linux", "/all", "/norestart"]).returncode
    if code not in (0, 3010):
        raise RuntimeError(f"WSL 组件启用失败，退出码 {code}")
    print("组件准备完成。请保存工作并手动重启电脑，再双击“一键准备解密服务”。不会自动重启。")


def request_feature_setup():
    print("Windows 未能导入 WSL1 环境。接下来仅请求管理员权限启用 WSL 1 组件。")
    print("如新版 WSL 仍提示未启用 WSL1，可在管理员终端运行：wsl --install --no-distribution --enable-wsl1")
    if input("现在启用 WSL 1 组件？输入 Y 继续，其他键退出：").strip().lower() != "y":
        return False
    executable = str(Path(sys.executable).resolve())
    parameters = "--enable-wsl" if getattr(sys, "frozen", False) else subprocess.list2cmdline([str(Path(__file__).resolve()), "--enable-wsl"])
    code = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, parameters, str(ROOT), 1)
    if code <= 32:
        raise RuntimeError("没有获得组件启用权限；未继续安装")
    return False


def verify_archive():
    archive = ROOT / "service/clean-rootfs.tar.gz"
    manifest = json.loads((ROOT / "service/rootfs-manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != manifest["sha256"]:
        raise RuntimeError("离线服务文件校验失败，请重新完整解压便携包")
    return archive


def setup():
    print("Music 工作台：独立解密服务准备\n仅创建 MusicWorkbench-Portable-* 环境。", flush=True)
    state = read_state()
    code, names = list_distributions()
    if code:
        return request_feature_setup()
    if state and state["name"] in names:
        print("本便携版环境已存在，跳过安装。")
        return True
    if not state:
        identifier = uuid.uuid4().hex
        state = {"id": identifier, "name": PREFIX + identifier[:12],
                 "install_dir": str((ROOT / "service-runtime/distro").resolve())}
        write_state(state)
    if state["name"] in names:
        raise RuntimeError("服务名称已被占用，未覆盖现有环境")
    archive = verify_archive()
    runtime = ROOT / "service-runtime"
    install = Path(state["install_dir"])
    if install.exists() and any(install.iterdir()):
        raise RuntimeError("新环境目录非空但 WSL 未注册；保留现场，未覆盖。请检查 service-runtime。")
    install.mkdir(parents=True, exist_ok=True)
    expanded = runtime / "import.tar"
    try:
        print("校验通过，解压离线系统…", flush=True)
        with gzip.open(archive, "rb") as src, expanded.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        print("注册独立 WSL1 环境，不会停止其他发行版…", flush=True)
        result = call(["wsl.exe", "--import", state["name"], install, expanded, "--version", "1"])
        if result.returncode:
            print(f"导入未成功，退出码 {result.returncode}。现有环境保持不变。")
            return request_feature_setup()
    finally:
        expanded.unlink(missing_ok=True)
    check = call(["wsl.exe", "-d", state["name"], "-u", "root", "--", "/bin/sh", "-c", "test -x /root/wrapper && test -x /root/rootfs/system/bin/main"])
    if check.returncode:
        raise RuntimeError("已导入，但 wrapper 文件检查失败；未启动登录")
    print("独立解密环境准备完成。")
    return True


def ports_ready():
    ports = []
    for port in (10020, 20020):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                ports.append(port)
        except OSError:
            pass
    return ports


def start():
    ports = ports_ready()
    if len(ports) == 2:
        print("端口已经就绪，使用现有服务；没有启动或改动其他环境。")
        return
    if ports:
        raise RuntimeError("10020/20020 中只有一个端口被占用，请先检查已有服务；未启动新服务")
    if not setup():
        return
    state = read_state()
    print("请在本机输入自己的 Apple Music 账号。密码不会写入脚本或便携包。")
    user = input("Apple ID: ").strip()
    password = getpass.getpass("密码（输入不显示）: ")
    if not user or not password:
        raise RuntimeError("账号或密码为空，未启动服务")
    print("下载期间保持此窗口打开；验证码如有提示请在本窗口输入。Ctrl+C 可结束本便携版服务。")
    args = ["wsl.exe", "-d", state["name"], "-u", "root", "--", "/bin/sh", "-c",
            'cd /root && exec /root/wrapper -H 127.0.0.1 -L "$1"', "workbench", user + ":" + password]
    try:
        process = subprocess.Popen(args)
        password = ""
        args[-1] = "[not retained]"
        process.wait()
    except KeyboardInterrupt:
        # This is our uniquely named service only; never use global --shutdown.
        call(["wsl.exe", "--terminate", state["name"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("本便携版服务已结束，其他 WSL 环境未受影响。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--enable-wsl", action="store_true")
    options = parser.parse_args()
    if options.plan:
        print(json.dumps(plan(), ensure_ascii=True, indent=2))
        return
    try:
        if options.enable_wsl:
            enable_wsl()
        elif options.start:
            start()
        else:
            setup()
    except Exception as exc:
        print("\n错误：", exc)
        sys.exitcode = 1
    finally:
        input("\n按 Enter 关闭此窗口…")
    if getattr(sys, "exitcode", 0):
        raise SystemExit(sys.exitcode)


if __name__ == "__main__":
    main()
