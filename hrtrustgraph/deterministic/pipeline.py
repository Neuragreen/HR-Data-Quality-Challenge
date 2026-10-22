"""Offline analysis orchestration and reviewable exports. No LLM or network calls."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .ingest import load_snapshot
from .matching import match_records
from .policy import load_policy
from .reports import calculate_reports
from .rules import detect_issues, field_trust, resolve_fields
from .scenario import simulate_patch
from .prioritization import rank_issues


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(path, rows, headers):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def analyze(input_directory, policy=None, as_of="2026-10-01", output_directory=None, simulation_limit=10, progress=None):
    notify = progress or (lambda stage: None)
    policy = policy or load_policy()
    notify("Reading and validating source files")
    snapshot = load_snapshot(input_directory, policy)
    if not snapshot.records:
        raise ValueError("No source records could be ingested. Inspect source files and policy mappings.")
    notify("Matching employee records across systems")
    matches = match_records(snapshot.records, policy)
    notify("Determining authoritative values and finding inconsistencies")
    resolutions = resolve_fields(snapshot, matches, policy, as_of)
    issues = detect_issues(snapshot, matches, resolutions, policy, as_of)
    notify("Calculating reports and data-quality indicators")
    reports = calculate_reports(snapshot, matches, policy, as_of)
    notify("Ranking findings using measured report consequences")
    issues = rank_issues(snapshot, matches, policy, as_of, issues, reports)
    trust = field_trust(snapshot, issues, policy)
    employees = [{"record_id": row["record_id"], "source_system": row["source_system"], "source_id": row["source_id"], "raw_fingerprint": row.get("raw_fingerprint", ""), "person_id": matches.assignments[row["record_id"]]["person_id"], "link_status": matches.assignments[row["record_id"]]["status"], "score": matches.assignments[row["record_id"]]["score"], "evidence": matches.assignments[row["record_id"]]["evidence"]} for row in snapshot.records]
    simulations = []
    notify("Previewing proposed corrections")
    by_id = {r["record_id"]: r for r in snapshot.records}
    for issue in issues:
        if len(simulations) >= simulation_limit:
            break
        if issue["recommendation_status"] == "proposed":
            patch = {"record_id": issue["record_id"], "field": issue["field"], "expected_value": by_id[issue["record_id"]]["values"].get(issue["field"]), "value": issue["suggested_value"]}
            simulation = simulate_patch(snapshot, matches, policy, as_of, patch)
            simulations.append({"issue_id": issue["issue_id"], **simulation})
    summary = {"engine": "deterministic-stdlib-v2", "snapshot_id": snapshot.snapshot_id, "as_of": as_of, "policy_version": policy["policy_version"], "source_record_count": len(snapshot.records), "records_by_source": dict(Counter(r["source_system"] for r in snapshot.records)), "person_groups": len({x["person_id"] for x in matches.assignments.values()}), "identity_status_counts": dict(Counter(x["status"] for x in matches.assignments.values())), "candidate_count": len(matches.candidates), "issue_count": len(issues), "issues_by_type": dict(Counter(x["issue_type"] for x in issues)), "proposed_corrections": sum(i["recommendation_status"] == "proposed" for i in issues), "schema_diagnostic_count": len(snapshot.diagnostics), "input_complete": not any(d.get("severity") == "error" for d in snapshot.diagnostics), "report_values": {key: {"value": value["value"] if value["availability"] == "available" else None, "availability": value["availability"], "unresolved": len(value["unresolved"]), "assurance": value["assurance"]} for key, value in reports.items()}, "precomputed_simulation_count": len(simulations), "ai_used": False, "network_used": False, "source_files_changed": False, "limits": ["Demo policy requires confirmation against the official data dictionary and dependencies.", "Matching scores express evidence, not calibrated probabilities.", "Results are conditional on the ingested sources. Missing or unreadable sources are exposed in diagnostics.", "Three implemented report definitions have calculated impact; other dependencies are potential exposure."]}
    if policy.get("reference_import"):
        summary["reference_import"] = {key: policy["reference_import"].get(key) for key in ("digest", "documents", "reviewed", "reviewed_at", "review_method")}
        summary["limits"][0] = "Imported field definitions and dependencies are recorded with provenance. Inherited authority, report meanings and freshness rules still require business confirmation."
    result = {"snapshot": snapshot, "matches": matches, "resolutions": resolutions, "issues": issues, "reports": reports, "trust": trust, "employees": employees, "simulations": simulations, "summary": summary, "policy": policy}
    if output_directory is not None:
        notify("Saving review evidence and exports")
        input_path, output_path = Path(input_directory).resolve(), Path(output_directory).resolve()
        if input_path == output_path or input_path in output_path.parents or output_path in input_path.parents:
            raise ValueError("Analysis outputs must use a separate directory outside the source input tree")
        output_path.mkdir(parents=True, exist_ok=True)
        write_json(output_path / "snapshot.json", asdict(snapshot))
        write_json(output_path / "identity.json", asdict(matches))
        write_json(output_path / "policy.json", policy)
        if policy.get("reference_import"):
            write_json(output_path / "reference_import.json", policy["reference_import"])
        write_json(output_path / "resolved_fields.json", resolutions)
        write_json(output_path / "issues.json", issues)
        write_json(output_path / "reports.json", reports)
        write_json(output_path / "diagnostics.json", snapshot.diagnostics)
        write_json(output_path / "impact_simulations.json", simulations)
        write_json(output_path / "summary.json", summary)
        issue_headers = ["issue_id", "record_id", "source_system", "source_id", "person_id", "field", "issue_type", "observed_value", "normalized_value", "suggested_value", "recommendation_status", "match_confidence", "issue_confidence", "fix_confidence", "confidence_kind", "priority_score", "priority_base_score", "priority_band", "priority_reasons", "measured_impact", "business_impact", "severity", "evidence", "rule_id", "policy_version", "dependencies", "status"]
        write_csv(output_path / "issues.csv", issues, issue_headers)
        write_csv(output_path / "employees.csv", employees, ["record_id", "source_system", "source_id", "raw_fingerprint", "person_id", "link_status", "score", "evidence"])
        candidate_headers = sorted({key for row in matches.candidates for key in row}) or ["record_id_a", "record_id_b", "score", "status", "evidence", "method"]
        write_csv(output_path / "candidate_links.csv", matches.candidates, candidate_headers)
        write_csv(output_path / "field_trust.csv", trust, ["source_system", "field", "records", "completeness", "validity_of_present", "issue_free_fraction", "trust_score", "completeness_required", "score_formula", "note"])
        markdown = ["# Deterministic HR analysis", "", f"Snapshot: `{snapshot.snapshot_id}`. As of {as_of}. Policy: `{policy['policy_version']}`.", "", f"Analysed {len(snapshot.records):,} source records and found {len(issues):,} issues. {summary['proposed_corrections']:,} have proposed corrections; every correction requires human review.", "", "## Reports", "", "| Report | Confirmed value | Availability | Cases requiring review |", "| --- | ---: | --- | ---: |"]
        markdown.extend(f"| {key} | {value['value'] if value['availability'] == 'available' else 'Unavailable'} | {value['availability']} | {len(value['unresolved'])} |" for key, value in reports.items())
        markdown.extend(["", "## Highest-priority issues", ""])
        for issue in issues[:12]:
            markdown.extend([f"- **{issue['priority_band']} {issue['issue_type']}** — {issue['source_system']} `{issue['source_id']}`, `{issue['field']}`. {issue['evidence']['explanation']}"])
        markdown.extend(["", "## Scope", "", "Sources are read-only. No AI, external service or production write-back is used. Numeric impacts cover Dubai headcount, leaver enabled accounts and payroll reconciliation. Field mappings, authority, time windows and dependencies are explicit provisional demo policies.", "", "Use issues.csv for the complete ranked queue, resolved_fields.json for determination evidence, reports.json for report contributors, diagnostics.json for ingestion failures and impact_simulations.json for the first proposed scenarios. Any proposed issue can be simulated on demand."])
        (output_path / "review.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    notify("Analysis complete")
    return result
