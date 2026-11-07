"""Behavioral regressions for local records and isolated website previews.

Run with: python3 -m unittest discover -s tests -v
All records, project files, and HTTP listeners belong to temporary fixtures.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlsplit


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
import workhub


@contextmanager
def running_hub(store):
    server = workhub.WorkhubServer(("127.0.0.1", 0), workhub.handler_for(store))
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield "http://127.0.0.1:{}/".format(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def get(url, headers=None):
    parsed = urlsplit(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


class WorkhubTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workhub-regression-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "中文项目"
        self.project.mkdir()
        self.data = self.root / "data"
        self.store = workhub.Store(self.data)

    def cli(self, *arguments):
        completed = subprocess.run(
            [sys.executable, str(REPOSITORY / "workhub.py"), "--data-dir", str(self.data), *arguments],
            capture_output=True, text=True, check=True,
        )
        return json.loads(completed.stdout)

    def website(self, name="site"):
        directory = self.project / name
        directory.mkdir()
        (directory / "index.html").write_text(
            '<!doctype html><html><link rel="stylesheet" href="/assets/style.css"><p>项目网站</p></html>',
            encoding="utf-8",
        )
        (directory / "assets").mkdir()
        (directory / "assets" / "style.css").write_text("body { color: green; }", encoding="utf-8")
        return directory

    def test_parallel_runs_finish_independently(self):
        for agent, run_id in (("codex", "one"), ("claude", "two")):
            self.store.record(self.project, agent, "running", "开始", run_id=run_id)
        self.store.record(self.project, "codex", "completed", "完成第一个任务", run_id="one")
        project = self.store.projects()[0]
        self.assertEqual(project["status"], "running")
        self.assertEqual(project["active_runs"], 1)
        self.store.record(self.project, "claude", "blocked", "另一个任务受阻", run_id="two")
        self.assertEqual(self.store.projects()[0]["status"], "blocked")
        self.store.record(self.project, "claude", "completed", "已解决并完成", run_id="two")
        self.assertEqual(self.store.projects()[0]["status"], "completed")
        self.assertEqual(len(self.store.events()), 5)

    def test_persisted_state_and_full_cli_export(self):
        self.store.register(self.project, name="真实中文项目")
        for index in range(6):
            self.store.record(
                self.project, "zcode", "completed", "实际记录 {}".format(index),
                run_id="run-{}".format(index),
            )
        reopened = workhub.Store(self.data)
        state = reopened.state(event_limit=2)
        self.assertEqual(state["stats"]["event_count"], 6)
        self.assertEqual(len(state["events"]), 2)
        self.assertTrue(state["has_more"])
        self.assertEqual(state["projects"][0]["name"], "真实中文项目")
        exported = self.cli("export")
        self.assertEqual(len(exported["events"]), 6)
        self.assertEqual(exported["projects"][0]["last_summary"], "实际记录 5")
        self.assertFalse(exported["has_more"])
        with running_hub(reopened) as hub:
            status, raw = get(hub + "api/state")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["stats"]["event_count"], 6)

    def test_thirty_two_concurrent_records_are_not_lost(self):
        def record(index):
            return self.store.record(
                self.project, "codex", "completed", "并发结果 {}".format(index),
                run_id="parallel-{}".format(index),
            )
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(record, range(32)))
        self.assertEqual(len({event["id"] for event in results}), 32)
        events = workhub.Store(self.data).events(limit=100)
        self.assertEqual(len(events), 32)
        self.assertEqual({event["summary"] for event in events}, {"并发结果 {}".format(i) for i in range(32)})
        self.assertEqual(self.store.projects()[0]["active_runs"], 0)

    def test_url_sites_reject_public_hosts_and_credentials(self):
        invalid = (
            "https://example.com/app", "http://192.168.1.2:8000/",
            "http://user:password@localhost:8000/", "http://localhost.evil:8000/",
            "file:///tmp/index.html", "http://127.0.0.1:0/",
        )
        for url in invalid:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    self.store.site_add(self.project, "不应登记", url=url)
        self.assertEqual(self.store.sites(), [])
        accepted = "http://localhost:8181/app#view"
        self.store.site_add(self.project, "本机应用", url=accepted)
        with running_hub(self.store) as hub:
            status, raw = get(hub + "api/sites")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["sites"][0]["preview_url"], accepted)

    def test_running_hub_discovers_new_directory_and_root_resources(self):
        directory = self.website()
        with running_hub(self.store) as hub:
            self.assertEqual(json.loads(get(hub + "api/sites")[1])["sites"], [])
            # A real CLI process writes while the already-running hub serves.
            registered = self.cli(
                "site-add", "--project", str(self.project), "--name", "目录站点",
                "--directory", str(directory), "--template", "radar",
            )
            status, raw = get(hub + "api/sites")
            self.assertEqual(status, 200)
            site = json.loads(raw)["sites"][0]
            self.assertEqual(site["id"], registered["id"])
            preview = site["preview_url"]
            self.assertNotEqual(urlsplit(preview).port, urlsplit(hub).port)
            self.assertIn("项目网站", get(preview)[1].decode("utf-8"))
            self.assertEqual(get(preview + "assets/style.css"), (200, b"body { color: green; }"))
            self.assertEqual(get(preview + "api/state")[0], 404)

    def test_directory_preview_rejects_hidden_and_escaping_paths(self):
        directory = self.website()
        (directory / ".env").write_text("PRIVATE", encoding="utf-8")
        outside = self.root / "outside.txt"
        outside.write_text("OUTSIDE", encoding="utf-8")
        (directory / "escape.txt").symlink_to(outside)
        self.store.site_add(self.project, "隔离站点", directory=directory)
        with running_hub(self.store) as hub:
            preview = json.loads(get(hub + "api/sites")[1])["sites"][0]["preview_url"]
            for route in (".env", "../outside.txt", "%2e%2e/outside.txt", "escape.txt"):
                with self.subTest(route=route):
                    status, body = get(preview + route)
                    self.assertEqual(status, 403)
                    self.assertNotIn(b"PRIVATE", body)
                    self.assertNotIn(b"OUTSIDE", body)
            self.assertEqual(get(preview, {"Host": "foreign.example"})[0], 403)

    def test_hub_shutdown_closes_all_directory_preview_ports(self):
        for name in ("first", "second"):
            self.store.site_add(self.project, name, directory=self.website(name))
        with running_hub(self.store) as hub:
            sites = json.loads(get(hub + "api/sites")[1])["sites"]
            previews = [site["preview_url"] for site in sites]
            self.assertEqual(len({urlsplit(url).port for url in previews}), 2)
            for url in previews:
                self.assertEqual(get(url)[0], 200)
        for url in previews:
            with self.subTest(url=url):
                with self.assertRaises(OSError):
                    get(url)


if __name__ == "__main__":
    unittest.main()
