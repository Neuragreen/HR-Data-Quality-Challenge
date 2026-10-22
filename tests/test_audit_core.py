"""Behavioral verification of local human-review history."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from hrtrustgraph.deterministic.audit import record_decision, verify_events


class HumanDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.issues = [
            {"issue_id": "ISS-proposed", "recommendation_status": "proposed", "suggested_value": "DISABLED"},
            {"issue_id": "ISS-uncertain", "recommendation_status": "investigate", "suggested_value": None},
        ]
        (self.directory / "issues.json").write_text(json.dumps(self.issues), encoding="utf-8")
        (self.directory / "summary.json").write_text(
            json.dumps({"snapshot_id": "SNAP-independent", "policy_version": "test-policy-1"}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def decide(self, decision="approve", issue="ISS-proposed", reviewer="Test reviewer", reason="Evidence reviewed"):
        return record_decision(self.directory, issue, decision, reviewer, reason)

    def events(self):
        path = self.directory / "decisions.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_decision_is_linked_to_snapshot_policy_and_reviewer(self):
        event = self.decide()
        self.assertEqual(event["snapshot_id"], "SNAP-independent")
        self.assertEqual(event["policy_version"], "test-policy-1")
        self.assertEqual(event["reviewer"], "Test reviewer")
        self.assertEqual(event["proposed_value"], "DISABLED")
        self.assertFalse(event["write_back_performed"])

    def test_history_is_appended_and_chained(self):
        first = self.decide()
        second = self.decide("investigate", reason="Request additional evidence")
        events = self.events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], first)
        self.assertEqual(events[1], second)
        self.assertEqual(second["previous_hash"], first["event_hash"])
        self.assertEqual(verify_events(events), second["event_hash"])

    def test_tampered_history_prevents_append(self):
        self.decide()
        altered = copy.deepcopy(self.events())
        altered[0]["reason"] = "Altered after review"
        path = self.directory / "decisions.jsonl"
        path.write_text(json.dumps(altered[0]) + "\n", encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.decide("reject")
        self.assertEqual(path.read_bytes(), before)

    def test_unresolved_investigation_cannot_be_approved(self):
        with self.assertRaises(ValueError):
            self.decide(issue="ISS-uncertain")
        self.assertFalse((self.directory / "decisions.jsonl").exists())

    def test_review_requires_existing_issue_reviewer_and_reason(self):
        for changes in ({"issue": "ISS-absent"}, {"reviewer": " "}, {"reason": " "}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.decide(**changes)
        self.assertFalse((self.directory / "decisions.jsonl").exists())

    def test_recording_decision_does_not_change_analysis_or_source_files(self):
        source = self.directory / "core_hr.csv"
        source.write_text("employee_id,status\nC-1,TERMINATED\n", encoding="utf-8")
        protected = {
            path.name: path.read_bytes()
            for path in (source, self.directory / "issues.json", self.directory / "summary.json")
        }
        self.decide()
        for filename, content in protected.items():
            self.assertEqual((self.directory / filename).read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
