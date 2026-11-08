"""Review provenance and actionable-question checks, with no real providers."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import assessments
import workhub


class ReviewQualityTests(unittest.TestCase):
    def evidence(self):
        return {"project_id": "example", "project_name": "Example",
                "evidence": [{"id": "event:1", "kind": "event", "source_type": "agent_report", "text": "An agent reports completing a check."}],
                "sufficient_evidence": True, "source_fingerprint": "fixture",
                "evidence_profile": {"agent_reports": 1, "user_statements": 0, "independent_verifications": 0, "scope": "registered_records"}}

    def result(self):
        return {"verdict": "needs_attention", "headline": "Check the recorded claim", "summary": "The recorded claim needs a reproducible check.",
                "strengths": [], "assumptions": [], "blind_spots": [], "next_actions": [], "confidence": "low",
                "questions": [{"kind": "evidence", "question": "Can the stated result be reproduced?", "why": "Only an agent report is present.", "suggested_check": "Run the recorded command against the fixture and compare its exit code and output.", "evidence_ids": ["event:1"]}],
                "dimensions": [{"key": d["key"], "score": None, "reason": "No independently checked result is supplied.", "evidence_ids": ["event:1"]} for d in assessments.RUBRIC]}

    def test_a_question_without_a_reason_or_check_is_not_a_valid_review(self):
        for field in ("question", "why", "suggested_check"):
            with self.subTest(field=field):
                raw = self.result()
                raw["questions"][0][field] = " "
                with self.assertRaises(assessments.ReviewError):
                    assessments.normalize_result(raw, self.evidence(), "fixture")

    def test_repeating_a_question_does_not_count_as_depth(self):
        raw = self.result()
        raw["questions"].append(copy.deepcopy(raw["questions"][0]))
        with self.assertRaises(assessments.ReviewError):
            assessments.normalize_result(raw, self.evidence(), "fixture")

    def test_provenance_and_protocol_are_kept_with_the_review(self):
        evidence = self.evidence()
        result = assessments.normalize_result(self.result(), evidence, "fixture")
        self.assertEqual(result["policy_version"], assessments.ASSESSMENT_POLICY_VERSION)
        self.assertEqual(result["evidence_profile"], evidence["evidence_profile"])
        self.assertEqual(result["evidence_profile"]["independent_verifications"], 0)

    def test_work_records_are_not_marked_as_independent_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            project = directory / "project"
            project.mkdir()
            store = workhub.Store(directory / "state")
            identifier = store.register(project)["id"]
            store.record(project, "codex", "completed", "The agent reports a successful test.")
            manager = assessments.AssessmentManager(store)
            try:
                bundle = manager.evidence(identifier)
                record = next(i for i in bundle["evidence"] if i["kind"] == "event")
                self.assertEqual(record["source_type"], "agent_report")
                self.assertEqual(bundle["evidence_profile"]["independent_verifications"], 0)
                previous = bundle["source_fingerprint"]
                with patch.object(assessments, "ASSESSMENT_POLICY_VERSION", "changed-policy"):
                    self.assertNotEqual(manager.evidence(identifier)["source_fingerprint"], previous)
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
