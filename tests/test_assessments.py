"""Project review behavior with fake providers; never calls a real GLM API."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
from io import BytesIO
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import assessments
import workhub


SECRET = "private-test-key-do-not-publish-12345"


def output(evidence):
    reference = evidence["evidence"][0]["id"]
    return {
        "verdict": "ready", "headline": "记录需要核查", "summary": "根据登记资料提出评议，尚未独立验证原始事实。",
        "strengths": ["已有登记记录"], "assumptions": ["记录可能仍需原始证据核验"],
        "questions": [{"id": "arbitrary", "kind": "evidence", "question": "怎样复核目标对应的结果？", "why": "登记陈述尚不等于独立验证", "suggested_check": "补充可复现步骤和结果文件", "evidence_ids": [reference, "not-a-real-id"]}],
        "blind_spots": ["复核范围可能尚未明确"], "next_actions": [{"priority": "high", "action": "补充验证步骤", "reason": "提升可核查性"}],
        "dimensions": [{"key": item["key"], "score": 3, "reason": "根据现有登记信息评估其记录完整程度", "evidence_ids": [reference, "not-a-real-id"]} for item in assessments.RUBRIC],
        "confidence": "medium",
    }


class FakeProvider:
    def __init__(self, fail=None, block=None, malformed=False):
        self.config = SimpleNamespace(keys=[SECRET])
        self.fail = fail
        self.block = block
        self.malformed = malformed
        self.calls = []
        self.started = threading.Event()
        self.lock = threading.Lock()

    def public(self):
        return {"configured": True, "model": "fake-glm", "provider": "GLM", "key_count": 1, "endpoint_host": "open.bigmodel.cn"}

    def complete(self, evidence):
        with self.lock:
            self.calls.append(copy.deepcopy(evidence))
        self.started.set()
        if self.block:
            if not self.block.wait(timeout=5):
                raise RuntimeError("fake provider timeout")
        if self.fail:
            raise self.fail
        if self.malformed:
            return {"headline": "incomplete result"}
        result = output(evidence)
        result["summary"] += " " + SECRET
        return result


@contextmanager
def server_for(store, manager):
    server = workhub.WorkhubServer(("127.0.0.1", 0), workhub.handler_for(store, reviews=manager))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw)
    finally:
        connection.close()


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workhub-assessments-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.project_path = self.directory / "项目"
        self.project_path.mkdir()
        self.store = workhub.Store(self.directory / "data")
        self.identifier = self.store.register(self.project_path, name="测试项目")["id"]

    def manager(self, provider=None):
        provider = provider or FakeProvider()
        manager = assessments.AssessmentManager(self.store, provider_factory=lambda: provider)
        self.addCleanup(manager.close)
        return manager, provider

    def substantive_records(self):
        for index in range(2):
            self.store.record(self.project_path, "codex", "completed", "实际结果 {}".format(index), details="目标：检验数据一致性；证据：可复现的输出与输入；验证：在临时目录对并发结果、失败路径、数据导出和重新启动进行了检查。" * 4, run_id="evidence-{}".format(index))

    def test_sparse_evidence_is_never_scored(self):
        manager, provider = self.manager()
        job = manager.submit([self.identifier])
        self.assertEqual(manager.wait(job["job_id"], timeout=5)["status"], "completed")
        review = manager.project(self.identifier)["review"]
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(review["verdict"], "insufficient_evidence")
        self.assertEqual(review["confidence"], "low")
        self.assertTrue(all(dimension["score"] is None for dimension in review["dimensions"]))
        self.assertEqual(review["strengths"], [])

    def test_only_existing_evidence_is_cited_and_secrets_are_redacted(self):
        self.substantive_records()
        (self.project_path / ".env").write_text("UNRELATED_PRIVATE_FILE_SHOULD_NEVER_BE_READ", encoding="utf-8")
        self.store.record(self.project_path, "codex", "completed", "不应发送凭据", details=SECRET, run_id="secret")
        manager, provider = self.manager()
        job = manager.submit([self.identifier])
        manager.wait(job["job_id"], timeout=5)
        detail = manager.project(self.identifier)
        allowed = {item["id"] for item in detail["evidence"]}
        for item in detail["review"]["dimensions"] + detail["review"]["questions"]:
            self.assertTrue(set(item["evidence_ids"]).issubset(allowed))
            self.assertNotIn("not-a-real-id", item["evidence_ids"])
        self.assertNotIn(SECRET, json.dumps(provider.calls))
        self.assertNotIn("UNRELATED_PRIVATE_FILE_SHOULD_NEVER_BE_READ", json.dumps(provider.calls))
        self.assertNotIn(SECRET, json.dumps(manager.public_state()))
        self.assertNotIn(SECRET, json.dumps(detail))

    def test_inflight_requests_deduplicate_and_unchanged_results_are_reused(self):
        release = threading.Event()
        self.addCleanup(release.set)
        manager, provider = self.manager(FakeProvider(block=release))
        first = manager.submit([self.identifier])
        self.assertTrue(provider.started.wait(timeout=2))
        with ThreadPoolExecutor(max_workers=6) as pool:
            duplicates = list(pool.map(lambda _: manager.submit([self.identifier]), range(6)))
        self.assertEqual({item["job_id"] for item in duplicates}, {first["job_id"]})
        release.set()
        self.assertEqual(manager.wait(first["job_id"], timeout=5)["status"], "completed")
        cached = manager.submit([self.identifier])
        self.assertEqual(manager.wait(cached["job_id"], timeout=5)["status"], "completed")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(cached["cached"], 1)

    def test_versions_persist_and_new_sources_mark_old_review_stale(self):
        manager, provider = self.manager()
        first_job = manager.submit([self.identifier])
        manager.wait(first_job["job_id"], timeout=5)
        first = manager.project(self.identifier)["review"]
        self.assertFalse(first["is_stale"])
        self.store.record(self.project_path, "zcode", "completed", "新增了真实核查记录", run_id="new-data")
        self.assertTrue(manager.project(self.identifier)["review"]["is_stale"])
        second_job = manager.submit([self.identifier], answer="用户补充：目标是复核导出一致性，验证步骤与输出文件仍需补充。")
        manager.wait(second_job["job_id"], timeout=5)
        reopened = assessments.AssessmentManager(workhub.Store(self.store.directory), provider_factory=lambda: provider)
        self.addCleanup(reopened.close)
        detail = reopened.project(self.identifier)
        self.assertEqual(len(detail["history"]), 2)
        self.assertNotEqual(detail["review"]["id"], first["id"])
        self.assertFalse(detail["review"]["is_stale"])
        self.assertTrue(detail["history"][1]["is_stale"])
        self.assertEqual(len(detail["answers"]), 1)
        self.assertEqual(len(self.store.events()), 1, "用户补充不能冒充 Agent 工作事件")

    def test_failure_or_malformed_output_never_creates_a_review(self):
        for provider in (FakeProvider(fail=RuntimeError(SECRET)), FakeProvider(malformed=True)):
            manager, _ = self.manager(provider)
            submitted = manager.submit([self.identifier], force=True)
            job = manager.wait(submitted["job_id"], timeout=5)
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["failed"], 1)
            self.assertIsNone(manager.project(self.identifier)["review"])
            self.assertNotIn(SECRET, json.dumps(job))

    def test_post_requires_json_marker_host_and_small_body(self):
        manager, _ = self.manager()
        body = json.dumps({"project_id": self.identifier})
        good = {"Content-Type": "application/json", "X-Workhub-Request": "1"}
        with server_for(self.store, manager) as port:
            self.assertEqual(request(port, "POST", "/api/reviews", body, {"Content-Type": "application/json"})[0], 403)
            self.assertEqual(request(port, "POST", "/api/reviews", body, {"X-Workhub-Request": "1", "Content-Type": "text/plain"})[0], 415)
            self.assertEqual(request(port, "POST", "/api/reviews", body, dict(good, Origin="https://elsewhere.example"))[0], 403)
            self.assertEqual(request(port, "POST", "/api/reviews", body, dict(good, Host="elsewhere.example"))[0], 403)
            self.assertEqual(request(port, "POST", "/api/reviews", "x" * 16385, good)[0], 413)
            self.assertEqual(request(port, "POST", "/api/reviews", "not json", good)[0], 400)
            self.assertEqual(request(port, "POST", "/api/reviews", json.dumps({"project_id": self.identifier, "command": ["untrusted-command"]}), good)[0], 400)
            status, accepted = request(port, "POST", "/api/reviews", body, good)
            self.assertEqual(status, 202)
            manager.wait(accepted["job_id"], timeout=5)
            status, job = request(port, "GET", "/api/reviews/job?id=" + accepted["job_id"])
            self.assertEqual(status, 200)
            self.assertEqual(job["status"], "completed")

    def test_unconfigured_provider_returns_an_error_without_a_fake_review(self):
        provider = FakeProvider()
        provider.public = lambda: {"configured": False, "model": "fake-glm", "provider": "GLM", "key_count": 0, "endpoint_host": "open.bigmodel.cn"}
        manager, _ = self.manager(provider)
        with server_for(self.store, manager) as port:
            status, payload = request(port, "POST", "/api/reviews", json.dumps({"project_id": self.identifier}), {"Content-Type": "application/json", "X-Workhub-Request": "1"})
            self.assertEqual(status, 503)
            self.assertIsInstance(payload["error"], str)
            self.assertIsNone(manager.project(self.identifier)["review"])
            self.assertEqual(provider.calls, [])


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workhub-provider-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def configuration(self, **changes):
        content = {"api_keys": [SECRET], "model": "glm-5.3-flash", "base_url": "https://open.bigmodel.cn/api/coding/paas/v4"}
        content.update(changes)
        path = self.directory / "glm.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        path.chmod(0o600)
        return assessments.ProviderConfig(self.directory, environ={})

    def test_configuration_is_private_and_environment_overrides_without_leaking_keys(self):
        self.configuration()
        config = assessments.ProviderConfig(self.directory, environ={"GLM_API_KEYS": '["override-one", "override-two"]', "GLM_MODEL": "glm-test", "GLM_BASE_URL": "https://api.z.ai/api/paas/v4"})
        self.assertTrue(config.public()["configured"])
        self.assertEqual(config.public()["key_count"], 2)
        self.assertEqual(config.public()["model"], "glm-test")
        self.assertNotIn("override-one", json.dumps(config.public()))
        self.assertNotIn(SECRET, json.dumps(config.public()))
        (self.directory / "glm.json").chmod(0o644)
        self.assertFalse(assessments.ProviderConfig(self.directory, environ={}).public()["configured"])

    def test_resource_error_and_authentication_error_are_not_retried_or_leaked(self):
        for status, code in ((429, "1113"), (429, "1310"), (401, "auth-error")):
            provider = assessments.GLMProvider(self.configuration(api_keys=[SECRET + code]))
            opener = SimpleNamespace(open=lambda *args, **kwargs: None)
            remote = json.dumps({"error": {"code": code, "message": SECRET}}).encode()
            with patch("assessments.build_opener", return_value=opener), patch.object(opener, "open", side_effect=HTTPError("https://open.bigmodel.cn", status, "secret " + SECRET, {}, BytesIO(remote))) as opened:
                with self.assertRaises(assessments.ReviewError) as caught:
                    provider.complete({"evidence": []})
                self.assertEqual(opened.call_count, 1)
                self.assertNotIn(SECRET, str(caught.exception))
                if code in ("1113", "1310"):
                    self.assertIn(code, str(caught.exception))

    def test_exhausted_key_does_not_starve_an_available_key(self):
        provider = assessments.GLMProvider(self.configuration(api_keys=["test-quota-exhausted", "test-healthy-key"]))
        calls = []
        def fake_network(key, evidence):
            calls.append(key)
            if key == "test-quota-exhausted":
                raise assessments.ReviewError("GLM 套餐额度已用尽（1310）", 502, "1310")
            return {"usable": True}
        with patch.object(provider, "_request", side_effect=fake_network):
            self.assertEqual(provider.complete({}), {"usable": True})
            self.assertEqual(provider.complete({}), {"usable": True})
        self.assertEqual(calls.count("test-quota-exhausted"), 1)
        self.assertEqual(calls.count("test-healthy-key"), 2)

    def test_redirects_are_refused_and_same_key_has_one_inflight_request(self):
        redirect = assessments.NoRedirects()
        self.assertIsNone(redirect.redirect_request(None, None, 302, "redirect", {}, "https://foreign.example"))
        config = self.configuration(api_keys=["test-one", "test-two", "test-three"])
        provider = assessments.GLMProvider(config)
        active = set()
        observed = []
        lock = threading.Lock()
        def fake_network(key, evidence):
            with lock:
                self.assertNotIn(key, active)
                active.add(key)
                observed.append(len(active))
            time.sleep(0.03)
            with lock:
                active.remove(key)
            return {"ok": True}
        with patch.object(provider, "_request", side_effect=fake_network):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(provider.complete, [{} for _ in range(12)]))
        self.assertEqual(len(results), 12)
        self.assertGreater(max(observed), 1)
        self.assertLessEqual(max(observed), 3)


class CleanTextTests(unittest.TestCase):
    def test_quoted_json_credentials_are_hidden_without_changing_evidence(self):
        original = {
            "api_key": "json-credential-value", "password": 'escaped-quote-"-value',
            "access_token": "json-access-token", "evidence_ids": ["event:42", "answer:7"],
            "sha256": "bfc56e4924bf455d8824057491c30df53741b38355df4bd535fe632826bf5736b",
            "text": "保留普通目标说明、证据和验证结果",
        }
        cleaned = assessments.clean_text(json.dumps(original, ensure_ascii=False))
        parsed = json.loads(cleaned)
        for key in ("api_key", "password", "access_token"):
            self.assertNotIn(original[key], cleaned)
            self.assertEqual(parsed[key], "[凭据已隐藏]")
        for key in ("evidence_ids", "sha256", "text"):
            self.assertEqual(parsed[key], original[key])
        self.assertNotIn("single-quoted-secret", assessments.clean_text("{'api_key': 'single-quoted-secret'}"))

    def test_url_query_credentials_are_hidden_but_other_parameters_remain(self):
        original = "来源 https://example.test/view?id=42&token=url-private-value&filter=active#section；核查 event:42"
        cleaned = assessments.clean_text(original)
        self.assertNotIn("url-private-value", cleaned)
        self.assertIn("?id=42&token=[凭据已隐藏]&filter=active#section", cleaned)
        self.assertIn("核查 event:42", cleaned)
        self.assertNotIn("first-token", assessments.clean_text("https://example.test/?token=first-token&item=9"))
        access_url = assessments.clean_text("https://example.test/?access_token=private-access&item=9#note")
        self.assertNotIn("private-access", access_url)
        self.assertIn("&item=9#note", access_url)

    def test_pem_private_keys_are_hidden_while_public_data_is_preserved(self):
        private = "-----BEGIN RSA PRIVATE KEY-----\nPRIVATE-TEST-BODY\n-----END RSA PRIVATE KEY-----"
        public = "-----BEGIN PUBLIC KEY-----\nPUBLIC-TEST-BODY\n-----END PUBLIC KEY-----"
        cleaned = assessments.clean_text("说明\n" + private + "\n" + public + "\nevent:42")
        self.assertNotIn("PRIVATE-TEST-BODY", cleaned)
        self.assertIn("[私钥已隐藏]", cleaned)
        self.assertIn(public, cleaned)
        self.assertIn("event:42", cleaned)


class EmbeddedThemeTests(unittest.TestCase):
    def test_only_html_is_themed_without_modifying_original_files(self):
        with tempfile.TemporaryDirectory(prefix="workhub-theme-") as temp:
            root = Path(temp)
            html = b'<!doctype html><html><HEAD><title>Example</title></HEAD><body>content</body></html>'
            (root / "index.html").write_bytes(html)
            (root / "app.js").write_bytes(b'const original = "unchanged";')
            server = workhub.WorkhubServer(("127.0.0.1", 0), workhub.directory_handler_for(root))
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            def raw_get(path):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                try:
                    connection.request("GET", path)
                    response = connection.getresponse()
                    return response.status, response.read()
                finally:
                    connection.close()
            try:
                status, themed = raw_get("/")
                self.assertEqual(status, 200)
                self.assertEqual(themed.count(b'/__workhub/theme.css'), 1)
                self.assertLess(themed.index(b'/__workhub/theme.css'), themed.index(b'</HEAD>'))
                self.assertEqual(raw_get('/?workhub_theme=original')[1], html)
                self.assertEqual(raw_get('/app.js')[1], b'const original = "unchanged";')
                self.assertEqual((root / "index.html").read_bytes(), html)
                css_one, css_two = b':root{--test-a:1}', b'body{color:green}'
                original_root = workhub.ROOT
                fake_root = root / "runtime"
                (fake_root / "static").mkdir(parents=True)
                (fake_root / "static/design-system.css").write_bytes(css_one)
                (fake_root / "static/embedded-theme.css").write_bytes(css_two)
                with patch.object(workhub, "ROOT", fake_root):
                    status, css = raw_get('/__workhub/theme.css')
                self.assertEqual(status, 200)
                self.assertIn(css_one, css)
                self.assertIn(css_two, css)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
