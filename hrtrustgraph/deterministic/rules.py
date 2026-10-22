"""Deterministic field determination, issue detection and plain-language evidence."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import timedelta

from .policy import DATE_FIELDS, dependencies_for, iso_date
from .reports import calculate_reports, current_observation, people_records


def employment_contexts(rows: list[dict], as_of: str):
    """Avoid comparing different employments simply because they share a person."""
    day = iso_date(as_of)
    # Ended employments remain comparable to their own historical payroll rows.
    # Excluding them would attach a rehire's old payroll record to the new job.
    core = [r for r in rows if r["source_system"] == "core_hr" and not (iso_date(r["values"].get("effective_from")) and iso_date(r["values"]["effective_from"]) > day)]
    groups = defaultdict(list)
    for row in core:
        key = row["values"].get("employment_id") or row["source_id"] or row["record_id"]
        groups[key].append(row)
    anchored_keys = list(groups)
    external_employments = defaultdict(set)
    for row in rows:
        if row["source_system"] not in {"core_hr", "access_directory"}:
            source_key = (row["source_system"], row["values"].get("hire_date"))
            employment_id = row["values"].get("employment_id")
            if employment_id:
                external_employments[source_key].add(employment_id)
    for row in rows:
        if row["source_system"] == "core_hr" or row["source_system"] == "access_directory" or not current_observation(row, day):
            continue
        start = row["values"].get("hire_date")
        if start and len(external_employments[row["source_system"], start]) > 1:
            groups["unresolved_context:" + row["record_id"]].append(row)
            continue
        candidates = [key for key in anchored_keys if start and any(r["values"].get("hire_date") == start for r in groups[key] if r["source_system"] == "core_hr")]
        if len(candidates) == 1:
            groups[candidates[0]].append(row)
        elif not start and len(anchored_keys) == 1:
            sole_owner = [r for r in groups[anchored_keys[0]] if r["source_system"] == "core_hr"]
            explicitly_secondary = sole_owner and all(str(r["values"].get("is_primary", "")).lower() in {"false", "0", "no"} for r in sole_owner)
            if explicitly_secondary and row["source_system"] == "learning":
                groups["unresolved_context:" + row["record_id"]].append(row)
            else:
                groups[anchored_keys[0]].append(row)
        else:
            groups["unresolved_context:" + row["record_id"]].append(row)
    return groups


def resolve_fields(snapshot, matches, policy: dict, as_of: str) -> list[dict]:
    day = iso_date(as_of)
    if day is None:
        raise ValueError("as_of must be an ISO date")
    resolved = []
    for person_id, rows in sorted(people_records(snapshot, matches).items()):
        for context, observations in sorted(employment_contexts(rows, as_of).items()):
            for field, authority in policy.get("authority", {}).items():
                comparable = [r for r in observations if r["source_system"] in authority["compare_sources"]]
                if not comparable:
                    continue
                owner_order = authority["sources"] if authority.get("allow_fallback") else authority["sources"][:1]
                owner = []
                for source in owner_order:
                    owner = [r for r in comparable if r["source_system"] == source]
                    if owner:
                        break
                value, status, reason = None, "unknown", "No authoritative observation is available for this employment context."
                evidence = [r["record_id"] for r in owner]
                if context.startswith("unresolved_context:"):
                    status, reason = "review_required", "The employee has multiple employments; this source record cannot be assigned to one safely."
                elif any(matches.assignments.get(r["record_id"], {}).get("status") == "review_required" for r in comparable):
                    status, reason = "review_required", "Identity matching is ambiguous; the field remains unresolved."
                elif owner:
                    invalid = any(field in r.get("invalid_fields", {}) for r in owner)
                    invalid_timeline = field in {"hire_date", "termination_date"} and any(iso_date(r["values"].get("hire_date")) and iso_date(r["values"].get("termination_date")) and iso_date(r["values"]["termination_date"]) < iso_date(r["values"]["hire_date"]) for r in owner)
                    age_limit = policy["sources"][owner[0]["source_system"]].get("max_record_age_days")
                    old = any(age_limit is not None and iso_date(r["values"].get("updated_at")) is not None and (day - iso_date(r["values"].get("updated_at"))).days > age_limit for r in owner)
                    values = {r["values"].get(field) for r in owner}
                    # A blank termination date is meaningful only when dates and status are valid.
                    nullable_end = field == "termination_date" and all(r["values"].get("employment_status") in {"ACTIVE", "ON_LEAVE"} for r in owner)
                    if invalid or old or invalid_timeline:
                        status, reason = "review_required", "The authoritative observation is invalid or exceeds its configured age limit; no fallback is authorised."
                    elif len(values) != 1:
                        status, reason = "review_required", "Authoritative observations disagree within the same employment context."
                    elif values == {None} and not nullable_end:
                        reason = "The authoritative value is missing; no replacement is established."
                    else:
                        value = next(iter(values))
                        status, reason = "resolved", f"Selected {owner[0]['source_system']} under the configured {field} authority policy for this employment."
                resolved.append({"person_id": person_id, "employment_context": context, "field": field, "value": value, "status": status, "evidence": evidence, "observation_ids": sorted(r["record_id"] for r in comparable), "reason": reason, "rule_id": "authority." + field, "policy_version": policy["policy_version"]})
    return resolved


def _original_value(row, field, policy):
    if field == "source_id":
        return row["source_id"]
    for alias in row.get("field_columns", {}).get(field, policy["sources"][row["source_system"]]["fields"].get(field, [])):
        if alias in row["raw"]:
            return row["raw"][alias] or None
    return row["values"].get(field)


def _usable_resolution(resolution, row, field):
    return resolution and resolution["status"] == "resolved" and resolution["value"] is not None and row["record_id"] not in resolution["evidence"]


def detect_issues(snapshot, matches, resolutions, policy: dict, as_of: str) -> list[dict]:
    day = iso_date(as_of)
    if day is None:
        raise ValueError("as_of must be an ISO date")
    issues = []
    rows_by_id = {row["record_id"]: row for row in snapshot.records}
    resolution_index = {}
    for resolution in resolutions:
        for record_id in resolution["observation_ids"]:
            resolution_index[record_id, resolution["field"]] = resolution

    def add(row, field, kind, reason, severity="medium", suggestion=None, evidence=None, rule=None, issue_confidence=1.0, fix_confidence=None):
        assignment = matches.assignments.get(row["record_id"], {})
        deps = dependencies_for(policy, row["source_system"], field)
        priority_config = policy["priority"]
        reach = min(priority_config["max_dependency_increment"], len(deps) * priority_config["dependency_increment"])
        score = min(100, priority_config[severity] + reach)
        ready = suggestion is not None and fix_confidence is not None and assignment.get("status") != "review_required"
        domain = policy["sources"][row["source_system"]].get("domains", {}).get(field)
        if ready and domain is not None and suggestion not in domain:
            ready = False
            reason = reason.replace(" The proposed value is a suggestion requiring human approval.", "")
            reason = reason.replace(" The configured authority supplies the proposed replacement.", "")
            reason += " The authoritative value is outside this source's declared valid codes; investigate the code mapping before proposing a correction."
        value = row["values"].get(field) if field != "source_id" else row["source_id"]
        issue_key = f"{row['record_id']}|{field}|{kind}"
        business = "access" if kind == "possible_ghost_access" else "payroll" if row["source_system"] == "payroll" and field in {"department", "job_code", "payroll_status", "hire_date", "termination_date"} else "reporting" if field in {"location", "employment_status", "department", "hire_date", "termination_date"} else "operational"
        evidence_ids = sorted(set(evidence or [row["record_id"]]))
        issues.append({"issue_id": "ISS-" + hashlib.sha256(issue_key.encode()).hexdigest()[:16], "record_id": row["record_id"], "source_system": row["source_system"], "source_id": row["source_id"], "person_id": assignment.get("person_id"), "field": field, "issue_type": kind, "observed_value": _original_value(row, field, policy), "normalized_value": value, "suggested_value": suggestion if ready else None, "recommendation_status": "proposed" if ready else "investigate", "match_confidence": assignment.get("score", 0.0), "issue_confidence": issue_confidence, "fix_confidence": fix_confidence if ready else None, "confidence_kind": "rule_evidence_score_not_calibrated_probability", "priority_score": score, "priority_band": "P0" if score >= 90 else "P1" if score >= 70 else "P2" if score >= 45 else "P3", "priority_reasons": [f"{severity} business severity contributes {priority_config[severity]} points", f"{business} consequence", f"{len(deps)} declared dependencies contribute {reach} points"], "business_impact": business, "severity": severity, "evidence": {"explanation": reason, "source_record_ids": evidence_ids, "matching_evidence": {record_id: matches.assignments.get(record_id, {}).get("evidence", []) for record_id in evidence_ids}, "as_of": as_of}, "rule_id": rule or kind + "." + field, "policy_version": policy["policy_version"], "dependencies": deps, "status": "OPEN"})

    duplicates = defaultdict(list)
    for row in snapshot.records:
        if row["source_id"]:
            scope_fields = policy["sources"][row["source_system"]].get("identifier_scope_fields", [])
            scope = tuple(row["values"].get(field) or "" for field in scope_fields)
            duplicates[row["source_system"], row["source_id"], scope].append(row)
    for (source, source_id, scope), records in sorted(duplicates.items()):
        if len(records) > 1:
            for row in records:
                add(row, "source_id", "duplicate_identifier", f"Identifier {source_id} appears on {len(records)} {source} records. Compare employment and assignment context before merging or removing anything.", "high", evidence=[r["record_id"] for r in records])

    # A matched person may have duplicate profiles under different local IDs.
    # Only enforce an explicitly declared profile grain: concurrent jobs and
    # multiple directory accounts are legitimate unless the policy says otherwise.
    profiles = defaultdict(list)
    for row in snapshot.records:
        config = policy["sources"][row["source_system"]]
        grain = config.get("unique_profile_fields")
        assignment = matches.assignments.get(row["record_id"], {})
        if grain is None or assignment.get("status") == "review_required":
            continue
        scope = tuple(row["values"].get(field) for field in grain)
        if grain and any(value is None for value in scope):
            continue
        profiles[row["source_system"], assignment.get("person_id"), scope].append(row)
    for (source, person_id, scope), records in sorted(profiles.items(), key=lambda item: str(item[0])):
        identifiers = {r["source_id"] for r in records if r["source_id"]}
        if len(identifiers) > 1:
            grain = policy["sources"][source]["unique_profile_fields"]
            description = "one profile per person" if not grain else "one observation per " + ", ".join(grain)
            for row in records:
                add(row, "source_id", "duplicate_profile", f"{len(identifiers)} distinct {source} identifiers belong to the same matched person within the configured grain ({description}). Review these profiles together; no identifier is deleted, merged or guessed.", "high", evidence=[r["record_id"] for r in records])

    for row in snapshot.records:
        source = row["source_system"]
        config = policy["sources"][source]
        values = row["values"]
        for field in config.get("required", []):
            aliases = row.get("field_columns", {}).get(field, config["fields"].get(field, []))
            if not any(alias in row["raw"] for alias in aliases):
                # A missing column is one schema diagnostic, not thousands of missing-cell issues.
                continue
            value = row["source_id"] if field == "source_id" else values.get(field)
            if value is None or value == "":
                if field in row.get("invalid_fields", {}):
                    continue
                resolution = resolution_index.get((row["record_id"], field))
                suggestion = resolution["value"] if _usable_resolution(resolution, row, field) else None
                explanation = f"{field} is required by the {source} policy but is missing. "
                explanation += resolution["reason"] if suggestion is not None else "The available evidence does not establish a safe replacement."
                add(row, field, "missing_value", explanation, "high" if source == "payroll" and field in {"department", "job_code"} else "medium", suggestion, (resolution or {}).get("evidence", []) + [row["record_id"]], fix_confidence=0.95 if suggestion is not None else None)
        for field, problem in row.get("invalid_fields", {}).items():
            resolution = resolution_index.get((row["record_id"], field))
            suggestion = resolution["value"] if _usable_resolution(resolution, row, field) else None
            kind = "invalid_date" if field in DATE_FIELDS else "invalid_code"
            add(row, field, kind, f"{source} contains {_original_value(row, field, policy)!r} for {field}; it violates the configured {'date format' if kind == 'invalid_date' else 'valid-value domain'}." + (" The configured authority supplies the proposed replacement." if suggestion is not None else " No safe replacement is established."), "high" if source == "payroll" else "medium", suggestion, (resolution or {}).get("evidence", []) + [row["record_id"]], fix_confidence=0.95 if suggestion is not None else None)
        start, end = iso_date(values.get("hire_date")), iso_date(values.get("termination_date"))
        if start and end and end < start:
            add(row, "termination_date", "temporal_inconsistency", f"Employment ends on {end.isoformat()} before its start on {start.isoformat()}. Review the source dates; neither date is automatically overwritten.", "high")
        valid_from, valid_to = iso_date(values.get("effective_from")), iso_date(values.get("effective_to"))
        if valid_from and valid_to and valid_to <= valid_from and not (start and end and end < start):
            add(row, "effective_to", "temporal_inconsistency", "Assignment validity ends on or before it starts. Effective periods use a start-inclusive, end-exclusive interval; review the assignment dates.", "high")
        updated = iso_date(values.get("updated_at"))
        age_limit = config.get("max_record_age_days")
        if updated and age_limit is not None and (day - updated).days > age_limit:
            add(row, "updated_at", "out_of_date_record", f"The record was last updated {(day - updated).days} days before the report date, exceeding the configured {age_limit}-day review limit. Age is evidence for review, not proof that unchanged values are wrong.", "low", issue_confidence=0.7)

    for resolution in resolutions:
        if resolution["status"] != "resolved":
            continue
        field = resolution["field"]
        owner_rows = [rows_by_id[record_id] for record_id in resolution["evidence"]]
        effective = max((iso_date(r["values"].get("effective_from")) for r in owner_rows if iso_date(r["values"].get("effective_from"))), default=None)
        for row in (rows_by_id[record_id] for record_id in resolution["observation_ids"] if record_id not in resolution["evidence"]):
            value = row["values"].get(field)
            if value is None or resolution["value"] is None or field in row.get("invalid_fields", {}) or value == resolution["value"]:
                continue
            updated = iso_date(row["values"].get("updated_at"))
            lag = policy.get("timing", {}).get("source_lag_days", {}).get(row["source_system"], 0)
            if effective and (day - effective).days <= lag:
                continue
            # Invalid employment timelines do not support additional cross-system date findings.
            if field in {"hire_date", "termination_date"}:
                start, end = iso_date(row["values"].get("hire_date")), iso_date(row["values"].get("termination_date"))
                if start and end and end < start:
                    continue
            explanation = f"{row['source_system']} reports {field}={value!r}, while authoritative observations report {resolution['value']!r} for the same employment. {resolution['reason']} The proposed value is a suggestion requiring human approval."
            add(row, field, "cross_system_conflict", explanation, "high" if row["source_system"] == "payroll" else "medium", resolution["value"], resolution["evidence"] + [row["record_id"]], rule="cross_source." + field, fix_confidence=0.95)

    report = calculate_reports(snapshot, matches, policy, as_of)["leaver_enabled_accounts"]
    accounts = set(report["contributors"])
    by_person = people_records(snapshot, matches)
    for row in snapshot.records:
        if row["record_id"] in accounts:
            person_id = matches.assignments[row["record_id"]]["person_id"]
            evidence = [r["record_id"] for r in by_person[person_id] if r["source_system"] == "core_hr"] + [row["record_id"]]
            add(row, "account_status", "possible_ghost_access", f"The linked Core HR employments have ended, no current active employment is established, and this account remains ENABLED beyond the configured {policy['reports']['access_grace_days']}-day grace period. Proposed value DISABLED follows the demo lifecycle policy; the system owner must review exceptions before approval.", "critical", "DISABLED", evidence, rule="lifecycle.leaver_account", fix_confidence=0.9)
    return sorted(issues, key=lambda issue: (-issue["priority_score"], issue["issue_id"]))


def field_trust(snapshot, issues: list[dict], policy: dict) -> list[dict]:
    """Measured completeness/validity/conflict rates, not an estimated truth probability."""
    rows = []
    affected = defaultdict(set)
    for issue in issues:
        affected[issue["source_system"], issue["field"]].add(issue["record_id"])
    for source, config in policy["sources"].items():
        observations = [r for r in snapshot.records if r["source_system"] == source]
        for field in config["fields"]:
            present_columns = any(any(alias in r["raw"] for alias in r.get("field_columns", {}).get(field, config["fields"][field])) for r in observations)
            if not present_columns:
                continue
            total = len(observations)
            present = sum((r["source_id"] if field == "source_id" else r["values"].get(field)) not in (None, "") or field in r.get("invalid_fields", {}) for r in observations)
            invalid = sum(field in r.get("invalid_fields", {}) for r in observations)
            flagged = len(affected[source, field])
            components = {"completeness": present / total if total else None, "validity_of_present": (present - invalid) / present if present else None, "issue_free_fraction": (total - flagged) / total if total else None}
            required = field in config.get("required", [])
            measured = [value for key, value in components.items() if value is not None and (key != "completeness" or required)]
            score = round(100 * min(measured), 1) if measured and (required or present) else None
            rows.append({"source_system": source, "field": field, "records": total, **components, "trust_score": score, "completeness_required": required, "score_formula": "100 × minimum of validity-of-present, issue-free fraction and (for required fields only) completeness; no score for optional fields without observations", "note": "Observed quality score only, not a probability of correctness. Optional blanks are shown in completeness but do not count as errors."})
    return rows
