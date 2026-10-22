"""Acceptance checks for the challenge's observable user workflows."""
import copy
import unittest

from hrtrustgraph.deterministic.policy import load_policy
from hrtrustgraph.deterministic.prioritization import rank_issues
from hrtrustgraph.deterministic.questions import answer_question
from hrtrustgraph.deterministic.reports import calculate_reports
from hrtrustgraph.deterministic.rules import detect_issues, field_trust, resolve_fields
from hrtrustgraph.deterministic.scenario import simulate_patch
from tests.test_determination import AS_OF, fixture, observation


class ChallengeRequirementsTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def issues(self, snapshot, matches):
        return detect_issues(snapshot, matches, resolve_fields(snapshot, matches, self.policy, AS_OF), self.policy, AS_OF)

    def test_different_learning_ids_are_duplicate_profiles_with_evidence_and_no_unsafe_fix(self):
        snapshot, matches = fixture(observation("core_hr", "C"), observation("learning", "L-one"), observation("learning", "L-two"))
        before = copy.deepcopy(snapshot)
        duplicates = [i for i in self.issues(snapshot, matches) if i["issue_type"] == "duplicate_profile"]
        self.assertEqual({i["source_id"] for i in duplicates}, {"L-one", "L-two"})
        self.assertTrue(all(len(i["evidence"]["source_record_ids"]) == 2 for i in duplicates))
        self.assertTrue(all(i["suggested_value"] is None for i in duplicates))
        self.assertEqual(snapshot, before)

    def test_same_employment_and_effective_date_under_different_ids_requires_duplicate_review(self):
        snapshot, matches = fixture(observation("core_hr", "C-one"), observation("core_hr", "C-two"))
        self.assertEqual(len([i for i in self.issues(snapshot, matches) if i["issue_type"] == "duplicate_profile"]), 2)

    def test_history_and_concurrent_employments_are_not_duplicate_profiles(self):
        snapshot, matches = fixture(observation("core_hr", "C-primary"), observation("core_hr", "C-secondary", employment_id="E-two", is_primary="false"), observation("core_hr", "C-history", effective_from="2019-01-01", effective_to="2020-01-01"))
        self.assertFalse(any(i["issue_type"] == "duplicate_profile" for i in self.issues(snapshot, matches)))

    def test_two_directory_accounts_are_legitimate(self):
        snapshot, matches = fixture(observation("core_hr", "C"), observation("access_directory", "D-one"), observation("access_directory", "D-two"))
        self.assertFalse(any(i["issue_type"] == "duplicate_profile" for i in self.issues(snapshot, matches)))

    def test_ambiguous_identity_does_not_establish_a_duplicate_profile(self):
        snapshot, matches = fixture(observation("learning", "L-one"), observation("learning", "L-two"))
        matches.assignments["learning:L-two"]["status"] = "review_required"
        self.assertFalse(any(i["issue_type"] == "duplicate_profile" for i in self.issues(snapshot, matches)))

    def test_payroll_fix_changes_reconciliation_without_changing_headcount(self):
        snapshot, matches = fixture(observation("core_hr", "C"), observation("payroll", "P", department="FIN-01"))
        before = copy.deepcopy(snapshot)
        reports = calculate_reports(snapshot, matches, self.policy, AS_OF)
        self.assertEqual(reports["payroll_reconciliation"]["value"], 1)
        self.assertEqual(reports["payroll_reconciliation"]["cases"][0]["mismatched_fields"], ["department"])
        effect = simulate_patch(snapshot, matches, self.policy, AS_OF, {"record_id": "payroll:P", "field": "department", "expected_value": "FIN-01", "value": "ENG-01"})
        self.assertEqual(effect["reports"]["payroll_reconciliation"]["after"], 0)
        self.assertEqual(effect["reports"]["active_headcount_dubai"]["delta"], 0)
        self.assertIn("payroll_reconciliation", effect["coverage"]["calculated_reports"])
        self.assertFalse(effect["source_files_changed"])
        self.assertEqual(snapshot, before)

    def test_unknown_authority_is_unresolved_in_payroll_report(self):
        snapshot, matches = fixture(observation("core_hr", "C", department=None), observation("payroll", "P"))
        report = calculate_reports(snapshot, matches, self.policy, AS_OF)["payroll_reconciliation"]
        self.assertEqual(report["value"], 0)
        self.assertEqual(len(report["unresolved"]), 1)
        self.assertEqual(report["assurance"]["readiness"], "review_required")

    def test_input_availability_is_distinct_from_readiness(self):
        snapshot, matches = fixture(observation("core_hr", "C"))
        report = calculate_reports(snapshot, matches, self.policy, AS_OF)["active_headcount_dubai"]
        self.assertEqual(report["availability"], "available")
        self.assertEqual(report["assurance"]["trust_score"], 100)
        self.assertEqual(report["assurance"]["readiness"], "review_required")
        self.assertFalse(report["assurance"]["publication_approved"])

    def test_unresolved_cases_reduce_evidence_coverage_even_with_confirmed_definitions(self):
        self.policy["reports"]["definitions_approved"] = True
        snapshot, matches = fixture(observation("core_hr", "C", hire_date=None))
        report = calculate_reports(snapshot, matches, self.policy, AS_OF)["active_headcount_dubai"]
        self.assertEqual(report["assurance"]["trust_score"], 0)
        self.assertEqual(report["assurance"]["readiness"], "review_required")

    def test_confirmed_complete_definitions_pass_checks_but_never_auto_approve_publication(self):
        self.policy["reports"]["definitions_approved"] = True
        snapshot, matches = fixture(observation("core_hr", "C"))
        report = calculate_reports(snapshot, matches, self.policy, AS_OF)["active_headcount_dubai"]
        self.assertEqual(report["assurance"]["readiness"], "checks_passed")
        self.assertFalse(report["assurance"]["publication_approved"])

    def test_missing_source_or_empty_population_has_no_invented_trust_score(self):
        snapshot, matches = fixture(observation("learning", "L"))
        reports = calculate_reports(snapshot, matches, self.policy, AS_OF)
        self.assertIsNone(reports["active_headcount_dubai"]["assurance"]["trust_score"])
        self.assertIsNone(reports["leaver_enabled_accounts"]["assurance"]["trust_score"])

    def test_fields_expose_a_formula_and_quality_score(self):
        snapshot, matches = fixture(observation("core_hr", "C-one"), observation("core_hr", "C-two", department=None))
        scores = field_trust(snapshot, self.issues(snapshot, matches), self.policy)
        department = next(r for r in scores if r["source_system"] == "core_hr" and r["field"] == "department")
        self.assertEqual(department["completeness"], 0.5)
        self.assertEqual(department["trust_score"], 50)
        self.assertIn("minimum", department["score_formula"])

    def test_optional_open_ended_dates_are_not_marked_untrustworthy_for_legitimate_blanks(self):
        snapshot, matches = fixture(observation("core_hr", "C"))
        scores = field_trust(snapshot, self.issues(snapshot, matches), self.policy)
        termination = next(r for r in scores if r["field"] == "termination_date")
        self.assertFalse(termination["completeness_required"])
        self.assertEqual(termination["completeness"], 0)
        self.assertIsNone(termination["trust_score"])

    def test_ranking_measurement_matches_full_snapshot_calculation_including_shared_id_peers(self):
        core, payroll, other_core, other_pay = observation("core_hr", "C"), observation("payroll", "P", department="FIN-01"), observation("core_hr", "C-other"), observation("payroll", "P-other")
        other_pay["source_id"] = payroll["source_id"]
        snapshot, matches = fixture(core, payroll, other_core, other_pay)
        matches.assignments[other_core["record_id"]]["person_id"] = "PERSON-2"
        matches.assignments[other_pay["record_id"]]["person_id"] = "PERSON-2"
        reports = calculate_reports(snapshot, matches, self.policy, AS_OF)
        issues = rank_issues(snapshot, matches, self.policy, AS_OF, self.issues(snapshot, matches), reports)
        issue = next(i for i in issues if i["record_id"] == payroll["record_id"] and i["field"] == "department")
        full = simulate_patch(snapshot, matches, self.policy, AS_OF, {"record_id": payroll["record_id"], "field": "department", "expected_value": "FIN-01", "value": "ENG-01"})
        for key, effect in full["reports"].items():
            measured = issue["measured_impact"]["reports"][key]
            self.assertEqual(measured["delta"], effect["delta"], key)
            self.assertEqual(measured["unresolved_after"], effect["unresolved_after"], key)
        self.assertEqual(full["reports"]["payroll_reconciliation"]["delta"], 0)

    def test_measured_payroll_change_increases_priority_and_discloses_the_basis(self):
        snapshot, matches = fixture(observation("core_hr", "C"), observation("payroll", "P", department="FIN-01"))
        reports = calculate_reports(snapshot, matches, self.policy, AS_OF)
        ranked = rank_issues(snapshot, matches, self.policy, AS_OF, self.issues(snapshot, matches), reports)
        issue = next(i for i in ranked if i["source_system"] == "payroll" and i["field"] == "department")
        self.assertEqual(issue["measured_impact"]["reports"]["payroll_reconciliation"]["delta"], -1)
        self.assertGreater(issue["priority_score"], issue["priority_base_score"])
        self.assertIn("payroll_reconciliation", issue["priority_reasons"][-1])

    def test_question_answers_reconciliation_with_sources_readiness_and_no_ai(self):
        snapshot, matches = fixture(observation("core_hr", "C"), observation("payroll", "P", department="FIN-01"))
        answer = answer_question(calculate_reports(snapshot, matches, self.policy, AS_OF), "How many payroll profiles have conflicts?")
        self.assertEqual(answer["answer"], 1)
        self.assertEqual(answer["sources"], ["core_hr", "payroll"])
        self.assertIn("readiness", answer["assurance"])
        self.assertFalse(answer["language_model_used"])


if __name__ == "__main__":
    unittest.main()
