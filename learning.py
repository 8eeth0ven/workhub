"""Project learning cards with durable revisions and user-owned acknowledgements.

Only explicitly supplied text is stored. This module never reads project source,
configuration, transcripts, or model providers. Source paths are references, not
an instruction to open files; their continued existence is not required.
"""

from datetime import date, datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import parse_qsl, unquote, urlsplit
import uuid

from assessments import ReviewError


class LearningError(ReviewError):
    """Safe validation/conflict errors; never includes rejected field values."""


STATUSES = ("pending", "understood", "needs_review")
MAX_PAYLOAD_BYTES = 100000
ORIGIN_FIELDS = {"agent", "run_id", "source_event_ids"}
PRIVATE_NAMES = {
    "glm.json", "llm.json", "credentials.json", "credentials.yaml",
    "credentials.yml", "secrets.json", "secrets.yaml", "secrets.yml",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "session.json",
}
TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{25,}|"
    r"sk-(?:proj-|ant-api\d*-)?[A-Za-z0-9_-]{24,}|xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16})\b"
)
SECRET_LITERAL = re.compile(
    r'''(?i)\b(?:api[_-]?keys?|access[_-]?token|refresh[_-]?token|password|secret|token)["']?\s*[:=]\s*["']([^"'\r\n]+)["']'''
)
BEARER = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]{16,})")
ENV_LITERAL = re.compile(r"(?m)^\s*(?:export\s+)?[A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|SECRET)\s*=\s*([A-Za-z0-9./+=-]{12,})\s*$")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _placeholder(value):
    return bool(re.match(r"(?i)^(?:YOUR[_ -]|REPLACE[_ -]|CHANGE[_ -]?ME|EXAMPLE(?:[_ -]|$)|DUMMY[_ -]|FAKE[_ -]|REDACTED|<[^>]+>$|\[凭据已隐藏\]$)", value))


def _sensitive(value):
    if re.search(r"-----BEGIN (?P<kind>(?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY)-----[\s\S]{24,}?-----END (?P=kind)-----", value, re.I):
        return True
    if any(not _placeholder(m.group(0).split("_", 1)[-1]) for m in TOKEN.finditer(value)):
        return True
    return any(not _placeholder(m.group(1)) for p in (SECRET_LITERAL, BEARER, ENV_LITERAL) for m in p.finditer(value))


def _text(value, name, maximum, required=False, default=""):
    if value is None:
        value = default
    if not isinstance(value, str) or len(value) > maximum or "\0" in value or (required and not value.strip()):
        raise LearningError("学习卡片字段无效：" + name)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise LearningError("学习卡片字段必须是有效 UTF-8 文本：" + name) from None
    if _sensitive(value):
        raise LearningError("学习卡片含疑似凭据，未保存；请移除后重试（" + name + "）", 422)
    return value


def _only_fields(value, allowed, name):
    if not isinstance(value, dict) or any(k not in allowed for k in value):
        raise LearningError("学习卡片含不支持的字段：" + name)


def _source_path(value):
    value = _text(value, "sources.path", 1000, required=True)
    parts = value.split("/")
    if (value != value.strip() or "\\" in value or ":" in value or any(ord(c) < 32 for c in value)
            or PurePosixPath(value).is_absolute() or any(not p or p in (".", "..") or p.startswith(".") for p in parts)
            or any(p.lower() in PRIVATE_NAMES for p in parts)
            or PurePosixPath(value).suffix.lower() in {".key", ".pem", ".p12", ".pfx", ".keystore", ".db", ".sqlite", ".sqlite3", ".log", ".pid"}
            or re.search(r"%(?:00|2e|2f|5c)", value, re.I)):
        raise LearningError("学习来源必须是项目内可引用的相对源码路径，不允许私有文件")
    return value


def _source_reference(item, field="sources"):
    _only_fields(item, {"path", "line", "symbol", "note"}, field)
    source = {"path": _source_path(item.get("path"))}
    if "line" in item:
        if type(item["line"]) is not int or not 0 < item["line"] <= 10000000:
            raise LearningError(field + ".line 必须为正整数")
        source["line"] = item["line"]
    for name, limit in (("symbol", 300), ("note", 1500)):
        if name in item:
            source[name] = _text(item[name], field + "." + name, limit)
    return source


def _references(value, field):
    if not isinstance(value, list) or len(value) > 20:
        raise LearningError(field + " 必须为最多 20 项的来源列表")
    return [_source_reference(item, field) for item in value]


def _text_list(value, field, count, length):
    if not isinstance(value, list) or len(value) > count:
        raise LearningError(field + " 必须为数量受限的列表")
    return [_text(item, field, length, required=True) for item in value]


def _public_https_url(value):
    """A public clickable source, never fetched by this module."""
    value = _text(value, "market_signals.url", 4096, required=True)
    if (value != value.strip() or any(ord(c) < 33 or ord(c) == 127 for c in value)
            or "\\" in value or re.search(r"%(?:00|0a|0d|5c)", value, re.I)):
        raise LearningError("前沿来源须为不含凭据的公开 HTTPS 链接")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (parsed.scheme.lower() != "https" or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or host.endswith(".") or "." not in host):
            raise ValueError()
        host = host.encode("idna").decode("ascii").lower()
        if (len(host) > 253 or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".test", ".invalid"))
                or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.split("."))):
            raise ValueError()
        # Browsers may interpret old-form IPv4 such as 127.1 or 0x7f.1.
        if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", part) for part in host.split(".")):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if re.fullmatch(r"[0-9.]+", host):
                raise ValueError()
        else:
            raise ValueError()
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=100):
            if re.search(r"token|secret|password|api.?key|authorization|signature|credential|session", key, re.I):
                raise ValueError()
        if _sensitive(unquote(value)):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise LearningError("前沿来源须为不含凭据的公开 HTTPS 链接") from None
    return value


def _access_date(value):
    value = _text(value, "market_signals.accessed_on", 10, required=True)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise LearningError("前沿来源的查阅日期须为 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise LearningError("前沿来源的查阅日期无效") from None
    if parsed > date.today():
        raise LearningError("前沿来源的查阅日期不能晚于今天")
    return value


def _interview(value):
    _only_fields(value, {"role_context", "talk_track", "questions", "decisions"}, "interview")
    result = {}
    for name, limit in (("role_context", 500), ("talk_track", 6000)):
        if name in value:
            result[name] = _text(value[name], "interview." + name, limit)
    if "questions" in value:
        questions = value["questions"]
        if not isinstance(questions, list) or len(questions) > 20:
            raise LearningError("interview.questions 必须为最多 20 项的列表")
        result["questions"] = []
        for question in questions:
            _only_fields(question, {"question", "answer_points", "follow_ups", "evidence"}, "interview.questions")
            entry = {"question": _text(question.get("question"), "interview.question", 2000, required=True)}
            for name in ("answer_points", "follow_ups"):
                if name in question:
                    entry[name] = _text_list(question[name], "interview." + name, 12, 2000)
            if "evidence" in question:
                entry["evidence"] = _references(question["evidence"], "interview.questions.evidence")
            result["questions"].append(entry)
    if "decisions" in value:
        decisions = value["decisions"]
        if not isinstance(decisions, list) or len(decisions) > 20:
            raise LearningError("interview.decisions 必须为最多 20 项的列表")
        result["decisions"] = []
        for decision in decisions:
            names = {"choice", "alternative", "reason", "tradeoff", "failure_mode", "validation", "evidence"}
            _only_fields(decision, names, "interview.decisions")
            entry = {"choice": _text(decision.get("choice"), "interview.decisions.choice", 2000, required=True)}
            for name in ("alternative", "reason", "tradeoff", "failure_mode", "validation"):
                if name in decision:
                    entry[name] = _text(decision[name], "interview.decisions." + name, 4000)
            if "evidence" in decision:
                entry["evidence"] = _references(decision["evidence"], "interview.decisions.evidence")
            result["decisions"].append(entry)
    return result


def _market_signals(value):
    if not isinstance(value, list) or len(value) > 20:
        raise LearningError("market_signals 必须为最多 20 项的列表")
    result = []
    for signal in value:
        fields = {"role", "organization", "region", "url", "accessed_on", "summary", "project_relevance", "limitations"}
        _only_fields(signal, fields, "market_signals")
        entry = {"role": _text(signal.get("role"), "market_signals.role", 300, required=True),
                 "organization": _text(signal.get("organization"), "market_signals.organization", 300, required=True),
                 "url": _public_https_url(signal.get("url")),
                 "accessed_on": _access_date(signal.get("accessed_on")),
                 "summary": _text(signal.get("summary"), "market_signals.summary", 3000, required=True)}
        for name, limit in (("region", 300), ("project_relevance", 3000), ("limitations", 3000)):
            if name in signal:
                entry[name] = _text(signal[name], "market_signals." + name, limit)
        result.append(entry)
    return result


def _payload(data):
    allowed = {"project_id", "project", "card_key", "title", "concept", "explanation", "implementation", "terms", "steps", "example", "self_check", "sources", "agent", "run_id", "source_event_ids", "why", "interview", "market_signals"}
    _only_fields(data, allowed, "card")
    if ("project_id" in data) == ("project" in data):
        raise LearningError("project_id 与 project 必须且只能提供一个")
    key = _text(data.get("card_key"), "card_key", 200, required=True)
    if key != key.strip() or any(ord(c) < 32 for c in key):
        raise LearningError("card_key 必须是稳定的非空主题标识")
    fields = {"card_key": key}
    for name, limit in (("title", 300), ("concept", 1000), ("explanation", 12000), ("implementation", 15000), ("self_check", 4000)):
        fields[name] = _text(data.get(name), name, limit, required=True)
    if "why" in data:
        fields["why"] = _text(data["why"], "why", 12000)
    if "interview" in data:
        fields["interview"] = _interview(data["interview"])
    if "market_signals" in data:
        fields["market_signals"] = _market_signals(data["market_signals"])
    fields["example"] = _text(data.get("example"), "example", 12000)
    fields["agent"] = _text(data.get("agent"), "agent", 100, default="unknown") or "unknown"
    fields["run_id"] = _text(data.get("run_id"), "run_id", 500)
    terms = data.get("terms", [])
    if not isinstance(terms, list) or len(terms) > 50:
        raise LearningError("terms 必须为最多 50 项的列表")
    fields["terms"] = []
    for item in terms:
        _only_fields(item, {"term", "definition", "english", "project_context", "distinction"}, "terms")
        term = {"term": _text(item.get("term"), "term", 200, required=True), "definition": _text(item.get("definition"), "definition", 2000, required=True)}
        for name, limit in (("english", 200), ("project_context", 2000), ("distinction", 2000)):
            if name in item:
                term[name] = _text(item[name], "terms." + name, limit)
        fields["terms"].append(term)
    steps = data.get("steps", [])
    if not isinstance(steps, list) or len(steps) > 30:
        raise LearningError("steps 必须为最多 30 项的列表")
    fields["steps"] = [_text(x, "steps", 3000, required=True) for x in steps]
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources or len(sources) > 50:
        raise LearningError("每张学习卡片至少需要一个真实源码来源，最多 50 项")
    fields["sources"] = []
    for item in sources:
        fields["sources"].append(_source_reference(item))
    source_paths = {item["path"] for item in fields["sources"]}
    for group in ("questions", "decisions"):
        for entry in fields.get("interview", {}).get(group, []):
            if any(ref["path"] not in source_paths for ref in entry.get("evidence", [])):
                raise LearningError("面试内容的项目证据须对应本卡已有源码来源", 422)
    events = data.get("source_event_ids", [])
    if not isinstance(events, list) or len(events) > 100 or any(type(x) is not int or not 0 < x <= 9223372036854775807 for x in events):
        raise LearningError("source_event_ids 必须为正整数列表")
    fields["source_event_ids"] = sorted(set(events))
    if len(json.dumps(fields, ensure_ascii=False).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise LearningError("学习卡片内容超过允许大小")
    return fields


def _knowledge(content):
    """Provenance does not change what the user is being asked to understand."""
    return {key: value for key, value in content.items() if key not in ORIGIN_FIELDS}


def _encode(content):
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class LearningStore:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS learning_cards (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    card_key TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id,card_key)
                );
                CREATE TABLE IF NOT EXISTS learning_versions (
                    card_id TEXT NOT NULL REFERENCES learning_cards(id),
                    revision INTEGER NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(card_id,revision)
                );
                CREATE TABLE IF NOT EXISTS learning_acknowledgements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    understood INTEGER NOT NULL CHECK(understood IN (0,1)),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(card_id,revision) REFERENCES learning_versions(card_id,revision)
                );
                CREATE TABLE IF NOT EXISTS learning_origins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    origin_hash TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    source_event_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(card_id,revision) REFERENCES learning_versions(card_id,revision),
                    UNIQUE(card_id,revision,origin_hash)
                );
                CREATE TABLE IF NOT EXISTS learning_removed (
                    card_id TEXT PRIMARY KEY REFERENCES learning_cards(id),
                    removed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learning_lifecycle (
                    card_id TEXT PRIMARY KEY REFERENCES learning_cards(id),
                    version INTEGER NOT NULL CHECK(version >= 0)
                );
                CREATE TABLE IF NOT EXISTS learning_user_edits (
                    card_id TEXT PRIMARY KEY REFERENCES learning_cards(id),
                    edited_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS learning_project_idx ON learning_cards(project_id,updated_at DESC);
                CREATE INDEX IF NOT EXISTS learning_ack_idx ON learning_acknowledgements(card_id,revision,id DESC);
                CREATE INDEX IF NOT EXISTS learning_origin_idx ON learning_origins(card_id,revision,id DESC);
            """)

    @staticmethod
    def _project(db, data):
        if "project_id" in data:
            identifier = _text(data["project_id"], "project_id", 200, required=True)
            row = db.execute("SELECT id FROM projects WHERE id=?", (identifier,)).fetchone()
        else:
            raw = _text(data["project"], "project", 4000, required=True)
            if not Path(raw).expanduser().is_absolute():
                raise LearningError("project 必须是已登记项目的真实绝对目录")
            try:
                path = str(Path(raw).expanduser().resolve())
            except (OSError, ValueError, RuntimeError):
                raise LearningError("项目路径无效") from None
            row = db.execute("SELECT id FROM projects WHERE path=?", (path,)).fetchone()
        if row is None:
            raise LearningError("学习卡片项目尚未登记", 404)
        return row["id"]

    @staticmethod
    def _row(db, identifier):
        identifier = _text(identifier, "id", 200, required=True)
        row = db.execute("""SELECT c.*,v.payload_hash,v.payload_json,v.created_at AS version_created_at,
            p.name AS project_name FROM learning_cards c
            JOIN learning_versions v ON v.card_id=c.id AND v.revision=c.revision
            JOIN projects p ON p.id=c.project_id WHERE c.id=?""", (identifier,)).fetchone()
        if row is None:
            raise LearningError("学习卡片不存在", 404)
        return row

    @staticmethod
    def _decode(db, row):
        acknowledgements = db.execute("""SELECT * FROM learning_acknowledgements
            WHERE card_id=? ORDER BY id DESC""", (row["id"],)).fetchall()
        latest = {}
        for item in acknowledgements:
            latest.setdefault(item["revision"], item)
        current = latest.get(row["revision"])
        understood = bool(current and current["understood"])
        previous = max((revision for revision, item in latest.items() if revision < row["revision"] and item["understood"]), default=None)
        prior_revision = max((r for r in latest if r < row["revision"]), default=None)
        prior_ack = latest.get(prior_revision)
        status = "understood" if understood else "pending" if current is not None else "needs_review" if prior_ack is not None and prior_ack["understood"] else "pending"
        acknowledgement = {"revision": current["revision"], "understood": bool(current["understood"]), "created_at": current["created_at"]} if current else None
        content = json.loads(row["payload_json"])
        origin = db.execute("SELECT * FROM learning_origins WHERE card_id=? AND revision=? ORDER BY id DESC LIMIT 1", (row["id"], row["revision"])).fetchone()
        provenance = {"agent": origin["agent"], "run_id": origin["run_id"], "source_event_ids": json.loads(origin["source_event_ids_json"])} if origin else {key: content.get(key, [] if key == "source_event_ids" else "unknown" if key == "agent" else "") for key in ORIGIN_FIELDS}
        content.update(provenance)
        lifecycle = db.execute("SELECT version FROM learning_lifecycle WHERE card_id=?", (row["id"],)).fetchone()
        lifecycle_version = lifecycle["version"] if lifecycle else 0
        return dict(content, lifecycle_version=lifecycle_version, id=row["id"], project_id=row["project_id"], project_name=row["project_name"], revision=row["revision"], created_at=row["created_at"], updated_at=row["updated_at"], version_created_at=row["version_created_at"], payload_hash=row["payload_hash"], content_hash=hashlib.sha256(_encode(_knowledge(content)).encode("utf-8")).hexdigest(), status=status, understood=understood, needs_review=status == "needs_review", acknowledgement=acknowledgement, previous_understood_revision=previous)

    @staticmethod
    def _origin(db, identifier, revision, content):
        origin = {key: content[key] for key in ORIGIN_FIELDS}
        fingerprint = hashlib.sha256(_encode(origin).encode("utf-8")).hexdigest()
        db.execute("""INSERT OR IGNORE INTO learning_origins
            (card_id,revision,origin_hash,agent,run_id,source_event_ids_json,created_at)
            VALUES(?,?,?,?,?,?,?)""", (identifier, revision, fingerprint, origin["agent"], origin["run_id"], json.dumps(origin["source_event_ids"]), _now()))

    def add_card(self, payload):
        if not isinstance(payload, dict):
            raise LearningError("学习卡片内容无效")
        expected = payload.get("expected_revision")
        if "expected_revision" in payload and (type(expected) is not int or expected <= 0):
            raise LearningError("expected_revision 必须为正整数")
        knowledge_payload = {k: v for k, v in payload.items() if k != "expected_revision"}
        content = _payload(knowledge_payload)
        encoded = _encode(_knowledge(content))
        fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            project = self._project(db, payload)
            for event_id in content["source_event_ids"]:
                event = db.execute("SELECT project_id FROM events WHERE id=?", (event_id,)).fetchone()
                if event is None or event["project_id"] != project:
                    raise LearningError("来源工作记录不存在或不属于该项目", 422)
            previous = db.execute("SELECT * FROM learning_cards WHERE project_id=? AND card_key=?", (project, content["card_key"])).fetchone()
            if previous:
                current = self._row(db, previous["id"])
                if db.execute("SELECT 1 FROM learning_removed WHERE card_id=?", (current["id"],)).fetchone():
                    raise LearningError("学习卡已移除，请先从回收站恢复", 409)
                if hashlib.sha256(_encode(_knowledge(json.loads(current["payload_json"]))).encode("utf-8")).hexdigest() == fingerprint:
                    self._origin(db, current["id"], current["revision"], content)
                    return self._decode(db, current)
                if expected is not None:
                    self._expected_revision(current, expected)
                elif db.execute("SELECT 1 FROM learning_user_edits WHERE card_id=?", (current["id"],)).fetchone():
                    raise LearningError("卡片曾由用户编辑；请读取当前版本并提供 expected_revision 后更新", 409)
                identifier, revision = current["id"], current["revision"] + 1
                stamp = _now()
                db.execute("UPDATE learning_cards SET revision=?,updated_at=? WHERE id=?", (revision, stamp, identifier))
            else:
                if expected is not None:
                    raise LearningError("学习卡片不存在，请刷新后重试", 409)
                identifier, revision, stamp = str(uuid.uuid4()), 1, _now()
                db.execute("INSERT INTO learning_cards(id,project_id,card_key,revision,created_at,updated_at) VALUES(?,?,?,?,?,?)", (identifier, project, content["card_key"], revision, stamp, stamp))
            db.execute("INSERT INTO learning_versions(card_id,revision,payload_hash,payload_json,created_at) VALUES(?,?,?,?,?)", (identifier, revision, fingerprint, encoded, stamp))
            self._origin(db, identifier, revision, content)
            return self._decode(db, self._row(db, identifier))

    def list(self, project_id=None, query="", status="", removed=False):
        if type(removed) is not bool:
            raise LearningError("回收站参数无效")
        query = _text(query, "query", 500).casefold()
        if status not in ("", *STATUSES):
            raise LearningError("学习状态无效")
        with self.store.connection() as db:
            params = []
            where = ""
            if project_id is not None:
                project_id = self._project(db, {"project_id": project_id})
                where = " WHERE c.project_id=?"
                params.append(project_id)
            if getattr(self.store, "workspace_only", False):
                where += (" AND " if where else " WHERE ") + "c.project_id IN (SELECT project_id FROM workspace_projects)"
            where += (" AND " if where else " WHERE ") + ("EXISTS" if removed else "NOT EXISTS") + " (SELECT 1 FROM learning_removed r WHERE r.card_id=c.id)"
            rows = db.execute("""SELECT c.*,v.payload_hash,v.payload_json,v.created_at AS version_created_at,
                p.name AS project_name FROM learning_cards c
                JOIN learning_versions v ON v.card_id=c.id AND v.revision=c.revision
                JOIN projects p ON p.id=c.project_id""" + where + " ORDER BY c.updated_at DESC,c.id", params).fetchall()
            cards = [self._decode(db, row) for row in rows]
        if query:
            cards = [card for card in cards if query in "\n".join([card["project_name"], *(card[k] for k in ("title", "concept", "explanation", "implementation", "example", "self_check")), card.get("why", ""), json.dumps(card["terms"], ensure_ascii=False), "\n".join(card["steps"]), json.dumps(card.get("interview", {}), ensure_ascii=False), json.dumps(card.get("market_signals", []), ensure_ascii=False)]).casefold()]
        stats = {"total": len(cards), **{key: sum(card["status"] == key for card in cards) for key in STATUSES}}
        return {"cards": [card for card in cards if not status or card["status"] == status], "stats": stats}

    def get(self, identifier, include_removed=False):
        if type(include_removed) is not bool:
            raise LearningError("回收站参数无效")
        with self.store.connection() as db:
            row = self._row(db, identifier)
            self._require_scope(db, row)
            if not include_removed and db.execute("SELECT 1 FROM learning_removed WHERE card_id=?", (identifier,)).fetchone():
                raise LearningError("学习卡片不存在", 404)
            card = self._decode(db, row)
            history = []
            for row in db.execute("SELECT * FROM learning_versions WHERE card_id=? ORDER BY revision DESC", (identifier,)):
                payload = json.loads(row["payload_json"])
                acks = [{"understood": bool(x["understood"]), "created_at": x["created_at"]} for x in db.execute("SELECT * FROM learning_acknowledgements WHERE card_id=? AND revision=? ORDER BY id DESC", (identifier, row["revision"]))]
                history.append({"revision": row["revision"], "title": payload["title"], "created_at": row["created_at"], "payload_hash": row["payload_hash"], "understood": bool(acks and acks[0]["understood"]), "acknowledgements": acks})
            origins = [{"revision": row["revision"], "agent": row["agent"], "run_id": row["run_id"], "source_event_ids": json.loads(row["source_event_ids_json"]), "created_at": row["created_at"]} for row in db.execute("SELECT * FROM learning_origins WHERE card_id=? ORDER BY revision DESC,id DESC", (identifier,))]
            return {"card": card, "history": history, "origins": origins}

    def _require_scope(self, db, row, project_id=None):
        if project_id is not None:
            project_id = _text(project_id, "project_id", 200, required=True)
            if row["project_id"] != project_id:
                raise LearningError("学习卡片不存在", 404)
        if getattr(self.store, "workspace_only", False) and not db.execute(
                "SELECT 1 FROM workspace_projects WHERE project_id=?", (row["project_id"],)).fetchone():
            raise LearningError("学习卡片不存在", 404)

    @staticmethod
    def _expected_revision(row, revision):
        if type(revision) is not int or revision <= 0:
            raise LearningError("expected_revision 必须为正整数")
        if revision != row["revision"]:
            raise LearningError("学习卡片已更新，请刷新后重试", 409)

    def edit(self, identifier, expected_revision, project_id, card):
        project_id = _text(project_id, "project_id", 200, required=True)
        # Validate the entire replacement before acquiring the write lock.
        if not isinstance(card, dict):
            raise LearningError("学习卡片内容无效")
        if "project" in card or ("project_id" in card and card["project_id"] != project_id):
            raise LearningError("不允许更改学习卡所属项目")
        candidate = dict(card, project_id=project_id)
        content = _payload(candidate)
        encoded = _encode(_knowledge(content))
        fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, identifier)
            self._require_scope(db, row, project_id)
            self._expected_revision(row, expected_revision)
            if db.execute("SELECT 1 FROM learning_removed WHERE card_id=?", (identifier,)).fetchone():
                raise LearningError("学习卡已移除，请先恢复", 409)
            if content["card_key"] != row["card_key"]:
                raise LearningError("不允许更改学习卡主题标识")
            for event_id in content["source_event_ids"]:
                event = db.execute("SELECT project_id FROM events WHERE id=?", (event_id,)).fetchone()
                if event is None or event["project_id"] != row["project_id"]:
                    raise LearningError("来源工作记录不存在或不属于该项目", 422)
            if fingerprint != row["payload_hash"]:
                revision = row["revision"] + 1
                stamp = _now()
                db.execute("UPDATE learning_cards SET revision=?,updated_at=? WHERE id=?", (revision, stamp, identifier))
                db.execute("INSERT INTO learning_versions(card_id,revision,payload_hash,payload_json,created_at) VALUES(?,?,?,?,?)", (identifier, revision, fingerprint, encoded, stamp))
                db.execute("INSERT INTO learning_user_edits(card_id,edited_at) VALUES(?,?) ON CONFLICT(card_id) DO UPDATE SET edited_at=excluded.edited_at", (identifier, stamp))
            else:
                revision = row["revision"]
            self._origin(db, identifier, revision, content)
            return self._decode(db, self._row(db, identifier))

    def set_removed(self, identifier, expected_revision, project_id, removed, expected_lifecycle_version):
        project_id = _text(project_id, "project_id", 200, required=True)
        if type(removed) is not bool:
            raise LearningError("移除状态无效")
        if type(expected_lifecycle_version) is not int or expected_lifecycle_version < 0:
            raise LearningError("expected_lifecycle_version 必须为非负整数")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, identifier)
            self._require_scope(db, row, project_id)
            self._expected_revision(row, expected_revision)
            lifecycle = db.execute("SELECT version FROM learning_lifecycle WHERE card_id=?", (identifier,)).fetchone()
            current = lifecycle["version"] if lifecycle else 0
            if current != expected_lifecycle_version:
                raise LearningError("学习卡状态已变化，请刷新后重试", 409)
            is_removed = bool(db.execute("SELECT 1 FROM learning_removed WHERE card_id=?", (identifier,)).fetchone())
            if is_removed != removed:
                if removed:
                    db.execute("INSERT INTO learning_removed(card_id,removed_at) VALUES(?,?)", (identifier, _now()))
                else:
                    db.execute("DELETE FROM learning_removed WHERE card_id=?", (identifier,))
                db.execute("INSERT INTO learning_lifecycle(card_id,version) VALUES(?,1) ON CONFLICT(card_id) DO UPDATE SET version=version+1", (identifier,))
            return self._decode(db, row)

    def acknowledge(self, identifier, revision, understood):
        if type(revision) is not int or revision <= 0:
            raise LearningError("revision 必须为正整数")
        if type(understood) is not bool:
            raise LearningError("understood 必须为布尔值")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, identifier)
            self._require_scope(db, row)
            if db.execute("SELECT 1 FROM learning_removed WHERE card_id=?", (identifier,)).fetchone():
                raise LearningError("学习卡已移除，请先恢复", 409)
            if revision != row["revision"]:
                raise LearningError("学习卡片已更新，请读取当前版本后重新勾选", 409)
            previous = db.execute("SELECT understood FROM learning_acknowledgements WHERE card_id=? AND revision=? ORDER BY id DESC LIMIT 1", (identifier, revision)).fetchone()
            if previous is None or bool(previous["understood"]) != understood:
                db.execute("INSERT INTO learning_acknowledgements(card_id,revision,understood,created_at) VALUES(?,?,?,?)", (identifier, revision, int(understood), _now()))
            return self._decode(db, row)
