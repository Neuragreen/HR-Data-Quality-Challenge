"""Read-only impact scenarios. This module has no source-file writer."""
from __future__ import annotations

import copy

from .policy import DATE_FIELDS, IDENTITY_FIELDS, dependencies_for, iso_date
from .reports import calculate_reports


def simulate_patch(snapshot, matches, policy, as_of, patch):
    """Apply exactly one validated semantic-field patch to an in-memory copy."""
    required = {"record_id", "field", "expected_value", "value"}
    if not required.issubset(patch):
        raise ValueError("Patch requires record_id, field, expected_value and value")
    field = patch["field"]
    if field in IDENTITY_FIELDS:
        raise ValueError("Identity-affecting patches require a separate identity review")
    original = next((r for r in snapshot.records if r["record_id"] == patch["record_id"]), None)
    if original is None:
        raise ValueError("Unknown source record")
    source = original["source_system"]
    source_policy = policy["sources"][source]
    if field not in source_policy["fields"]:
        raise ValueError("Field is not mapped for this source")
    if original["values"].get(field) != patch["expected_value"]:
        raise ValueError("Expected current value differs from the frozen snapshot")
    value = patch["value"]
    if value is not None:
        value = str(value).strip()
    if field in DATE_FIELDS and value is not None and (iso_date(value) is None or len(value) != 10):
        raise ValueError("Scenario dates must use valid ISO YYYY-MM-DD values")
    valid = source_policy.get("domains", {}).get(field)
    if valid and value not in valid:
        raise ValueError("Proposed value is outside the source's approved domain")
    if field in source_policy.get("required", []) and not value:
        raise ValueError("A required field cannot be cleared")
    if field == "is_primary" and str(value).lower() not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError("is_primary requires a boolean value")
    candidate = {**original["values"], field: value}
    hire, end = iso_date(candidate.get("hire_date")), iso_date(candidate.get("termination_date"))
    valid_from, valid_to = iso_date(candidate.get("effective_from")), iso_date(candidate.get("effective_to"))
    if field in {"hire_date", "termination_date"} and hire and end and end < hire:
        raise ValueError("Proposed correction would end employment before it starts")
    if field in {"effective_from", "effective_to"} and valid_from and valid_to and valid_to <= valid_from:
        raise ValueError("Proposed correction would reverse the assignment validity period")
    # Copy only the changed observation. The baseline and every other record
    # are read-only; this keeps independent per-employee ranking scenarios small.
    scenario = copy.copy(snapshot)
    target = copy.deepcopy(original)
    scenario.records = [target if r["record_id"] == original["record_id"] else r for r in snapshot.records]
    target["values"][field] = value
    target["invalid_fields"].pop(field, None)
    aliases = target.get("field_columns", {}).get(field) or source_policy["fields"][field]
    raw_field = next((alias for alias in aliases if alias in target["raw"]), aliases[0])
    # Raw is an isolated scenario observation, never a write-back to a file.
    target["raw"][raw_field] = value or ""
    before = calculate_reports(snapshot, matches, policy, as_of)
    after = calculate_reports(scenario, matches, policy, as_of)
    effects = {}
    for report_id in before:
        baseline, proposed = before[report_id], after[report_id]
        effects[report_id] = {"before": baseline["value"], "after": proposed["value"], "delta": proposed["value"] - baseline["value"], "availability": proposed["availability"], "contributors_added": sorted(set(proposed["contributors"]) - set(baseline["contributors"])), "contributors_removed": sorted(set(baseline["contributors"]) - set(proposed["contributors"])), "unresolved_before": len(baseline["unresolved"]), "unresolved_after": len(proposed["unresolved"]), "uncertainty_increased": len(proposed["unresolved"]) > len(baseline["unresolved"]), "readiness_before": baseline["assurance"]["readiness"], "readiness_after": proposed["assurance"]["readiness"], "trust_score_before": baseline["assurance"]["trust_score"], "trust_score_after": proposed["assurance"]["trust_score"]}
    dependencies = dependencies_for(policy, source, field)
    downstream_reports = sorted(node.removeprefix("report:") for node in dependencies if node.startswith("report:"))
    downstream_systems = sorted({node.split(".")[0] for node in dependencies if not node.startswith("report:")})
    coverage = {"calculated_reports": sorted(effects), "potential_only_systems": downstream_systems, "potential_only_reports": sorted(set(downstream_reports) - set(effects)), "unmodelled_behavior": "Application transformations, propagation timing and monetary payroll amounts are not simulated. A zero delta only applies to the report definitions listed here."}
    return {"snapshot_id": snapshot.snapshot_id, "policy_version": policy["policy_version"], "as_of": as_of, "patch": patch, "target_system": source, "status": "simulated", "reports": effects, "potential_dependencies": dependencies, "potential_downstream_systems": downstream_systems, "potential_downstream_reports": downstream_reports, "coverage": coverage, "source_files_changed": False, "identity_frozen": True, "limitations": "Only implemented report calculations are recomputed. Dependency paths indicate potential exposure; no downstream application or automatic propagation is executed."}
