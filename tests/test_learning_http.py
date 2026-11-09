import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection

from learning import LearningStore
from workhub import Store, WorkhubServer, handler_for


class LearningHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "state")
        self.project_id = self.store.register(self.project)["id"]
        self.learning = LearningStore(self.store)
        self.payload = dict(project_id=self.project_id, card_key="cache", title="Cache", concept="Reuse known work", explanation="A cache reuses a result.", implementation="The project checks a key first.", self_check="When must the cache expire?", sources=[{"path": "app.py", "line": 1}])
        self.card = self.learning.add_card(self.payload)
        self.server = WorkhubServer(("127.0.0.1", 0), handler_for(self.store, learning=self.learning))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, payload=None, origin=None, marker=True):
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if marker:
            headers["X-Workhub-Request"] = "1"
        if origin is not None:
            headers["Origin"] = origin
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request(method, path, json.dumps(payload) if payload is not None else None, headers)
        response = conn.getresponse()
        data = json.loads(response.read())
        status = response.status
        conn.close()
        return status, data

    def ack(self, value=True, revision=1):
        return {"card_id": self.card["id"], "revision": revision, "understood": value}

    def test_reads_do_not_acknowledge_and_user_can_toggle(self):
        status, listing = self.request("GET", "/api/learning")
        self.assertEqual(status, 200)
        self.assertEqual(listing["stats"]["pending"], 1)
        self.assertEqual(listing["global_stats"]["understood"], 0)
        self.assertEqual(listing["projects"][0]["id"], self.project_id)
        status, result = self.request("POST", "/api/learning/ack", self.ack(), f"http://127.0.0.1:{self.port}")
        self.assertEqual(status, 200)
        self.assertTrue(result["card"]["understood"])
        self.assertTrue(LearningStore(Store(self.root / "state")).get(self.card["id"])["card"]["understood"])
        status, result = self.request("POST", "/api/learning/ack", self.ack(False))
        self.assertEqual(status, 200)
        self.assertEqual(result["card"]["status"], "pending")

    def test_foreign_origin_missing_marker_and_bad_payload_cannot_mark(self):
        self.assertEqual(self.request("POST", "/api/learning/ack", self.ack(), "https://foreign.example")[0], 403)
        self.assertEqual(self.request("POST", "/api/learning/ack", self.ack(), marker=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/learning/ack", self.ack("true"))[0], 400)
        self.assertEqual(self.request("POST", "/api/learning/ack", dict(self.ack(), force=True))[0], 400)
        self.assertFalse(self.learning.get(self.card["id"])["card"]["understood"])

    def test_stale_card_returns_conflict_and_requires_fresh_confirmation(self):
        self.learning.acknowledge(self.card["id"], 1, True)
        updated = self.learning.add_card(dict(self.payload, implementation="Now the key includes a version."))
        self.assertEqual(updated["status"], "needs_review")
        self.assertEqual(self.request("POST", "/api/learning/ack", self.ack())[0], 409)
        status, detail = self.request("GET", "/api/learning/card?id=" + self.card["id"])
        self.assertEqual(status, 200)
        self.assertEqual(detail["card"]["revision"], 2)
        self.assertFalse(detail["card"]["understood"])

    def test_cli_add_lists_without_acknowledging(self):
        file = self.root / "card.json"
        file.write_text(json.dumps(dict(self.payload, card_key="cli-card")), encoding="utf-8")
        script = Path(__file__).resolve().parents[1] / "workhub.py"
        args = [sys.executable, str(script), "--data-dir", str(self.root / "state")]
        result = subprocess.run(args + ["learn-add", "--project", str(self.project), "--file", str(file)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["understood"])
        file.write_text(json.dumps(dict(self.payload, understood=True)), encoding="utf-8")
        result = subprocess.run(args + ["learn-add", "--project", str(self.project), "--file", str(file)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
