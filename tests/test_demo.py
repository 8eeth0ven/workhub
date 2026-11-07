"""Read-only demo isolation. All listeners/databases are temporary fixtures."""
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from examples import demo
import workhub


@contextmanager
def running_demo():
    with demo.demo_server(0) as server:
        directory = server.RequestHandlerClass.site_manager.store.directory.parent
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            yield server.server_port, directory
        finally:
            server.shutdown()
            thread.join(timeout=3)


def request(port, path, method="GET", body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/json", "X-Workhub-Request": "1"} if body else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, response.read()
    connection.close()
    return result


class DemoIsolationTests(unittest.TestCase):
    def test_demo_never_constructs_real_provider_or_reads_global_integrations(self):
        with patch.object(workhub, "AssessmentManager", side_effect=AssertionError("real manager must not be used")), patch.object(workhub, "integrations", side_effect=AssertionError("global integration must not be read")), patch.dict(os.environ, {"AGENT_WORKHUB_HOME": "/unused-private-global-database", "GLM_API_KEY": "demo-must-not-read-this-key"}):
            with running_demo() as (port, temporary):
                endpoints = ["/api/health", "/api/state", "/api/sites", "/api/integrations", "/api/reviews"]
                state = json.loads(request(port, "/api/state")[1])
                for project in state["projects"]:
                    endpoints.extend(["/api/project?id=" + project["id"], "/api/reviews/project?id=" + project["id"]])
                for endpoint in endpoints:
                    status, body = request(port, endpoint)
                    self.assertEqual(status, 200, endpoint)
                    self.assertNotIn(str(Path.home()).encode(), body)
                    self.assertNotIn(str(temporary).encode(), body)
                    self.assertNotIn(b"/Users/", body)
                    self.assertNotIn(b"demo-must-not-read-this-key", body)
                    self.assertTrue(json.loads(body)["is_demo"])
                self.assertEqual(len(state["projects"]), 4)
                self.assertTrue(all(project["path"].startswith("examples/") for project in state["projects"]))
                sites = json.loads(request(port, "/api/sites")[1])["sites"]
                self.assertEqual(len(sites), 3)
                for site in sites:
                    self.assertTrue(site["directory"].startswith("examples/"))
                    url = urlsplit(site["preview_url"])
                    status, page = request(url.port, "/")
                    self.assertEqual(status, 200)
                    self.assertNotIn(str(Path.home()).encode(), page)
                    self.assertIn(b'href="template-shell.css"', page)
                    self.assertNotIn(b'/templates/template-shell.css', page)
                    for asset in ("design-system.css", "runtime.js", "template-shell.css"):
                        status, body = request(url.port, "/" + asset)
                        self.assertEqual(status, 200, asset)
                        self.assertGreater(len(body), 0)
                    status, body = request(url.port, "/data.json")
                    self.assertEqual(status, 200)
                    self.assertTrue(json.loads(body)["is_demo"])
                reviews = json.loads(request(port, "/api/reviews")[1])
                self.assertFalse(reviews["provider"]["configured"])
                self.assertEqual(reviews["provider"]["key_count"], 0)
                self.assertTrue(all(review["is_demo"] for review in reviews["reviews"]))
                self.assertTrue(all("未调用模型" in review["summary"] for review in reviews["reviews"]))
            self.assertFalse(temporary.exists(), "temporary database and websites must be removed")

    def test_post_is_read_only_and_first_paint_marks_demo(self):
        with running_demo() as (port, temporary):
            status, body = request(port, "/api/reviews", "POST", '{"all":true}')
            self.assertEqual(status, 405)
            self.assertIn("演示模式".encode(), body)
            status, page = request(port, "/")
            self.assertEqual(status, 200)
            self.assertIn(b'id="demo-banner" class="demo-banner" role="note">', page)
            self.assertNotIn(str(Path.home()).encode(), page)
            self.assertIn(b'>W</span>', page)


if __name__ == "__main__":
    unittest.main()
