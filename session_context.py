"""Bounded, project-linked transcript excerpts for an explicitly requested review.

Only known JSONL formats are parsed. Records remain unverified statements, and
the caller persists only a small redacted excerpt, never a complete transcript.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from urllib.parse import unquote, urlsplit

MAX_SESSIONS = 3
MAX_BYTES = 4 * 1024 * 1024
MAX_LINE = 256 * 1024
MAX_HEADER_BYTES = 512 * 1024
MAX_HEADER_LINES = 64
MAX_EXCERPTS = 8
MAX_TEXT = 1000
MAX_TOTAL_TEXT = 6500
MAX_CANDIDATES = 96
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
INJECTED = ("# AGENTS.md", "<environment_context>", "<external_browser_tabs>",
            "<external_codex_apps_", "<send_user_message_question_reply>",
            "# Browser comments:", "<INSTRUCTIONS>")


def _normal(text):
    return re.sub(r"\s+", "", text).strip()


def _safe_text(text, redact):
    text = redact(text, MAX_TEXT * 4)
    assignment = r'''\b(?:[a-z0-9]+_)*(?:api[_-]?key|access[_-]?key(?:_id)?|secret[_-]?key|password|secret|session[_-]?token|access[_-]?token|refresh[_-]?token|token)["']?\s*[:=]\s*'''
    text = re.sub(r'''(?i)(''' + assignment + r''')(["'])(?:\\.|(?!\2)[^\\])*\2''', lambda m: m.group(1) + m.group(2) + "[凭据已隐藏]" + m.group(2), text)
    text = re.sub(r'''(?i)(''' + assignment + r''')[^\s"'\[\]#,;&]+''', r"\1[凭据已隐藏]", text)
    text = re.sub(r'''(?i)((?:proxy-)?authorization["']?\s*[:=]\s*["']?basic\s+)[A-Za-z0-9+/=_-]{8,}''', r"\1[凭据已隐藏]", text)
    text = re.sub(r"-----BEGIN [^-\n]*PRIVATE KEY-----[\s\S]*", "[私钥已隐藏]", text, flags=re.I)
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-|ant-api\d*-)?[A-Za-z0-9_-]{16,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b", "[凭据已隐藏]", text)
    text = re.sub(r"(?i)(?:[A-Za-z]:[\\/]Users[\\/][^\s\"'<>]+|/(?:Users|home)/[^\s\"'<>]+)", "[本机路径]", text)
    text = re.sub(r"(?i)(https?://)[^/\s@]+@", r"\1[凭据已隐藏]@", text)
    text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[邮箱已隐藏]", text)
    return text[:MAX_TEXT]


def _roots(home):
    return {
        "codex": home / ".codex" / "sessions",
        "claude": home / ".claude" / "projects",
        "zcode": home / ".zcode" / "sessions",
        "zcode-projects": home / ".zcode" / "projects",
    }


def _open_log(path, roots):
    """Open beneath an allowed root without following child symlinks."""
    path = Path(path)
    for root in roots:
        try:
            relative = path.relative_to(root)
            if not relative.parts or any(p in ("", ".", "..") for p in relative.parts):
                continue
            if path.suffix != ".jsonl" or root.is_symlink():
                continue
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            directory = os.open(root, flags | getattr(os, "O_DIRECTORY", 0))
            try:
                for part in relative.parts[:-1]:
                    child = os.open(part, flags | getattr(os, "O_DIRECTORY", 0), dir_fd=directory)
                    os.close(directory)
                    directory = child
                descriptor = os.open(relative.parts[-1], flags, dir_fd=directory)
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    os.close(descriptor)
                    continue
                return os.fdopen(descriptor, "rb")
            finally:
                os.close(directory)
        except (OSError, ValueError, TypeError):
            continue
    return None


def _walk_names(root, deadline):
    """Inspect bounded file names only; never read unrelated transcript content."""
    if root.is_symlink():
        return
    pending = [root]
    seen = 0
    directories = 0
    while pending and seen < MAX_CANDIDATES and directories < 128 and time.monotonic() < deadline:
        parent = pending.pop()
        directories += 1
        try:
            entries = sorted(os.scandir(parent), key=lambda e: e.name, reverse=True)
        except OSError:
            continue
        children = []
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                children.append(Path(entry.path))
            elif entry.name.endswith(".jsonl") and entry.is_file(follow_symlinks=False):
                seen += 1
                yield Path(entry.path)
                if seen >= MAX_CANDIDATES:
                    break
        pending.extend(reversed(children))


def _archive_links(store, identifier):
    links = {}
    with store.connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='archive_entries'").fetchone():
            return links
        rows = db.execute("SELECT record_kind,payload_json FROM archive_entries WHERE project_id=? AND record_kind IN ('session','prompt') ORDER BY created_at DESC,rowid DESC LIMIT 64", (identifier,)).fetchall()
        for row in rows:
            try:
                data = json.loads(row["payload_json"])
            except (ValueError, TypeError):
                continue
            sid = data.get("session_id")
            if not isinstance(sid, str) or not SESSION_ID.fullmatch(sid):
                continue
            link = links.setdefault(sid, {"session_id": sid, "agent": data.get("agent", "unknown"), "references": [], "anchors": [], "shared": False})
            reference = data.get("reference")
            if isinstance(reference, str) and reference:
                link["references"].append(reference)
            content = data.get("content")
            if row["record_kind"] == "prompt" and data.get("record_type") == "original" and data.get("role", "user") == "user" and isinstance(content, str) and 8 <= len(_normal(content)) <= 12000:
                link["anchors"].append(_normal(content))
        # Shared chats require a matching project prompt window, never just cwd.
        for sid, link in links.items():
            matches = db.execute("SELECT DISTINCT project_id FROM archive_entries WHERE record_kind IN ('session','prompt') AND instr(payload_json,?)>0 LIMIT 20", (sid,)).fetchall()
            link["shared"] = any(row["project_id"] != identifier for row in matches)
    return links


def _codex_index(home, project_path, links):
    path = home / ".codex" / "state_5.sqlite"
    if path.is_symlink() or not path.is_file():
        return []
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.15) as db:
            columns = {r[1] for r in db.execute("PRAGMA table_info(threads)")}
            if not {"id", "rollout_path", "cwd"}.issubset(columns):
                return []
            result = []
            for sid, link in list(links.items())[:12]:
                row = db.execute("SELECT id,rollout_path,cwd FROM threads WHERE id=? LIMIT 1", (sid,)).fetchone()
                if row:
                    result.append((Path(row[1]), dict(link, association="archive")))
            order = "updated_at DESC" if "updated_at" in columns else "id DESC"
            for row in db.execute("SELECT id,rollout_path,cwd FROM threads WHERE cwd=? ORDER BY " + order + " LIMIT 3", (str(project_path),)):
                if row[0] not in links and isinstance(row[0], str) and SESSION_ID.fullmatch(row[0]):
                    result.append((Path(row[1]), {"session_id": row[0], "agent": "codex", "anchors": [], "shared": False, "association": "cwd"}))
            return result
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return []


def _reference_path(reference):
    if reference.startswith("file://"):
        parsed = urlsplit(reference)
        return Path(unquote(parsed.path)) if parsed.netloc in ("", "localhost") else None
    return Path(reference) if reference.startswith("/") else None


def _record_message(obj):
    if not isinstance(obj, dict):
        return None
    if obj.get("type") == "response_item":
        payload = obj.get("payload") or {}
        if not isinstance(payload, dict) or payload.get("type") != "message" or payload.get("role") not in ("user", "assistant"):
            return None
        role = payload["role"]
        if role == "assistant" and payload.get("channel") != "final":
            return None
        content = payload.get("content")
        if not isinstance(content, list):
            return None
        text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") in ("input_text", "output_text") and isinstance(c.get("text"), str))
        return role, text, None
    if obj.get("type") in ("user", "assistant"):
        message = obj.get("message") or {}
        if not isinstance(message, dict) or message.get("role", obj["type"]) not in ("user", "assistant"):
            return None
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
        else:
            return None
        return message.get("role", obj["type"]), text, obj.get("cwd")
    return None


def _extract(path, link, roots, project_path, redact, deadline):
    handle = _open_log(path, roots)
    if handle is None:
        return [], "unavailable"
    with handle:
        metadata = os.fstat(handle.fileno())
        sid, cwd, source_format = None, None, None
        header_bytes = 0
        for _ in range(MAX_HEADER_LINES):
            if header_bytes >= MAX_HEADER_BYTES or time.monotonic() >= deadline:
                break
            first = handle.readline(min(MAX_LINE + 1, MAX_HEADER_BYTES - header_bytes + 1))
            if not first:
                break
            header_bytes += len(first)
            if header_bytes > MAX_HEADER_BYTES:
                break
            if len(first) > MAX_LINE:
                # Drain a long physical record without parsing continuations
                # as standalone JSON. Both line and total header work are bound.
                while first and not first.endswith(b"\n") and header_bytes < MAX_HEADER_BYTES:
                    first = handle.readline(min(MAX_LINE + 1, MAX_HEADER_BYTES - header_bytes + 1))
                    header_bytes += len(first)
                continue
            try:
                record = json.loads(first)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(record, dict):
                continue
            if record.get("type") == "session_meta":
                meta = record.get("payload") or {}
                if not isinstance(meta, dict):
                    continue
                sid = meta.get("id") or meta.get("session_id")
                cwd = meta.get("cwd")
                source_format = "codex-jsonl"
                break
            if record.get("type") in ("user", "assistant") and record.get("sessionId") and record.get("cwd"):
                sid, cwd = record["sessionId"], record["cwd"]
                source_format = "claude-compatible-jsonl"
                break
        if source_format is None:
            return [], "unsupported"
        if sid != link["session_id"] or not isinstance(cwd, str) or not Path(cwd).is_absolute():
            return [], "unrelated"
        # A linked shared chat needs an archived prompt, even if its initial cwd
        # happens to be this project. That cwd does not identify later turns.
        allow_cwd_window = not link.get("shared")
        current_cwd = Path(cwd).resolve()
        start = max(0, metadata.st_size - MAX_BYTES)
        handle.seek(start)
        if start:
            handle.readline(MAX_LINE + 1)
        start = handle.tell()
        if start:
            # The latest project context may lie before the sampled tail.
            # Initial session cwd cannot establish ownership of this window.
            current_cwd = None
            if link.get("shared"):
                # An anchor unique in this sample can occur again outside it.
                # Without an exact archived source position, a shared tail is
                # ambiguous and must not be attributed to either project.
                return [], "no_relevant_content"
        read = 0
        line_number = 1 if start == 0 else None
        recent = deque(maxlen=MAX_EXCERPTS)
        in_window = False
        user_norm = None
        user_offset = None
        assistant = None
        fresh_user = False
        current_anchored = False
        anchor_counts = {}
        truncated = start > 0
        def save_window():
            if not in_window or not user_norm:
                return
            parts = [("user", user_text, user_offset, user_line)]
            if assistant:
                parts.append(("assistant", *assistant))
            recent.append((parts, user_norm))
        while read < MAX_BYTES and time.monotonic() < deadline:
            offset = handle.tell()
            raw = handle.readline(min(MAX_LINE + 1, MAX_BYTES - read + 1))
            if not raw:
                break
            read += len(raw)
            if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
                # Do not parse a truncated JSON record or a continuation.
                while raw and not raw.endswith(b"\n") and read < MAX_BYTES:
                    raw = handle.readline(min(MAX_LINE + 1, MAX_BYTES - read + 1))
                    read += len(raw)
                truncated = True
                if line_number is not None:
                    line_number += 1
                continue
            try:
                obj = json.loads(raw)
            except (ValueError, UnicodeError):
                if line_number is not None:
                    line_number += 1
                continue
            if isinstance(obj, dict) and obj.get("type") == "turn_context":
                payload = obj.get("payload") or {}
                declared = payload.get("cwd") if isinstance(payload, dict) else None
                next_cwd = Path(declared).resolve() if isinstance(declared, str) and Path(declared).is_absolute() else None
                # Codex can place context immediately before OR after the user
                # record. Reclassify a fresh user before any assistant activity;
                # otherwise close the old window on a project transition.
                if fresh_user:
                    in_window = current_anchored or (allow_cwd_window and next_cwd == project_path)
                    if not in_window:
                        assistant = None
                elif next_cwd != current_cwd:
                    save_window()
                    in_window, user_norm, assistant = False, None, None
                current_cwd = next_cwd
                if line_number is not None:
                    line_number += 1
                continue
            if isinstance(obj, dict):
                payload = obj.get("payload") or {}
                if obj.get("type") == "assistant" or (obj.get("type") == "response_item" and isinstance(payload, dict) and payload.get("role") == "assistant"):
                    fresh_user = False
            message = _record_message(obj)
            current_line = line_number
            if line_number is not None:
                line_number += 1
            if not message:
                continue
            role, text, record_cwd = message
            text = text.strip()
            if not text or text.startswith(INJECTED):
                continue
            if role == "user":
                normalized = _normal(text)
                if normalized == user_norm:
                    continue
                save_window()
                user_norm, user_text, user_offset, user_line, assistant = normalized, text, offset, current_line, None
                anchored = normalized in link.get("anchors", ())
                current_anchored, fresh_user = anchored, True
                own_cwd = current_cwd == project_path if record_cwd is None else (isinstance(record_cwd, str) and Path(record_cwd).is_absolute() and Path(record_cwd).resolve() == project_path)
                in_window = anchored or (own_cwd and allow_cwd_window)
                if anchored:
                    anchor_counts[normalized] = anchor_counts.get(normalized, 0) + 1
            elif in_window:
                assistant = (text, offset, current_line)
        save_window()
        items = []
        for window, anchor in list(recent)[-3:]:
            if link.get("shared") and anchor_counts.get(anchor, 0) != 1:
                continue
            for role, text, offset, line in window:
                clean = _safe_text(text, redact)
                if len(clean) < 12:
                    continue
                identifier = "session:" + link["session_id"] + ":" + str(offset)
                items.append({"id": identifier, "kind": "session", "source_type": "session_statement", "text": clean,
                              "session_id": link["session_id"], "agent": link["agent"], "role": role,
                              "source_ref": link["session_id"] + (":L" + str(line) if line else ":byte" + str(offset)),
                              "line": line, "byte_offset": offset, "source_format": source_format,
                              "association": "archived_prompt" if link.get("shared") else link["association"],
                              "truncated": truncated, "excerpt_hash": hashlib.sha256(clean.encode()).hexdigest()})
        return items, "included" if items else "no_relevant_content"


def collect_session_context(store, project, redact, home=None):
    """Called only by review submission, never GET/list polling or model tests."""
    if home is None and os.environ.get("WORKHUB_SESSION_CONTEXT", "").lower() == "off":
        return {"items": [], "session_count": 0, "status": "disabled", "bounded": True, "transcripts_stored": False}
    home = Path(home or Path.home()).resolve()
    project_path = Path(project["path"]).resolve()
    roots = _roots(home)
    deadline = time.monotonic() + 3
    links = _archive_links(store, project["id"])
    candidates = _codex_index(home, project_path, links)
    # Explicit references may also be a project-owned exported JSONL, but only
    # with a matching real session id/header. Arbitrary files are not accepted.
    for link in list(links.values())[:12]:
        for reference in link["references"][:2]:
            path = _reference_path(reference)
            if path:
                candidates.insert(0, (path, dict(link, association="archive")))
    unresolved = {sid: link for sid, link in links.items() if not any(c[1]["session_id"] == sid for c in candidates)}
    if unresolved:
        for root in roots.values():
            for path in _walk_names(root, deadline):
                for sid, link in unresolved.items():
                    if path.name.endswith(sid + ".jsonl"):
                        candidates.append((path, dict(link, association="archive")))
    # Claude stores sessions in a project-specific directory. Only that exact
    # folder is considered for cwd discovery, not other projects' transcripts.
    folder = roots["claude"] / re.sub(r"[^A-Za-z0-9-]", "-", str(project_path))
    for path in _walk_names(folder, deadline):
        try:
            sid = path.stem
            if SESSION_ID.fullmatch(sid) and sid not in links:
                candidates.append((path, {"session_id": sid, "agent": "claude", "anchors": [], "shared": False, "association": "cwd"}))
        except (ValueError, TypeError):
            pass
    output = []
    states = []
    seen = set()
    attempted = set()
    total = 0
    for path, link in candidates:
        candidate_key = (str(path), link["session_id"])
        if link["session_id"] in seen or candidate_key in attempted or len(attempted) >= MAX_SESSIONS * 2 or len(seen) >= MAX_SESSIONS or time.monotonic() >= deadline:
            continue
        attempted.add(candidate_key)
        if link["association"] == "cwd":
            with store.connection() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='archive_entries'").fetchone():
                    link["shared"] = bool(db.execute("SELECT 1 FROM archive_entries WHERE project_id<>? AND record_kind IN ('session','prompt') AND instr(payload_json,?)>0 LIMIT 1", (project["id"], link["session_id"])).fetchone())
        items, state = _extract(path, link, list(roots.values()) + [project_path], project_path, redact, deadline)
        states.append(state)
        if state in ("included", "no_relevant_content"):
            seen.add(link["session_id"])
        for item in items:
            if len(output) >= MAX_EXCERPTS or total + len(item["text"]) > MAX_TOTAL_TEXT:
                break
            output.append(item)
            total += len(item["text"])
    status = "included" if output else ("no_relevant_content" if "no_relevant_content" in states else ("unavailable" if states else "not_found"))
    return {"items": output, "session_count": len({i["session_id"] for i in output}), "status": status,
            "bounded": True, "transcripts_stored": False, "max_sessions": MAX_SESSIONS, "max_text": MAX_TOTAL_TEXT}
