#!/usr/bin/env python3
"""Install shared Agent Workhub instructions without replacing user rules."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import uuid


REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skill" / "agent-workhub"
START = "<!-- AGENT-WORKHUB:START -->"
END = "<!-- AGENT-WORKHUB:END -->"
WRAPPER_MARKER = "# agent-workhub-managed"


class InstallError(Exception):
    pass


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def require_inside(path: Path, root: Path) -> None:
    """Reject parent links that would move an install outside its chosen root."""
    if not path.parent.resolve().is_relative_to(root.resolve()):
        raise InstallError(f"父目录符号链接超出安装范围，未修改：{path}")


def rule_text() -> str:
    return (
        f"{START}\n"
        "## 统一项目工作记录（必读）\n\n"
        f"所有项目类任务开始前，必须先读取 `{SKILL / 'SKILL.md'}`。\n"
        "Codex、Z Code、Claude Code 及子 Agent 均使用这份协议：开工、实质进展、"
        "完成或受阻时，把真实工作记录到本机统一项目看板；每个任务使用独立 run-id。\n"
        "项目包含网站时，还必须把实际网站接入门户内嵌切换；新建网站先查看模板库，"
        "按任务复用 radar、library 或 brief 布局，共用固定设计体系，不为每个项目重新换皮。\n"
        "用户启用模型评议后，在重要里程碑按技能中的苏格拉底项目评议协议检查假设、证据和遗漏；资料不足不得编造评分。\n"
        f"记录入口：`{SKILL / 'scripts' / 'report.py'}`（用 Python 3 执行；`--help` 查看命令）。\n"
        "项目是否进入中控由用户手动选择；register/record 不自动加入，不得自行 workspace-add。网站默认原样展示。\n"
        "保留项目的原有规则；不记录凭据或完整聊天。无法写入时明确报告失败，"
        "不得声称已经同步。此规则不授权任何额外的项目操作。\n"
        f"{END}"
    )


def merge_rule(original: str, block: str) -> str:
    if original.count(START) != original.count(END) or original.count(START) > 1:
        raise InstallError("检测到不完整或重复的 AGENT-WORKHUB 标记，请先手动整理")
    if START in original:
        begin = original.index(START)
        end = original.index(END) + len(END)
        if end < begin:
            raise InstallError("AGENT-WORKHUB 标记顺序不正确，未修改")
        return original[:begin] + block + original[end:]
    separator = "" if not original else ("\n" if original.endswith("\n") else "\n\n")
    return original + separator + block + "\n"


def wrapper_text(data_dir: Path) -> str:
    return (
        "#!/bin/sh\n"
        f"{WRAPPER_MARKER}\n"
        "if [ -z \"${AGENT_WORKHUB_HOME:-}\" ]; then\n"
        f"  AGENT_WORKHUB_HOME={shlex.quote(str(data_dir))}\n"
        "  export AGENT_WORKHUB_HOME\n"
        "fi\n"
        f"exec {shlex.quote(sys.executable)} {shlex.quote(str(REPO / 'workhub.py'))} \"$@\"\n"
    )


def read_regular(path: Path) -> tuple[bytes | None, int]:
    if path.is_symlink():
        raise InstallError(f"为避免修改链接目标，拒绝覆盖符号链接文件：{path}")
    if not lexists(path):
        return None, 0o644
    if not path.is_file():
        raise InstallError(f"目标不是普通文件，未修改：{path}")
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.workhub-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global", dest="global_install", action="store_true", help="接入本用户的 Codex、Z Code、Claude Code")
    p.add_argument("--project", type=Path, help="仅接入指定的现有项目目录")
    p.add_argument("--name", help="项目显示名称，与 --project 一起使用")
    site_source = p.add_mutually_exclusive_group()
    site_source.add_argument("--site-url", help="接入本机已运行的网站，如 http://127.0.0.1:3000")
    site_source.add_argument("--site-dir", type=Path, help="接入包含 index.html 的静态网站目录")
    p.add_argument("--site-name", help="门户中的网站名称；默认使用项目显示名称")
    p.add_argument("--template", choices=("radar", "library", "brief"), help="网站模板分类；只登记分类，不生成模板")
    p.add_argument("--home", type=Path, default=Path.home(), help="安装根目录；测试时可指定临时目录")
    p.add_argument("--dry-run", action="store_true", help="仅显示计划，不写文件或数据库")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if not args.global_install and args.project is None:
        p.error("至少指定 --global 或 --project")
    if args.name and args.project is None:
        p.error("--name 需要与 --project 一起使用")
    has_site = args.site_url is not None or args.site_dir is not None
    if has_site and args.project is None:
        p.error("--site-url 或 --site-dir 需要与 --project 一起使用")
    if (args.site_name is not None or args.template is not None) and not has_site:
        p.error("--site-name 和 --template 需要同时指定 --site-url 或 --site-dir")
    home = args.home.expanduser().resolve()
    data_dir = Path(os.environ.get("AGENT_WORKHUB_HOME", str(home / ".local/share/agent-workhub"))).expanduser().resolve()
    if "AGENT_WORKHUB_HOME" not in os.environ:
        require_inside(home / ".local/share/agent-workhub/backups", home)
    project = args.project.expanduser().resolve() if args.project else None
    if project is not None and not project.is_dir():
        raise InstallError(f"项目目录不存在：{project}")
    site_dir = args.site_dir.expanduser().resolve() if args.site_dir is not None else None
    if site_dir is not None and (not site_dir.is_dir() or not (site_dir / "index.html").is_file()):
        raise InstallError(f"静态网站目录必须存在且包含 index.html：{site_dir}")
    site_url = args.site_url
    if site_url is not None:
        try:
            parsed = urlsplit(site_url)
            port = parsed.port
            valid = (parsed.scheme in ("http", "https") and
                     parsed.hostname in ("127.0.0.1", "localhost", "::1") and
                     parsed.username is None and parsed.password is None and
                     not any(ord(character) < 33 for character in site_url) and
                     (port is None or 1 <= port <= 65535))
        except ValueError:
            valid = False
        if not valid:
            raise InstallError("网站 URL 必须是无凭据的本机 HTTP(S) 地址（localhost、127.0.0.1 或 ::1）")
    if not (SKILL / "SKILL.md").is_file():
        raise InstallError(f"未找到共用技能：{SKILL}")

    # Complete conflict detection before the first mutation.
    files: list[tuple[Path, bytes | None, bytes, int]] = []
    links: list[tuple[Path, Path]] = []
    rules: list[Path] = []
    if args.global_install:
        rules.extend([home / ".codex/AGENTS.md", home / ".zcode/AGENTS.md", home / ".claude/CLAUDE.md"])
        for relative in [".codex/skills/agent-workhub", ".agents/skills/agent-workhub", ".zcode/skills/agent-workhub", ".claude/skills/agent-workhub"]:
            link = home / relative
            require_inside(link, home)
            if lexists(link):
                if not link.is_symlink() or link.resolve() != SKILL.resolve():
                    raise InstallError(f"同名技能已存在且不属于本项目，未覆盖：{link}")
            else:
                links.append((link, SKILL))
        wrapper = home / ".local/bin/agent-workhub"
        require_inside(wrapper, home)
        old, mode = read_regular(wrapper)
        if old is not None and WRAPPER_MARKER.encode() not in old.splitlines()[:3]:
            raise InstallError(f"同名命令已存在且不属于本项目，未覆盖：{wrapper}")
        new = wrapper_text(data_dir).encode("utf-8")
        if old != new or not mode & 0o111:
            files.append((wrapper, old, new, mode | 0o111))
    if project is not None:
        rules.extend([project / "AGENTS.md", project / "CLAUDE.md"])
    for rule in dict.fromkeys(rules):
        require_inside(rule, project if project and rule.parent == project else home)
        old, mode = read_regular(rule)
        try:
            original = old.decode("utf-8") if old is not None else ""
        except UnicodeDecodeError as exc:
            raise InstallError(f"规则文件不是 UTF-8，未修改：{rule}") from exc
        merged = merge_rule(original, rule_text()).encode("utf-8")
        if merged != old:
            files.append((rule, old, merged, mode))
    if project is not None and not (REPO / "workhub.py").is_file():
        raise InstallError(f"未找到项目登记程序：{REPO / 'workhub.py'}")

    plan = {
        "dry_run": args.dry_run,
        "write_files": [str(item[0]) for item in files],
        "skill_links": [str(item[0]) for item in links],
        "register_project": str(project) if project else None,
        "data_dir": str(data_dir),
    }
    site_command = None
    if has_site:
        site_name = args.site_name or args.name or project.name
        site_command = [sys.executable, str(REPO / "workhub.py"), "site-add", "--project", str(project), "--name", site_name]
        if site_url is not None:
            site_command.extend(["--url", site_url])
        else:
            site_command.extend(["--directory", str(site_dir)])
        if args.template:
            site_command.extend(["--template", args.template])
        plan["register_site"] = {
            "project": str(project), "name": site_name,
            "url": site_url, "directory": str(site_dir) if site_dir is not None else None,
            "template": args.template,
            "command": site_command,
        }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    backup_dir = None
    originals = [(path, old) for path, old, _, _ in files if old is not None]
    if originals:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_dir = data_dir / "backups" / f"{stamp}-{uuid.uuid4().hex[:8]}"
        require_inside(backup_dir, data_dir)
        backup_dir.mkdir(parents=True, mode=0o700)
        for index, (path, old) in enumerate(originals):
            atomic_write(backup_dir / f"{index:03d}-{path.name}", old, 0o600)
        atomic_write(backup_dir / "manifest.json", json.dumps(
            {f"{index:03d}-{path.name}": str(path) for index, (path, _) in enumerate(originals)},
            ensure_ascii=False, indent=2,
        ).encode("utf-8"), 0o600)
    for path, old, content, mode in files:
        # A second check avoids overwriting changes made after preflight.
        current, _ = read_regular(path)
        if current != old:
            raise InstallError(f"安装期间文件发生变化，停止以保留新内容：{path}")
        atomic_write(path, content, mode)
    for link, target in links:
        link.parent.mkdir(parents=True, exist_ok=True)
        # symlink() fails rather than replacing any concurrently created target.
        link.symlink_to(target, target_is_directory=True)
    if project is not None:
        command = [sys.executable, str(REPO / "workhub.py"), "register", "--path", str(project)]
        if args.name:
            command.extend(["--name", args.name])
        env = dict(os.environ, AGENT_WORKHUB_HOME=str(data_dir))
        completed = subprocess.run(command, env=env, capture_output=True, text=True)
        if completed.returncode:
            raise InstallError("规则已安装，但项目登记失败：" + completed.stderr.strip())
        plan["project_registration"] = json.loads(completed.stdout)
        if site_command is not None:
            site_completed = subprocess.run(site_command, env=env, capture_output=True, text=True)
            if site_completed.returncode:
                raise InstallError("规则和项目已登记，但网站接入失败：" + site_completed.stderr.strip())
            plan["site_registration"] = json.loads(site_completed.stdout)
    plan["backup_dir"] = str(backup_dir) if backup_dir else None
    plan["installed"] = True
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InstallError, OSError, ValueError) as error:
        print(f"安装失败：{error}", file=sys.stderr)
        raise SystemExit(1)
