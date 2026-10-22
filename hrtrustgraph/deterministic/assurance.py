"""Explainable quality scores and reporting readiness, never truth probabilities."""
from __future__ import annotations


def report_assurance(report, policy):
    population = report["population_count"]
    unresolved = len(report["unresolved"])
    assessed = max(0, population - unresolved)
    available = report["availability"] == "available"
    score = round(100 * assessed / population, 1) if population and available else None
    reasons = []
    if not available:
        reasons.append("Required source data is missing or has schema errors.")
    if not population:
        reasons.append("There are no source cases from which to measure coverage.")
    if unresolved:
        reasons.append(f"{unresolved} of {population} source cases remain unresolved; the confirmed count may be incomplete.")
    approved = policy.get("reports", {}).get("definitions_approved", False) is True
    if not approved:
        reasons.append("Report definitions and authority are provisional and require business-owner confirmation.")
    state = "unavailable" if not available or not population else "review_required" if reasons else "checks_passed"
    if state == "checks_passed":
        reasons.append("All cases were assessed under the configured, confirmed definitions. Publication still requires human sign-off.")
    return {"trust_score": score, "score_kind": "evidence_coverage_not_probability", "score_formula": "100 × assessed source cases / total source cases; unmeasurable when inputs are unavailable or population is empty", "assessed_cases": assessed, "population_count": population, "readiness": state, "readiness_reasons": reasons, "business_definition_confirmed": approved, "publication_approved": False}
