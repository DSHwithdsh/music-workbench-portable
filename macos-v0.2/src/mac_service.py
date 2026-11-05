"""App-owned ARM64 Docker service; no credentials in Docker config or scripts."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import subprocess
import uuid
import zipfile

from mac_runtime import ROOT, RESOURCES

WRAPPER_SHA = "8de5da67e375038ff5a08761c71ccaf90ac5ec711a6d0924ba7328b5e116e0a6"
PREFIX = "musicworkbench-mac-"
LABEL = "org.musicworkbench.owner"
IMAGE = "musicworkbench-wrapper-arm64:" + WRAPPER_SHA[:12]


def docker_binary():
    candidates = [Path("/Applications/Docker.app/Contents/Resources/bin/docker"),
                  Path("/opt/homebrew/bin/docker"), Path("/usr/local/bin/docker")]
    if found := shutil.which("docker"):
        candidates.append(Path(found))
    return next((p for p in candidates if p.is_file()), candidates[0])


def call(*args, capture=True):
    command = [str(docker_binary()), *map(str, args)]
    result = subprocess.run(command, capture_output=capture, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError("Docker 操作失败，请检查 Docker Desktop 是否启动：" + (result.stderr[-1500:] if capture else str(result.returncode)))
    return result


def read_state():
    path = ROOT / "service-runtime/service.json"
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    identity = state.get("id", "")
    if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity) or state.get("name") != PREFIX + identity[:12]:
        raise ValueError("服务状态不属于本 Mac 工作台，未操作容器")
    return state


def ports():
    ready = []
    for port in (10020, 20020):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                ready.append(port)
        except OSError:
            pass
    return ready


def plan():
    return {"operation": "plan only; no Docker commands or service state writes", "platform": "linux/arm64",
            "image": IMAGE, "container": PREFIX + "<unique-id>",
            "host_ports": ["127.0.0.1:10020:10020", "127.0.0.1:20020:20020"],
            "account_storage": str(ROOT / "service-runtime/account"),
            "credentials": "entered inside interactive container; never passed as Docker environment, command arguments or log input",
            "other_containers": "never replaced, stopped or removed", "privileged": False,
            "macOS_runtime": "not yet verified"}


def unpack_wrapper(destination):
    archive = RESOURCES / "service/Wrapper.arm64.latest.zip"
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != WRAPPER_SHA:
            raise ValueError("ARM64 服务素材校验失败")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("服务构建目录必须为空")
    destination.mkdir(parents=True, exist_ok=True)
    symlinks = []
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            relative = PurePosixPath(member.filename)
            if relative.is_absolute() or ".." in relative.parts or "\\" in member.filename:
                raise ValueError("服务压缩包包含不安全路径")
            if not relative.parts or relative.parts[0] not in ("wrapper", "rootfs"):
                continue
            if str(relative).startswith("rootfs/data/") and not member.is_dir() and not member.filename.endswith(".gitkeep"):
                raise ValueError("服务素材意外包含账号文件，未继续")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = member.external_attr >> 16
            if member.is_dir():
                target.mkdir(exist_ok=True)
            elif mode & 0o170000 == 0o120000:
                link = source.read(member).decode("utf-8")
                # Android images use absolute /system links; retain inside image only.
                symlinks.append((link, target))
            else:
                target.write_bytes(source.read(member))
                target.chmod(mode & 0o777 or 0o644)
    # Install links last, so no archive member can write through an earlier link.
    for link, target in symlinks:
        if target.exists():
            raise ValueError("服务素材存在文件与链接路径冲突")
        os.symlink(link, target)
    (destination / "wrapper").chmod(0o755)
    for name in ("Dockerfile", "login.sh"):
        shutil.copy2(RESOURCES / "service" / name, destination / name)


def owned_container(state):
    result = subprocess.run([str(docker_binary()), "container", "inspect", state["name"]], capture_output=True, text=True)
    if result.returncode:
        # Confirm daemon availability; an inspect error alone is not proof of absence.
        call("info", "--format", "{{.ServerVersion}}")
        return None
    data = json.loads(result.stdout)[0]
    if data.get("Config", {}).get("Labels", {}).get(LABEL) != state["id"]:
        raise ValueError("同名容器不属于本工作台，未操作")
    return data


def prepare():
    if not docker_binary().is_file():
        raise RuntimeError("请先安装 Apple Silicon 版 Docker Desktop 并启动，然后重试")
    call("info", "--format", "{{.ServerVersion}}")
    runtime = ROOT / "service-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    state = read_state()
    if state is None:
        identity = uuid.uuid4().hex
        state = {"id": identity, "name": PREFIX + identity[:12]}
        with (runtime / "service.json").open("x", encoding="utf-8") as stream:
            json.dump(state, stream)
    existing = owned_container(state)
    if existing is not None:
        return state
    image = subprocess.run([str(docker_binary()), "image", "inspect", IMAGE], capture_output=True, text=True)
    if image.returncode == 0:
        labels = json.loads(image.stdout)[0].get("Config", {}).get("Labels", {})
        if labels.get("org.musicworkbench.wrapper-sha256") != WRAPPER_SHA:
            raise ValueError("同名镜像来源不符，未覆盖")
    else:
        context = runtime / ("build-" + uuid.uuid4().hex[:8])
        unpack_wrapper(context)
        print("首次构建独立 ARM64 服务镜像，需要联网获取 Debian 基础镜像。", flush=True)
        call("build", "--platform", "linux/arm64", "--label", "org.musicworkbench.wrapper-sha256=" + WRAPPER_SHA,
             "-t", IMAGE, context, capture=False)
    account = runtime / "account"
    account.mkdir(exist_ok=True)
    account.chmod(0o700)
    call("create", "--platform", "linux/arm64", "-it", "--name", state["name"], "--label", LABEL + "=" + state["id"],
         "-p", "127.0.0.1:10020:10020", "-p", "127.0.0.1:20020:20020",
         "--mount", f"type=bind,source={account},target=/app/rootfs/data",
         "--entrypoint", "/app/workbench-login.sh", IMAGE)
    return state


def start():
    ready = ports()
    if len(ready) == 2:
        print("端口已就绪，继续使用已有服务，未操作容器。")
        return
    if ready:
        raise ValueError("只有一个服务端口被占用，请先检查已有服务")
    state = prepare()
    data = owned_container(state)
    try:
        if data["State"]["Running"]:
            call("attach", state["name"], capture=False)
        else:
            print("请在下方登录自己的 Apple Music 账号；下载结束后可按 Ctrl+C 结束此独立服务。", flush=True)
            call("start", "-ai", state["name"], capture=False)
    except KeyboardInterrupt:
        stop()


def stop():
    state = read_state()
    if state is None:
        print("没有本工作台的独立容器记录，未操作其他容器。")
        return
    data = owned_container(state)
    if data is not None and data["State"]["Running"]:
        call("stop", "--time", "10", state["name"])
        print("本工作台独立容器已停止；账号数据保留，其他容器未操作。")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args(argv)
    if args.plan:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
    elif args.stop:
        stop()
    elif args.setup:
        prepare()
    else:
        start()


if __name__ == "__main__":
    main()
