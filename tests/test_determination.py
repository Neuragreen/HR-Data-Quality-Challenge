"""Independent behavioral checks for the deterministic analysis engine.

Fixtures declare identity explicitly so these tests isolate determination and
reporting from the matcher. They contain no real employee information.
"""
from __future__ import annotations

import copy
import unittest

from hrtrustgraph.deterministic.models import MatchResult, Snapshot
from hrtrustgraph.deterministic.policy import load_policy
from hrtrustgraph.deterministic.reports import calculate_reports
from hrtrustgraph.deterministic.rules import detect_issues, resolve_fields
from hrtrustgraph.deterministic.scenario import simulate_patch


AS_OF = "2026-10-01"


def observation(source: str, source_id: str, **overrides) -> dict:
    values = {
        "name": "Example Employee",
        "email": "example.employee@example.test",
        "birth_date": "1990-05-12",
        "employment_id": "E-1" if source != "access_directory" else None,
        "department": "ENG-01" if source != "access_directory" else None,
        "job_code": "ENGINEER" if source != "access_directory" else None,
        "employment_status": "ACTIVE" if source == "core_hr" else None,
        "payroll_status": "ELIGIBLE" if source == "payroll" else None,
        "account_status": "ENABLED" if source == "access_directory" else None,
        "location": "DUBAI",
        "hire_date": "2020-01-01" if source != "access_directory" else None,
        "termination_date": None,
        "effective_from": "2020-01-01" if source == "core_hr" else None,
        "effective_to": None,
        "updated_at": "2026-09-30",
        "is_primary": "true" if source == "core_hr" else None,
    }
    values.update(overrides)
    return {
        "record_id": f"{source}:{source_id}",
        "source_system": source,
        "source_id": source_id,
        "raw": {key: value or "" for key, value in values.items()},
        "values": values,
        "invalid_fields": {},
    }


def fixture(*records: dict) -> tuple[Snapshot, MatchResult]:
    snapshot = Snapshot(
        snapshot_id="independent-test-snapshot",
        records=list(records),
        diagnostics=[],
        source_hashes={},
    )
    matches = MatchResult(
        assignments={
            row["record_id"]: {
                "person_id": "PERSON-1",
                "status": "linked",
                "score": 0.99,
                "evidence": ["Identity established by test fixture"],
            }
            for row in records
        },
        candidates=[],
    )
    return snapshot, matches


def count(reports: dict, key: str) -> int:
    result = reports[key]
    return result["value"] if "value" in result else result["count"]


class DeterminationBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def reports(self, *records: dict) -> dict:
        snapshot, matches = fixture(*records)
        return calculate_reports(snapshot, matches, self.policy, AS_OF)

    def test_duplicate_observations_do_not_inflate_headcount(self):
        first = observation("core_hr", "C-1")
        duplicate = observation("core_hr", "C-1-copy")
        self.assertEqual(count(self.reports(first, duplicate), "active_headcount_dubai"), 1)

    def test_future_hire_does_not_count_as_active(self):
        future = observation(
            "core_hr", "C-future", hire_date="2026-11-01", effective_from="2026-11-01"
        )
        self.assertEqual(count(self.reports(future), "active_headcount_dubai"), 0)

    def test_an_active_concurrent_employment_prevents_leaver_exception(self):
        old = observation(
            "core_hr", "C-old", employment_id="E-old", employment_status="TERMINATED",
            termination_date="2025-01-01", effective_to="2025-01-02", is_primary="false",
        )
        current = observation(
            "core_hr", "C-new", employment_id="E-new", hire_date="2025-05-01",
            effective_from="2025-05-01",
        )
        directory = observation("access_directory", "A-1")
        reports = self.reports(old, current, directory)
        self.assertEqual(count(reports, "active_headcount_dubai"), 1)
        self.assertEqual(count(reports, "leaver_enabled_accounts"), 0)

    def test_future_termination_is_not_a_current_leaver(self):
        core = observation("core_hr", "C-1", termination_date="2026-11-01")
        directory = observation("access_directory", "A-1")
        self.assertEqual(count(self.reports(core, directory), "leaver_enabled_accounts"), 0)

    def test_ended_employment_with_enabled_account_is_an_exception(self):
        core = observation(
            "core_hr", "C-1", employment_status="TERMINATED", termination_date="2026-01-01"
        )
        directory = observation("access_directory", "A-1")
        reports = self.reports(core, directory)
        self.assertEqual(count(reports, "leaver_enabled_accounts"), 1)
        self.assertEqual(count(reports, "active_headcount_dubai"), 0)

    def test_disabled_account_is_not_a_leaver_exception(self):
        core = observation(
            "core_hr", "C-1", employment_status="TERMINATED", termination_date="2026-01-01"
        )
        directory = observation("access_directory", "A-1", account_status="DISABLED")
        self.assertEqual(count(self.reports(core, directory), "leaver_enabled_accounts"), 0)

    def test_missing_authoritative_hire_date_remains_unresolved(self):
        reports = self.reports(observation("core_hr", "C-1", hire_date=None))
        self.assertEqual(count(reports, "active_headcount_dubai"), 0)
        self.assertTrue(reports["active_headcount_dubai"]["unresolved"])

    def test_invalid_assignment_effective_date_remains_unresolved(self):
        core = observation("core_hr", "C-1", effective_from=None)
        core["invalid_fields"]["effective_from"] = {
            "reason": "invalid_date", "raw_value": "not-a-date"
        }
        reports = self.reports(core)
        self.assertEqual(count(reports, "active_headcount_dubai"), 0)
        self.assertTrue(reports["active_headcount_dubai"]["unresolved"])

    def test_reversed_assignment_period_remains_unresolved(self):
        core = observation(
            "core_hr", "C-1", effective_from="2026-09-01", effective_to="2026-08-01"
        )
        reports = self.reports(core)
        self.assertEqual(count(reports, "active_headcount_dubai"), 0)
        self.assertTrue(reports["active_headcount_dubai"]["unresolved"])

    def test_duplicate_rows_for_one_directory_account_do_not_count_twice(self):
        core = observation(
            "core_hr", "C-1", employment_status="TERMINATED", termination_date="2026-01-01"
        )
        directory = observation("access_directory", "A-1")
        duplicate = copy.deepcopy(directory)
        duplicate["record_id"] = "access_directory:A-1-duplicate-row"
        reports = self.reports(core, directory, duplicate)
        self.assertLessEqual(count(reports, "leaver_enabled_accounts"), 1)

    def test_uncertain_identity_is_visible_in_unresolved_report_cases(self):
        snapshot, matches = fixture(observation("core_hr", "C-1"))
        matches.assignments["core_hr:C-1"]["status"] = "review_required"
        reports = calculate_reports(snapshot, matches, self.policy, AS_OF)
        self.assertEqual(count(reports, "active_headcount_dubai"), 0)
        self.assertTrue(reports["active_headcount_dubai"]["unresolved"])

    def test_missing_core_source_makes_report_unavailable(self):
        snapshot, matches = fixture(observation("payroll", "P-1"))
        snapshot.diagnostics.append({"source_system": "core_hr", "code": "missing_source", "severity": "error"})
        reports = calculate_reports(snapshot, matches, self.policy, AS_OF)
        self.assertEqual(reports["active_headcount_dubai"]["availability"], "unavailable")
        self.assertEqual(reports["leaver_enabled_accounts"]["availability"], "unavailable")

    def test_report_calculation_does_not_change_input(self):
        snapshot, matches = fixture(observation("core_hr", "C-1"))
        before = copy.deepcopy(snapshot)
        calculate_reports(snapshot, matches, self.policy, AS_OF)
        self.assertEqual(snapshot, before)

    def test_system_specific_statuses_are_not_compared_as_one_field(self):
        snapshot, matches = fixture(
            observation("core_hr", "C-1"),
            observation("payroll", "P-1"),
            observation("access_directory", "A-1"),
        )
        resolved = resolve_fields(snapshot, matches, self.policy, AS_OF)
        issues = detect_issues(snapshot, matches, resolved, self.policy, AS_OF)
        status_conflicts = [
            item for item in issues
            if "conflict" in item.get("issue_type", "")
            and item.get("field") in {"status", "employment_status", "payroll_status", "account_status"}
        ]
        self.assertEqual(status_conflicts, [])

    def test_employee_id_can_repeat_across_configured_employment_grain(self):
        self.policy["sources"]["core_hr"]["identifier_scope_fields"] = ["employment_id"]
        first = observation("core_hr", "C-1", employment_id="E-1")
        second = observation("core_hr", "C-2", employment_id="E-2")
        second["source_id"] = first["source_id"]
        snapshot, matches = fixture(first, second)
        resolved = resolve_fields(snapshot, matches, self.policy, AS_OF)
        issues = detect_issues(snapshot, matches, resolved, self.policy, AS_OF)
        self.assertFalse(any(item["issue_type"] == "duplicate_identifier" for item in issues))

    def test_same_hire_date_does_not_select_between_concurrent_payroll_employments(self):
        core = observation("core_hr", "C-1", employment_id="CORE-employment")
        payroll_a = observation("payroll", "P-1", employment_id="PAY-employment-A")
        payroll_b = observation(
            "payroll", "P-2", employment_id="PAY-employment-B",
            department="FIN-01", job_code="ANALYST",
        )
        snapshot, matches = fixture(core, payroll_a, payroll_b)
        resolved = resolve_fields(snapshot, matches, self.policy, AS_OF)
        for payroll in (payroll_a, payroll_b):
            source_resolutions = [
                item for item in resolved
                if payroll["record_id"] in item["observation_ids"]
                and item["field"] in {"department", "job_code"}
            ]
            self.assertTrue(source_resolutions)
            self.assertTrue(all(item["status"] == "review_required" for item in source_resolutions))
        issues = detect_issues(snapshot, matches, resolved, self.policy, AS_OF)
        unsafe_fixes = [
            item for item in issues
            if item["source_system"] == "payroll" and item["field"] in {"department", "job_code"}
            and item.get("suggested_value") is not None
        ]
        self.assertEqual(unsafe_fixes, [])

    def test_explicitly_nonprimary_assignment_does_not_define_primary_headcount(self):
        reports = self.reports(observation("core_hr", "C-secondary", is_primary="false"))
        self.assertEqual(count(reports, "active_headcount_dubai"), 0)
        self.assertTrue(reports["active_headcount_dubai"]["unresolved"])

    def test_person_grain_learning_job_is_not_overwritten_from_nonprimary_assignment(self):
        snapshot, matches = fixture(
            observation("core_hr", "C-secondary", is_primary="false"),
            observation(
                "learning", "L-person", employment_id=None, hire_date=None,
                department="FIN-01", job_code="ANALYST",
            ),
        )
        resolved = resolve_fields(snapshot, matches, self.policy, AS_OF)
        learning_fields = [
            item for item in resolved
            if "learning:L-person" in item["observation_ids"]
            and item["field"] in {"department", "job_code"}
        ]
        self.assertTrue(learning_fields)
        self.assertTrue(all(item["status"] == "review_required" for item in learning_fields))
        issues = detect_issues(snapshot, matches, resolved, self.policy, AS_OF)
        self.assertFalse(any(
            item["source_system"] == "learning" and item.get("suggested_value") is not None
            for item in issues
        ))

    def test_repeated_identifier_within_same_configured_grain_is_flagged(self):
        self.policy["sources"]["core_hr"]["identifier_scope_fields"] = ["employment_id"]
        first = observation("core_hr", "C-1", employment_id="E-1")
        duplicate = observation("core_hr", "C-2", employment_id="E-1")
        duplicate["source_id"] = first["source_id"]
        snapshot, matches = fixture(first, duplicate)
        resolved = resolve_fields(snapshot, matches, self.policy, AS_OF)
        issues = detect_issues(snapshot, matches, resolved, self.policy, AS_OF)
        self.assertTrue(any(item["issue_type"] == "duplicate_identifier" for item in issues))

    def test_invalid_authoritative_department_does_not_copy_downstream_value(self):
        core = observation("core_hr", "C-1", department=None)
        core["invalid_fields"]["department"] = {
            "reason": "invalid_code", "raw_value": "UNKNOWN-DEPARTMENT"
        }
        snapshot, matches = fixture(core, observation("payroll", "P-1"))
        resolved = resolve_fields(snapshot, matches, self.policy, AS_OF)
        departments = [item for item in resolved if item["field"] == "department"]
        self.assertTrue(departments)
        self.assertTrue(all(item["status"] != "resolved" for item in departments))
        self.assertTrue(all(item.get("value") is None for item in departments))

    def test_authoritative_contradiction_requires_review(self):
        snapshot, matches = fixture(
            observation("core_hr", "C-1", department="ENG-01"),
            observation("core_hr", "C-2", department="FIN-01"),
        )
        resolved = resolve_fields(snapshot, matches, self.policy, AS_OF)
        departments = [item for item in resolved if item["field"] == "department"]
        self.assertTrue(departments)
        self.assertTrue(all(item["status"] != "resolved" for item in departments))

    def test_impossible_authoritative_timeline_cannot_supply_date_fix(self):
        snapshot, matches = fixture(
            observation("core_hr", "C-1", termination_date="2019-01-01"),
            observation("payroll", "P-1", termination_date="2026-01-01"),
        )
        resolved = resolve_fields(snapshot, matches, self.policy, AS_OF)
        end_dates = [item for item in resolved if item["field"] == "termination_date"]
        self.assertTrue(end_dates)
        self.assertTrue(all(item["status"] != "resolved" for item in end_dates))
        issues = detect_issues(snapshot, matches, resolved, self.policy, AS_OF)
        unsafe = [
            item for item in issues
            if item["source_system"] == "payroll" and item["field"] == "termination_date"
            and item.get("suggested_value") == "2019-01-01"
        ]
        self.assertEqual(unsafe, [])

    def test_disabling_one_account_changes_only_access_report(self):
        snapshot, matches = fixture(
            observation("core_hr", "C-1", employment_status="TERMINATED", termination_date="2026-01-01"),
            observation("access_directory", "A-1"),
        )
        before = copy.deepcopy(snapshot)
        result = simulate_patch(snapshot, matches, self.policy, AS_OF, {
            "record_id": "access_directory:A-1", "field": "account_status",
            "expected_value": "ENABLED", "value": "DISABLED",
        })
        self.assertEqual(result["reports"]["leaver_enabled_accounts"]["before"], 1)
        self.assertEqual(result["reports"]["leaver_enabled_accounts"]["after"], 0)
        self.assertEqual(result["reports"]["leaver_enabled_accounts"]["delta"], -1)
        self.assertEqual(result["reports"]["active_headcount_dubai"]["delta"], 0)
        self.assertEqual(snapshot, before)
        self.assertFalse(result["source_files_changed"])

    def test_unrelated_department_fix_has_zero_report_delta(self):
        snapshot, matches = fixture(observation("core_hr", "C-1"))
        result = simulate_patch(snapshot, matches, self.policy, AS_OF, {
            "record_id": "core_hr:C-1", "field": "department",
            "expected_value": "ENG-01", "value": "FIN-01",
        })
        self.assertTrue(all(item["delta"] == 0 for item in result["reports"].values()))

    def test_stale_expected_value_is_rejected(self):
        snapshot, matches = fixture(observation("access_directory", "A-1"))
        with self.assertRaises(ValueError):
            simulate_patch(snapshot, matches, self.policy, AS_OF, {
                "record_id": "access_directory:A-1", "field": "account_status",
                "expected_value": "DISABLED", "value": "ENABLED",
            })

    def test_out_of_domain_scenario_value_is_rejected(self):
        snapshot, matches = fixture(observation("access_directory", "A-1"))
        with self.assertRaises(ValueError):
            simulate_patch(snapshot, matches, self.policy, AS_OF, {
                "record_id": "access_directory:A-1", "field": "account_status",
                "expected_value": "ENABLED", "value": "UNRECOGNISED-STATE",
            })

    def test_identity_changes_require_a_separate_review(self):
        snapshot, matches = fixture(observation("core_hr", "C-1"))
        with self.assertRaises(ValueError):
            simulate_patch(snapshot, matches, self.policy, AS_OF, {
                "record_id": "core_hr:C-1", "field": "email",
                "expected_value": "example.employee@example.test", "value": "another@example.test",
            })


if __name__ == "__main__":
    unittest.main()
