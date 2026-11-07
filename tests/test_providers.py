"""Provider adapter contracts. Only temporary CLI processes and loopback HTTP run."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import assessments
import workhub


FAKE_KEY = "synthetic-provider-test-credential"
EVIDENCE = {"project_id": "demo", "project_name": "Example", "evidence": [{"id": "project:demo", "kind": "project", "text": "Example project"}], "sufficient_evidence": False, "source_fingerprint": "example-fingerprint"}


class ProviderFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workhub-provider-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def write(self, name, data):
        path = self.directory / name
        path.write_text(json.dumps(data), encoding="utf-8")
        path.chmod(0o600)
        return path

    def config(self, provider="openai", **values):
        data = {"provider": provider, "model": "example-model", "api_keys": [FAKE_KEY], "max_retries": 0}
        data.update(values)
        self.write("llm.json", data)
        return assessments.ProviderConfig(self.directory, environ={})

    def fake_request(self, config, envelope):
        calls = []
        def opened(request, timeout):
            calls.append((request, timeout))
            return BytesIO(json.dumps(envelope).encode())
        with patch("assessments.build_opener", return_value=SimpleNamespace(open=opened)):
            result = assessments.create_provider(config).complete(EVIDENCE)
        return result, calls


class ProviderAdapterTests(ProviderFixture):
    def test_new_file_and_generic_environment_take_precedence_without_cross_provider_keys(self):
        self.write("glm.json", {"api_keys": ["synthetic-legacy-key"], "model": "glm-example"})
        legacy = assessments.ProviderConfig(self.directory, environ={})
        self.assertEqual(legacy.public()["provider_id"], "glm")
        self.assertTrue(legacy.public()["configured"])
        self.write("llm.json", {"provider": "openai", "model": "file-model", "api_keys": [FAKE_KEY]})
        env = {"WORKHUB_LLM_MODEL": "environment-model", "WORKHUB_LLM_API_KEY": "synthetic-env-key", "GLM_API_KEY": "must-not-be-forwarded"}
        selected = assessments.ProviderConfig(self.directory, environ=env)
        self.assertEqual(selected.model, "environment-model")
        self.assertEqual(selected.keys, ["synthetic-env-key"])
        self.assertEqual(selected.public()["provider_id"], "openai")
        self.write("llm.json", {"provider": "anthropic", "model": "example-model"})
        selected = assessments.ProviderConfig(self.directory, environ={"GLM_API_KEY": "must-not-be-forwarded"})
        self.assertEqual(selected.keys, [])
        self.assertFalse(selected.public()["configured"])
        self.write("llm.json", {"model": "explicit-new-file", "api_keys": [FAKE_KEY]})
        selected = assessments.ProviderConfig(self.directory, environ={"GLM_API_KEY": "must-not-be-forwarded"})
        self.assertEqual(selected.public()["provider_id"], "openai")
        self.assertEqual(selected.keys, [FAKE_KEY])

    def test_openai_request_uses_declared_model_endpoint_auth_and_json_contract(self):
        config = self.config(timeout_seconds=4)
        result, calls = self.fake_request(config, {"choices": [{"message": {"content": '{"ok":true}'}}]})
        request, timeout = calls[0]
        body = json.loads(request.data)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(headers["authorization"], "Bearer " + FAKE_KEY)
        self.assertEqual(body["model"], "example-model")
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("temperature", body)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["messages"][0]["content"], assessments.build_prompt(EVIDENCE)["system"])
        self.assertEqual(timeout, 4)

    def test_explicit_https_compatible_host_and_parameter_options(self):
        config = self.config(base_url="https://gateway.example.test/v1", json_mode=False, token_parameter="max_tokens", max_tokens=2000)
        self.assertTrue(config.public()["configured"])
        _, calls = self.fake_request(config, {"choices": [{"message": {"content": '{"ok":true}'}}]})
        body = json.loads(calls[0][0].data)
        self.assertEqual(calls[0][0].full_url, "https://gateway.example.test/v1/chat/completions")
        self.assertEqual(body["max_tokens"], 2000)
        self.assertNotIn("response_format", body)
        env_config = assessments.ProviderConfig(self.directory, environ={"WORKHUB_LLM_BASE_URL": "https://environment.example.test/v1"})
        self.assertTrue(env_config.public()["configured"])

    def test_anthropic_uses_native_headers_system_and_text_blocks(self):
        config = self.config("anthropic", anthropic_version="2026-10-21")
        result, calls = self.fake_request(config, {"content": [{"type": "thinking", "thinking": "not a result"}, {"type": "text", "text": '{"ok":'}, {"type": "text", "text": 'true}'}]})
        request, _ = calls[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        body = json.loads(request.data)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["x-api-key"], FAKE_KEY)
        self.assertEqual(headers["anthropic-version"], "2026-10-21")
        self.assertNotIn("authorization", headers)
        self.assertEqual(body["system"], assessments.build_prompt(EVIDENCE)["system"])
        self.assertEqual([message["role"] for message in body["messages"]], ["user"])
        self.assertNotIn("response_format", body)
        self.assertNotIn("temperature", body)

    def test_ollama_real_loopback_http_has_no_fabricated_authorization(self):
        observed = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                observed.append((self.path, dict(self.headers), json.loads(body)))
                response = json.dumps({"choices": [{"message": {"content": '{"local":true}'}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            config = self.config("ollama", api_keys=[], base_url="http://127.0.0.1:{}/v1".format(server.server_port))
            self.assertTrue(config.public()["configured"])
            self.assertEqual(config.public()["key_count"], 0)
            self.assertEqual(assessments.create_provider(config).complete(EVIDENCE), {"local": True})
            self.assertEqual(observed[0][0], "/v1/chat/completions")
            self.assertNotIn("authorization", {key.lower(): value for key, value in observed[0][1].items()})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_nonlocal_http_credentials_urls_and_placeholders_are_rejected(self):
        for provider, url in (("ollama", "http://192.0.2.10/v1"), ("openai", "http://127.0.0.1:9000/v1"), ("anthropic", "https://user:password@api.anthropic.com/v1")):
            with self.subTest(provider=provider, url=url):
                self.assertFalse(self.config(provider, base_url=url).public()["configured"])
        self.assertFalse(self.config(model="MODEL", api_keys=["YOUR_API_KEY"]).public()["configured"])
        self.write("llm.json", {"provider": {"bad": "shape"}})
        self.assertFalse(assessments.ProviderConfig(self.directory, environ={}).public()["configured"])
        invalid = self.config(base_url="http://remote.example.test/v1", model=FAKE_KEY)
        self.assertNotIn(FAKE_KEY, json.dumps(invalid.public()))

    def test_output_limit_retry_bound_and_safe_errors(self):
        config = self.config(max_output_bytes=1024, max_retries=1)
        provider = assessments.create_provider(config)
        with patch("assessments.build_opener", return_value=SimpleNamespace(open=lambda *_a, **_k: BytesIO(b"x" * 1025))):
            with self.assertRaises(assessments.ReviewError) as caught:
                provider.complete(EVIDENCE)
            self.assertIn("超过", str(caught.exception))
        def failure(*_args, **_kwargs):
            raise HTTPError(config.endpoint, 500, FAKE_KEY, {}, BytesIO(FAKE_KEY.encode()))
        with patch("assessments.build_opener", return_value=SimpleNamespace(open=failure)), patch("assessments.time.sleep") as slept:
            with self.assertRaises(assessments.ReviewError) as caught:
                provider.complete(EVIDENCE)
            self.assertNotIn(FAKE_KEY, str(caught.exception))
            self.assertEqual(slept.call_count, 1)

    def test_configured_concurrency_is_respected_with_multiple_keys(self):
        provider = assessments.create_provider(self.config(api_keys=["synthetic-pool-one", "synthetic-pool-two"], concurrency=1))
        active = 0
        maximum = 0
        lock = threading.Lock()
        def fake_network(_key, _evidence):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(active, maximum)
            time.sleep(0.02)
            with lock:
                active -= 1
            return {"ok": True}
        with patch.object(provider, "_request", side_effect=fake_network):
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(len(list(pool.map(provider.complete, [EVIDENCE] * 6))), 6)
        self.assertEqual(maximum, 1)


@unittest.skipUnless(sys.platform != "win32", "CLI process groups require macOS/Linux")
class CLIProviderTests(ProviderFixture):
    def script(self, source, **values):
        path = self.directory / "wrapper.py"
        path.write_text(source, encoding="utf-8")
        extra = values.pop("arguments", [])
        return self.config("cli", api_keys=[], command=[sys.executable, str(path), *extra], **values)

    def test_cli_receives_full_prompt_without_a_shell_and_is_publicly_private(self):
        marker = self.directory / "must-not-exist"
        literal = "$(touch {})".format(marker)
        config = self.script("import json,sys\np=json.load(sys.stdin)\nprint(json.dumps({'protocol':p['protocol'],'system':p['system'],'evidence':p['evidence'],'argument':sys.argv[1]}))\n", arguments=[literal])
        self.assertTrue(config.public()["configured"])
        self.assertEqual(config.public()["key_count"], 0)
        self.assertEqual(config.public()["mode"], "cli")
        self.assertNotIn(str(self.directory), json.dumps(config.public()))
        result = assessments.create_provider(config).complete(EVIDENCE)
        self.assertEqual(result["protocol"], "workhub.review.v1")
        self.assertEqual(result["system"], assessments.build_prompt(EVIDENCE)["system"])
        self.assertEqual(result["evidence"], EVIDENCE)
        self.assertEqual(result["argument"], literal)
        self.assertFalse(marker.exists())

    def test_explicit_result_envelope_is_supported(self):
        provider = assessments.create_provider(self.script("import json,sys\njson.load(sys.stdin)\nprint(json.dumps({'result':{'wrapped':True}}))\n", output_format="result"))
        self.assertEqual(provider.complete(EVIDENCE), {"wrapped": True})

    def test_cli_reviews_use_normalization_and_configuration_changes_invalidate_cache(self):
        source = """import json,sys
p=json.load(sys.stdin)
ref=p['evidence']['evidence'][0]['id']
r={'verdict':'ready','headline':'Example review','summary':'Evidence is still limited.','strengths':[],'assumptions':[],'questions':[],'blind_spots':[],'next_actions':[],'confidence':'high','dimensions':[{'key':k,'score':4,'reason':'Declared evidence','evidence_ids':[ref]} for k in ('goal','evidence','verification','risks','next_steps')]}
print(json.dumps(r))
"""
        self.script(source)
        project = self.directory / "example-project"
        project.mkdir()
        store = workhub.Store(self.directory)
        identifier = store.register(project)["id"]
        factory = lambda: assessments.create_provider(assessments.ProviderConfig(self.directory, environ={}))
        manager = assessments.AssessmentManager(store, provider_factory=factory)
        try:
            first = manager.submit([identifier])
            self.assertEqual(manager.wait(first["job_id"], timeout=4)["status"], "completed")
            review = manager.project(identifier)["review"]
            self.assertEqual(review["provider_id"], "cli")
            self.assertEqual(review["verdict"], "insufficient_evidence")
            self.assertTrue(all(dimension["score"] is None for dimension in review["dimensions"]))
            self.script(source.replace("print(json.dumps(r))", "print(json.dumps({'result':r}))"), output_format="result")
            second = manager.submit([identifier])
            self.assertEqual(second["cached"], 0)
            self.assertEqual(manager.wait(second["job_id"], timeout=4)["status"], "completed")
            self.assertNotEqual(manager.project(identifier)["review"]["id"], review["id"])
            self.assertEqual(len(manager.project(identifier)["history"]), 2)
        finally:
            manager.close()

    def test_cli_stderr_arguments_and_nonjson_output_do_not_leak_in_errors(self):
        source = "import sys\nsys.stderr.write(sys.argv[1])\nsys.exit(7)\n"
        provider = assessments.create_provider(self.script(source, arguments=[FAKE_KEY]))
        with self.assertRaises(assessments.ReviewError) as caught:
            provider.complete(EVIDENCE)
        self.assertNotIn(FAKE_KEY, str(caught.exception))
        self.assertNotIn("wrapper.py", str(caught.exception))
        provider = assessments.create_provider(self.script("print('progress log, not JSON')\n"))
        with self.assertRaises(assessments.ReviewError):
            provider.complete(EVIDENCE)

    def test_cli_output_is_terminated_when_limit_is_crossed(self):
        provider = assessments.create_provider(self.script("import sys,time\nwhile True:\n sys.stdout.write('x'*2048);sys.stdout.flush();time.sleep(.01)\n", max_output_bytes=1024, timeout_seconds=5))
        started = time.monotonic()
        with self.assertRaises(assessments.ReviewError) as caught:
            provider.complete(EVIDENCE)
        self.assertIn("超过", str(caught.exception))
        self.assertLess(time.monotonic() - started, 2)

    def test_cli_timeout_stops_its_child_process_group(self):
        marker = self.directory / "child-would-survive"
        pidfile = self.directory / "spawned-child"
        child = "import time,pathlib;time.sleep(1);pathlib.Path({!r}).write_text('survived')".format(str(marker))
        source = "import subprocess,sys,time,pathlib\np=subprocess.Popen([sys.executable,'-c',{!r}])\npathlib.Path({!r}).write_text(str(p.pid))\ntime.sleep(30)\n".format(child, str(pidfile))
        provider = assessments.create_provider(self.script(source, timeout_seconds=0.4))
        with self.assertRaises(assessments.ReviewError) as caught:
            provider.complete(EVIDENCE)
        self.assertIn("超时", str(caught.exception))
        self.assertTrue(pidfile.exists())
        time.sleep(0.8)
        self.assertFalse(marker.exists(), "本次 CLI 子进程不能在超时后继续运行")


if __name__ == "__main__":
    unittest.main()
