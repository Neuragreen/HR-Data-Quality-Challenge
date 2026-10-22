"""Identity tests target wrong merges, lost evidence and nondeterminism."""

import copy
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from hrtrustgraph.deterministic.ingest import load_snapshot, raw_fingerprint
from hrtrustgraph.deterministic.matching import match_records


def source_policy(filename="core.csv", formats=None):
    return {
        "filename": filename,
        "fields": {
            "source_id": ["ID"], "name": ["Full Name"], "email": ["Email"],
            "birth_date": ["DOB"], "employment_id": ["Assignment"],
            "employment_status": ["Employment"], "account_status": ["Account"],
            "hire_date": ["Hired"], "department": ["Dept"],
            "access_exempt_until": ["Exempt Until"],
        },
        "date_formats": formats or ["%Y-%m-%d"],
        "required": ["source_id", "name"],
        "domains": {"employment_status": ["ACTIVE", "TERMINATED"], "department": ["FIN", "OPS"]},
        "value_maps": {"employment_status": {"A": "ACTIVE", "T": "TERMINATED"},
                       "account_status": {"Y": "ENABLED", "N": "DISABLED"}},
    }


def write_csv(directory, filename, rows, fields=None):
    fields = fields or list(rows[0])
    with (Path(directory) / filename).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def record(record_id, source, source_id, name="Aisha Noor", email="aisha@example.test", dob="1988-04-12", employment=None):
    values = {"name": name, "email": email, "birth_date": dob,
              "employment_id": employment, "department": "FIN", "location": "Dubai"}
    raw = {"source_id": source_id, **values}
    return {"record_id": record_id, "source_system": source, "source_id": source_id,
            "values": values, "raw": raw, "raw_fingerprint": raw_fingerprint(raw), "invalid_fields": {}}


class IngestionTests(unittest.TestCase):
    def test_code_maps_and_domains_ignore_case_spacing_and_unicode_width(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = source_policy()
            policy["fields"].update({"location": ["City"], "payroll_status": ["Pay"]})
            policy["domains"].update({"location": ["DUBAI", "ABU_DHABI"], "payroll_status": ["ELIGIBLE"]})
            policy["value_maps"]["location"] = {"DXB": "DUBAI", "ABU DHABI": "ABU_DHABI"}
            rows = [{"ID": "E-1", "Full Name": " José Noor ", "City": " abu dhabi ", "Pay": "eligible", "Employment": "a", "Account": "y", "Email": "Mixed@Example.Test"},
                    {"ID": "E-2", "Full Name": "Noor", "City": "ｄｘｂ", "Pay": "ELIGIBLE", "Employment": "active", "Account": "N", "Email": "b@example.test"}]
            write_csv(directory, "core.csv", rows)
            loaded = {r["source_id"]: r for r in load_snapshot(directory, {"sources": {"core_hr": policy}}).records}
            self.assertEqual(loaded["E-1"]["values"]["location"], "ABU_DHABI")
            self.assertEqual(loaded["E-2"]["values"]["location"], "DUBAI")
            self.assertEqual(loaded["E-1"]["values"]["payroll_status"], "ELIGIBLE")
            self.assertEqual(loaded["E-2"]["values"]["employment_status"], "ACTIVE")
            self.assertEqual(loaded["E-1"]["values"]["email"], "mixed@example.test")
            self.assertEqual(loaded["E-1"]["values"]["name"], "José Noor")
            self.assertTrue(all(not r["invalid_fields"] for r in loaded.values()))

    def test_dates_and_domains_are_validated_without_discarding_original(self):
        with tempfile.TemporaryDirectory() as directory:
            original = {"ID": "E-8", "Full Name": " Aisha Noor ", "DOB": "1988-04-12",
                        "Hired": "2026-2-03", "Employment": "A", "Account": "Y", "Dept": "UNKNOWN"}
            write_csv(directory, "core.csv", [original])
            snapshot = load_snapshot(directory, {"sources": {"core_hr": source_policy()}})
            row = snapshot.records[0]
            self.assertEqual(row["raw"], original)
            self.assertEqual(row["values"]["name"], "Aisha Noor")
            self.assertEqual(row["values"]["employment_status"], "ACTIVE")
            self.assertEqual(row["values"]["account_status"], "ENABLED")
            self.assertIsNone(row["values"]["hire_date"])
            self.assertEqual(row["invalid_fields"]["hire_date"]["reason"], "invalid_date")
            self.assertIsNone(row["values"]["department"])
            self.assertEqual(row["invalid_fields"]["department"]["raw_value"], "UNKNOWN")
            expected = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            self.assertEqual(row["raw_fingerprint"], expected)

    def test_source_date_formats_and_access_exemption_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            write_csv(directory, "core.csv", [{"ID": "E-1", "Full Name": "A", "Hired": "2026-03-04"}])
            write_csv(directory, "directory.csv", [{"ID": "D-1", "Full Name": "A", "Hired": "04/03/2026", "Exempt Until": "11/10/2026"},
                                                    {"ID": "D-2", "Full Name": "B", "Hired": "04/03/2026", "Exempt Until": "31/31/2026"}])
            policy = {"sources": {"core_hr": source_policy(), "access_directory": source_policy("directory.csv", ["%d/%m/%Y"])}}
            rows = {row["source_id"]: row for row in load_snapshot(directory, policy).records}
            self.assertEqual(rows["E-1"]["values"]["hire_date"], rows["D-1"]["values"]["hire_date"])
            self.assertEqual(rows["D-1"]["values"]["access_exempt_until"], "2026-10-11")
            self.assertIsNone(rows["D-2"]["values"]["access_exempt_until"])
            self.assertIn("access_exempt_until", rows["D-2"]["invalid_fields"])

    def test_missing_optional_columns_do_not_create_schema_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            write_csv(directory, "core.csv", [{"ID": "E-1", "Full Name": "A"}])
            snapshot = load_snapshot(directory, {"sources": {"core_hr": source_policy()}})
            self.assertEqual(snapshot.diagnostics, [])
            self.assertIsNone(snapshot.records[0]["values"]["employment_status"])
            write_csv(directory, "core.csv", [{"ID": "E-1", "Unexpected Name": "A"}])
            snapshot = load_snapshot(directory, {"sources": {"core_hr": source_policy()}})
            self.assertEqual([(d["code"], d.get("field")) for d in snapshot.diagnostics],
                             [("missing_required_field", "name")])

    def test_ambiguous_headers_do_not_choose_arbitrary_value(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = source_policy()
            policy["fields"]["name"] = ["Full Name", "Display Name"]
            write_csv(directory, "core.csv", [{"ID": "E-1", "Full Name": "A", "Display Name": "B"}])
            snapshot = load_snapshot(directory, {"sources": {"core_hr": policy}})
            self.assertIsNone(snapshot.records[0]["values"]["name"])
            self.assertEqual(snapshot.records[0]["invalid_fields"]["name"]["reason"], "ambiguous_columns")
            self.assertEqual(snapshot.diagnostics[0]["code"], "ambiguous_field_mapping")

    def test_field_columns_preserve_normalized_header_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            write_csv(directory, "core.csv", [{" id ": "E-1", "FULL-NAME": ""}])
            snapshot = load_snapshot(directory, {"sources": {"core_hr": source_policy()}})
            row = snapshot.records[0]
            self.assertEqual(row["field_columns"]["source_id"], [" id "])
            self.assertEqual(row["field_columns"]["name"], ["FULL-NAME"])
            self.assertIsNone(row["values"]["name"])
            self.assertEqual(snapshot.diagnostics, [])

    def test_record_multiset_and_logical_snapshot_ignore_row_order(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{"ID": "E-1", "Full Name": "A"}, {"ID": "E-1", "Full Name": "A"}, {"ID": "E-2", "Full Name": "B"}]
            policy = {"sources": {"core_hr": source_policy()}}
            write_csv(directory, "core.csv", rows)
            baseline = load_snapshot(directory, policy)
            write_csv(directory, "core.csv", list(reversed(rows)))
            reordered = load_snapshot(directory, policy)
            self.assertEqual(baseline.snapshot_id, reordered.snapshot_id)
            self.assertEqual(baseline.records, reordered.records)
            self.assertNotEqual(baseline.source_hashes, reordered.source_hashes)
            self.assertEqual(len({row["record_id"] for row in baseline.records}), 3)


class IdentityTests(unittest.TestCase):
    def test_weak_blocks_drop_known_dob_nonmatches_but_retain_missing_dob_candidates(self):
        rows = [record("a", "core_hr", "C-1", email="a@example.test", dob="1980-01-01"),
                record("b", "payroll", "P-1", email="b@example.test", dob="1990-01-01"),
                record("c", "learning", "L-1", email=None, dob=None)]
        result = match_records(rows, {})
        pairs = {(c["record_id_a"], c["record_id_b"]) for c in result.candidates}
        self.assertNotIn(("a", "b"), pairs)
        self.assertIn(("a", "c"), pairs)
        self.assertIn(("b", "c"), pairs)
        self.assertEqual(result.assignments["c"]["status"], "review_required")

    def test_lower_threshold_does_not_turn_name_only_into_accepted_identity(self):
        rows = [record("a", "core_hr", "C-1", email=None, dob=None),
                record("b", "payroll", "P-1", email=None, dob=None)]
        result = match_records(rows, {"matching": {"accept_score": .6, "review_score": .5}})
        self.assertNotEqual(result.assignments["a"]["person_id"], result.assignments["b"]["person_id"])
        self.assertEqual(result.candidates[0]["status"], "review_required")

    def test_email_requires_corroboration_and_birth_date_conflicts_veto(self):
        core = record("core", "core_hr", "C-1")
        unrelated = record("other", "payroll", "P-9", name="Completely Different", dob="1970-01-01")
        result = match_records([core, unrelated], {})
        self.assertNotEqual(result.assignments["core"]["person_id"], result.assignments["other"]["person_id"])
        self.assertEqual(result.candidates[0]["status"], "rejected")
        unrelated["values"]["birth_date"] = None
        result = match_records([core, unrelated], {})
        self.assertEqual(result.candidates[0]["status"], "review_required")
        self.assertEqual(result.assignments["other"]["status"], "review_required")

    def test_name_birth_date_match_can_survive_changed_email_and_ids(self):
        rows = [record("core", "core_hr", "C-17"),
                record("pay", "payroll", "XY-9002", name="NOOR, AISHA", email="changed@example.test")]
        result = match_records(rows, {})
        self.assertEqual(result.assignments["core"]["person_id"], result.assignments["pay"]["person_id"])
        self.assertEqual(result.assignments["pay"]["status"], "linked")
        self.assertEqual(result.candidates[0]["method"], "name_and_birth_date")
        self.assertEqual(result.candidates[0]["score_kind"], "evidence_score_not_probability")

    def test_multiple_employments_and_duplicate_rows_share_person_without_losing_rows(self):
        rows = [record("core_a", "core_hr", "C-1", employment="CORE-A"),
                record("core_b", "core_hr", "C-2", employment="CORE-B"),
                record("pay_a", "payroll", "P-1", employment="PAY-A"),
                record("pay_dup", "payroll", "P-1", employment="PAY-A")]
        result = match_records(rows, {})
        self.assertEqual(len(result.assignments), 4)
        self.assertEqual(len({a["person_id"] for a in result.assignments.values()}), 1)
        self.assertEqual({a["status"] for a in result.assignments.values()}, {"linked"})
        self.assertEqual(rows[0]["values"]["employment_id"], "CORE-A")
        self.assertEqual(rows[1]["values"]["employment_id"], "CORE-B")

    def test_tied_independent_candidates_are_not_forced_into_a_cluster(self):
        rows = [record("core_a", "core_hr", "C-1", dob=None),
                record("core_b", "core_hr", "C-2", dob=None),
                record("pay", "payroll", "P-1", dob=None)]
        result = match_records(rows, {})
        self.assertEqual(len({a["person_id"] for a in result.assignments.values()}), 3)
        self.assertEqual({a["status"] for a in result.assignments.values()}, {"review_required"})
        self.assertFalse(any(candidate["status"] == "accepted" for candidate in result.candidates))

    def test_missing_dob_bridge_does_not_merge_conflicting_birth_dates(self):
        rows = [record("a", "core_hr", "C-1", dob="1980-01-01"),
                record("b", "payroll", "P-1", dob=None),
                record("c", "learning", "L-1", dob="1990-01-01")]
        result = match_records(rows, {})
        self.assertNotEqual(result.assignments["a"]["person_id"], result.assignments["c"]["person_id"])
        by_person = {}
        for row in rows:
            by_person.setdefault(result.assignments[row["record_id"]]["person_id"], set()).add(row["values"]["birth_date"])
        self.assertTrue(all(len(dates - {None}) <= 1 for dates in by_person.values()))
        self.assertTrue(any("Cluster-level" in " ".join(candidate["evidence"]) for candidate in result.candidates))

    def test_source_numeric_suffixes_are_never_identity_evidence(self):
        rows = [record("core", "core_hr", "CH-00123", name="A Person", email=None, dob=None),
                record("pay", "payroll", "PY-123", name="Different Person", email=None, dob=None)]
        result = match_records(rows, {})
        self.assertEqual(len(result.assignments), 2)
        self.assertNotEqual(result.assignments["core"]["person_id"], result.assignments["pay"]["person_id"])
        self.assertEqual({a["status"] for a in result.assignments.values()}, {"single_source"})

    def test_core_anchor_survives_row_reorder_and_unrelated_raw_content_change(self):
        rows = [record("old_record_hash", "core_hr", "C-17"), record("p", "payroll", "P-99")]
        original = copy.deepcopy(rows)
        result = match_records(rows, {})
        reordered = match_records(list(reversed(rows)), {})
        self.assertEqual(result, reordered)
        self.assertEqual(rows, original)
        rows[0]["record_id"] = "new_record_hash"
        rows[0]["raw"]["unrelated_note"] = "New note"
        updated = match_records(rows, {})
        self.assertEqual(result.assignments["old_record_hash"]["person_id"], updated.assignments["new_record_hash"]["person_id"])

    def test_unicode_name_is_not_stripped_to_empty(self):
        rows = [record("a", "core_hr", "C-1", name="عائشة نور"),
                record("b", "payroll", "P-1", name="عائشة نور")]
        result = match_records(rows, {})
        self.assertEqual(result.assignments["a"]["person_id"], result.assignments["b"]["person_id"])
        self.assertEqual(result.assignments["a"]["status"], "linked")


if __name__ == "__main__":
    unittest.main()
