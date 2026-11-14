"""Read known client project directories, without importing conversations or secrets.

Metadata sources and compatibility limits are documented in docs/project-catalog.md.
These entries are candidates only; listing or selecting never admits a project.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone


MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_PROJECTS = 2000


class ProjectCatalog:
    def __init__(self, home=None):
        self.home = Path(home).expanduser() if home is not None else Path.home()
        # Tests pass a synthetic home and never inherit real client locations.
        self.codex = Path(os.environ.get("CODEX_HOME", self.home / ".codex")) if home is None else self.home / ".codex"
        self.zcode = Path(os.environ.get("ZCODE_DATA_BASE_DIR", self.home)) / ".zcode" if home is None else self.home / ".zcode"
        self.claude = Path(os.environ.get("CLAUDE_CONFIG_DIR", self.home / ".claude")) if home is None else self.home / ".claude"
        self.claude_settings = self.claude / ".claude.json" if home is None and os.environ.get("CLAUDE_CONFIG_DIR") else self.home / ".claude.json"

    @staticmethod
    def _json(path):
        if not path.is_file():
            return None
        with path.open("rb") as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError("project metadata too large")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None

    @staticmethod
    def _database(path):
        # mode=ro does not create or migrate a client database; WAL is read normally.
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return db

    @staticmethod
    def _columns(db, table):
        # Table names are constants from the readers below, never request input.
        return {row["name"] for row in db.execute("PRAGMA table_info(" + table + ")")}

    def _codex(self):
        databases = [p for p in self.codex.glob("state_*.sqlite") if re.fullmatch(r"state_\d+\.sqlite", p.name)]
        latest = max(databases, key=lambda p: int(p.stem.split("_")[1])) if databases else None
        if latest:
            try:
                db = self._database(latest)
                try:
                    if {"id", "name"} <= self._columns(db, "projects") and {"project_id", "path"} <= self._columns(db, "project_roots"):
                        rows = [(row["path"], row["name"]) for row in db.execute(
                            "SELECT p.name,r.path FROM projects p JOIN project_roots r ON r.project_id=p.id LIMIT ?", (MAX_PROJECTS,))]
                        if rows:
                            return rows
                finally:
                    db.close()
            except (OSError, sqlite3.Error):
                pass  # Desktop JSON is a compatible fallback during DB updates.
        data = self._json(self.codex / ".codex-global-state.json") or {}
        entries = []
        projects = data.get("local-projects", {})
        if isinstance(projects, dict):
            for project in list(projects.values())[:MAX_PROJECTS]:
                if not isinstance(project, dict):
                    continue
                roots = project.get("rootPaths", [])
                if isinstance(roots, list):
                    for path in roots[:100]:
                        entries.append((path, project.get("name")))
        for key in ("electron-saved-workspace-roots", "saved-workspace-roots"):
            roots = data.get(key, [])
            if isinstance(roots, list):
                entries.extend((path, None) for path in roots[:MAX_PROJECTS])
        if entries:
            return entries
        # CLI-only installations may have no desktop registry. Read cwd only.
        if latest is None:
            return entries
        db = self._database(latest)
        try:
            if "cwd" in self._columns(db, "threads"):
                entries.extend((row[0], None) for row in db.execute("SELECT DISTINCT cwd FROM threads WHERE cwd IS NOT NULL LIMIT ?", (MAX_PROJECTS,)))
        finally:
            db.close()
        return entries

    def _zcode(self):
        path = self.zcode / "v2" / "tasks-index.sqlite"
        if not path.is_file():
            return []
        db = self._database(path)
        try:
            projects = self._columns(db, "projects")
            roots = self._columns(db, "project_roots")
            hosts = self._columns(db, "hosts")
            if {"project_id", "root_path"} <= roots and {"project_id", "name", "host_id"} <= projects:
                where = "COALESCE(p.deleted,0)=0" if "deleted" in projects else "1=1"
                join = ""
                if {"host_id", "kind"} <= hosts:
                    join = " JOIN hosts h ON h.host_id=p.host_id"
                    where += " AND h.kind='local'"
                else:
                    # Legacy indexes use the fixed local host id; do not import remotes.
                    where += " AND p.host_id='local'"
                query = "SELECT p.name,r.root_path FROM projects p JOIN project_roots r ON r.project_id=p.project_id" + join + " WHERE " + where + " LIMIT ?"
                return [(row["root_path"], row["name"]) for row in db.execute(query, (MAX_PROJECTS,))]
            return []
        finally:
            db.close()

    def _claude(self):
        data = self._json(self.claude_settings) or {}
        projects = data.get("projects", {})
        if not isinstance(projects, dict):
            return []
        # Keys are directories. Values include unrelated settings and are ignored.
        return [(path, None) for path in list(projects)[:MAX_PROJECTS]]

    @staticmethod
    def _canonical(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            return None
        value = value.strip()
        # Do not probe network shares or remote URLs while building a local list.
        if value.startswith(("\\\\", "//")) or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            return None
        try:
            path = path.resolve(strict=True)
            return str(path) if path.is_dir() else None
        except (OSError, ValueError, RuntimeError):
            return None

    def list(self):
        combined = {}
        statuses = []
        for agent, reader in (("codex", self._codex), ("zcode", self._zcode), ("claude", self._claude)):
            count = 0
            try:
                entries = reader()
                for value, label in entries[:MAX_PROJECTS]:
                    path = self._canonical(value)
                    if path is None:
                        continue
                    key = os.path.normcase(path)
                    if key not in combined:
                        name = label.strip() if isinstance(label, str) and label.strip() else Path(path).name or path
                        name = " ".join(name.split())[:300]
                        combined[key] = {"id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:24], "path":path, "name":name, "agents":[]}
                    if agent not in combined[key]["agents"]:
                        combined[key]["agents"].append(agent)
                        count += 1
                statuses.append({"agent":agent, "count":count, "status":"ready" if count else "empty"})
            except (OSError, ValueError, sqlite3.Error, RuntimeError):
                # Do not return client file contents, SQL details or credential fields.
                statuses.append({"agent":agent, "count":0, "status":"unavailable"})
        recent = self._recent_activity()
        for key, project in combined.items():
            project.update(recent.get(key, {"last_active_at":None,"activity_source":None}))
        return {"projects":sorted(combined.values(), key=lambda p:(not bool(p['last_active_at']), -(p['last_active_at'] or 0), p["name"].casefold(), p["path"].casefold())), "sources":statuses}

    def _recent_activity(self):
        """Read directory/timestamp columns only; never task text, titles or messages."""
        result = {}
        def keep(value, timestamp, source):
            path = self._canonical(value)
            if path is None:
                return
            try:
                if isinstance(timestamp, (int,float)) or str(timestamp).replace('.','',1).isdigit():
                    seconds = float(timestamp)
                    if seconds > 100000000000:
                        seconds /= 1000
                else:
                    parsed = datetime.fromisoformat(str(timestamp).replace('Z','+00:00'))
                    seconds = parsed.replace(tzinfo=timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()
                if not 0 < seconds <= datetime.now(timezone.utc).timestamp()+86400:
                    return
            except (ValueError,TypeError,OverflowError):
                return
            key = os.path.normcase(path)
            if seconds > result.get(key,{}).get('last_active_at',0):
                result[key] = {'last_active_at':seconds,'activity_source':source}
        databases = [p for p in self.codex.glob('state_*.sqlite') if re.fullmatch(r'state_\d+\.sqlite',p.name)]
        if databases:
            db = None
            try:
                db = self._database(max(databases,key=lambda p:int(p.stem.split('_')[1])))
                columns = self._columns(db,'threads')
                field = 'updated_at_ms' if 'updated_at_ms' in columns else 'updated_at' if 'updated_at' in columns else None
                if field and 'cwd' in columns:
                    for row in db.execute('SELECT cwd,MAX('+field+') AS activity FROM threads WHERE cwd IS NOT NULL GROUP BY cwd ORDER BY activity DESC LIMIT ?', (MAX_PROJECTS,)):
                        keep(row['cwd'],row['activity'],'codex')
                if field and 'project_id' in columns and {'project_id','path'} <= self._columns(db,'project_roots'):
                    for row in db.execute('SELECT r.path,MAX(t.'+field+') AS activity FROM threads t JOIN project_roots r ON r.project_id=t.project_id GROUP BY r.path LIMIT ?', (MAX_PROJECTS,)):
                        keep(row['path'],row['activity'],'codex')
            except (sqlite3.Error,OSError):
                pass
            finally:
                if db: db.close()
        db = None
        try:
            path=self.zcode/'v2/tasks-index.sqlite'
            if path.is_file():
                db=self._database(path)
                if {'project_id','updated_at'} <= self._columns(db,'tasks') and {'project_id','root_path'} <= self._columns(db,'project_roots') and {'host_id','kind'} <= self._columns(db,'hosts'):
                    deleted=' AND COALESCE(t.deleted,0)=0' if 'deleted' in self._columns(db,'tasks') else ''
                    for row in db.execute("SELECT r.root_path,MAX(t.updated_at) AS activity FROM tasks t JOIN projects p ON p.project_id=t.project_id JOIN hosts h ON h.host_id=p.host_id JOIN project_roots r ON r.project_id=p.project_id WHERE h.kind='local'"+deleted+' GROUP BY r.root_path LIMIT ?', (MAX_PROJECTS,)):
                        keep(row['root_path'],row['activity'],'zcode')
        except (sqlite3.Error,OSError):
            pass
        finally:
            if db: db.close()
        return result
