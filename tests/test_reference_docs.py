"""Reference imports must change executable checks, retain evidence and abstain."""
import copy
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from hrtrustgraph.deterministic.ingest import load_snapshot
from hrtrustgraph.deterministic.policy import load_policy
from hrtrustgraph.deterministic.reference_docs import MAX_DOCUMENT_BYTES, preview_references


ROOT = Path(__file__).resolve().parents[1]


def repository_documents():
    return {name: (ROOT / "data" / name).read_text(encoding="utf-8")
            for name in ("data_dictionary.md", "dependencies.md")}


def compact_documents(dictionary=None, dependencies=None):
    return {"data_dictionary.md": dictionary or """# Test dictionary
### Core HR
Dates: %Y-%m-%d.
| Canonical field | Source column | Mandatory | Allowed codes | Definition |
| --- | --- | --- | --- | --- |
| source_id | worker_key | Yes | | Opaque source-local identifier |
| name | legal_name | Yes | | Employee name supplied by Core HR |
| department | cost_centre | Yes | NEW-FIN, NEW-OPS | Approved cost-centre code |
""", "dependencies.md": dependencies or """# Declared impact paths
| From | To |
| --- | --- |
| Core HR.department | report:payroll_reconciliation |
"""}


class ReferenceDocumentTests(unittest.TestCase):
    def setUp(self):
        self.base = load_policy()

    def test_repository_documents_roundtrip_without_changing_executable_settings(self):
        docs = repository_documents()
        before = copy.deepcopy(self.base)
        preview = preview_references(self.base, docs)
        self.assertTrue(preview["ready"], preview["errors"])
        self.assertEqual(len(preview["definitions"]), 44)
        self.assertEqual(len(preview["dependencies"]), 28)
        self.assertEqual(preview["changes"], [])
        for name, original in before["sources"].items():
            for setting in ("fields", "required", "domains", "date_formats", "value_maps"):
                self.assertEqual(preview["policy"]["sources"][name][setting], original[setting])
        self.assertEqual(self.base, before)
        self.assertEqual(preview["documents"][0]["sha256"], hashlib.sha256(docs["data_dictionary.md"].encode()).hexdigest())
        self.assertEqual(preview["policy"]["reference_import"]["digest"], preview["digest"])
        self.assertIn("line", preview["definitions"][0])
        self.assertIn("line", preview["dependencies"][0])

    def test_imported_columns_and_code_lists_drive_actual_ingestion(self):
        docs = compact_documents()
        preview = preview_references(self.base, docs)
        self.assertTrue(preview["ready"], preview["errors"])
        config = preview["policy"]["sources"]["core_hr"]
        self.assertEqual(config["domains"], {"department": ["NEW-FIN", "NEW-OPS"]})
        self.assertNotIn("job_code", config["fields"])
        self.assertEqual(config["field_definitions"]["department"]["description"], "Approved cost-centre code")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core_hr.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["worker_key", "legal_name", "cost_centre", "department"])
                writer.writeheader()
                writer.writerows([{"worker_key": "W-1", "legal_name": "Aisha Noor", "cost_centre": "NEW-FIN", "department": "OLD"},
                                  {"worker_key": "W-2", "legal_name": "Lina Ali", "cost_centre": "FIN-01", "department": "NEW-FIN"}])
            original_bytes = path.read_bytes()
            rows = {row["source_id"]: row for row in load_snapshot(directory, preview["policy"]).records}
            self.assertEqual(rows["W-1"]["values"]["department"], "NEW-FIN")
            self.assertNotIn("department", rows["W-1"]["invalid_fields"])
            self.assertEqual(rows["W-2"]["invalid_fields"]["department"]["reason"], "invalid_code")
            self.assertEqual(rows["W-2"]["invalid_fields"]["department"]["allowed_values"], ["NEW-FIN", "NEW-OPS"])
            self.assertEqual(path.read_bytes(), original_bytes)
        self.assertEqual(preview["policy"]["dependencies"], [{"source": "core_hr.department", "target": "report:payroll_reconciliation"}])

    def test_source_column_and_report_display_names_are_supported(self):
        docs = compact_documents(dependencies="Payroll.dept -> Payroll Reconciliation Report")
        preview = preview_references(self.base, docs)
        self.assertTrue(preview["ready"], preview["errors"])
        self.assertEqual(preview["dependencies"][0]["source"], "payroll.dept")
        self.assertEqual(preview["dependencies"][0]["target"], "report:payroll_reconciliation")

    def test_system_level_edges_and_new_explicit_reports_are_potential_only(self):
        preview = preview_references(self.base, compact_documents(dependencies="Core HR → Payroll\nPayroll → report:cost_summary"))
        self.assertTrue(preview["ready"], preview["errors"])
        self.assertEqual(preview["policy"]["dependencies"][0], {"source": "core_hr", "target": "payroll"})
        self.assertTrue(any("system-level" in message for message in preview["warnings"]))
        self.assertTrue(any("calculation is not implemented" in message for message in preview["warnings"]))

    def test_missing_required_column_setting_is_visible_and_base_rules_remain_unapproved(self):
        docs = compact_documents()
        docs["data_dictionary.md"] = """### core_hr
| Semantic field | Source columns | Description |
| --- | --- | --- |
| source_id | employee_id | Source identifier |
"""
        docs["dependencies.md"] = "core_hr.source_id -> report:payroll_reconciliation"
        self.base["reports"]["definitions_approved"] = True
        preview = preview_references(self.base, docs)
        self.assertTrue(preview["ready"], preview["errors"])
        self.assertEqual(preview["policy"]["sources"]["core_hr"]["required"], ["source_id"])
        self.assertFalse(preview["policy"]["reports"]["definitions_approved"])
        self.assertEqual(preview["policy"]["authority"], self.base["authority"])
        self.assertTrue(any("Required setting" in message for message in preview["warnings"]))
        self.assertTrue(any("date formats remain inherited" in message for message in preview["warnings"]))
        self.assertIn("authority", preview["policy"]["reference_import"]["inherited_policy_sections"])

    def test_unknown_source_and_field_are_blocking(self):
        for replacement, expected in (("### Unknown HR", "Unknown source"), ("### core_hr", "Unknown semantic field")):
            dictionary = f"""{replacement}
| Field | Source column | Required |
| --- | --- | --- |
| source_id | employee_id | Yes |
| unknown_compensation_flag | mystery | No |
"""
            preview = preview_references(self.base, compact_documents(dictionary=dictionary))
            self.assertFalse(preview["ready"])
            self.assertTrue(any(expected in message for message in preview["errors"]), preview["errors"])

    def test_conflicting_duplicate_and_invalid_required_flags_block(self):
        docs = compact_documents()
        docs["data_dictionary.md"] += "| department | another_column | Yes | NEW-FIN | Other interpretation |\n"
        preview = preview_references(self.base, docs)
        self.assertFalse(preview["ready"])
        self.assertTrue(any("Conflicting definitions" in message for message in preview["errors"]))
        docs = compact_documents()
        docs["data_dictionary.md"] = docs["data_dictionary.md"].replace("| Yes | NEW-FIN", "| Sometimes | NEW-FIN")
        preview = preview_references(self.base, docs)
        self.assertFalse(preview["ready"])
        self.assertTrue(any("Required must be Yes or No" in message for message in preview["errors"]))

    def test_unsupported_or_malformed_table_rows_cannot_be_silently_dropped(self):
        for extra in ("\n| Other Field | Other Meaning |\n| --- | --- |\n| x | y |\n",
                      "\n| raw table without | separator |\n",
                      "| name | a | No |\n"):
            docs = compact_documents()
            docs["data_dictionary.md"] += extra
            preview = preview_references(self.base, docs)
            self.assertFalse(preview["ready"], extra)
            self.assertTrue(any("data_dictionary.md:" in message for message in preview["errors"]))

    def test_unsupported_free_prose_is_not_treated_as_a_policy(self):
        preview = preview_references(self.base, {"data_dictionary.md": "Core HR holds trustworthy employee details.",
                                               "dependencies.md": "Payroll feeds most downstream reports."})
        self.assertFalse(preview["ready"])
        self.assertTrue(any("No supported field definitions" in message for message in preview["errors"]))
        self.assertTrue(any("No supported dependencies" in message for message in preview["errors"]))

    def test_invalid_dependency_unknown_field_or_implicit_unknown_report_blocks(self):
        for declaration in ("core_hr.not_a_field -> payroll.dept", "core_hr.department -> Unknown Dashboard", "unknown.department -> payroll.dept"):
            preview = preview_references(self.base, compact_documents(dependencies=declaration))
            self.assertFalse(preview["ready"], declaration)
            self.assertTrue(any("dependencies.md:1:" in message for message in preview["errors"]))

    def test_prose_inline_arrow_examples_do_not_add_false_lineage(self):
        docs = compact_documents()
        docs["dependencies.md"] += "\nExamples: `core_hr.location -> report:unimplemented_summary` should be reviewed.\n"
        preview = preview_references(self.base, docs)
        self.assertTrue(preview["ready"], preview["errors"])
        self.assertEqual(len(preview["dependencies"]), 1)

    def test_explicit_code_maps_cannot_override_the_valid_code_list(self):
        docs = compact_documents()
        docs["data_dictionary.md"] += '\nValue mappings: `{"department": {"Legacy": "FIN-01"}}`.\n'
        preview = preview_references(self.base, docs)
        self.assertFalse(preview["ready"])
        self.assertTrue(any("outside the declared code list" in message for message in preview["errors"]))

    def test_normalization_cannot_make_explicit_code_maps_ambiguous(self):
        docs = compact_documents()
        docs["data_dictionary.md"] += '\nValue mappings: `{"department": {"LEGACY": "NEW-FIN", "legacy": "NEW-OPS"}}`.\n'
        preview = preview_references(self.base, docs)
        self.assertFalse(preview["ready"])
        self.assertTrue(any("conflicting value mappings" in message for message in preview["errors"]))

    def test_uninterpreted_table_columns_are_visible_in_preview(self):
        docs = compact_documents()
        docs["data_dictionary.md"] = docs["data_dictionary.md"].replace("| Definition |", "| Authority |")
        preview = preview_references(self.base, docs)
        self.assertTrue(preview["ready"], preview["errors"])
        self.assertTrue(any("authority" in message and "not executable declarations" in message for message in preview["warnings"]))
        self.assertEqual(preview["policy"]["authority"], self.base["authority"])

    def test_incompatible_inherited_maps_are_removed_with_visible_warning(self):
        docs = repository_documents()
        docs["data_dictionary.md"] = docs["data_dictionary.md"].replace("| ACTIVE, ON_LEAVE, TERMINATED |", "| ACTIVE |", 1)
        docs["data_dictionary.md"] = "\n".join(line for line in docs["data_dictionary.md"].splitlines()
                                                 if not line.startswith('Value mappings: `{"employment_status"'))
        preview = preview_references(self.base, docs)
        self.assertTrue(preview["ready"], preview["errors"])
        self.assertNotIn("employment_status", preview["policy"]["sources"]["core_hr"]["value_maps"])
        self.assertTrue(any("Removed inherited value mappings" in message for message in preview["warnings"]))

    def test_missing_pair_empty_oversized_and_non_utf8_documents_block(self):
        for documents in ({"data_dictionary.md": "text"},
                          {"data_dictionary.md": "", "dependencies.md": " "},
                          {"data_dictionary.md": "x" * (MAX_DOCUMENT_BYTES + 1), "dependencies.md": "text"},
                          {"data_dictionary.md": "\ud800", "dependencies.md": "text"}):
            preview = preview_references(self.base, documents)
            self.assertFalse(preview["ready"])
            self.assertTrue(preview["errors"])

    def test_open_ended_lists_and_unrecognized_date_formats_block(self):
        for old, new in (("NEW-FIN, NEW-OPS", "NEW-FIN, etc."), ("%Y-%m-%d", "%Y-%Q-%d")):
            docs = compact_documents()
            docs["data_dictionary.md"] = docs["data_dictionary.md"].replace(old, new)
            preview = preview_references(self.base, docs)
            self.assertFalse(preview["ready"])

    def test_preview_digest_changes_with_document_or_selected_base_policy(self):
        docs = compact_documents()
        preview = preview_references(self.base, docs)
        self.assertEqual(preview["digest"], preview_references(self.base, docs)["digest"])
        docs["data_dictionary.md"] += "\nReview context changed.\n"
        self.assertNotEqual(preview["digest"], preview_references(self.base, docs)["digest"])
        changed_policy = copy.deepcopy(self.base)
        changed_policy["reports"]["access_grace_days"] = 9
        self.assertNotEqual(preview["digest"], preview_references(changed_policy, compact_documents())["digest"])
        self.assertTrue(preview["policy"]["policy_version"].endswith(preview["digest"][:12]))


if __name__ == "__main__":
    unittest.main()
