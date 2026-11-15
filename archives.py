"""Local project archives. Explicit inputs only; no transcript or home scanning."""

from datetime import datetime, timezone
import base64
import binascii
import hashlib
from html.parser import HTMLParser
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import uuid
from urllib.parse import unquote, unquote_to_bytes, urlsplit
from xml.etree import ElementTree

from assessments import ReviewError, clean_text


KINDS = ("session", "prompt", "artifact")
STATUSES = ("unknown", "draft", "reviewed", "published")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".ico"}
FILE_EXTENSIONS = IMAGE_EXTENSIONS | {".html", ".htm", ".css", ".txt", ".md", ".pdf"}
MAX_CONTENT = 100000


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def digest(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def has_sensitive(text):
    # Explicit sample placeholders are not credentials. This is format-based
    # detection, not a claim that arbitrary secret strings can be recognized.
    candidate = re.sub(r'''(?i)["']?(?:api[_-]?key|password|secret|access[_-]?token|refresh[_-]?token|token)["']?\s*[:=]\s*["']?(?:YOUR_[A-Z0-9_]+|REDACTED|\[凭据已隐藏\])["']?''', "[credential placeholder]", text)
    return clean_text(candidate, len(candidate) + 1000) != candidate.strip()


def field(value, name, maximum=2000, default="", required=False):
    if value is None:
        value = default
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()) or "\0" in value:
        raise ReviewError("归档字段无效：" + name)
    if has_sensitive(value):
        raise ReviewError("归档字段含疑似凭据，未保存；请移除凭据后重试（" + name + "）", 422)
    return value


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ReviewError("归档文件必须是包内相对路径")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("..", ".") or part.startswith(".") for part in path.parts):
        raise ReviewError("归档文件路径不允许")
    return path.as_posix()


def inside_file(directory, relative):
    relative = relative_path(relative)
    root = Path(directory)
    file = root / relative
    if root.is_symlink() or any((root / Path(*PurePosixPath(relative).parts[:index])).is_symlink() for index in range(1, len(PurePosixPath(relative).parts) + 1)):
        raise ReviewError("归档文件不允许符号链接")
    resolved = file.resolve()
    if root.resolve() not in resolved.parents:
        raise ReviewError("归档文件超出登记目录")
    return resolved


class ImageReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []
        self.stylesheets = []
        self.image_slots = []

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == "img":
            candidate = values.get("src") or (values.get("srcset", "").strip().split()[0] if values.get("srcset", "").strip() else None)
            if candidate:
                self.image_slots.append(candidate)
        if tag == "link" and "stylesheet" in values.get("rel", "").split() and values.get("href"):
            self.stylesheets.append(values["href"])
        if tag in ("img", "source"):
            if values.get("src"):
                self.references.append(values["src"])
            if values.get("srcset"):
                self.references.extend(item.strip().split()[0] for item in values["srcset"].split(",") if item.strip())


def embedded_image(reference):
    check = {"path": "embedded:" + digest(reference), "exists": False, "embedded": True, "reason": "invalid_data_image"}
    try:
        header, value = reference.split(",", 1)
        mime = header[5:].split(";", 1)[0].lower()
        encoded = unquote_to_bytes(value)
        body = base64.b64decode(re.sub(br"\s+", b"", encoded), validate=True) if ";base64" in header.lower() else encoded
        if not body or len(body) > 25 * 1024 * 1024:
            return check
        valid = False
        if mime == "image/png":
            valid = body.startswith(b"\x89PNG\r\n\x1a\n") and b"IHDR" in body[:40] and body.endswith(b"IEND\xaeB`\x82")
        elif mime in ("image/jpeg", "image/jpg"):
            valid = body.startswith(b"\xff\xd8\xff") and body.endswith(b"\xff\xd9")
        elif mime == "image/gif":
            valid = body.startswith((b"GIF87a", b"GIF89a")) and body.endswith(b";")
        elif mime == "image/webp":
            valid = body.startswith(b"RIFF") and body[8:12] == b"WEBP"
        elif mime == "image/svg+xml":
            valid = ElementTree.fromstring(body).tag.split("}")[-1] == "svg"
        check.update(exists=valid, mime=mime, size=len(body), sha256=digest(body), reason="embedded_signature_checked" if valid else "invalid_image_signature")
    except (ValueError, UnicodeError, binascii.Error, ElementTree.ParseError):
        pass
    return check


class ArchiveStore:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS archive_entries (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    record_kind TEXT NOT NULL CHECK(record_kind IN ('session','prompt','artifact')),
                    logical_key TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id,record_kind,logical_key,revision)
                );
                CREATE INDEX IF NOT EXISTS archive_project_idx ON archive_entries(project_id,record_kind,created_at DESC);
            """)

    def _project(self, identifier):
        if not isinstance(identifier, str) or not identifier:
            raise ReviewError("缺少项目 ID")
        with self.store.connection() as db:
            if getattr(self.store, "workspace_only", False) and db.execute("SELECT 1 FROM workspace_projects WHERE project_id=?", (identifier,)).fetchone() is None:
                raise ReviewError("项目未加入中控", 404)
            if db.execute("SELECT 1 FROM projects WHERE id=?", (identifier,)).fetchone() is None:
                raise ReviewError("归档项目尚未登记，请先 register", 404)

    @staticmethod
    def _validate(data, kind):
        common = {"project_id", "title", "agent", "session_id", "source", "source_ref"}
        specific = {
            "session": {"reference", "started_at"},
            "prompt": {"content", "purpose", "role", "record_type", "prompt_key", "derived_from", "redact_sensitive"},
            "artifact": {"directory", "entry", "files", "images", "prompt_ids", "status", "kind", "version", "generated_at", "artifact_key"},
        }
        if not isinstance(data, dict) or any(key not in common | specific[kind] for key in data):
            raise ReviewError("归档请求含不支持的字段；不会保存完整聊天或自动读取历史")

    @staticmethod
    def _common(data):
        source = field(data.get("source"), "source", default="unknown", maximum=200)
        source_ref = field(data.get("source_ref"), "source_ref", maximum=4000)
        return {"source": source or "unknown", "source_kind": source or "unknown", "source_ref": source_ref, "evidence": [{"label": "source", "ref": source_ref}] if source_ref else [], "verification": "unverified"}

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        return dict(json.loads(row["payload_json"]), id=row["id"], project_id=row["project_id"], revision=row["revision"], created_at=row["created_at"], logical_key=row["logical_key"], payload_hash=row["payload_hash"])

    def _save(self, identifier, kind, logical_key, payload, entry_id=None):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        fingerprint = digest(encoded)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM projects WHERE id=?", (identifier,)).fetchone() is None:
                raise ReviewError("归档项目尚未登记", 404)
            previous = db.execute("SELECT * FROM archive_entries WHERE project_id=? AND record_kind=? AND logical_key=? ORDER BY revision DESC LIMIT 1", (identifier, kind, logical_key)).fetchone()
            if previous and previous["payload_hash"] == fingerprint:
                return self._decode(previous)
            entry_id = entry_id or str(uuid.uuid4())
            revision = previous["revision"] + 1 if previous else 1
            db.execute("INSERT INTO archive_entries(id,project_id,record_kind,logical_key,revision,payload_hash,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (entry_id, identifier, kind, logical_key, revision, fingerprint, encoded, now()))
            return self._decode(db.execute("SELECT * FROM archive_entries WHERE id=?", (entry_id,)).fetchone())

    def add_session(self, data):
        self._validate(data, "session")
        identifier = data.get("project_id")
        self._project(identifier)
        agent = field(data.get("agent"), "agent", required=True, maximum=100)
        session = field(data.get("session_id"), "session_id", required=True, maximum=500)
        started = data.get("started_at")
        if started is not None:
            started = field(started, "started_at", maximum=100)
            try:
                datetime.fromisoformat(started.replace("Z", "+00:00"))
            except ValueError:
                raise ReviewError("started_at 必须为明确的 ISO 日期；未知请留空")
        payload = dict(self._common(data), agent=agent, session_id=session, external_id=session, title=field(data.get("title"), "title", required=True, maximum=500), reference=field(data.get("reference"), "reference", maximum=4000), started_at=started)
        return self._save(identifier, "session", digest(agent + "\0" + session), payload)

    def add_prompt(self, data):
        self._validate(data, "prompt")
        identifier = data.get("project_id")
        self._project(identifier)
        content = data.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > MAX_CONTENT or "\0" in content:
            raise ReviewError("提示词原文须为非空 UTF-8 文本，最多 100000 字符")
        redact = data.get("redact_sensitive", False)
        if type(redact) is not bool:
            raise ReviewError("redact_sensitive 必须为布尔值")
        redacted = has_sensitive(content)
        original_hash = digest(content)
        record_type = data.get("record_type", "original")
        if record_type not in ("original", "derived"):
            raise ReviewError("record_type 必须为 original 或 derived")
        if redacted:
            if not redact:
                raise ReviewError("提示词含疑似凭据，未保存原文；请移除凭据或显式选择脱敏派生副本", 422)
            content = clean_text(content, MAX_CONTENT)
            record_type = "derived"
        title = field(data.get("title"), "title", maximum=500, required=True)
        agent = field(data.get("agent"), "agent", maximum=100, default="unknown")
        session = field(data.get("session_id"), "session_id", maximum=500)
        purpose = field(data.get("purpose"), "purpose", maximum=2000)
        key = field(data.get("prompt_key"), "prompt_key", maximum=500) or digest("\0".join((agent, session, title, purpose)))
        derived = data.get("derived_from")
        if derived:
            previous = self.get(derived, "prompt")
            if previous["project_id"] != identifier:
                raise ReviewError("派生提示词不能引用其他项目的原文")
            record_type = "derived"
        payload = dict(self._common(data), title=title, content=content, agent=agent, session_id=session, purpose=purpose, role=field(data.get("role"), "role", default="user", maximum=100), record_type=record_type, kind=record_type, prompt_key=key, derived_from=derived or None, original_hash=original_hash, content_hash=digest(content), redacted=redacted)
        return self._save(identifier, "prompt", key, payload)

    def _files_root(self):
        root = self.store.directory / "archive_files"
        if root.is_symlink():
            raise ReviewError("归档存储目录不允许符号链接")
        root.mkdir(mode=0o700, exist_ok=True)
        return root

    def add_artifact(self, data):
        self._validate(data, "artifact")
        identifier = data.get("project_id")
        self._project(identifier)
        source = Path(field(data.get("directory"), "directory", required=True, maximum=4000)).expanduser()
        if source.is_symlink() or not source.is_dir():
            raise ReviewError("图文包必须是显式指定的现有目录，且不能为符号链接")
        source = source.resolve()
        entry = relative_path(data.get("entry", "index.html"))
        if not inside_file(source, entry).is_file():
            raise ReviewError("登记的图文入口文件不存在")
        status = data.get("status", "unknown")
        kind = data.get("kind", "publication")
        if status not in STATUSES or kind not in ("publication", "evidence", "report"):
            raise ReviewError("图文状态或类型无效")
        common = self._common(data)
        if status == "published" and common["source_ref"].strip().lower() in ("", "unknown"):
            raise ReviewError("登记 published 必须显式提供来源或发布凭据引用；不会根据文件生成推断已发布")
        images = data.get("images", [])
        files = data.get("files", [])
        prompt_ids = data.get("prompt_ids", [])
        if not isinstance(images, list) or len(images) > 100 or not isinstance(files, list) or len(files) > 25 or not isinstance(prompt_ids, list) or len(prompt_ids) > 100:
            raise ReviewError("图文图片或提示词关联格式无效")
        for prompt_id in prompt_ids:
            if self.get(prompt_id, "prompt")["project_id"] != identifier:
                raise ReviewError("图文不能关联其他项目的提示词")
        title = field(data.get("title"), "title", required=True, maximum=500)
        generated = data.get("generated_at")
        if generated is not None:
            generated = field(generated, "generated_at", maximum=100)
            try:
                datetime.fromisoformat(generated.replace("Z", "+00:00"))
            except ValueError:
                raise ReviewError("generated_at 必须为明确的 ISO 日期；未知请留空")
        key = field(data.get("artifact_key"), "artifact_key", maximum=500) or digest(str(source / entry))
        record_id = str(uuid.uuid4())
        target = self._files_root() / record_id
        target.mkdir(mode=0o700)
        manifest, references = {}, [("", path) for path in images]
        primary_slots, attachment_slots = [], []
        total = 0
        try:
            missing_references = []
            queue = [relative_path(entry)] + [relative_path(path) for path in files] + [relative_path(path) for path in images]
            explicit_files = set(queue)
            visited = set()
            while queue:
                relative = queue.pop(0)
                if relative in visited:
                    continue
                visited.add(relative)
                if len(visited) > 256:
                    raise ReviewError("图文包引用文件过多")
                file = inside_file(source, relative)
                if file.suffix.lower() not in FILE_EXTENSIONS:
                    raise ReviewError("图文引用文件格式不允许")
                if not file.is_file():
                    if relative in explicit_files:
                        raise ReviewError("显式登记的图文文件不存在")
                    missing_references.append(relative)
                    continue
                if file.stat().st_size > 25 * 1024 * 1024:
                    raise ReviewError("图文包含过大的文件")
                body = file.read_bytes()
                total += len(body)
                if total > 80 * 1024 * 1024:
                    raise ReviewError("图文包超过大小上限")
                resources = []
                if file.suffix.lower() in (".html", ".htm", ".css", ".txt", ".md"):
                    try:
                        text = body.decode("utf-8")
                    except UnicodeError:
                        raise ReviewError("图文文本文件须为 UTF-8")
                    if has_sensitive(text):
                        raise ReviewError("图文包含疑似凭据，未归档；请检查原包", 422)
                    if file.suffix.lower() in (".html", ".htm"):
                        parser = ImageReferences()
                        parser.feed(text)
                        if relative == entry:
                            primary_slots = parser.image_slots
                        else:
                            attachment_slots.extend(parser.image_slots)
                        references.extend((relative, ref) for ref in parser.references)
                        resources.extend(parser.references + parser.stylesheets)
                    css_refs = re.findall(r'''url\(\s*["']?([^\s)"']+)["']?\s*\)''', text)
                    references.extend((relative, ref) for ref in css_refs)
                    resources.extend(css_refs)
                    if file.suffix.lower() == ".css":
                        resources.extend(re.findall(r'''@import\s+["']([^"']+)["']''', text))
                for resource in resources:
                    if resource.strip().lower().startswith("data:"):
                        continue
                    parsed = urlsplit(resource)
                    if parsed.scheme or parsed.netloc or not parsed.path:
                        continue
                    path = unquote(parsed.path)
                    path = path.lstrip("/") if path.startswith("/") else (PurePosixPath(relative).parent / path).as_posix()
                    path = relative_path(posixpath.normpath(path))
                    if Path(path).suffix.lower() in FILE_EXTENSIONS:
                        queue.append(path)
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination.write_bytes(body)
                destination.chmod(0o600)
                manifest[relative] = {"sha256": digest(body), "size": len(body), "mime": mimetypes.guess_type(relative)[0] or "application/octet-stream"}
            if entry not in manifest:
                raise ReviewError("图文入口格式不在允许的只读文件类型中")
            def image_check(base, reference):
                if isinstance(reference, str) and reference.strip().lower().startswith("data:"):
                    return embedded_image(reference.strip())
                reference = field(reference, "image", maximum=4000, required=True)
                parsed = urlsplit(reference)
                if parsed.scheme or parsed.netloc:
                    return {"path": reference, "exists": None, "reason": "external_not_fetched"}
                path = unquote(parsed.path)
                if path.startswith("/"):
                    path = path.lstrip("/")
                else:
                    path = (PurePosixPath(base).parent / path).as_posix()
                path = relative_path(posixpath.normpath(path))
                return {"path": path, "exists": path in manifest, "embedded": False}
            primary_checks = [image_check(entry, ref) for ref in primary_slots]
            image_checks = [image_check(base, reference) for base, reference in references if isinstance(reference, str) and (reference.lower().startswith("data:") or urlsplit(reference).scheme or urlsplit(reference).netloc or Path(urlsplit(reference).path).suffix.lower() in IMAGE_EXTENSIONS)]
            image_checks = list({check["path"]: check for check in image_checks + primary_checks}.values())
            payload = dict(common, title=title, kind=kind, status=status, version=field(data.get("version"), "version", default="unknown", maximum=200), generated_at=generated, agent=field(data.get("agent"), "agent", default="unknown", maximum=100), session_id=field(data.get("session_id"), "session_id", maximum=500), prompt_ids=prompt_ids, directory=str(source), entry=entry, files=files, artifact_key=key, manifest=manifest, missing_references=missing_references, package_hash=digest(json.dumps(manifest, sort_keys=True)), images=image_checks, html_count=sum(Path(path).suffix.lower() in (".html", ".htm") for path in manifest), image_count=sum(Path(path).suffix.lower() in IMAGE_EXTENSIONS for path in manifest), original_hash=None, redacted=False)
            payload["original_hash"] = manifest[entry]["sha256"]
            payload["content_hash"] = manifest[entry]["sha256"]
            payload["primary_images"] = primary_checks
            payload["image_file_count"] = payload["image_count"]
            payload["image_count"] = len(primary_checks)
            payload["embedded_image_count"] = sum(check.get("embedded", False) for check in primary_checks)
            payload["attachment_image_count"] = len(attachment_slots)
            result = self._save(identifier, "artifact", key, payload, record_id)
            if result["id"] != record_id:
                shutil.rmtree(target)
            return self.artifact_state(result)
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            raise

    def get(self, identifier, kind=None):
        if not isinstance(identifier, str):
            raise ReviewError("归档 ID 无效")
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM archive_entries WHERE id=?", (identifier,)).fetchone()
        if row is None or (kind and row["record_kind"] != kind):
            raise ReviewError("归档记录不存在", 404)
        return self._decode(row)

    def artifact_file(self, identifier, path):
        artifact = self.get(identifier, "artifact")
        relative = relative_path(path)
        metadata = artifact["manifest"].get(relative)
        if metadata is None:
            raise ReviewError("文件不在该图文包的登记白名单中", 404)
        folder = self._files_root() / artifact["id"]
        file = inside_file(folder, relative)
        if not file.is_file() or file.stat().st_size != metadata["size"]:
            raise ReviewError("归档文件缺失或发生变化", 409)
        body = file.read_bytes()
        if digest(body) != metadata["sha256"]:
            raise ReviewError("归档文件校验不一致，未提供该文件", 409)
        return body, metadata["mime"]

    def artifact_state(self, artifact):
        missing = []
        for path in artifact["manifest"]:
            try:
                self.artifact_file(artifact["id"], path)
            except (ReviewError, OSError):
                missing.append(path)
        result = dict(artifact)
        result["missing_files"] = missing
        primary = artifact.get("primary_images", artifact["images"])
        result["missing_image_count"] = sum(image["exists"] is False or image["path"] in missing for image in primary)
        result["unverified_image_count"] = sum(image["exists"] is None for image in primary)
        result["verified_image_count"] = sum(image["exists"] is True and image["path"] not in missing for image in primary)
        result["file_state"] = "missing" if missing or artifact.get("missing_references") or result["missing_image_count"] else "present"
        result["images_verified"] = bool(primary) and all(image["exists"] is True and image["path"] not in missing for image in primary)
        result["preview_url"] = None
        return result

    def list(self, identifier=None, query="", limit=100):
        if identifier:
            self._project(identifier)
        if not isinstance(query, str) or len(query) > 500:
            raise ReviewError("归档搜索词无效")
        output = {"project_id": identifier, "sessions": [], "prompts": [], "artifacts": [], "counts": {}, "has_more": {}}
        with self.store.connection() as db:
            for kind, plural in (("session", "sessions"), ("prompt", "prompts"), ("artifact", "artifacts")):
                where = "e.record_kind=? AND NOT EXISTS (SELECT 1 FROM archive_entries n WHERE n.project_id=e.project_id AND n.record_kind=e.record_kind AND n.logical_key=e.logical_key AND n.revision>e.revision)"
                if getattr(self.store, "workspace_only", False):
                    where += " AND e.project_id IN (SELECT project_id FROM workspace_projects)"
                parameters = [kind]
                if identifier:
                    where += " AND e.project_id=?"
                    parameters.append(identifier)
                if query:
                    where += " AND instr(lower(e.payload_json),lower(?))>0"
                    parameters.append(query)
                count = db.execute("SELECT COUNT(*) FROM archive_entries e WHERE " + where, parameters).fetchone()[0]
                rows = db.execute("SELECT e.* FROM archive_entries e WHERE " + where + " ORDER BY e.created_at DESC,e.rowid DESC LIMIT ?", parameters + [limit]).fetchall()
                values = [self._decode(row) for row in rows]
                if kind == "artifact":
                    values = [self.artifact_state(value) for value in values]
                if kind == "prompt":
                    values = [dict(value, version=value["revision"]) for value in values]
                output[plural] = values
                output["counts"][plural] = count
                output["has_more"][plural] = count > len(values)
        output["agent_usage"] = self.agent_usage(identifier)
        output["policy"] = {"full_transcripts_stored": False, "raw_prompts_sent_to_models_by_default": False, "sources_verified_automatically": False}
        return output

    def agent_usage(self, identifier=None):
        where = " WHERE project_id=?" if identifier else ""
        parameters = [identifier] if identifier else []
        if getattr(self.store, "workspace_only", False):
            where += (" AND " if where else " WHERE ") + "project_id IN (SELECT project_id FROM workspace_projects)"
        with self.store.connection() as db:
            rows = db.execute("SELECT project_id,agent,COUNT(*) AS event_count,COUNT(DISTINCT run_id) AS run_count,MAX(created_at) AS last_seen FROM events" + where + " GROUP BY project_id,agent", parameters).fetchall()
        return [dict(row, source="worklog", session_id=None) for row in rows]

    def projects(self):
        projects = self.store.projects()
        with self.store.connection() as db:
            rows = db.execute("SELECT project_id,record_kind,COUNT(DISTINCT logical_key) AS n FROM archive_entries GROUP BY project_id,record_kind").fetchall()
        counts = {(row["project_id"], row["record_kind"]): row["n"] for row in rows}
        usage = self.agent_usage()
        return {"projects": [dict(project, session_count=counts.get((project["id"], "session"), 0), prompt_count=counts.get((project["id"], "prompt"), 0), artifact_count=counts.get((project["id"], "artifact"), 0), agent_usage=[item for item in usage if item["project_id"] == project["id"]]) for project in projects]}

    def prompt(self, identifier):
        prompt = self.get(identifier, "prompt")
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM archive_entries WHERE project_id=? AND record_kind='prompt' AND logical_key=? ORDER BY revision DESC", (prompt["project_id"], prompt["logical_key"])).fetchall()
        return {"prompt": dict(prompt, version=prompt["revision"]), "history": [dict(self._decode(row), version=row["revision"]) for row in rows]}

    def artifact(self, identifier):
        artifact = self.get(identifier, "artifact")
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM archive_entries WHERE project_id=? AND record_kind='artifact' AND logical_key=? ORDER BY revision DESC", (artifact["project_id"], artifact["logical_key"])).fetchall()
        return {"artifact": self.artifact_state(artifact), "history": [self.artifact_state(self._decode(row)) for row in rows]}
