"""Generator labels and evaluator math are independent of detection code."""
import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta

import tempfile
import unittest
from pathlib import Path

from hrtrustgraph.deterministic.evaluation import evaluate_analysis, evaluate_issues, evaluate_matching
from hrtrustgraph.deterministic.synthetic import HEADERS, SYSTEMS, fingerprint, generate_pack


def rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def check_seeded_generation_is_reproducible_and_truth_is_separate(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    a = generate_pack(first, n=120, seed=47)
    b = generate_pack(second, n=120, seed=47)
    assert a == b
    assert a["as_of"] == "2026-10-01"
    assert a["source_rows"]["core_hr"] > 120  # correct employment history exists
    for system in SYSTEMS:
        assert (first / "input" / f"{system}.csv").read_bytes() == (second / "input" / f"{system}.csv").read_bytes()
        source_rows = rows(first / "input" / f"{system}.csv")
        assert set(source_rows[0]) == set(HEADERS[system])
        assert not any("TRUTH-" in str(row) for row in source_rows)
    assert not (first / "input" / "identity.csv").exists()
    assert not (first / "input" / "issues.csv").exists()
    different = generate_pack(tmp_path / "different", n=120, seed=48)
    assert different["input_sha256"] != a["input_sha256"]


def check_truth_record_keys_match_untouched_source_string_rows(tmp_path):
    generate_pack(tmp_path, n=120, seed=89)
    truth = {row["record_id"]: row for row in rows(tmp_path / "truth" / "identity.csv")}
    for system in SYSTEMS:
        occurrence = Counter()
        for raw in rows(tmp_path / "input" / f"{system}.csv"):
            digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
            assert fingerprint(raw) == digest
            occurrence[digest] += 1
            assert f"{system}:{digest[:20]}:{occurrence[digest]}" in truth
    labelled = rows(tmp_path / "truth" / "issues.csv")
    assert all(row["record_id"] in truth for row in labelled)
    kinds = {row["issue_type"] for row in labelled}
    assert {"missing_value", "invalid_code", "invalid_date", "cross_system_conflict", "duplicate_identifier", "possible_ghost_access", "temporal_inconsistency", "out_of_date_record"} <= kinds


def check_contingency_pair_evaluation_matches_a_small_manual_partition():
    identity = [{"record_id": "a", "person_id": "x", "source_system": "core_hr", "source_id": "1"},
                {"record_id": "b", "person_id": "x", "source_system": "payroll", "source_id": "2"},
                {"record_id": "c", "person_id": "y", "source_system": "core_hr", "source_id": "3"},
                {"record_id": "d", "person_id": "y", "source_system": "learning", "source_id": "4"}]
    prediction = [{"record_id": "a", "person_id": "p"}, {"record_id": "b", "person_id": "p"},
                  {"record_id": "c", "person_id": "p"}, {"record_id": "d", "person_id": "q"}]
    result = evaluate_matching(prediction, identity)
    assert result["all_record_pairs"]["true_positive"] == 1
    assert result["all_record_pairs"]["false_positive"] == 2
    assert result["all_record_pairs"]["false_negative"] == 1
    assert result["cross_system_pairs"]["predicted"] == 2
    assert result["cross_system_pairs"]["true_positive"] == 1


def check_multiset_issue_metrics_and_correction_abstention_are_separate():
    identity = [{"record_id": "a", "person_id": "p", "source_system": "core_hr", "source_id": "1"}]
    issue = {"record_id": "a", "source_system": "core_hr", "field": "department", "issue_type": "missing_value"}
    expected = [{**issue, "expected_value": "IT-01", "suggestion_expected": "true"}]
    result = evaluate_issues([issue, issue], expected, identity)
    assert result["overall"]["true_positive"] == 1
    assert result["overall"]["false_positive"] == 1
    assert result["corrections"]["matched_issues_with_abstention"] == 1
    assert result["corrections"]["suggestion_precision"] is None
    assert result["corrections"]["end_to_end_correct_correction_coverage"] == 0
    corrected = evaluate_issues([{**issue, "suggested_value": "IT-01"}], expected, identity)
    assert corrected["corrections"]["suggestion_precision"] == 1


def check_generated_truth_self_evaluates_as_expected_without_detector(tmp_path):
    generate_pack(tmp_path / "pack", n=80, seed=11)
    identity = rows(tmp_path / "pack" / "truth" / "identity.csv")
    issues = rows(tmp_path / "pack" / "truth" / "issues.csv")
    perfect_matches = evaluate_matching(identity, identity)
    assert perfect_matches["all_record_pairs"]["f1"] == 1
    perfect_issues = evaluate_issues([{**row, "suggested_value": row["expected_value"]} for row in issues], issues, identity)
    assert perfect_issues["overall"]["f1"] == 1
    assert perfect_issues["corrections"]["suggestion_precision"] == 1
    output = tmp_path / "oracle_output"
    output.mkdir()
    for filename, records in (("employees.csv", identity), ("issues.csv", [{**row, "suggested_value": row["expected_value"]} for row in issues])):
        with (output / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    report = evaluate_analysis(output, tmp_path / "pack" / "truth", tmp_path / "report.json")
    assert report["issues"]["overall"]["f1"] == 1
    assert json.loads((tmp_path / "report.json").read_text())["matching"]["record_coverage"] == 1
    # This is an evaluator unit test, not a claim of detector accuracy.


def check_unknown_records_do_not_gain_true_pairs_or_cross_system_pairs():
    identity = [{"record_id": "a", "person_id": "true", "source_system": "core_hr", "source_id": "1"}]
    predicted = [{"record_id": "a", "person_id": "p", "source_system": "core_hr"},
                 {"record_id": "unknown", "person_id": "p", "source_system": "core_hr"}]
    result = evaluate_matching(predicted, identity)
    assert result["all_record_pairs"]["false_positive"] == 1
    assert result["cross_system_pairs"]["predicted"] == 0
    assert result["unknown_predicted_records"] == 1


def check_source_presentations_and_effective_interval_semantics(tmp_path):
    generate_pack(tmp_path, n=120, seed=54)
    payroll = rows(tmp_path / "input" / "payroll.csv")
    learning = rows(tmp_path / "input" / "learning.csv")
    core = rows(tmp_path / "input" / "core_hr.csv")
    # Valid presentation differences are independent of planted corruption.
    assert all("/" in row["updated_at"] for row in payroll)
    assert all(datetime.strptime(row["updated_at"], "%d-%b-%Y") for row in learning)
    for row in core:
        if row["termination_date"]:
            assert date.fromisoformat(row["effective_to"]) == date.fromisoformat(row["termination_date"]) + timedelta(days=1)
        assert date.fromisoformat(row["birth_date"]) < date.fromisoformat(row["hire_date"]) - timedelta(days=18 * 365) if row["birth_date"] else True
    labelled = rows(tmp_path / "truth" / "issues.csv")
    invalid_dates = [row for row in labelled if row["issue_type"] == "invalid_date"]
    assert invalid_dates
    assert all(date.fromisoformat(row["expected_value"]) for row in invalid_dates)


def check_profiles_and_inputs_are_validated(tmp_path):
    with unittest.TestCase().assertRaises(ValueError):
        generate_pack(tmp_path, n=0)
    with unittest.TestCase().assertRaises(ValueError):
        generate_pack(tmp_path, n=5, profile="unknown")
    with unittest.TestCase().assertRaises(ValueError):
        generate_pack(tmp_path, n=5, as_of="not-a-date")
    a = generate_pack(tmp_path / "dev", n=25, seed=9, profile="development")
    b = generate_pack(tmp_path / "val", n=25, seed=9, profile="validation")
    assert a["input_sha256"] != b["input_sha256"]


class SyntheticCoreTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name)

    def test_seeded_generation(self):
        check_seeded_generation_is_reproducible_and_truth_is_separate(self.path)

    def test_record_keys(self):
        check_truth_record_keys_match_untouched_source_string_rows(self.path)

    def test_pair_metrics(self):
        check_contingency_pair_evaluation_matches_a_small_manual_partition()

    def test_corrections_and_multisets(self):
        check_multiset_issue_metrics_and_correction_abstention_are_separate()

    def test_evaluator_oracle(self):
        check_generated_truth_self_evaluates_as_expected_without_detector(self.path)

    def test_validation(self):
        check_profiles_and_inputs_are_validated(self.path)

    def test_unknown_records(self):
        check_unknown_records_do_not_gain_true_pairs_or_cross_system_pairs()

    def test_presentations_and_intervals(self):
        check_source_presentations_and_effective_interval_semantics(self.path)

    def test_existing_pack_is_preserved_without_explicit_overwrite(self):
        generated = generate_pack(self.path, n=30, seed=88)
        before = (self.path / "input" / "core_hr.csv").read_bytes()
        with self.assertRaises(FileExistsError):
            generate_pack(self.path, n=40, seed=89)
        self.assertEqual((self.path / "input" / "core_hr.csv").read_bytes(), before)
        self.assertTrue(generated["generator_version"])
        self.assertIn("issues.csv", generated["truth_sha256"])

    def test_pack_references_describe_nullable_dates_and_executable_payroll_dependencies(self):
        generate_pack(self.path, n=20, seed=88)
        dictionary = (self.path / "input" / "data_dictionary.md").read_text()
        dependencies = (self.path / "input" / "dependencies.md").read_text()
        self.assertIn("active employments can have no termination date", dictionary)
        self.assertNotIn("Empty means unknown", dictionary)
        self.assertIn("core_hr.department -> payroll.dept", dependencies)
        self.assertIn("payroll.department -> Payroll Reconciliation Report", dependencies)
        self.assertIn("core_hr.effective_to -> Dubai Active Headcount Report", dependencies)


if __name__ == "__main__":
    unittest.main()
