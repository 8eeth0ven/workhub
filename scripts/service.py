#!/usr/bin/env python3
"""Manage Agent Workhub as a detached session service or optional launchd job.

An explicit --home is staging-only: it never invokes launchctl, even on macOS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
from xml.parsers.expat import ExpatError


REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "workhub.py"
LABEL = "local.agent-workhub"
LAUNCHCTL = "/bin/launchctl"


class ServiceError(Exception):
    pass


def require_inside(path: Path, root: Path) -> None:
    if not path.parent.resolve().is_relative_to(root.resolve()):
        raise ServiceError(f"父目录链接超出服务配置范围：{path}")


def load_owned(path: Path) -> dict | None:
    if path.is_symlink():
        raise ServiceError(f"拒绝覆盖符号链接配置：{path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise ServiceError(f"服务配置不是普通文件：{path}")
    try:
        with path.open("rb") as stream:
            value = plistlib.load(stream)
    except (plistlib.InvalidFileException, ValueError, TypeError, ExpatError) as error:
        raise ServiceError(f"已有 plist 无法解析，未覆盖：{path}") from error
    arguments = value.get("ProgramArguments", []) if isinstance(value, dict) else []
    environment = value.get("EnvironmentVariables", {}) if isinstance(value, dict) else {}
    runtime_backend = str(Path(environment.get("AGENT_WORKHUB_HOME", "/nonexistent")) / "runtime/workhub.py") if isinstance(environment, dict) else ""
    owned_runtime = (isinstance(environment, dict) and
                     environment.get("AGENT_WORKHUB_SOURCE_REPOSITORY") == str(REPO) and
                     isinstance(arguments, list) and len(arguments) >= 2 and arguments[1] == runtime_backend)
    if (not isinstance(value, dict) or value.get("Label") != LABEL or
            not isinstance(arguments, list) or len(arguments) < 2 or
            (arguments[1] != str(BACKEND) and not owned_runtime)):
        raise ServiceError(f"同名服务配置不属于当前仓库，未覆盖：{path}")
    return value


def configuration(home: Path, data: Path, port: int) -> dict:
    logs = data / "logs"
    runtime = data / "runtime"
    return {
        "Label": LABEL,
        "ProgramArguments": [str(Path(sys.executable).resolve()), str(runtime / "workhub.py"), "serve", "--host", "127.0.0.1", "--port", str(port)],
        "WorkingDirectory": str(runtime),
        "EnvironmentVariables": {"AGENT_WORKHUB_HOME": str(data), "AGENT_WORKHUB_SOURCE_REPOSITORY": str(REPO), "PYTHONUNBUFFERED": "1"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "service.stdout.log"),
        "StandardErrorPath": str(logs / "service.stderr.log"),
    }


def runtime_payload() -> dict[str, bytes]:
    """Snapshot only product code/assets, never project records or secrets."""
    payload = {module: (REPO / module).read_bytes() for module in ("workhub.py", "assessments.py")}
    for name in ("static", "templates"):
        directory = REPO / name
        if not directory.is_dir() or directory.is_symlink():
            raise ServiceError(f"运行资源目录缺失或为符号链接：{directory}")
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ServiceError(f"运行资源不可包含符号链接：{path}")
            if path.is_file() and not any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(directory).parts):
                payload[str(path.relative_to(REPO))] = path.read_bytes()
    return payload


def runtime_manifest(payload: dict[str, bytes]) -> dict:
    return {"source_repository": str(REPO), "files": {
        name: hashlib.sha256(content).hexdigest() for name, content in sorted(payload.items())}}


def runtime_matches(directory: Path, payload: dict[str, bytes]) -> bool:
    require_inside(directory / "workhub.py", directory.parent)
    if directory.is_symlink():
        raise ServiceError(f"运行目录不可是符号链接：{directory}")
    if not directory.exists():
        return False
    marker = directory / ".workhub-runtime.json"
    try:
        previous = json.loads(marker.read_text())
    except (OSError, ValueError) as error:
        raise ServiceError(f"已有 runtime 缺少归属记录，未覆盖：{directory}") from error
    if previous.get("source_repository") != str(REPO):
        raise ServiceError(f"已有 runtime 不属于当前仓库，未覆盖：{directory}")
    if previous != runtime_manifest(payload):
        return False
    for name, content in payload.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
            return False
    return True


def sync_runtime(directory: Path, payload: dict[str, bytes]) -> bool:
    if runtime_matches(directory, payload):
        return False
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staged = Path(tempfile.mkdtemp(prefix=".workhub-runtime-", dir=directory.parent))
    old = directory.parent / f".workhub-runtime-old-{uuid.uuid4().hex}"
    moved_old = False
    try:
        for name, content in payload.items():
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        (staged / ".workhub-runtime.json").write_text(json.dumps(runtime_manifest(payload), ensure_ascii=False, indent=2))
        if directory.exists():
            directory.rename(old)
            moved_old = True
        staged.rename(directory)
    except BaseException:
        if moved_old and not directory.exists():
            old.rename(directory)
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)
        if old.exists() and directory.exists():
            shutil.rmtree(old)
    return True


def atomic_plist(path: Path, value: dict) -> None:
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{LABEL}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            plistlib.dump(value, stream, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def launchctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run([LAUNCHCTL, *arguments], capture_output=True, text=True, timeout=15)
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"退出码 {result.returncode}"
        raise ServiceError(f"launchctl {' '.join(arguments[:1])} 失败：{detail}")
    return result


def loaded_job(target: str, allowed_backends=None) -> tuple[bool, bool]:
    result = launchctl("print", target, check=False)
    if result.returncode:
        return False, False
    if not any(path in result.stdout for path in (allowed_backends or [str(BACKEND)])):
        raise ServiceError(f"已加载的同名 launchd 任务不属于当前仓库，未操作：{target}")
    running = any(line.strip().startswith("pid = ") for line in result.stdout.splitlines())
    return True, running


def is_port_open(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def health(port: int) -> bool:
    try:
        # Never send local health checks through a configured external proxy.
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=0.8) as response:
            result = json.load(response)
        return result.get("ok") is True and result.get("service") == "agent-workhub"
    except (OSError, URLError, ValueError, AttributeError):
        return False


def stored_port(value: dict) -> int:
    arguments = value["ProgramArguments"]
    try:
        port = int(arguments[arguments.index("--port") + 1])
    except (ValueError, IndexError, TypeError) as error:
        raise ServiceError("已有服务缺少有效端口，请重新执行 install --port") from error
    if not 1 <= port <= 65535:
        raise ServiceError("已有服务端口无效，请重新执行 install --port")
    return port


def process_identity(pid: int) -> tuple[str, str] | None:
    if not isinstance(pid, int) or pid <= 1:
        return None
    started = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, timeout=3)
    command = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=3)
    if started.returncode or command.returncode:
        return None
    return started.stdout.strip(), command.stdout.strip()


def owned_session_running(value: dict) -> bool:
    identity = process_identity(value.get("pid"))
    return bool(identity and identity[0] == value.get("started") and
                identity[1] == value.get("command") and str(BACKEND) in identity[1])


def write_session(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".workhub-session-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def session_main(args, home: Path, data: Path, staging: bool) -> int:
    record = data / "session.json"
    require_inside(record, data)
    if record.is_symlink():
        raise ServiceError(f"后台服务记录不可是符号链接：{record}")
    value = None
    if record.exists():
        try:
            value = json.loads(record.read_text())
        except (ValueError, UnicodeError) as error:
            raise ServiceError("后台服务记录格式无效，未操作任何进程") from error
        if not isinstance(value, dict):
            raise ServiceError("后台服务记录必须是对象，未操作任何进程")
        if value.get("source_repository") != str(REPO) or value.get("backend") != str(BACKEND):
            raise ServiceError(f"已有后台服务记录不属于当前仓库，未操作：{record}")
    if args.action in ("start", "stop") and value is None:
        raise ServiceError("尚未安装独立后台服务，请先执行 install --mode session")
    port = args.port or (value.get("port") if value else 8765)
    command = [str(Path(sys.executable).resolve()), str(BACKEND), "serve", "--host", "127.0.0.1", "--port", str(port)]
    result = {"action": args.action, "mode": "session", "staging_only": staging, "dry_run": args.dry_run,
              "record": str(record), "url": f"http://127.0.0.1:{port}", "logs": str(data / "logs"),
              "note": "当前登录会话的独立后台进程，不依赖聊天保活；没有设置自动登录启动。"}
    if args.dry_run:
        result["process_plan"] = command if args.action in ("install", "start") else args.action
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    running = bool(value and not staging and owned_session_running(value))
    if args.action in ("stop", "uninstall"):
        if running:
            os.kill(value["pid"], signal.SIGTERM)
            for _ in range(30):
                if not owned_session_running(value):
                    break
                time.sleep(0.1)
            else:
                raise ServiceError("已发送停止信号但该后台进程仍未退出；未操作其他进程")
        if args.action == "uninstall" and record.exists():
            record.unlink()
        result.update(installed=record.exists(), running=False, healthy=False)
    elif args.action == "status":
        result.update(installed=value is not None, running=running, healthy=health(port) if running else False,
                      pid=value.get("pid") if value else None)
    elif staging:
        write_session(record, {"source_repository": str(REPO), "backend": str(BACKEND), "port": port, "pid": None})
        result.update(installed=True, running=False, healthy=False)
    else:
        if running and value["port"] != port:
            if is_port_open(port):
                raise ServiceError(f"端口 {port} 已占用；保留当前后台服务")
            os.kill(value["pid"], signal.SIGTERM)
            for _ in range(30):
                if not owned_session_running(value):
                    running = False
                    break
                time.sleep(0.1)
            if running:
                raise ServiceError("旧后台服务未退出，未启动重复实例")
        if not running:
            if is_port_open(port):
                raise ServiceError(f"端口 {port} 已被现有进程占用，未停止它；请选择其他端口")
            logs = data / "logs"
            require_inside(logs / "session.stdout.log", data)
            logs.mkdir(parents=True, exist_ok=True, mode=0o700)
            environment = dict(os.environ, AGENT_WORKHUB_HOME=str(data), PYTHONUNBUFFERED="1")
            with (logs / "session.stdout.log").open("ab") as stdout, (logs / "session.stderr.log").open("ab") as stderr:
                process = subprocess.Popen(command, cwd=REPO, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=stdout, stderr=stderr, start_new_session=True, close_fds=True)
            identity = process_identity(process.pid)
            if identity is None:
                raise ServiceError("后台进程启动后立即退出，请查看日志")
            value = {"source_repository": str(REPO), "backend": str(BACKEND), "port": port,
                     "pid": process.pid, "started": identity[0], "command": identity[1]}
            write_session(record, value)
        for _ in range(40):
            if owned_session_running(value) and health(port):
                result.update(installed=True, running=True, healthy=True, pid=value["pid"])
                break
            if not owned_session_running(value):
                raise ServiceError("后台进程已退出，请查看日志")
            time.sleep(0.25)
        else:
            raise ServiceError("后台进程存在但健康检查失败，请查看日志；可用 stop --mode session 停止")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "start", "status", "stop", "uninstall"))
    parser.add_argument("--port", type=int, help="install 的监听端口，默认 8765")
    parser.add_argument("--mode", choices=("session", "launchd"), help="session 为独立后台；launchd 为可选自动登录启动。已装 session 时自动选它")
    parser.add_argument("--home", type=Path, help="仅暂存配置到该目录；绝不注册或操作真实 launchd")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不写入或操作服务")
    args = parser.parse_args(argv)
    if os.name != "posix" and not args.home and not args.dry_run:
        raise ServiceError("后台服务管理当前支持 macOS/Linux；其他系统请直接运行 workhub.py serve")
    if args.port is not None and (args.action != "install" or not 1 <= args.port <= 65535):
        parser.error("--port 仅用于 install，范围为 1 至 65535")
    staging = args.home is not None
    home = (args.home if staging else Path.home()).expanduser().resolve()
    data = (home / ".local/share/agent-workhub" if staging else Path(
        os.environ.get("AGENT_WORKHUB_HOME", str(home / ".local/share/agent-workhub"))
    )).expanduser().resolve()
    plist = home / "Library/LaunchAgents" / f"{LABEL}.plist"
    if args.mode == "session" or (args.mode is None and ((data / "session.json").exists() or not plist.exists())):
        return session_main(args, home, data, staging)
    require_inside(plist, home)
    if "AGENT_WORKHUB_HOME" not in os.environ:
        require_inside(home / ".local/share/agent-workhub/logs", home)
    require_inside(data / "logs/service.stdout.log", data)
    existing = load_owned(plist)
    if existing is not None and args.action != "install":
        stored_environment = existing.get("EnvironmentVariables", {})
        if not isinstance(stored_environment, dict):
            raise ServiceError("已有服务环境配置无效，请重新执行 install")
        stored_data = stored_environment.get("AGENT_WORKHUB_HOME")
        if stored_data:
            data = Path(stored_data).expanduser().resolve()
    if args.action == "install" and not BACKEND.is_file():
        raise ServiceError(f"找不到服务程序：{BACKEND}")
    if args.action in ("start", "stop") and existing is None:
        raise ServiceError(f"尚未安装服务，请先执行 install；配置位置：{plist}")
    desired = configuration(home, data, args.port or 8765) if args.action == "install" else existing
    payload = runtime_payload() if args.action == "install" else None
    runtime = data / "runtime"
    needs_sync = not runtime_matches(runtime, payload) if payload is not None else False
    port = stored_port(desired) if desired is not None else args.port or 8765
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{LABEL}"
    result = {
        "action": args.action, "label": LABEL, "plist": str(plist),
        "staging_only": staging, "dry_run": args.dry_run,
        "url": f"http://127.0.0.1:{port}", "logs": str(data / "logs"), "runtime": str(runtime),
    }
    command_plan = []
    if args.action in ("install", "start"):
        command_plan = [[LAUNCHCTL, "bootstrap", domain, str(plist)], [LAUNCHCTL, "kickstart", target]]
    elif args.action in ("stop", "uninstall") and existing is not None:
        command_plan = [[LAUNCHCTL, "bootout", target]]
    result["launchctl_plan"] = command_plan
    if args.dry_run:
        result["configuration"] = desired
        result["sync_runtime"] = needs_sync
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if not staging and sys.platform != "darwin":
        raise ServiceError("持续服务使用 macOS launchd；其他系统可用 --home 暂存验证或直接运行 workhub.py serve")
    if staging:
        if args.action == "install":
            (data / "logs").mkdir(parents=True, exist_ok=True, mode=0o700)
            sync_runtime(runtime, payload)
            atomic_plist(plist, desired)
        elif args.action == "uninstall" and existing is not None:
            plist.unlink()
        result.update(installed=plist.exists(), loaded=False, running=False, healthy=False)
        result["note"] = "显式 --home 为暂存模式，未调用 launchctl 或启动服务。"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    allowed_backends = {str(BACKEND)}
    for config in (existing, desired):
        if config is not None:
            allowed_backends.add(config["ProgramArguments"][1])
    loaded, running = loaded_job(target, allowed_backends)
    if args.action == "status":
        result.update(installed=existing is not None, loaded=loaded, running=running, healthy=health(port) if running else False)
    elif args.action in ("stop", "uninstall"):
        if loaded and existing is None:
            raise ServiceError("同名任务已加载但缺少本仓库 plist，为避免影响其他任务未停止")
        if loaded:
            launchctl("bootout", target)
        if args.action == "uninstall" and existing is not None:
            plist.unlink()
        result.update(installed=plist.exists(), loaded=False, running=False, healthy=False)
    else:
        # A manual preview must not be mistaken for the launchd-owned product.
        if not loaded and is_port_open(port):
            raise ServiceError(f"端口 {port} 已被现有进程占用；请先停止你启动的实例或使用 install --port 指定其他端口")
        if loaded and existing is not None and stored_port(existing) != port and is_port_open(port):
            raise ServiceError(f"新端口 {port} 已被现有进程占用；保留当前服务，请使用其他端口")
        if args.action == "install":
            changed = existing != desired or needs_sync
            if loaded and changed:
                launchctl("bootout", target)
                loaded = False
            (data / "logs").mkdir(parents=True, exist_ok=True, mode=0o700)
            result["runtime_updated"] = sync_runtime(runtime, payload)
            if changed:
                atomic_plist(plist, desired)
        if not loaded:
            launchctl("bootstrap", domain, str(plist))
        launchctl("kickstart", target)
        for _ in range(40):
            loaded, running = loaded_job(target, allowed_backends)
            if loaded and running and health(port):
                result.update(installed=True, loaded=True, running=True, healthy=True)
                break
            time.sleep(0.25)
        else:
            raise ServiceError("launchd 已注册，但服务健康检查未通过；请查看服务日志")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ServiceError, OSError, subprocess.SubprocessError) as error:
        chosen_home = Path.home()
        if "--home" in sys.argv:
            index = sys.argv.index("--home")
            if index + 1 < len(sys.argv):
                chosen_home = Path(sys.argv[index + 1]).expanduser()
        logs = Path(os.environ.get("AGENT_WORKHUB_HOME", str(chosen_home / ".local/share/agent-workhub"))) / "logs"
        print(f"服务操作失败：{error}\n日志目录：{logs}", file=sys.stderr)
        raise SystemExit(1)
