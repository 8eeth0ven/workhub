"""Persistent archive behavior with temporary data and isolated local previews."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import quote, urlsplit

import archives
import workhub


@contextmanager
def hub(store):
    server = workhub.WorkhubServer(("127.0.0.1", 0), workhub.handler_for(store))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:{}/".format(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(url, method="GET", payload=None, headers=None):
    parsed = urlsplit(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    try:
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        connection.request(method, parsed.path + ("?" + parsed.query if parsed.query else ""), body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workhub-archives-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "example-project"
        self.project.mkdir()
        self.store = workhub.Store(self.root / "data")
        self.identifier = self.store.register(self.project)["id"]
        self.archives = archives.ArchiveStore(self.store)

    def prompt(self, **changes):
        values = {"project_id": self.identifier, "title": "Original request", "content": "  Exact user request.\n\n", "agent": "codex", "session_id": "example-session", "source": "unknown"}
        values.update(changes)
        return self.archives.add_prompt(values)

    def package(self, missing=False):
        directory = self.root / "shared-publications"
        directory.mkdir(exist_ok=True)
        (directory / "images").mkdir(exist_ok=True)
        (directory / "index.html").write_text('<!doctype html><html><head><link rel="stylesheet" href="theme.css"></head><body><img src="images/figure.svg"><script>fetch("/api/archives")</script></body></html>', encoding="utf-8")
        (directory / "theme.css").write_text("body{background:white}", encoding="utf-8")
        (directory / "editor.html").write_text("<html><body>Editable copy</body></html>", encoding="utf-8")
        (directory / "other-private-report.html").write_text("This sibling was never selected", encoding="utf-8")
        (directory / ".env").write_text("private-content", encoding="utf-8")
        (directory / "app.js").write_text("untrusted script", encoding="utf-8")
        if not missing:
            (directory / "images/figure.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Figure</text></svg>', encoding="utf-8")
        return directory

    def artifact(self, **changes):
        values = {"project_id": self.identifier, "title": "A publication", "directory": str(self.package()), "status": "draft"}
        values.update(changes)
        return self.archives.add_artifact(values)

    def test_unknown_session_source_and_worklog_agent_usage_do_not_invent_history(self):
        self.store.record(self.project, "zcode", "completed", "A real worklog", run_id="known-run")
        initial = self.archives.list(self.identifier)
        self.assertEqual(initial["sessions"], [])
        self.assertEqual(initial["agent_usage"][0]["source"], "worklog")
        self.assertIsNone(initial["agent_usage"][0]["session_id"])
        payload = {"project_id": self.identifier, "agent": "codex", "session_id": "known-session", "title": "Imported reference"}
        first = self.archives.add_session(payload)
        self.assertEqual(self.archives.add_session(payload)["id"], first["id"])
        self.assertIsNone(first["started_at"])
        self.assertEqual(first["source"], "unknown")
        self.assertEqual(self.archives.projects()["projects"][0]["session_count"], 1)

    def test_exact_prompt_history_and_hashes_survive_reopening(self):
        first = self.prompt(prompt_key="stable-task")
        exact = "  Exact user request.\n\n"
        self.assertEqual(first["content"], exact)
        self.assertEqual(first["original_hash"], hashlib.sha256(exact.encode()).hexdigest())
        second = self.prompt(prompt_key="stable-task", content="A reconstructed reusable instruction", derived_from=first["id"])
        self.assertEqual(second["record_type"], "derived")
        self.assertEqual(second["revision"], 2)
        reopened = archives.ArchiveStore(workhub.Store(self.store.directory))
        detail = reopened.prompt(first["id"])
        self.assertEqual(len(detail["history"]), 2)
        self.assertEqual(detail["prompt"]["content"], exact)
        self.assertEqual(reopened.list(self.identifier)["prompts"][0]["id"], second["id"])

    def test_sensitive_original_is_rejected_or_explicitly_saved_as_redacted_derivative(self):
        secret = "sensitive-" + "example-value"
        original = "Configuration " + json.dumps({"api_" + "key": secret})
        with self.assertRaises(archives.ReviewError) as caught:
            self.prompt(content=original)
        self.assertEqual(caught.exception.status, 422)
        self.assertNotIn(secret, str(caught.exception))
        self.assertEqual(self.archives.list()["counts"]["prompts"], 0)
        saved = self.prompt(content=original, redact_sensitive=True)
        self.assertTrue(saved["redacted"])
        self.assertEqual(saved["record_type"], "derived")
        self.assertNotIn(secret, saved["content"])
        self.assertEqual(saved["original_hash"], hashlib.sha256(original.encode()).hexdigest())
        self.assertNotEqual(saved["original_hash"], saved["content_hash"])
        with self.assertRaises(archives.ReviewError):
            self.archives.add_session({"project_id": self.identifier, "title": "x", "agent": "codex", "session_id": "x", "transcript": "must not be silently accepted"})

    def test_project_boundaries_and_concurrent_revisions(self):
        with self.assertRaises(archives.ReviewError):
            self.prompt(project_id="missing-project")
        first = self.prompt()
        other = self.root / "other-project"
        other.mkdir()
        second_id = self.store.register(other)["id"]
        with self.assertRaises(archives.ReviewError):
            self.prompt(project_id=second_id, derived_from=first["id"])
        with ThreadPoolExecutor(max_workers=5) as pool:
            versions = list(pool.map(lambda i: self.prompt(prompt_key="concurrent", content="Version {}".format(i)), range(10)))
        self.assertEqual({version["revision"] for version in versions}, set(range(1, 11)))

    def test_only_explicit_entry_dependencies_are_snapshotted_and_state_is_not_published(self):
        directory = self.package()
        artifact = self.archives.add_artifact({"project_id": self.identifier, "title": "Single file in a shared directory", "directory": str(directory)})
        self.assertEqual(artifact["status"], "unknown")
        self.assertIsNone(artifact["generated_at"])
        self.assertEqual(set(artifact["manifest"]), {"index.html", "theme.css", "images/figure.svg"})
        self.assertEqual(artifact["image_count"], 1)
        self.assertTrue(artifact["images_verified"])
        self.assertEqual(artifact["file_state"], "present")
        self.assertEqual(self.archives.add_artifact({"project_id": self.identifier, "title": "Single file in a shared directory", "directory": str(directory)})["id"], artifact["id"])
        (directory / "index.html").unlink()
        self.assertIn(b"doctype", self.archives.artifact_file(artifact["id"], "index.html")[0])
        with self.assertRaises(archives.ReviewError):
            self.archives.artifact_file(artifact["id"], "other-private-report.html")
        with self.assertRaises(archives.ReviewError):
            self.archives.artifact_file(artifact["id"], "../workhub.sqlite3")

    def test_editor_files_missing_images_and_publication_claims_are_explicit(self):
        directory = self.package(missing=True)
        artifact = self.archives.add_artifact({"project_id": self.identifier, "title": "Missing image", "directory": str(directory), "files": ["editor.html"], "status": "draft"})
        self.assertEqual(artifact["html_count"], 2)
        self.assertEqual(artifact["missing_image_count"], 1)
        self.assertEqual(artifact["file_state"], "missing")
        self.assertFalse(artifact["images_verified"])
        with self.assertRaises(archives.ReviewError):
            self.archives.add_artifact({"project_id": self.identifier, "title": "Not proof of publication", "directory": str(directory), "status": "published"})

    def test_embedded_primary_images_are_signature_checked_without_double_counting_editor(self):
        directory = self.package()
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
        svg = "data:image/svg+xml," + quote('<svg xmlns="http://www.w3.org/2000/svg"><text>Embedded</text></svg>')
        invalid = "data:image/png;base64,YWJj"
        content = '<html><body>' + ''.join('<img src="{}">'.format(image) for image in (png, svg, invalid)) + '</body></html>'
        (directory / "index.html").write_text(content, encoding="utf-8")
        (directory / "editor.html").write_text(content, encoding="utf-8")
        artifact = self.archives.add_artifact({"project_id": self.identifier, "title": "Embedded only", "directory": str(directory), "files": ["editor.html"]})
        self.assertEqual(artifact["image_count"], 3)
        self.assertEqual(artifact["embedded_image_count"], 3)
        self.assertEqual(artifact["attachment_image_count"], 3)
        self.assertEqual(artifact["image_file_count"], 0)
        self.assertEqual(artifact["verified_image_count"], 2)
        self.assertEqual(artifact["missing_image_count"], 1)
        self.assertFalse(artifact["images_verified"])
        self.assertNotIn("base64,", json.dumps(artifact["images"]))
        (directory / "index.html").write_text(content.replace('<img src="{}">'.format(invalid), ''), encoding="utf-8")
        valid = self.archives.add_artifact({"project_id": self.identifier, "title": "Embedded only", "directory": str(directory)})
        self.assertEqual(valid["image_count"], 2)
        self.assertEqual(valid["verified_image_count"], 2)
        self.assertTrue(valid["images_verified"])
        history = self.archives.artifact(artifact["id"])
        self.assertEqual(len(history["history"]), 2)
        self.assertEqual(history["artifact"]["id"], artifact["id"])

    def test_source_and_snapshot_symlinks_and_tampering_are_rejected(self):
        directory = self.package()
        private = self.root / "private.svg"
        private.write_text("<svg>private</svg>", encoding="utf-8")
        image = directory / "images/figure.svg"
        image.unlink()
        image.symlink_to(private)
        with self.assertRaises(archives.ReviewError):
            self.archives.add_artifact({"project_id": self.identifier, "title": "No symlink imports", "directory": str(directory)})
        image.unlink()
        image.write_text("<svg>public</svg>", encoding="utf-8")
        artifact = self.archives.add_artifact({"project_id": self.identifier, "title": "Good snapshot", "directory": str(directory)})
        snapshot = self.store.directory / "archive_files" / artifact["id"] / "images/figure.svg"
        snapshot.write_text("<svg>tamper</svg>", encoding="utf-8")
        with self.assertRaises(archives.ReviewError):
            self.archives.artifact_file(artifact["id"], "images/figure.svg")
        snapshot.unlink()
        snapshot.symlink_to(private)
        with self.assertRaises(archives.ReviewError):
            self.archives.artifact_file(artifact["id"], "images/figure.svg")

    def test_http_write_guards_search_history_and_isolated_scriptless_reader(self):
        first = self.prompt(prompt_key="api-history")
        self.prompt(prompt_key="api-history", content="Follow-up version")
        artifact = self.artifact()
        headers = {"Content-Type": "application/json", "X-Workhub-Request": "1"}
        with hub(self.store) as url:
            payload = {"project_id": self.identifier, "agent": "codex", "session_id": "API session", "title": "API imported"}
            self.assertEqual(request(url + "api/archives/session", "POST", payload)[0], 403)
            self.assertEqual(request(url + "api/archives/session", "POST", payload, dict(headers, Origin="https://foreign.example"))[0], 403)
            self.assertEqual(request(url + "api/archives/session", "POST", payload, headers)[0], 201)
            status, body, _ = request(url + "api/archives?project_id=" + self.identifier + "&q=" + quote("Follow-up"))
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["counts"]["prompts"], 1)
            history = json.loads(request(url + "api/archives/prompt?id=" + first["id"])[1])
            self.assertEqual(len(history["history"]), 2)
            items = json.loads(request(url + "api/archives?project_id=" + self.identifier)[1])
            preview = items["artifacts"][0]["preview_url"]
            self.assertNotEqual(urlsplit(url).port, urlsplit(preview).port)
            status, _, response_headers = request(preview)
            self.assertEqual(status, 200)
            self.assertIn("sandbox", response_headers["Content-Security-Policy"])
            self.assertNotIn("allow-scripts", response_headers["Content-Security-Policy"])
            self.assertEqual(request(preview.replace("index.html", "images/figure.svg"))[0], 200)
            self.assertEqual(request(preview.replace("index.html", "other-private-report.html"))[0], 404)
            self.assertEqual(request(preview.replace("index.html", "api/archives"))[0], 404)
            self.assertEqual(request(preview, "POST", payload, headers)[0], 405)
        with self.assertRaises(OSError):
            request(preview)

    def test_cli_content_file_preserves_utf8_and_runtime_contains_archive_module(self):
        content = "  真实提示词原文，不作改写。\n\n"
        file = self.root / "selected-prompt.txt"
        file.write_text(content, encoding="utf-8")
        result = subprocess.run([sys.executable, str(workhub.ROOT / "workhub.py"), "--data-dir", str(self.store.directory), "archive-prompt", "--project", str(self.project), "--title", "CLI original", "--content-file", str(file)], capture_output=True, text=True, check=True)
        saved = json.loads(result.stdout)
        self.assertEqual(saved["content"], content)
        self.assertEqual(self.archives.get(saved["id"], "prompt")["content"], content)
        from scripts.service import runtime_payload
        self.assertEqual(runtime_payload()["archives.py"], (workhub.ROOT / "archives.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
