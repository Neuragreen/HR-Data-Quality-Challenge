"""Pure as-of calculations. Counts carry contributors and unresolved cases."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .policy import iso_date
from .assurance import report_assurance


def people_records(snapshot, matches):
    grouped = defaultdict(list)
    for row in snapshot.records:
        assignment = matches.assignments.get(row["record_id"], {})
        person_id = assignment.get("person_id", row["record_id"])
        grouped[person_id].append(row)
    return grouped


def current_observation(row, as_of):
    """Assignment validity is start inclusive, end exclusive."""
    values = row["values"]
    if any(field in row.get("invalid_fields", {}) for field in ("effective_from", "effective_to")):
        return False
    start, end = iso_date(values.get("effective_from")), iso_date(values.get("effective_to"))
    return not ((start and start > as_of) or (end and end <= as_of))


def employment_state(row, as_of, policy):
    """Return active, ended, future or unknown; never equate unknown with inactive."""
    values = row["values"]
    updated = iso_date(values.get("updated_at"))
    max_age = policy["sources"].get(row["source_system"], {}).get("max_record_age_days")
    if updated and max_age is not None and (as_of - updated).days > max_age:
        return "unknown"
    if any(field in row.get("invalid_fields", {}) for field in ("hire_date", "termination_date", "employment_status", "effective_from", "effective_to")):
        return "unknown"
    start, end = iso_date(values.get("hire_date")), iso_date(values.get("termination_date"))
    valid_from, valid_to = iso_date(values.get("effective_from")), iso_date(values.get("effective_to"))
    status = values.get("employment_status")
    if start is None or (end and end < start) or (valid_from and valid_to and valid_to <= valid_from):
        return "unknown"
    if start > as_of:
        return "future"
    ended = end and (end < as_of if policy["reports"].get("employment_end_date_inclusive", True) else end <= as_of)
    if ended:
        # ACTIVE after its effective end is contradictory, rather than safe evidence of a leaver.
        return "ended" if status == "TERMINATED" else "unknown"
    if status in policy["reports"]["headcount_statuses"]:
        return "active"
    return "unknown"


def _employment_rows(rows, as_of):
    """Select latest applicable assignment per employment, retain contradictions."""
    groups = defaultdict(list)
    for row in rows:
        if row["source_system"] == "core_hr":
            key = row["values"].get("employment_id") or row["source_id"] or row["record_id"]
            groups[key].append(row)
    selected = []
    for group in groups.values():
        eligible = [r for r in group if current_observation(r, as_of)]
        # Historical ended employments remain needed for access review.
        candidates = eligible or group
        latest = max((r["values"].get("effective_from") or "" for r in candidates), default="")
        latest_rows = [r for r in candidates if (r["values"].get("effective_from") or "") == latest]
        signatures = {tuple(r["values"].get(field) for field in ("employment_status", "hire_date", "termination_date", "location", "is_primary")) for r in latest_rows}
        if len(signatures) > 1:
            # Contradictory authoritative observations do not become a confident active/ended state.
            selected.extend({**r, "invalid_fields": {**r.get("invalid_fields", {}), "employment_status": "Contradictory authoritative employment observations"}} for r in latest_rows)
        else:
            selected.extend(latest_rows)
    return selected


def calculate_reports(snapshot, matches, policy: dict, as_of: str) -> dict:
    day = iso_date(as_of)
    if day is None:
        raise ValueError("as_of must be an ISO date")
    head_people, head_contributors, head_unknown = set(), set(), []
    access_accounts, access_people, access_unknown = set(), set(), []
    grace = timedelta(days=policy["reports"].get("access_grace_days", 3))
    target_location = policy["reports"].get("headcount_location", "DUBAI")
    account_groups = defaultdict(list)
    for row in snapshot.records:
        if row["source_system"] == "access_directory":
            account_groups[row["source_id"] or row["record_id"]].append(row)
    people = people_records(snapshot, matches)
    for person_id, rows in sorted(people.items()):
        core = _employment_rows(rows, day)
        identity_uncertain = any(matches.assignments.get(r["record_id"], {}).get("status") == "review_required" for r in rows)
        states = [(row, employment_state(row, day, policy)) for row in core]
        live = [row for row, state in states if state == "active" and current_observation(row, day)]
        unknown = [row for row, state in states if state == "unknown"]
        active_employments = {r["values"].get("employment_id") or r["source_id"] for r in live}
        primary = [r for r in live if str(r["values"].get("is_primary", "")).lower() in ("true", "1", "yes")]
        primary_unspecified = all(r["values"].get("is_primary") is None for r in live)
        relevant = primary if primary else (live if len(active_employments) <= 1 and primary_unspecified else [])
        locations = {r["values"].get("location") for r in relevant}
        if identity_uncertain or unknown or (live and (not relevant or len(locations) != 1 or None in locations)):
            head_unknown.append({"person_id": person_id, "record_ids": [r["record_id"] for r in core], "reason": "Identity, employment dates, status or primary location requires review"})
        elif relevant and locations == {target_location}:
            head_people.add(person_id)
            head_contributors.update(r["record_id"] for r in relevant)
        # Directory-only identities do not silently disappear from the uncertainty count.
        elif not core:
            head_unknown.append({"person_id": person_id, "record_ids": [r["record_id"] for r in rows], "reason": "No linked Core HR employment"})

        for account in (r for r in rows if r["source_system"] == "access_directory"):
            duplicates = account_groups[account["source_id"] or account["record_id"]]
            if account["record_id"] != min(r["record_id"] for r in duplicates):
                continue
            duplicate_states = {r["values"].get("account_status") for r in duplicates}
            duplicate_people = {matches.assignments.get(r["record_id"], {}).get("person_id") for r in duplicates}
            if len(duplicate_states) > 1 or len(duplicate_people) > 1:
                access_unknown.append({"record_id": account["record_id"], "person_id": person_id, "reason": "Duplicate account identifier has contradictory state or identity"})
                continue
            account_status = account["values"].get("account_status")
            if account_status == "DISABLED":
                continue
            updated = iso_date(account["values"].get("updated_at"))
            max_age = policy["sources"].get("access_directory", {}).get("max_record_age_days")
            stale = updated and max_age is not None and (day - updated).days > max_age
            if account_status != "ENABLED" or identity_uncertain or not core or unknown or stale:
                access_unknown.append({"record_id": account["record_id"], "person_id": person_id, "reason": "Account state or linked employment requires review"})
                continue
            if live:
                continue
            ended = [r for r, state in states if state == "ended"]
            # A not-yet-started employee is not a leaver. An earlier ended employment can still qualify.
            if not ended:
                continue
            latest_end = max(iso_date(r["values"]["termination_date"]) for r in ended)
            exempt = iso_date(account["values"].get("access_exempt_until"))
            if "access_exempt_until" in account.get("invalid_fields", {}):
                access_unknown.append({"record_id": account["record_id"], "person_id": person_id, "reason": "Invalid access exception expiry"})
                continue
            if (exempt and exempt >= day) or day <= latest_end + grace:
                continue
            access_accounts.add(account["record_id"])
            access_people.add(person_id)
    base = {"as_of": as_of, "policy_version": policy["policy_version"], "snapshot_id": snapshot.snapshot_id}
    present_sources = {r["source_system"] for r in snapshot.records} | set(snapshot.source_hashes)
    source_errors = {d.get("source_system") for d in snapshot.diagnostics if d.get("severity") == "error"}
    def availability(required):
        return "unavailable" if not required.issubset(present_sources) else "incomplete" if required & source_errors else "available"
    reports = {
        "active_headcount_dubai": {**base, "sources": ["core_hr"], "availability": availability({"core_hr"}), "population_count": len(people), "value": len(head_people), "unit": "distinct_people", "contributors": sorted(head_contributors), "people": sorted(head_people), "unresolved": head_unknown, "definition": "Distinct people with eligible current employment and a primary Dubai assignment. Employment end-date inclusion and leave statuses follow the policy."},
        "leaver_enabled_accounts": {**base, "sources": ["core_hr", "access_directory"], "availability": availability({"core_hr", "access_directory"}), "population_count": len(account_groups), "value": len(access_accounts), "unit": "directory_accounts", "affected_people": len(access_people), "contributors": sorted(access_accounts), "people": sorted(access_people), "unresolved": access_unknown, "definition": "Enabled accounts linked to ended employment, with no current active employment, after the configured grace period and access exceptions. Potential exposure requiring human review."},
    }
    # The resolver uses the temporal helpers above but does not calculate reports.
    # Import at call time to keep that dependency acyclic during module loading.
    from .rules import resolve_fields
    resolutions = resolve_fields(snapshot, matches, policy, as_of)
    index = {(record_id, res["field"]): res for res in resolutions for record_id in res["observation_ids"]}
    payroll_groups = defaultdict(list)
    for row in snapshot.records:
        if row["source_system"] == "payroll":
            scope = tuple(row["values"].get(field) for field in policy["sources"]["payroll"].get("identifier_scope_fields", []))
            payroll_groups[(row["source_id"] or row["record_id"], scope)].append(row)
    discrepancies, payroll_unknown, payroll_people, payroll_cases = set(), [], set(), []
    records_by_id = {r["record_id"]: r for r in snapshot.records}
    fields = policy.get("reports", {}).get("payroll_reconciliation_fields", ["department", "job_code", "location", "hire_date", "termination_date"])
    for group in payroll_groups.values():
        row = min(group, key=lambda r: r["record_id"])
        person_id = matches.assignments.get(row["record_id"], {}).get("person_id")
        contradictory = len({tuple(r["values"].get(field) for field in fields) for r in group}) > 1
        contradictory |= len({matches.assignments.get(r["record_id"], {}).get("person_id") for r in group}) > 1
        mismatches, undecidable, evidence = [], [], {row["record_id"]}
        if contradictory:
            undecidable.append("Duplicate payroll identifier has contradictory values or identity")
        updated = iso_date(row["values"].get("updated_at"))
        age_limit = policy["sources"].get("payroll", {}).get("max_record_age_days")
        if updated and age_limit is not None and (day - updated).days > age_limit:
            undecidable.append("Payroll observation exceeds its configured freshness limit")
        for field in ([] if undecidable else fields):
            res = index.get((row["record_id"], field))
            if not res or res["status"] != "resolved":
                undecidable.append(f"{field}: authoritative employment context is unresolved")
                continue
            evidence.update(res["evidence"])
            # A blank termination date is valid for an active employment.
            if field in row.get("invalid_fields", {}) or row["values"].get(field) != res["value"]:
                effective = max((iso_date(records_by_id[rid]["values"].get("effective_from")) for rid in res["evidence"] if iso_date(records_by_id[rid]["values"].get("effective_from"))), default=None)
                lag = policy.get("timing", {}).get("source_lag_days", {}).get("payroll", 0)
                if effective and (day - effective).days <= lag:
                    undecidable.append(f"{field}: source is within the configured propagation allowance")
                else:
                    mismatches.append(field)
        if mismatches:
            discrepancies.add(row["record_id"])
            payroll_people.add(person_id)
        if undecidable:
            payroll_unknown.append({"record_id": row["record_id"], "person_id": person_id, "reason": "; ".join(undecidable)})
        if mismatches or undecidable:
            payroll_cases.append({"record_id": row["record_id"], "person_id": person_id, "mismatched_fields": mismatches, "source_record_ids": sorted(evidence), "unresolved_fields": undecidable})
    reports["payroll_reconciliation"] = {**base, "sources": ["core_hr", "payroll"], "availability": availability({"core_hr", "payroll"}), "population_count": len(payroll_groups), "value": len(discrepancies), "unit": "payroll_profiles", "contributors": sorted(discrepancies), "people": sorted(p for p in payroll_people if p), "unresolved": payroll_unknown, "cases": payroll_cases, "definition": "Distinct payroll profiles with at least one established disagreement against valid Core HR authority for the same employment, across " + ", ".join(fields) + ". A profile can also have unresolved fields. This is reconciliation exposure, not a monetary payroll calculation."}
    for report in reports.values():
        report["assurance"] = report_assurance(report, policy)
    return reports
