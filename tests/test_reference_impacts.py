"""Independent behavioral checks for imported metadata and downstream safety."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from hrtrustgraph.deterministic.ingest import load_snapshot
from hrtrustgraph.deterministic.policy import dependencies_for, load_policy
from hrtrustgraph.deterministic.reference_docs import preview_references
from hrtrustgraph.deterministic.rules import detect_issues, resolve_fields
from tests.test_determination import AS_OF, fixture, observation
from tests.test_identity_core import write_csv


ROOT = Path(__file__).resolve().parents[1]


class ImportedMetadataImpactTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()
        self.documents = {
            filename: (ROOT / "data" / filename).read_text(encoding="utf-8")
            for filename in ("data_dictionary.md", "dependencies.md")
        }

    def test_system_feed_exposes_system_and_broad_reports_without_inventing_field_mapping(self):
        self.policy["dependencies"] = [
            {"source": "core_hr", "target": "payroll"},
            {"source": "payroll", "target": "report:whole_payroll_extract"},
            {"source": "payroll.department", "target": "report:department_report"},
            {"source": "payroll.job_code", "target": "learning.job_code"},
        ]
        exposure = dependencies_for(self.policy, "core_hr", "department")
        self.assertEqual(exposure, ["payroll", "report:whole_payroll_extract"])
        self.assertNotIn("payroll.department", exposure)
        self.assertNotIn("report:department_report", exposure)
        self.assertNotIn("learning.job_code", exposure)

    def test_explicit_field_feed_chains_through_target_source_alias_and_canonical_name(self):
        self.policy["dependencies"] = [
            {"source": "core_hr.department", "target": "payroll.dept"},
            {"source": "payroll.department", "target": "report:department_report"},
            {"source": "payroll.position_code", "target": "report:unrelated_job_report"},
            {"source": "payroll", "target": "report:whole_payroll_extract"},
        ]
        self.assertEqual(
            dependencies_for(self.policy, "core_hr", "department"),
            ["payroll.dept", "report:department_report", "report:whole_payroll_extract"],
        )
        self.assertNotIn("report:unrelated_job_report", dependencies_for(self.policy, "core_hr", "department"))
        # Traversal remains finite when feeds return to an earlier equivalent field.
        self.policy["dependencies"].append({"source": "payroll.department", "target": "core_hr.department"})
        self.assertEqual(len(dependencies_for(self.policy, "core_hr", "department")), 3)

    def test_imported_spaced_column_alias_continues_through_canonical_dependency(self):
        dictionary = self.documents["data_dictionary.md"].replace(
            "| department | dept |", "| department | Department Code |"
        )
        documents = {
            "data_dictionary.md": dictionary,
            "dependencies.md": """# Declared dependencies

| Upstream field | Downstream field or report |
| --- | --- |
| core_hr.department | payroll.Department Code |
| payroll.department | report:payroll_department_report |
""",
        }
        preview = preview_references(self.policy, documents)
        self.assertTrue(preview["ready"], preview["errors"])
        self.assertIn(
            "report:payroll_department_report",
            dependencies_for(preview["policy"], "core_hr", "department"),
            "A CSV column containing spaces must connect to the same canonical field downstream",
        )

    def test_imported_document_content_binds_snapshot_while_csv_bytes_and_row_ids_stay_fixed(self):
        first = preview_references(self.policy, self.documents)
        self.assertTrue(first["ready"], first["errors"])
        changed_documents = dict(self.documents)
        changed_documents["dependencies.md"] += "\ncore_hr.department -> report:additional_declared_report\n"
        second = preview_references(self.policy, changed_documents)
        self.assertTrue(second["ready"], second["errors"])
        with tempfile.TemporaryDirectory() as directory:
            write_csv(directory, "core_hr.csv", [{"employee_id": "SYN-1", "name": "Synthetic Example", "department": "ENG-01"}])
            before = load_snapshot(directory, first["policy"])
            after = load_snapshot(directory, second["policy"])
        self.assertNotEqual(first["digest"], second["digest"])
        self.assertNotEqual(before.snapshot_id, after.snapshot_id)
        self.assertEqual(before.source_hashes, after.source_hashes)
        self.assertEqual([row["record_id"] for row in before.records], [row["record_id"] for row in after.records])
        self.assertIn("report:additional_declared_report", dependencies_for(second["policy"], "core_hr", "department"))

    def test_repeated_metadata_review_does_not_change_logical_snapshot(self):
        preview = preview_references(self.policy, self.documents)
        self.assertTrue(preview["ready"], preview["errors"])
        first_policy = copy.deepcopy(preview["policy"])
        second_policy = copy.deepcopy(preview["policy"])
        first_policy["reference_import"].update(reviewed=True, reviewed_at="2026-10-01T10:00:00Z", review_method="ui")
        second_policy["reference_import"].update(reviewed=True, reviewed_at="2026-10-02T11:00:00Z", review_method="cli")
        with tempfile.TemporaryDirectory() as directory:
            write_csv(directory, "core_hr.csv", [{"employee_id": "SYN-1", "name": "Synthetic Example"}])
            first = load_snapshot(directory, first_policy)
            second = load_snapshot(directory, second_policy)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(first.records, second.records)
        self.assertEqual(first.source_hashes, second.source_hashes)

    def test_authoritative_value_outside_target_codes_remains_investigation(self):
        core = observation("core_hr", "CORE-SYN", department="ENG-01")
        payroll = observation("payroll", "PAY-SYN", department="FIN-01")
        snapshot, matches = fixture(core, payroll)
        self.policy["sources"]["payroll"]["domains"]["department"] = ["FIN-01", "OPS-01"]
        resolutions = resolve_fields(snapshot, matches, self.policy, AS_OF)
        findings = detect_issues(snapshot, matches, resolutions, self.policy, AS_OF)
        target = [issue for issue in findings if issue["record_id"] == payroll["record_id"] and issue["field"] == "department"]
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]["issue_type"], "cross_system_conflict")
        self.assertEqual(target[0]["recommendation_status"], "investigate")
        self.assertIsNone(target[0]["suggested_value"])
        self.assertIsNone(target[0]["fix_confidence"])
        self.assertIn("outside this source's declared valid codes", target[0]["evidence"]["explanation"])

    def test_missing_target_value_does_not_get_an_out_of_domain_authority_suggestion(self):
        core = observation("core_hr", "CORE-SYN", department="ENG-01")
        payroll = observation("payroll", "PAY-SYN", department=None)
        payroll["raw"]["dept"] = payroll["raw"].pop("department")
        payroll["field_columns"] = {"department": ["dept"]}
        snapshot, matches = fixture(core, payroll)
        self.policy["sources"]["payroll"]["domains"]["department"] = ["FIN-01"]
        resolutions = resolve_fields(snapshot, matches, self.policy, AS_OF)
        findings = detect_issues(snapshot, matches, resolutions, self.policy, AS_OF)
        target = next(issue for issue in findings if issue["record_id"] == payroll["record_id"] and issue["field"] == "department")
        self.assertEqual(target["issue_type"], "missing_value")
        self.assertEqual(target["recommendation_status"], "investigate")
        self.assertIsNone(target["suggested_value"])


if __name__ == "__main__":
    unittest.main()
