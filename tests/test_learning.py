"""Durable learning revisions and explicit user acknowledgement boundaries."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from learning import LearningError, LearningStore
from workhub import Store


class LearningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workhub-learning-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "example-project"
        self.other = self.root / "another-project"
        self.project.mkdir()
        self.other.mkdir()
        (self.project / "app.py").write_text("def transaction(): pass\n", encoding="utf-8")
        self.store = Store(self.root / "data")
        self.pid = self.store.register(self.project)["id"]
        self.other_id = self.store.register(self.other)["id"]
        self.learning = LearningStore(self.store)

    def payload(self, **changes):
        value = {
            "project_id": self.pid, "card_key": "sqlite/transaction",
            "title": "事务如何防止只保存一半", "concept": "事务把一组修改一起保存或一起撤销。",
            "explanation": "把一次保存看成一个整体，中途出错就撤销这组修改。",
            "implementation": "app.py 的 transaction 函数包住本次记录修改。",
            "terms": [{"term": "transaction", "definition": "一起提交或撤销的一组数据修改"}],
            "steps": ["开始事务", "保存修改", "成功时提交，出错时撤销"],
            "example": "with db: db.execute(statement, parameters)",
            "self_check": "第二次修改失败时，第一次修改应保留还是撤销？为什么？",
            "sources": [{"path": "app.py", "line": 1, "symbol": "transaction", "note": "本次实现入口"}],
            "agent": "codex", "run_id": "example-run", "source_event_ids": [],
        }
        value.update(changes)
        return value

    def add(self, **changes):
        return self.learning.add_card(self.payload(**changes))

    def test_idempotency_and_project_path_resolve_to_same_card(self):
        first = self.add()
        again = self.add()
        by_path = self.payload()
        del by_path["project_id"]
        by_path["project"] = str(self.project)
        same = self.learning.add_card(by_path)
        self.assertEqual((again["id"], again["revision"]), (first["id"], 1))
        self.assertEqual(same["id"], first["id"])
        self.assertEqual(same["payload_hash"], first["payload_hash"])
        self.assertEqual(first["status"], "pending")
        self.assertFalse(first["understood"])
        self.assertIsNone(first["acknowledgement"])

    def test_revision_is_durable_and_prior_understanding_requires_review(self):
        first = self.add()
        self.learning.acknowledge(first["id"], 1, True)
        second = self.add(implementation="app.py 同时保存项目记录与版本号，失败时一并撤销。")
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["status"], "needs_review")
        self.assertFalse(second["understood"])
        self.assertEqual(second["previous_understood_revision"], 1)
        reopened = LearningStore(Store(self.store.directory))
        detail = reopened.get(first["id"])
        self.assertEqual(detail["card"]["revision"], 2)
        self.assertEqual([x["revision"] for x in detail["history"]], [2, 1])
        self.assertTrue(detail["history"][1]["understood"])
        with self.store.connection() as db:
            old = db.execute("SELECT payload_json FROM learning_versions WHERE card_id=? AND revision=1", (first["id"],)).fetchone()[0]
        self.assertIn("transaction", old)

    def test_explicit_uncheck_of_new_version_is_pending_not_forever_needs_review(self):
        card = self.add()
        self.learning.acknowledge(card["id"], 1, True)
        second = self.add(concept="更新后的事务说明。")
        self.assertEqual(second["status"], "needs_review")
        unchecked = self.learning.acknowledge(card["id"], 2, False)
        self.assertEqual(unchecked["status"], "pending")
        self.assertEqual(unchecked["previous_understood_revision"], 1)
        self.assertFalse(unchecked["acknowledgement"]["understood"])
        self.assertTrue(self.learning.get(card["id"])["history"][1]["understood"])

    def test_provenance_only_changes_do_not_invalidate_understanding(self):
        first = self.add()
        self.learning.acknowledge(first["id"], 1, True)
        event = self.store.record(self.project, "zcode", "completed", "Another actual source event", run_id="another-source-run")
        second = self.add(agent="zcode", run_id="another-source-run", source_event_ids=[event["id"]])
        self.assertEqual(second["revision"], 1)
        self.assertEqual(second["content_hash"], first["content_hash"])
        self.assertEqual(second["status"], "understood")
        self.assertEqual(second["agent"], "zcode")
        detail = self.learning.get(first["id"])
        self.assertEqual(len(detail["history"]), 1)
        self.assertEqual(len(detail["origins"]), 2)
        self.add(agent="zcode", run_id="another-source-run", source_event_ids=[event["id"]])
        self.assertEqual(len(self.learning.get(first["id"])["origins"]), 2)
        with self.store.connection() as db:
            stored = db.execute("SELECT payload_json FROM learning_versions WHERE card_id=?", (first["id"],)).fetchone()[0]
        self.assertNotIn("another-source-run", stored)
        changed = self.add(implementation="The implementation now explains rollback across two writes.")
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(changed["status"], "needs_review")

    def test_more_recent_historical_uncheck_overrides_earlier_understood(self):
        first = self.add()
        self.learning.acknowledge(first["id"], 1, True)
        second = self.add(concept="Second explanation")
        self.learning.acknowledge(second["id"], 2, False)
        third = self.add(concept="Third explanation")
        self.assertEqual(third["status"], "pending")
        history = self.learning.get(first["id"])["history"]
        self.assertFalse(history[1]["understood"])
        self.assertTrue(history[2]["understood"])
        self.assertEqual(history[2]["acknowledgements"][0]["understood"], True)

    def test_check_cancel_and_recheck_preserve_the_user_event_trail(self):
        card = self.add()
        checked = self.learning.acknowledge(card["id"], 1, True)
        self.assertEqual(checked["status"], "understood")
        self.learning.acknowledge(card["id"], 1, True)
        cancelled = self.learning.acknowledge(card["id"], 1, False)
        self.assertEqual(cancelled["status"], "pending")
        history = self.learning.get(card["id"])["history"][0]
        self.assertEqual([x["understood"] for x in history["acknowledgements"]], [False, True])
        rechecked = self.learning.acknowledge(card["id"], 1, True)
        self.assertTrue(rechecked["understood"])
        self.assertEqual(len(self.learning.get(card["id"])["history"][0]["acknowledgements"]), 3)

    def test_stale_revision_is_conflict_and_cannot_ack_latest(self):
        card = self.add()
        self.add(explanation="说明补充了失败后的撤销行为。")
        for flag in [True, False]:
            with self.assertRaises(LearningError) as caught:
                self.learning.acknowledge(card["id"], 1, flag)
            self.assertEqual(caught.exception.status, 409)
        self.assertIsNone(self.learning.get(card["id"])["card"]["acknowledgement"])

    def test_acknowledgement_requires_exact_bool_and_integer_revision(self):
        card = self.add()
        for flag in [1, 0, "true", "false", None, [], {}]:
            with self.subTest(flag=flag), self.assertRaises(LearningError):
                self.learning.acknowledge(card["id"], 1, flag)
        for revision in [True, 0, -1, "1", 1.0, None]:
            with self.subTest(revision=revision), self.assertRaises(LearningError):
                self.learning.acknowledge(card["id"], revision, True)

    def test_import_cannot_supply_user_understanding_or_server_metadata(self):
        for key, value in [("understood", True), ("status", "understood"), ("acknowledgement", {}), ("revision", 2), ("id", "example")]:
            with self.subTest(key=key), self.assertRaises(LearningError):
                self.add(**{key: value})
        self.assertEqual(self.learning.list()["stats"]["total"], 0)

    def test_content_and_sources_are_required_with_limits(self):
        for field in ["title", "concept", "explanation", "implementation", "self_check", "card_key"]:
            with self.subTest(field=field), self.assertRaises(LearningError):
                self.add(**{field: " "})
        for sources in [None, [], "app.py", [None]]:
            with self.subTest(sources=sources), self.assertRaises(LearningError):
                self.add(sources=sources)
        for field, value in [("title", "x" * 301), ("steps", ["step"] * 31), ("terms", [{"term": "a", "definition": "b"}] * 51)]:
            with self.subTest(field=field), self.assertRaises(LearningError):
                self.add(**{field: value})

    def test_sources_reject_traversal_absolute_hidden_and_private_files(self):
        paths = ["../app.py", "/tmp/app.py", "src/../../app.py", "./app.py", "src//app.py", "src/./app.py", ".env", "src/.hidden.py", "src/../app.py", "C:/private/app.py", "src\\app.py", "secrets.pem", "id_rsa", "glm.json", "credentials.json", "data/workhub.sqlite3", "%2e%2e/app.py", "src/%2fetc", "src/\napp.py", "file:app.py"]
        for path in paths:
            with self.subTest(path=path), self.assertRaises(LearningError):
                self.add(sources=[{"path": path}])

    def test_source_schema_and_lists_are_strict(self):
        for source in [{"path": "app.py", "line": True}, {"path": "app.py", "line": 0}, {"path": "app.py", "line": "1"}, {"path": "app.py", "read_file": True}]:
            with self.subTest(source=source), self.assertRaises(LearningError):
                self.add(sources=[source])
        for changes in [{"terms": ["word"]}, {"terms": [{"term": "word", "definition": "meaning", "html": True}]}, {"steps": "first"}, {"steps": [1]}, {"source_event_ids": [True]}, {"source_event_ids": ["1"]}, {"source_event_ids": [2**64]}, {"example": {"code": "example"}}]:
            with self.subTest(changes=changes), self.assertRaises(LearningError):
                self.add(**changes)

    def test_markup_and_normal_code_remain_literal_and_are_not_executed(self):
        literal = '<img src=x onerror="alert(1)"><script>fetch("/private")</script>'
        code = 'api_key = os.environ["PROVIDER_API_KEY"]\npassword = hash_password(input_value)\ntoken = parser.next_token()'
        card = self.add(explanation=literal, example=code, sources=[{"path": "app.py", "symbol": literal}])
        saved = self.learning.get(card["id"])["card"]
        self.assertEqual(saved["explanation"], literal)
        self.assertEqual(saved["sources"][0]["symbol"], literal)
        self.assertEqual(saved["example"], code)

    def test_credentials_reject_safely_while_placeholders_and_hashes_are_allowed(self):
        value = "sk-" + "a1B2c3D4" * 5
        private_key = "-----BEGIN " + "PRIVATE KEY-----\n" + "A" * 64 + "\n-----END " + "PRIVATE KEY-----"
        for text in [value, 'api_key="' + "sensitive-test-value" + '"', 'password="' + "bad" + '"', "PROVIDER_API_KEY=" + "aB7cD8eF9gH0iJ1k", "Bearer " + "secret-test-value" * 2, private_key]:
            with self.subTest(text=text[:10]), self.assertRaises(LearningError) as caught:
                self.add(example=text)
            self.assertEqual(caught.exception.status, 422)
            self.assertNotIn(value, str(caught.exception))
        card = self.add(example='api_key="YOUR_API_KEY"; digest="' + "a" * 64 + '"; private-key header: -----BEGIN PRIVATE KEY-----')
        self.assertIn("YOUR_API_KEY", card["example"])

    def test_invalid_utf8_and_total_payload_limit_fail_as_validation(self):
        with self.assertRaises(LearningError) as caught:
            self.add(explanation="\ud800")
        self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(LearningError):
            self.add(terms=[{"term": "术语", "definition": "解" * 2000}] * 50)

    def test_project_identity_and_event_provenance_are_isolated(self):
        card = self.add()
        other = self.add(project_id=self.other_id)
        self.assertNotEqual(card["id"], other["id"])
        self.assertEqual(self.learning.list(self.pid)["stats"]["total"], 1)
        event = self.store.record(self.project, "codex", "completed", "A real implementation event", run_id="learning-source-run")
        with_source = self.add(source_event_ids=[event["id"], event["id"]])
        self.assertEqual(with_source["source_event_ids"], [event["id"]])
        with self.assertRaises(LearningError):
            self.add(project_id=self.other_id, source_event_ids=[event["id"]])
        with self.assertRaises(LearningError):
            self.add(source_event_ids=[999999])

    def test_missing_projects_and_cards_fail_without_registering_anything(self):
        for changes in [{"project_id": "missing"}, {"project_id": self.pid, "project": str(self.project)}]:
            with self.assertRaises(LearningError):
                self.add(**changes)
        for identifier in ["missing", ""]:
            with self.assertRaises(LearningError):
                self.learning.get(identifier)
            with self.assertRaises(LearningError):
                self.learning.acknowledge(identifier, 1, True)
        self.assertEqual(self.learning.list()["cards"], [])

    def test_query_stats_and_status_filter_use_current_revisions(self):
        first = self.add()
        second = self.add(card_key="api/routing", title="API 路由", concept="路由把地址交给处理函数。")
        self.learning.acknowledge(first["id"], 1, True)
        self.learning.acknowledge(second["id"], 1, True)
        self.add(card_key="api/routing", title="API 路由", concept="路由说明已更新。")
        self.add(card_key="cli/arguments", title="命令行参数")
        result = self.learning.list(self.pid, status="needs_review")
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["stats"], {"total": 3, "pending": 1, "understood": 1, "needs_review": 1})
        query = self.learning.list(self.pid, query="路由")
        self.assertEqual(query["stats"]["total"], 1)
        with self.assertRaises(LearningError):
            self.learning.list(status="complete")

    def test_concurrent_identical_imports_keep_one_revision(self):
        with ThreadPoolExecutor(max_workers=5) as pool:
            cards = list(pool.map(lambda _: self.add(), range(12)))
        self.assertEqual(len({x["id"] for x in cards}), 1)
        self.assertEqual({x["revision"] for x in cards}, {1})

    def test_concurrent_distinct_updates_are_serialized_without_lost_revisions(self):
        first = self.add()
        with ThreadPoolExecutor(max_workers=5) as pool:
            cards = list(pool.map(lambda i: self.add(explanation="Concurrent version " + str(i)), range(8)))
        self.assertEqual({x["revision"] for x in cards}, set(range(2, 10)))
        self.assertEqual(len(self.learning.get(first["id"])["history"]), 9)

    def test_source_reference_survives_file_removal_without_reading_source(self):
        (self.project / "app.py").unlink()
        card = self.add()
        self.assertEqual(card["sources"][0]["path"], "app.py")
        reopened = LearningStore(Store(self.store.directory))
        self.assertEqual(reopened.get(card["id"])["card"]["concept"], card["concept"])


if __name__ == "__main__":
    unittest.main()
