#!/usr/bin/env python3
"""Agent Workhub: a local, persistent project journal and read-only dashboard.

Work events are written by the CLI; guarded HTTP requests can start reviews.
The server binds to loopback and rejects foreign Host headers so a website
cannot use DNS rebinding to read the journal.
Python 3.9+ and its standard library are sufficient.
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from assessments import AssessmentManager, ReviewError


ROOT = Path(__file__).resolve().parent
STATUSES = ("running", "completed", "blocked", "paused")
EVENT_LIMIT = 500
TEMPLATES = (
    {"id": "radar", "name": "信息雷达", "description": "汇集线索、来源与待处理信息，按优先级追踪动态。", "category": "信息收集"},
    {"id": "library", "name": "知识资料库", "description": "分类管理项目资料、参考链接和可检索的知识卡片。", "category": "知识管理"},
    {"id": "brief", "name": "分析简报", "description": "呈现关键发现、证据、进展与下一步行动。", "category": "研究分析"},
)


def template_catalog():
    return [dict(item, preview_url="/templates/{}/index.html".format(item["id"])) for item in TEMPLATES]


def local_site_url(value):
    """Accept explicit HTTP(S) loopback URLs without resolving hostnames."""
    if not value or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        raise ValueError("网站 URL 必须是有效的本机 HTTP(S) 地址")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("网站仅接受不含账号密码的本机 HTTP(S) URL")
    if parsed.hostname != "localhost":
        try:
            if not ipaddress.ip_address(parsed.hostname).is_loopback:
                raise ValueError("只允许本机网站 URL")
        except ValueError:
            raise ValueError("网站主机必须为 localhost 或回环 IP")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("网站 URL 端口范围 1 至 65535")
    return value


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_path(value):
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("项目目录不存在：" + str(path))
    return str(path)


def project_id(path):
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]


class Store:
    """Open one short-lived connection per operation; SQLite serializes writers."""

    def __init__(self, data_dir=None):
        raw = data_dir or os.environ.get("AGENT_WORKHUB_HOME") or "~/.local/share/agent-workhub"
        self.directory = Path(raw).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = self.directory / "workhub.sqlite3"
        with self.connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    agent TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('running','completed','blocked','paused')),
                    summary TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    task TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    run_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_project_idx ON events(project_id, id DESC);
                CREATE TABLE IF NOT EXISTS runs (
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    agent TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    task TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, agent, run_id)
                );
                CREATE TABLE IF NOT EXISTS sites (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('url','directory')),
                    url TEXT,
                    directory TEXT,
                    template_id TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sites_project_idx ON sites(project_id);
                PRAGMA user_version = 2;
            """)
        with contextlib.suppress(OSError):
            self.database.chmod(0o600)

    @contextlib.contextmanager
    def connection(self):
        db = sqlite3.connect(str(self.database), timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 20000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _register(db, path, name=None, description=None):
        identifier = project_id(path)
        now = timestamp()
        db.execute(
            "INSERT OR IGNORE INTO projects (id,path,name,description,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (identifier, path, name or Path(path).name or path, description or "", now, now),
        )
        if name is not None:
            db.execute("UPDATE projects SET name = ?, updated_at = ? WHERE id = ? AND name != ?", (name, now, identifier, name))
        if description is not None:
            db.execute("UPDATE projects SET description = ?, updated_at = ? WHERE id = ? AND description != ?", (description, now, identifier, description))
        return identifier

    def register(self, path, name=None, description=None):
        path = canonical_path(path)
        if name is not None and not name.strip():
            raise ValueError("项目名不能为空")
        with self.connection() as db:
            identifier = self._register(db, path, name, description)
        return self.project(identifier)

    def record(self, path, agent, status, summary, details="", task="", run_id=None):
        path = canonical_path(path)
        agent = agent.strip()
        summary = summary.strip()
        if not agent or not summary:
            raise ValueError("agent 和 summary 不能为空")
        if status not in STATUSES:
            raise ValueError("未知状态：" + status)
        if len(agent) > 100 or len(summary) > 20000 or len(details) > 200000 or len(task) > 20000:
            raise ValueError("记录超过允许长度")
        if run_id is None:
            # Stable fallback: progress/finish for the same agent and task update
            # one run. Parallel sessions should supply explicit distinct IDs.
            run_id = "task-" + hashlib.sha256(task.encode("utf-8")).hexdigest()[:20]
        if not run_id.strip() or len(run_id) > 300:
            raise ValueError("run-id 必须为 1 至 300 个字符")
        now = timestamp()
        with self.connection() as db:
            # Begin before registering so project, event, and run are atomic.
            db.execute("BEGIN IMMEDIATE")
            identifier = self._register(db, path)
            cursor = db.execute(
                "INSERT INTO events (project_id,agent,status,summary,details,task,created_at,run_id) VALUES (?,?,?,?,?,?,?,?)",
                (identifier, agent, status, summary, details, task, now, run_id),
            )
            db.execute(
                "INSERT INTO runs (project_id,agent,run_id,task,status,updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(project_id,agent,run_id) DO UPDATE SET task=excluded.task,status=excluded.status,updated_at=excluded.updated_at",
                (identifier, agent, run_id, task, status, now),
            )
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, identifier))
            event = db.execute("SELECT e.*,p.name AS project_name FROM events e JOIN projects p ON p.id=e.project_id WHERE e.id=?", (cursor.lastrowid,)).fetchone()
        return dict(event)

    def site_add(self, project, name, url=None, directory=None, template=None, description=None):
        project = canonical_path(project)
        name = name.strip()
        if not name or len(name) > 300:
            raise ValueError("网站名必须为 1 至 300 个字符")
        if (url is None) == (directory is None):
            raise ValueError("必须且只能提供 url 或 directory")
        if template is not None and template not in {item["id"] for item in TEMPLATES}:
            raise ValueError("未知模板：" + template)
        if description is not None and len(description) > 20000:
            raise ValueError("网站说明超过允许长度")
        if url is not None:
            kind, target = "url", local_site_url(url)
        else:
            kind, target = "directory", canonical_path(directory)
        pid = project_id(project)
        identifier = hashlib.sha256((pid + "\0" + kind + "\0" + target).encode("utf-8")).hexdigest()[:24]
        now = timestamp()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._register(db, project)
            previous = db.execute("SELECT template_id,description FROM sites WHERE id=?", (identifier,)).fetchone()
            if previous:
                if template is None:
                    template = previous["template_id"]
                if description is None:
                    description = previous["description"]
            db.execute(
                "INSERT INTO sites (id,project_id,name,kind,url,directory,template_id,description,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,template_id=excluded.template_id,description=excluded.description,updated_at=excluded.updated_at",
                (identifier, pid, name, kind, target if kind == "url" else None, target if kind == "directory" else None, template, description or "", now, now),
            )
        return next(site for site in self.sites() if site["id"] == identifier)

    def sites(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT s.*,p.name AS project_name,p.path AS project_path FROM sites s JOIN projects p ON p.id=s.project_id ORDER BY s.updated_at DESC,s.name COLLATE NOCASE"
            )]

    def site_remove(self, identifier):
        with self.connection() as db:
            cursor = db.execute("DELETE FROM sites WHERE id=?", (identifier,))
            return {"ok": True, "id": identifier, "removed": cursor.rowcount > 0}

    @staticmethod
    def _projects(db):
        projects = []
        run_map = {}
        for row in db.execute("SELECT project_id,agent,status FROM runs"):
            run_map.setdefault(row["project_id"], []).append(dict(row))
        counts = {row["project_id"]: row["n"] for row in db.execute("SELECT project_id,COUNT(*) AS n FROM events GROUP BY project_id")}
        last = {row["project_id"]: row["summary"] for row in db.execute("SELECT project_id,summary FROM events WHERE id IN (SELECT MAX(id) FROM events GROUP BY project_id)")}
        for row in db.execute("SELECT * FROM projects ORDER BY updated_at DESC, name COLLATE NOCASE"):
            project = dict(row)
            runs = run_map.get(project["id"], [])
            statuses = {run["status"] for run in runs}
            project["status"] = next((status for status in ("running", "blocked", "paused", "completed") if status in statuses), "registered")
            project["active_runs"] = sum(run["status"] == "running" for run in runs)
            project["blocked_runs"] = sum(run["status"] == "blocked" for run in runs)
            project["agents"] = sorted({run["agent"] for run in runs})
            project["event_count"] = counts.get(project["id"], 0)
            project["last_summary"] = last.get(project["id"], "尚无工作记录")
            projects.append(project)
        return projects

    def projects(self):
        with self.connection() as db:
            return self._projects(db)

    def project(self, identifier):
        return next((project for project in self.projects() if project["id"] == identifier), None)

    def events(self, path=None, limit=100, offset=0, identifier=None):
        if path is not None:
            identifier = project_id(canonical_path(path))
        with self.connection() as db:
            return self._events(db, identifier, limit, offset)

    @staticmethod
    def _events(db, identifier=None, limit=100, offset=0):
        where = " WHERE e.project_id=?" if identifier else ""
        params = ([identifier] if identifier else []) + [limit, offset]
        query = "SELECT e.*,p.name AS project_name FROM events e JOIN projects p ON p.id=e.project_id" + where + " ORDER BY e.id DESC LIMIT ? OFFSET ?"
        return [dict(row) for row in db.execute(query, params)]

    def state(self, event_limit=EVENT_LIMIT):
        with self.connection() as db:
            # A read transaction gives the UI a consistent snapshot while other
            # agents append events using separate connections.
            db.execute("BEGIN")
            projects = self._projects(db)
            events = self._events(db, limit=-1 if event_limit is None else event_limit)
            count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {
            "projects": projects,
            "events": events,
            "stats": {
                "project_count": len(projects),
                "event_count": count,
                "running_count": sum(p["status"] == "running" for p in projects),
                "blocked_count": sum(p["blocked_runs"] > 0 for p in projects),
            },
            "agents": sorted({agent for p in projects for agent in p["agents"]}),
            "event_limit": event_limit,
            "has_more": count > len(events),
            "generated_at": timestamp(),
        }


def integrations():
    entries = (
        ("codex", "~/.codex/AGENTS.md", "~/.codex/skills/agent-workhub/SKILL.md"),
        ("zcode", "~/.zcode/AGENTS.md", "~/.zcode/skills/agent-workhub/SKILL.md"),
        ("claude", "~/.claude/CLAUDE.md", "~/.claude/skills/agent-workhub/SKILL.md"),
    )
    results = []
    for agent, rules_raw, skill_raw in entries:
        rules = Path(rules_raw).expanduser()
        skill = Path(skill_raw).expanduser()
        try:
            text = rules.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            text = ""
        required = "AGENT-WORKHUB" in text
        results.append({"agent": agent, "name": {"codex": "Codex", "zcode": "Z Code", "claude": "Claude Code"}[agent], "ready": required and skill.is_file(), "installed": required and skill.is_file(), "rules_present": rules.is_file(), "required_read": required, "skill_present": skill.is_file(), "rules_path": str(rules), "rule_path": str(rules), "skill_path": str(skill)})
    return {"integrations": results}


class WorkhubServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_close(self):
        super().server_close()
        manager = getattr(self.RequestHandlerClass, "site_manager", None)
        if manager is not None:
            manager.close()
        reviews = getattr(self.RequestHandlerClass, "assessment_manager", None)
        if reviews is not None:
            reviews.close(wait=False)


def handler_for(store, manager=None, reviews=None):
    manager = manager or (SiteManager(store) if store is not None else None)
    reviews = reviews or (AssessmentManager(store) if store is not None else None)
    class Handler(BaseHTTPRequestHandler):
        server_version = "AgentWorkhub/1"
        sys_version = ""
        site_manager = manager
        assessment_manager = reviews

        def log_message(self, fmt, *args):
            # Avoid logging raw request URLs (or terminal escape sequences).
            return

        def valid_host(self):
            values = self.headers.get_all("Host", [])
            if len(values) != 1:
                return False
            raw = values[0]
            if any(c.isspace() for c in raw) or any(c in raw for c in "/\\@?#,"):
                return False
            try:
                parsed = urlsplit("http://" + raw)
                return parsed.hostname in ("localhost", "127.0.0.1", "::1") and (parsed.port or 80) == self.server.server_port
            except ValueError:
                return False

        def respond(self, code, body, content_type="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.end_headers()
            if self.command != "HEAD":
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(body)

        def json_response(self, code, payload):
            self.respond(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            if not self.check_access():
                return
            if store is None:
                self.json_response(405, {"error": "项目静态网站只允许读取"})
                return
            if self.path != "/api/reviews":
                self.json_response(404, {"error": "接口不存在"})
                return
            if self.headers.get("X-Workhub-Request") != "1":
                self.json_response(403, {"error": "缺少本机评议请求标记"})
                return
            if self.headers.get_content_type() != "application/json":
                self.json_response(415, {"error": "评议请求须为 JSON"})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ReviewError("不支持分块请求体")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ReviewError("JSON 请求体须为 1 至 16384 字节", 413)
                self.connection.settimeout(5)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ReviewError("请求体不完整")
                payload = json.loads(raw)
                if not isinstance(payload, dict) or any(key not in ("project_id", "all", "answer", "force") for key in payload):
                    raise ReviewError("评议请求参数无效")
                all_projects = payload.get("all", False)
                force = payload.get("force", False)
                identifier = payload.get("project_id")
                if type(all_projects) is not bool or type(force) is not bool or (all_projects and identifier is not None):
                    raise ReviewError("请指定单个项目或 all:true")
                if not all_projects and (not isinstance(identifier, str) or not identifier):
                    raise ReviewError("缺少项目 ID")
                result = reviews.submit(project_ids=[identifier] if identifier else None, all_projects=all_projects, answer=payload.get("answer"), force=force)
                self.json_response(202, result)
            except ReviewError as error:
                self.json_response(error.status, {"error": str(error)})
            except (ValueError, UnicodeError, TimeoutError):
                self.json_response(400, {"error": "JSON 请求体无效或未完整发送"})
            except (OSError, sqlite3.Error):
                self.json_response(500, {"error": "本机评议任务创建失败，请稍后重试"})

        def check_access(self):
            if not self.valid_host():
                self.json_response(403, {"error": "仅允许本机 Host"})
                return False
            # Cross-origin browser reads are deliberately unavailable. CLI tools
            # and same-origin dashboard fetches do not need a permissive CORS API.
            origin = self.headers.get("Origin")
            if origin:
                try:
                    parsed_origin = urlsplit(origin)
                    if parsed_origin.scheme != "http" or parsed_origin.netloc.lower() != self.headers.get("Host").lower():
                        self.json_response(403, {"error": "不允许跨站请求"})
                        return False
                except ValueError:
                    self.json_response(403, {"error": "无效来源"})
                    return False
            return True

        def serve_file(self, directory, route):
            relative = route.lstrip("/") or "index.html"
            # Never publish dotfiles, even when a project root was selected.
            if any(part.startswith(".") for part in Path(relative).parts):
                self.json_response(403, {"error": "路径不允许"})
                return
            root = Path(directory).resolve()
            file = (root / relative).resolve()
            if file.is_dir():
                file = (file / "index.html").resolve()
            if root not in file.parents:
                self.json_response(403, {"error": "路径不允许"})
            elif not file.is_file():
                self.json_response(404, {"error": "页面不存在"})
            else:
                content_type = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
                if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
                    content_type += "; charset=utf-8"
                body = file.read_bytes()
                if content_type.startswith("text/html"):
                    body = self.transform_html(body)
                self.respond(200, body, content_type)

        def transform_html(self, body):
            return body

        def do_GET(self):
            if not self.check_access():
                return
            try:
                request = urlsplit(self.path)
                route = unquote(request.path, errors="strict")
                if request.scheme or request.netloc:
                    raise ValueError("不支持绝对请求地址")
                if route == "/api/health":
                    self.json_response(200, {"ok": True, "service": "agent-workhub", "version": 1})
                elif route == "/api/state":
                    self.json_response(200, store.state())
                elif route == "/api/integrations":
                    self.json_response(200, integrations())
                elif route == "/api/sites":
                    self.json_response(200, {"sites": manager.sites(), "templates": template_catalog()})
                elif route == "/api/reviews":
                    self.json_response(200, reviews.public_state())
                elif route == "/api/reviews/job":
                    identifier = parse_qs(request.query).get("id", [""])[0]
                    self.json_response(200, reviews.job(identifier))
                elif route == "/api/reviews/project":
                    identifier = parse_qs(request.query).get("id", [""])[0]
                    self.json_response(200, reviews.project(identifier))
                elif route == "/api/project":
                    query = parse_qs(request.query)
                    identifier = query.get("id", [""])[0]
                    project = store.project(identifier)
                    if project is None:
                        self.json_response(404, {"error": "项目不存在"})
                        return
                    offset = int(query.get("offset", ["0"])[0])
                    limit = int(query.get("limit", ["100"])[0])
                    if offset < 0 or not 1 <= limit <= EVENT_LIMIT:
                        raise ValueError("offset 必须非负；limit 范围 1 至 500")
                    events = store.events(identifier=identifier, limit=limit, offset=offset)
                    self.json_response(200, {"project": project, "events": events, "offset": offset, "limit": limit, "has_more": offset + len(events) < project["event_count"]})
                elif route.startswith("/api/"):
                    self.json_response(404, {"error": "接口不存在"})
                elif route.startswith("/templates/"):
                    self.serve_file(ROOT / "templates", route[len("/templates/"):])
                else:
                    self.serve_file(ROOT / "static", route)
            except ReviewError as error:
                self.json_response(error.status, {"error": str(error)})
            except (ValueError, UnicodeError) as error:
                self.json_response(400, {"error": str(error)})
            except (OSError, sqlite3.Error):
                self.json_response(500, {"error": "本机记录读取失败，请检查服务日志或数据目录"})

    return Handler


def directory_handler_for(directory):
    """A project gets its own origin and root; it cannot read Workhub APIs."""
    base = handler_for(None)

    class DirectoryHandler(base):
        def transform_html(self, body):
            if parse_qs(urlsplit(self.path).query).get("workhub_theme") == ["original"] or b"/__workhub/theme.css" in body:
                return body
            link = b'\n<link rel="stylesheet" href="/__workhub/theme.css" data-workhub-theme="shared">\n'
            closing = re.search(br"</head\s*>", body, flags=re.IGNORECASE)
            if closing:
                return body[:closing.start()] + link + body[closing.start():]
            return body + link

        def do_GET(self):
            if not self.check_access():
                return
            try:
                request = urlsplit(self.path)
                if request.scheme or request.netloc:
                    raise ValueError("不支持绝对请求地址")
                if request.path == "/__workhub/theme.css":
                    stylesheet = b"\n".join((ROOT / "static" / filename).read_bytes() for filename in ("design-system.css", "embedded-theme.css"))
                    self.respond(200, stylesheet, "text/css; charset=utf-8")
                    return
                self.serve_file(directory, unquote(request.path, errors="strict"))
            except (ValueError, UnicodeError) as error:
                self.json_response(400, {"error": str(error)})
            except OSError:
                self.json_response(500, {"error": "项目网站文件读取失败"})

    return DirectoryHandler


class SiteManager:
    """Own dynamically discovered directory previews for one hub process."""

    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.previews = {}

    @staticmethod
    def _stop(preview):
        preview["server"].shutdown()
        preview["server"].server_close()
        preview["thread"].join(timeout=2)

    def sites(self):
        sites = self.store.sites()
        with self.lock:
            current = {site["id"]: site for site in sites if site["kind"] == "directory"}
            for identifier in list(self.previews):
                if identifier not in current or self.previews[identifier]["directory"] != current[identifier]["directory"]:
                    self._stop(self.previews.pop(identifier))
            for site in sites:
                if site["kind"] == "url":
                    site["preview_url"] = site["url"]
                    site["embedding_warning"] = "网站由原项目服务提供；若页面空白，请检查服务运行状态及本站允许嵌入的配置。"
                    continue
                directory = Path(site["directory"])
                if not directory.is_dir():
                    previous = self.previews.pop(site["id"], None)
                    if previous:
                        self._stop(previous)
                    site["preview_url"] = None
                    site["embedding_warning"] = "网站目录已不存在，请重新接入目录。"
                    continue
                preview = self.previews.get(site["id"])
                if preview is None:
                    try:
                        server = WorkhubServer(("127.0.0.1", 0), directory_handler_for(directory))
                        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
                        thread.start()
                    except OSError:
                        site["preview_url"] = None
                        site["embedding_warning"] = "无法启动本机目录预览，请检查本机服务资源。"
                        continue
                    preview = {"directory": str(directory), "server": server, "thread": thread}
                    self.previews[site["id"]] = preview
                site["preview_url"] = "http://127.0.0.1:{}/".format(preview["server"].server_port)
                site["embedding_warning"] = ""
        return sites

    def close(self):
        with self.lock:
            previews, self.previews = self.previews, {}
            for preview in previews.values():
                self._stop(preview)


def bounded_limit(value):
    number = int(value)
    if not 1 <= number <= 10000:
        raise argparse.ArgumentTypeError("limit 范围 1 至 10000")
    return number


def build_parser():
    parser = argparse.ArgumentParser(description="本机 Agent 项目统一记录与总览网站")
    parser.add_argument("--data-dir", help="数据目录（默认 ~/.local/share/agent-workhub）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="创建数据库")
    register = sub.add_parser("register", help="幂等接入已有项目目录")
    register.add_argument("--path", required=True)
    register.add_argument("--name")
    register.add_argument("--description")
    record = sub.add_parser("record", help="追加一条真实工作记录")
    record.add_argument("--project", required=True)
    record.add_argument("--agent", required=True)
    record.add_argument("--status", required=True, choices=STATUSES)
    record.add_argument("--summary", required=True)
    record.add_argument("--details", default="")
    record.add_argument("--task", default="")
    record.add_argument("--run-id")
    sub.add_parser("projects", help="输出全部项目 JSON")
    events = sub.add_parser("events", help="输出最新事件 JSON")
    events.add_argument("--project")
    events.add_argument("--limit", type=bounded_limit, default=100)
    sub.add_parser("export", help="导出全部项目和完整事件 JSON")
    sub.add_parser("integrations", help="检查各 Agent 必读入口")
    review = sub.add_parser("review", help="同步运行证据约束的模型项目评议")
    review_target = review.add_mutually_exclusive_group(required=True)
    review_target.add_argument("--project", help="已登记项目的目录")
    review_target.add_argument("--all", action="store_true", help="评议全部已登记项目")
    review.add_argument("--force", action="store_true", help="即使证据未变化也重新评议；仍不重复运行中的任务")
    review.add_argument("--answer", help="用户补充的项目证据，仅用于单个项目")
    sub.add_parser("review-list", help="输出最新评议、任务与不含凭据的提供方状态")
    site_add = sub.add_parser("site-add", help="接入已有本机网站或静态网站目录")
    site_add.add_argument("--project", required=True)
    site_add.add_argument("--name", required=True)
    source = site_add.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="正在运行的本机 HTTP(S) 网站地址")
    source.add_argument("--directory", help="静态网站文件目录")
    site_add.add_argument("--template", choices=[item["id"] for item in TEMPLATES])
    site_add.add_argument("--description")
    sub.add_parser("site-list", help="输出已接入网站 JSON（预览端口从网站 API 获取）")
    site_remove = sub.add_parser("site-remove", help="取消一个网站接入，不删除网站文件")
    site_remove.add_argument("--id", required=True)
    serve = sub.add_parser("serve", help="运行本机只读看板")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "integrations":
            result = integrations()
        else:
            if args.command == "serve" and args.host not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("只允许 127.0.0.1、localhost 或 ::1")
            store = Store(args.data_dir)
            if args.command == "init":
                result = {"ok": True, "database": str(store.database)}
            elif args.command == "register":
                result = store.register(args.path, args.name, args.description)
            elif args.command == "record":
                result = store.record(args.project, args.agent, args.status, args.summary, args.details, args.task, args.run_id)
            elif args.command == "projects":
                result = store.projects()
            elif args.command == "events":
                result = store.events(args.project, args.limit)
            elif args.command == "export":
                result = store.state(event_limit=None)
                result["sites"] = store.sites()
            elif args.command == "site-add":
                result = store.site_add(args.project, args.name, args.url, args.directory, args.template, args.description)
            elif args.command == "site-list":
                result = store.sites()
            elif args.command == "site-remove":
                result = store.site_remove(args.id)
            elif args.command in ("review", "review-list"):
                assessment = AssessmentManager(store)
                try:
                    if args.command == "review-list":
                        result = assessment.public_state()
                    else:
                        identifier = project_id(canonical_path(args.project)) if args.project else None
                        submitted = assessment.submit(project_ids=[identifier] if identifier else None, all_projects=args.all, answer=args.answer, force=args.force)
                        job = assessment.wait(submitted["job_id"])
                        result = {"job": job, "reviews": [assessment.project(pid)["review"] for pid in job["project_ids"]]}
                        print(json.dumps(result, ensure_ascii=False, indent=2))
                        return 1 if job["failed"] else 0
                finally:
                    assessment.close()
            elif args.command == "serve":
                if args.host == "localhost":
                    args.host = "127.0.0.1"
                try:
                    address = ipaddress.ip_address(args.host)
                except ValueError:
                    raise ValueError("只允许 127.0.0.1、localhost 或 ::1")
                if not address.is_loopback:
                    raise ValueError("看板仅允许绑定本机回环地址")
                if not 0 <= args.port <= 65535:
                    raise ValueError("port 范围 0 至 65535")
                server_type = WorkhubServer
                if address.version == 6:
                    import socket
                    server_type = type("IPv6WorkhubServer", (WorkhubServer,), {"address_family": socket.AF_INET6})
                with server_type((args.host, args.port), handler_for(store)) as server:
                    host = "[::1]" if address.version == 6 else args.host
                    print("Agent Workhub: http://{}:{}".format(host, server.server_port), flush=True)
                    try:
                        server.serve_forever()
                    except KeyboardInterrupt:
                        pass
                return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ReviewError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except (ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
