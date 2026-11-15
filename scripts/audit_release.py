#!/usr/bin/env python3
"""Scan only release candidates; never read user configuration or print secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", "reports"}
RUNTIME_DIRECTORIES = {"runtime", "logs", "exports", ".workhub", ".agent-workhub"}
PRIVATE_NAMES = {".env", "llm.json", "glm.json", ".gitcredentials", ".git-credentials", "credentials.json", "session.json", "id_rsa", "id_ecdsa", "id_ed25519", "id_dsa"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
HOME_PATH = re.compile(r'''(?<![\w])/(?:Users|home)/[A-Za-z0-9._-]+(?:/|(?=["'\s]))''')
WINDOWS_HOME = re.compile(r'''[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][^\\/\s"'<>]+''', re.I)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{25,}|sk-(?:proj-|ant-api\d*-)?[A-Za-z0-9_-]{24,}|xox[baprs]-[A-Za-z0-9-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b")
BEARER = re.compile(r"\bBearer\s+([A-Za-z0-9._~+/=-]{16,})", re.I)
ASSIGNMENT = re.compile(r'''(?i)\b(?:api[_-]?keys?|access[_-]?token|refresh[_-]?token|password|secret|token)["']?\s*[:=]\s*(?:\[\s*)?["']([^"'\r\n]{12,})["']''')
ENV_ASSIGNMENT = re.compile(r"(?mi)^\s*(?:export\s+)?[A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|SECRET)\s*=\s*([A-Za-z0-9_./+=-]{12,})\s*(?:#.*)?$")
PRIVATE_KEY = re.compile(r"-----BEGIN (?P<kind>(?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY)-----(?P<body>[\s\S]*?)-----END (?P=kind)-----")


def candidates(root: Path) -> tuple[list[Path], str]:
    if (root / ".git").exists():
        result = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        if result.returncode == 0:
            names = {os.fsdecode(name) for name in result.stdout.split(b"\0") if name}
            return sorted((root / name for name in names), key=str), "git-candidates"
    result = []
    for directory, children, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(children):
            path = base / name
            if name in SKIP_DIRECTORIES:
                children.remove(name)
            elif name in RUNTIME_DIRECTORIES or path.is_symlink():
                result.append(path)
                children.remove(name)
        result.extend(base / name for name in files)
    return sorted(result, key=str), "source-tree"


def forbidden_kind(relative: Path) -> str | None:
    lower = relative.name.lower()
    if (any(part.lower() in {"tests", "test", "__tests__"} for part in relative.parts[:-1]) or
            re.fullmatch(r"(?:test_.*\.py|.*_test\.(?:py|go)|.*\.(?:test|spec)\..+)", lower)):
        return "test-only-artifact"
    if any(part in RUNTIME_DIRECTORIES or part == "reports" for part in relative.parts):
        return "runtime-artifact"
    if lower in PRIVATE_NAMES or (lower.startswith(".env.") and lower != ".env.example"):
        return "private-configuration"
    if ".sqlite" in lower or re.search(r"\.db(?:-|$)", lower):
        return "database-artifact"
    if lower.endswith((".log", ".pid", ".p12", ".pfx", ".key", ".zip", ".tar", ".tar.gz")):
        return "private-or-generated-artifact"
    if relative.suffix.lower() in IMAGE_SUFFIXES and relative.parts[:2] != ("docs", "images"):
        return "screenshot-outside-docs-images"
    return None


def placeholder(value: str, relative: Path) -> bool:
    if re.match(r"YOUR[_ -]|REPLACE[_ -]|CHANGE[_ -]?ME|EXAMPLE(?:[_ -]|$)|DUMMY[_ -]|FAKE[_ -]|SYNTHETIC[_ -]|<[^>]+>$", value, re.I):
        return True
    # Test fixtures remain explicit and textual. Random provider-shaped tokens
    # are detected separately even when they occur in a test source file.
    if relative.parts and relative.parts[0] == "tests":
        return bool(re.search(r"test|json-credential|json-access|escaped-quote|single-quoted|url-private|first-token|private-access", value, re.I))
    return False


def text_findings(text: str, relative: Path) -> list[dict]:
    found = []

    def add(kind: str, offset: int) -> None:
        entry = {"path": relative.as_posix(), "kind": kind, "line": text.count("\n", 0, offset) + 1}
        if entry not in found:
            found.append(entry)

    for pattern in (HOME_PATH, WINDOWS_HOME):
        for match in pattern.finditer(text):
            add("personal-home-path", match.start())
    for match in EMAIL.finditer(text):
        domain = match.group(1).lower()
        # GitHub's fixed SSH transport user is protocol syntax, not an email address.
        if text[match.start():match.end()+1] == 'git@github.com:':
            continue
        if (relative.parts[:1] == ("tests",) and match.group(0).lower().startswith("password@") and
                text[max(0, match.start() - 5):match.start()] == "user:"):
            continue
        if domain not in ("example.com", "example.org", "example.net") and not domain.endswith((".test", ".invalid", ".example")):
            add("email-address", match.start())
    for match in TOKEN.finditer(text):
        if not re.fullmatch(r"(?:gh[pousr]_|github_pat_|sk-(?:proj-|ant-api\d*-)?)?(?:YOUR|EXAMPLE|DUMMY|FAKE)[A-Z0-9_-]*", match.group(0)):
            add("provider-token", match.start())
    for pattern in (BEARER, ASSIGNMENT, ENV_ASSIGNMENT):
        for match in pattern.finditer(text):
            if not placeholder(match.group(1), relative):
                add("credential-like-value", match.start())
    for match in PRIVATE_KEY.finditer(text):
        body = match.group("body").replace("\\n", "\n").strip()
        if relative.parts[:1] == ("tests",) and body == "PRIVATE-TEST-BODY":
            continue
        add("private-key", match.start())
    return found


def audit(root: Path) -> dict:
    paths, source = candidates(root)
    findings = []
    scanned = 0
    for path in paths:
        relative = path.relative_to(root)
        kind = forbidden_kind(relative)
        if kind:
            findings.append({"path": relative.as_posix(), "kind": kind})
            continue  # Do not read the contents of private configuration.
        if path.is_symlink():
            findings.append({"path": relative.as_posix(), "kind": "symbolic-link"})
            continue
        if not path.exists():
            continue  # A tracked deletion has no outgoing file contents.
        if not path.is_file() or (relative.suffix.lower() in IMAGE_SUFFIXES and relative.parts[:2] == ("docs", "images")):
            continue
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                findings.append({"path": relative.as_posix(), "kind": "oversized-source-requires-review"})
                continue
            content = path.read_bytes()
            if content.startswith(b"SQLite format 3\x00"):
                findings.append({"path": relative.as_posix(), "kind": "database-artifact"})
                continue
            text = content.decode("utf-8")
        except (OSError, UnicodeError):
            findings.append({"path": relative.as_posix(), "kind": "unreadable-source"})
            continue
        scanned += 1
        findings.extend(text_findings(text, relative))
    return {"ok": not findings, "scope": source, "candidate_count": len(paths), "text_files_scanned": scanned, "findings": findings}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Release directory, defaults to this repository")
    parser.add_argument("--report", type=Path, help="Optional JSON report inside the release directory")
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        parser.error("release directory does not exist")
    result = audit(root)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        report = args.report if args.report.is_absolute() else root / args.report
        if not report.resolve().is_relative_to(root) or report.is_symlink():
            parser.error("report must remain inside the release directory")
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
