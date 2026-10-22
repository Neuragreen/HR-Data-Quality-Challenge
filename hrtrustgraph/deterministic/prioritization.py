"""Business severity plus reproducible, measured report consequences."""
from collections import defaultdict

from .models import Snapshot
from .scenario import simulate_patch


def rank_issues(snapshot, matches, policy, as_of, issues, reports):
    people, identifiers = defaultdict(list), defaultdict(set)
    for row in snapshot.records:
        person = matches.assignments[row["record_id"]]["person_id"]
        people[person].append(row)
        if row["source_id"]:
            identifiers[row["source_system"], row["source_id"]].add(person)
    by_id = {r["record_id"]: r for r in snapshot.records}
    weights = policy["priority"].get("report_change_points", {})
    for issue in issues:
        issue["priority_base_score"] = issue["priority_score"]
        issue["measured_impact"] = {"status": "not_calculable", "reason": "No supported correction; business severity remains in the ranking."}
        if issue["recommendation_status"] != "proposed":
            continue
        # Reports are separable by identity group except duplicate source keys.
        # Include the full transitive closure of those shared-key groups too.
        selected, pending = set(), [issue["person_id"]]
        while pending:
            person = pending.pop()
            if person in selected:
                continue
            selected.add(person)
            for row in people[person]:
                pending.extend(identifiers[row["source_system"], row["source_id"]] - selected)
        rows = [row for person in selected for row in people[person]]
        subset = Snapshot(snapshot.snapshot_id, rows, snapshot.diagnostics, snapshot.source_hashes)
        row = by_id[issue["record_id"]]
        patch = {"record_id": row["record_id"], "field": issue["field"], "expected_value": row["values"].get(issue["field"]), "value": issue["suggested_value"]}
        try:
            simulation = simulate_patch(subset, matches, policy, as_of, patch)
        except ValueError as exc:
            issue["measured_impact"] = {"status": "not_calculable", "reason": str(exc)}
            continue
        effects, points = {}, 0
        for key, effect in simulation["reports"].items():
            baseline = reports[key]
            uncertainty_delta = effect["unresolved_after"] - effect["unresolved_before"]
            effects[key] = {"before": baseline["value"], "after": baseline["value"] + effect["delta"], "delta": effect["delta"], "unresolved_before": len(baseline["unresolved"]), "unresolved_after": len(baseline["unresolved"]) + uncertainty_delta, "availability": baseline["availability"]}
            if baseline["availability"] == "available" and (effect["delta"] or uncertainty_delta):
                points += weights.get(key, 0)
        points = min(policy["priority"].get("max_report_change_points", 15), points)
        issue["measured_impact"] = {"status": "calculated", "method": "Isolated correction with frozen identity; independent affected employee groups, including shared-key peers, recalculated with the same report functions.", "reports": effects, "ranking_points": points}
        issue["priority_score"] = min(100, issue["priority_base_score"] + points)
        issue["priority_band"] = "P0" if issue["priority_score"] >= 90 else "P1" if issue["priority_score"] >= 70 else "P2" if issue["priority_score"] >= 45 else "P3"
        changed = [key for key, effect in effects.items() if effect["delta"] or effect["unresolved_after"] != effect["unresolved_before"]]
        issue["priority_reasons"].append(f"Measured change to {', '.join(changed) if changed else 'none of the implemented reports'} contributes {points} points; no monetary amount is inferred.")
    return sorted(issues, key=lambda i: (-i["priority_score"], i["issue_id"]))
