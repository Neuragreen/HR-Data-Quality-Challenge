"""Independent stdlib evaluation against evaluator-only synthetic world labels.

No detector or generator internals are imported. Pair metrics use contingency
counts, avoiding quadratic pair expansion on the roughly 20,000 source records.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _choose2(count: int) -> int:
    return count * (count - 1) // 2


def _metrics(tp: int, predicted: int, expected: int) -> dict:
    precision = tp / predicted if predicted else (1.0 if not expected else 0.0)
    recall = tp / expected if expected else 1.0
    return {"true_positive": tp, "false_positive": predicted - tp, "false_negative": expected - tp,
            "predicted": predicted, "expected": expected, "precision": round(precision, 6), "recall": round(recall, 6),
            "f1": round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0}


def _record_resolver(identity: list[dict]):
    known_ids = {row["record_id"] for row in identity}
    by_fingerprint, by_source_id = defaultdict(list), defaultdict(list)
    for row in identity:
        by_fingerprint[(row["source_system"], row.get("raw_fingerprint", ""))].append(row["record_id"])
        by_source_id[(row["source_system"], row["source_id"])].append(row["record_id"])

    def resolve(row):
        record_id = row.get("record_id", row.get("source_record_id", ""))
        if record_id in known_ids:
            return record_id
        system = row.get("source_system", "")
        fingerprint = row.get("raw_fingerprint", "")
        possibilities = by_fingerprint.get((system, fingerprint), []) if fingerprint else []
        if len(possibilities) == 1:
            return possibilities[0]
        source_id = row.get("source_id", row.get("source_employee_id", ""))
        possibilities = by_source_id.get((system, source_id), [])
        return possibilities[0] if len(possibilities) == 1 else (record_id or f"unresolved:{system}:{source_id}")
    return resolve


def evaluate_matching(predicted: list[dict], identity: list[dict]) -> dict:
    """Compare partitions using pair counts, including same-source history.

    Missing predictions are singleton clusters; repeated predictions cannot
    double-count a record. Unknown output records add false predicted pairs.
    """
    resolve = _record_resolver(identity)
    truth = {row["record_id"]: row for row in identity}
    assignments, prediction_sources, duplicates = {}, {}, 0
    for row in predicted:
        record_id = resolve(row)
        if record_id in assignments:
            duplicates += 1
            continue
        cluster = row.get("person_id", row.get("canonical_employee_id", ""))
        assignments[record_id] = cluster or "__singleton__:" + record_id
        prediction_sources[record_id] = row.get("source_system", "")
    true_sizes, true_source_sizes = Counter(), Counter()
    pred_sizes, pred_source_sizes = Counter(), Counter()
    intersections, intersection_sources = Counter(), Counter()
    for record_id, row in truth.items():
        true_person = row["person_id"]
        source = row["source_system"]
        predicted_person = assignments.get(record_id, "__missing__:" + record_id)
        true_sizes[true_person] += 1
        true_source_sizes[(true_person, source)] += 1
        pred_sizes[predicted_person] += 1
        pred_source_sizes[(predicted_person, source)] += 1
        intersections[(true_person, predicted_person)] += 1
        intersection_sources[(true_person, predicted_person, source)] += 1
    unknown = 0
    for record_id, predicted_person in assignments.items():
        if record_id not in truth:
            unknown += 1
            # Unknown source rows are distinct from every true row. Their
            # predicted cluster pairs therefore contribute only false positives.
            source = prediction_sources.get(record_id) or "__unknown__:" + record_id
            pred_sizes[predicted_person] += 1
            pred_source_sizes[(predicted_person, source)] += 1
    expected_pairs = sum(map(_choose2, true_sizes.values()))
    predicted_pairs = sum(map(_choose2, pred_sizes.values()))
    correct_pairs = sum(map(_choose2, intersections.values()))
    all_metrics = _metrics(correct_pairs, predicted_pairs, expected_pairs)
    cross_expected = expected_pairs - sum(map(_choose2, true_source_sizes.values()))
    cross_predicted = predicted_pairs - sum(map(_choose2, pred_source_sizes.values()))
    cross_correct = correct_pairs - sum(map(_choose2, intersection_sources.values()))
    return {"all_record_pairs": all_metrics, "cross_system_pairs": _metrics(cross_correct, cross_predicted, cross_expected),
            "truth_record_count": len(truth), "predicted_known_record_count": len(set(assignments) & set(truth)),
            "record_coverage": round(len(set(assignments) & set(truth)) / len(truth), 6) if truth else 1.0,
            "unknown_predicted_records": unknown, "duplicate_record_predictions": duplicates,
            "method": "Cluster contingency counts; no quadratic pair enumeration. Missing predictions are singleton clusters."}


def _value(value) -> str:
    return str(value if value is not None else "").strip().upper()


def evaluate_issues(predicted: list[dict], expected: list[dict], identity: list[dict]) -> dict:
    resolve = _record_resolver(identity)

    def key(row):
        return (row.get("source_system", ""), resolve(row), row.get("field", ""), row.get("issue_type", ""))

    expected_counts = Counter(key(row) for row in expected)
    predicted_counts = Counter(key(row) for row in predicted)
    matched_counts = expected_counts & predicted_counts
    kinds = sorted({row.get("issue_type", "") for row in expected + predicted})
    per_type = {}
    for kind in kinds:
        per_type[kind] = _metrics(sum(value for issue, value in matched_counts.items() if issue[3] == kind),
                                  sum(value for issue, value in predicted_counts.items() if issue[3] == kind),
                                  sum(value for issue, value in expected_counts.items() if issue[3] == kind))
    truth_buckets = defaultdict(list)
    for row in expected:
        truth_buckets[key(row)].append(row)
    correct_fixes = wrong_fixes = unsupported_fixes = safe_abstentions = matched_issues = 0
    required = sum(row.get("suggestion_expected", "").lower() == "true" for row in expected)
    recoverable_matched = recoverable_proposed = 0
    for row in predicted:
        bucket = truth_buckets.get(key(row), [])
        suggested = row.get("suggested_value", "")
        proposed = bool(_value(suggested))
        if not bucket:
            if proposed:
                unsupported_fixes += 1
            continue
        truth = bucket.pop(0)
        matched_issues += 1
        should_suggest = truth.get("suggestion_expected", "").lower() == "true"
        if should_suggest:
            recoverable_matched += 1
        if proposed:
            if should_suggest:
                recoverable_proposed += 1
                if _value(suggested) == _value(truth.get("expected_value", "")):
                    correct_fixes += 1
                else:
                    wrong_fixes += 1
            else:
                unsupported_fixes += 1
        else:
            safe_abstentions += 1
    total_proposed = correct_fixes + wrong_fixes + unsupported_fixes
    false_positive_examples = [{"source_system": item[0], "record_id": item[1], "field": item[2], "issue_type": item[3], "count": count}
                               for item, count in (predicted_counts - expected_counts).items()][:20]
    return {"overall": _metrics(sum(matched_counts.values()), sum(predicted_counts.values()), sum(expected_counts.values())), "per_type": per_type,
            "corrections": {"expected_recoverable_corrections": required, "matched_recoverable_issues": recoverable_matched,
                            "correct_suggestions": correct_fixes, "wrong_suggestions": wrong_fixes, "unsupported_suggestions": unsupported_fixes,
                            "proposed_suggestions": total_proposed, "matched_issues_with_abstention": safe_abstentions,
                            "suggestion_precision": round(correct_fixes / total_proposed, 6) if total_proposed else None,
                            "end_to_end_correct_correction_coverage": round(correct_fixes / required, 6) if required else None,
                            "suggestion_rate_on_detected_recoverable_issues": round(recoverable_proposed / recoverable_matched, 6) if recoverable_matched else None,
                            "note": "Accuracy and coverage are separate. A withheld suggestion is not a fabricated correction; known generator truth may still be unsafe to infer from inputs."},
            "false_positive_examples": false_positive_examples,
            "matching_key": "source_system + record_id (raw fingerprint and occurrence) + canonical field + issue_type; multiset comparison"}


def evaluate_analysis(output_directory, truth_directory, destination=None) -> dict:
    """Evaluate issues.csv and employees.csv against a separate truth directory."""
    output_directory, truth_directory = Path(output_directory), Path(truth_directory)
    issues_path, employees_path = output_directory / "issues.csv", output_directory / "employees.csv"
    for path in (issues_path, employees_path, truth_directory / "issues.csv", truth_directory / "identity.csv"):
        if not path.is_file():
            raise FileNotFoundError(f"Required evaluation input is missing: {path}")
    identity = _read_csv(truth_directory / "identity.csv")
    result = {"schema_version": "1.0", "issues": evaluate_issues(_read_csv(issues_path), _read_csv(truth_directory / "issues.csv"), identity),
              "matching": evaluate_matching(_read_csv(employees_path), identity),
              "limitations": ["Scores describe this synthetic generator family, not external or official challenge accuracy.",
                              "Ground truth must stay outside the detector input directory. Workflow separation is not a secure holdout.",
                              "The generator labels primary planted issue categories; redundant invalid-value conflicts count as extra predictions.",
                              "Correction correctness does not establish that a recommendation was supported by sufficient evidence."]}
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


evaluate_pack = evaluate_analysis
