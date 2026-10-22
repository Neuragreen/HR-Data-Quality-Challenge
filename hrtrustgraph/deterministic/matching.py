"""Conservative, blocked identity matching without external dependencies.

Scores rank explicit evidence and are not calibrated probabilities. Shared source
ID suffixes, department/job agreement and name-only similarity never establish
identity. This prototype does not infer Arabic/Latin transliterations. Ambiguous
observations retain separate provisional identities for human review.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from itertools import combinations

from .models import MatchResult


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _name(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", _text(value)).casefold()
    return " ".join("".join(
        char if char.isalnum() else " "
        for char in decomposed if not unicodedata.combining(char)
    ).split())


def _email(value: object) -> str:
    value = unicodedata.normalize("NFKC", _text(value)).casefold()
    if value.count("@") != 1 or any(char.isspace() for char in value):
        return ""
    local, domain = value.split("@")
    return value if local and domain else ""


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return max(SequenceMatcher(None, left, right).ratio(),
               SequenceMatcher(None, " ".join(sorted(left.split())),
                               " ".join(sorted(right.split()))).ratio())


class _Clusters:
    def __init__(self, records: dict[str, dict]):
        self.parent = {record_id: record_id for record_id in records}
        self.members = {record_id: {record_id} for record_id in records}
        self.dobs = {record_id: {record["values"]["birth_date"]}
                     if record.get("values", {}).get("birth_date") else set()
                     for record_id, record in records.items()}

    def find(self, record_id: str) -> str:
        root = record_id
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[record_id] != record_id:
            next_id = self.parent[record_id]
            self.parent[record_id] = root
            record_id = next_id
        return root

    def join(self, left: str, right: str) -> bool:
        left, right = self.find(left), self.find(right)
        if left == right:
            return True
        if self.dobs[left] and self.dobs[right] and self.dobs[left] != self.dobs[right]:
            return False
        # Deterministic roots make output independent of input iteration order.
        left, right = sorted((left, right))
        self.parent[right] = left
        self.members[left].update(self.members.pop(right))
        self.dobs[left].update(self.dobs.pop(right))
        return True


def _pair_evidence(left: dict, right: dict, config: dict) -> dict:
    a, b = left.get("values", {}), right.get("values", {})
    name_a, name_b = _name(a.get("name")), _name(b.get("name"))
    email_a, email_b = _email(a.get("email")), _email(b.get("email"))
    dob_a, dob_b = _text(a.get("birth_date")), _text(b.get("birth_date"))
    same_name = bool(name_a and name_b and sorted(name_a.split()) == sorted(name_b.split()))
    name_score = 1.0 if same_name else _similarity(name_a, name_b)
    same_email = bool(email_a and email_a == email_b)
    same_dob = bool(dob_a and dob_a == dob_b)
    conflicting_dob = bool(dob_a and dob_b and dob_a != dob_b)
    same_source = left["source_system"] == right["source_system"]
    same_source_id = bool(same_source and left.get("source_id") and left.get("source_id") == right.get("source_id"))
    exact_duplicate = bool(same_source and left.get("raw_fingerprint") and
                           left.get("raw_fingerprint") == right.get("raw_fingerprint"))
    evidence = []
    if same_name:
        evidence.append("Normalized full names agree (including token-order and accent normalization).")
    elif name_a and name_b:
        evidence.append(f"Normalized name similarity is {name_score:.3f}.")
    if same_email:
        evidence.append("Normalized email addresses agree.")
    elif email_a and email_b:
        evidence.append("Email addresses differ; a name or source-ID suffix cannot explain this alone.")
    if same_dob:
        evidence.append("Valid dates of birth agree.")
    if same_source_id:
        evidence.append("The complete source-local identifier agrees within the same source.")
    if exact_duplicate:
        evidence.append("Raw source observations are exact duplicates.")
    high_cue = bool(same_email and (same_name or name_score >= .9)) or same_source_id
    if conflicting_dob:
        evidence.append("Conflicting valid dates of birth veto identity linkage.")
        return {"score": 0.0, "method": "conflicting_birth_dates", "evidence": evidence,
                "veto": True, "high_cue": high_cue, "equivalent_same_source": False,
                "sufficient_evidence": False}
    if exact_duplicate:
        score, method = 1.0, "exact_duplicate_observation"
    elif same_email and same_name:
        score, method = (1.0 if same_dob else .98), "email_and_name"
    elif same_dob and same_name:
        score, method = .97, "name_and_birth_date"
    elif same_email and name_score >= .90:
        score, method = (.98 if same_dob else .94), "email_and_similar_name"
    elif same_dob and name_score >= .90:
        score, method = .94, "birth_date_and_similar_name"
    elif same_email and same_dob:
        score, method = .96, "email_and_birth_date"
    elif same_email:
        score, method = .76, "email_requires_corroboration"
    elif same_name:
        score, method = .68, "name_requires_corroboration"
    elif name_score >= .88:
        score, method = .65, "similar_name_requires_corroboration"
    else:
        score, method = 0.0, "insufficient_identity_evidence"
    # Global employment IDs are used only when policy explicitly guarantees a
    # shared namespace. Independent local identifiers are never treated alike.
    if (config.get("shared_employment_id", False) and a.get("employment_id") and
            a.get("employment_id") == b.get("employment_id") and same_name):
        score, method = max(score, .97), "shared_employment_id_and_name"
        evidence.append("An explicitly configured globally shared employment identifier agrees.")
    equivalent_same_source = same_source and (
        exact_duplicate or
        (same_source_id and (same_name and (same_email or same_dob))) or
        (same_dob and same_name and (same_email or
          (a.get("employment_id") and b.get("employment_id"))))
    )
    if same_source and not equivalent_same_source and score >= config.get("accept_score", .92):
        evidence.append("Separate source observations lack sufficient evidence to collapse their identities.")
    return {"score": score, "method": method, "evidence": evidence,
            "veto": False, "high_cue": high_cue,
            "equivalent_same_source": equivalent_same_source,
            "sufficient_evidence": method not in {
                "email_requires_corroboration", "name_requires_corroboration",
                "similar_name_requires_corroboration", "insufficient_identity_evidence",
            }}


def _candidate_pairs(records: list[dict], config: dict) -> tuple[set[tuple[str, str]], set[str]]:
    buckets: dict[tuple, list[str]] = defaultdict(list)
    duplicate_buckets: dict[tuple, list[str]] = defaultdict(list)
    birth_dates = {record["record_id"]: _text(record.get("values", {}).get("birth_date"))
                   for record in records}
    for record in records:
        record_id, values = record["record_id"], record.get("values", {})
        name, email = _name(values.get("name")), _email(values.get("email"))
        dob, location = _text(values.get("birth_date")), _name(values.get("location"))
        if email:
            buckets[("email", email)].append(record_id)
        if name:
            ordered_name = " ".join(sorted(name.split()))
            buckets[("exact_name", ordered_name)].append(record_id)
            if dob:
                buckets[("name_prefix_dob", name[:2], dob)].append(record_id)
                buckets[("last_token_dob", name.split()[-1][:3], dob)].append(record_id)
            if location:
                buckets[("name_prefix_location", name[:3], location)].append(record_id)
        if record.get("source_id"):
            buckets[("local_id", record["source_system"], record["source_id"])].append(record_id)
        if record.get("raw_fingerprint"):
            duplicate_buckets[(record["source_system"], record["raw_fingerprint"])].append(record_id)
        if config.get("shared_employment_id", False) and values.get("employment_id"):
            buckets[("employment_id", values["employment_id"])].append(record_id)
    pairs: set[tuple[str, str]] = set()
    crowded: set[str] = set()
    max_block_size = int(config.get("max_block_size", 200))
    for key, bucket in buckets.items():
        if len(bucket) > max_block_size:
            # Broad name blocks are weak evidence; a crowded mailbox/local ID is
            # a meaningful ambiguity. Other independent blocks may still work.
            if key[0] in {"email", "local_id", "employment_id"}:
                crowded.update(bucket)
            continue
        ordered = sorted(set(bucket))
        if key[0] in {"email", "local_id", "employment_id"}:
            # Contradictory DOBs remain visible when a strong identifier agrees.
            pairs.update(combinations(ordered, 2))
        else:
            # Known incompatible DOBs plus a weak name/location block cannot
            # establish a supported link. Split before creating/scoring pairs,
            # while retaining every comparison involving an unknown DOB.
            by_dob: dict[str, list[str]] = defaultdict(list)
            for record_id in ordered:
                by_dob[birth_dates[record_id]].append(record_id)
            missing = by_dob.pop("", [])
            pairs.update(combinations(missing, 2))
            for subgroup in by_dob.values():
                pairs.update(combinations(subgroup, 2))
                for missing_id in missing:
                    pairs.update(tuple(sorted((missing_id, other))) for other in subgroup)
    for bucket in duplicate_buckets.values():
        ordered = sorted(bucket)
        pairs.update(zip(ordered, ordered[1:]))
    return pairs, crowded


def match_records(records: list[dict], policy: dict) -> MatchResult:
    """Assign every observation, retaining uncertainty instead of forcing joins.

    Exact duplicates and corroborated same-source employments can form a single
    person. Reciprocal unique-best comparisons operate on these equivalent groups,
    rather than imposing one-record-per-source. Every merge checks all known DOBs
    in both components, preventing a missing-DOB bridge from joining contradictions.
    """
    config = dict(policy.get("matching", {}))
    accept_score = float(config.get("accept_score", .92))
    review_score = float(config.get("review_score", .65))
    minimum_margin = float(config.get("minimum_margin", .02))
    if not 0 <= review_score <= accept_score <= 1 or minimum_margin < 0:
        raise ValueError("Matching thresholds must satisfy 0 <= review_score <= accept_score <= 1.")
    by_id = {record["record_id"]: record for record in records}
    if len(by_id) != len(records):
        raise ValueError("record_id must be unique before identity matching.")
    pairs, crowded = _candidate_pairs(records, config)
    candidates = []
    internals = {}
    for left_id, right_id in sorted(pairs):
        left, right = by_id[left_id], by_id[right_id]
        result = _pair_evidence(left, right, config)
        internals[(left_id, right_id)] = result
        candidates.append({
            "record_id_a": left_id, "record_id_b": right_id,
            "source_system_a": left["source_system"], "source_system_b": right["source_system"],
            "score": round(result["score"], 6), "method": result["method"],
            "evidence": list(result["evidence"]),
            "status": "review_required" if result["score"] >= review_score else "rejected",
            "score_kind": "evidence_score_not_probability",
        })
    clusters = _Clusters(by_id)
    uncertain = set(crowded)
    for candidate in candidates:
        left_id, right_id = candidate["record_id_a"], candidate["record_id_b"]
        result = internals[(left_id, right_id)]
        if result["veto"]:
            if result["high_cue"]:
                uncertain.update((left_id, right_id))
            continue
        if (by_id[left_id]["source_system"] == by_id[right_id]["source_system"] and
                by_id[left_id].get("source_id") and
                by_id[left_id].get("source_id") == by_id[right_id].get("source_id") and
                not result["equivalent_same_source"]):
            uncertain.update((left_id, right_id))
            candidate["evidence"].append("The same source-local identifier occurs on incompatible observations; identity requires review.")
        if result["equivalent_same_source"] and result["score"] >= accept_score:
            if clusters.join(left_id, right_id):
                candidate["status"] = "accepted"
            else:
                candidate["status"] = "rejected"
                candidate["evidence"].append("Cluster-level date-of-birth contradiction prevented merge.")
                uncertain.update((left_id, right_id))
    # Freeze equivalence groups for ranking. Candidate identity is not the same
    # thing as the number of source rows representing that identity.
    units = {record_id: clusters.find(record_id) for record_id in by_id}
    best_options: dict[tuple, dict[str, float]] = defaultdict(dict)
    for candidate in candidates:
        left_id, right_id = candidate["record_id_a"], candidate["record_id_b"]
        if (candidate["score"] < review_score or
                by_id[left_id]["source_system"] == by_id[right_id]["source_system"]):
            continue
        left_unit, right_unit = units[left_id], units[right_id]
        for unit, target_source, other_unit in (
            (left_unit, by_id[right_id]["source_system"], right_unit),
            (right_unit, by_id[left_id]["source_system"], left_unit),
        ):
            options = best_options[(unit, target_source)]
            options[other_unit] = max(options.get(other_unit, 0), candidate["score"])

    def unique_best(unit: str, target_source: str, other_unit: str) -> bool:
        options = best_options.get((unit, target_source), {})
        if other_unit not in options:
            return False
        score = options[other_unit]
        alternatives = [value for key, value in options.items() if key != other_unit]
        # Equality is always ambiguous, even if the requested margin is zero.
        return not alternatives or (score > max(alternatives) and
                                    score - max(alternatives) + 1e-12 >= minimum_margin)

    for candidate in sorted(candidates, key=lambda item: (-item["score"], item["record_id_a"], item["record_id_b"])):
        left_id, right_id = candidate["record_id_a"], candidate["record_id_b"]
        if candidate["status"] == "accepted" or candidate["score"] < accept_score:
            continue
        if not internals[(left_id, right_id)]["sufficient_evidence"]:
            continue
        if by_id[left_id]["source_system"] == by_id[right_id]["source_system"]:
            uncertain.update((left_id, right_id))
            continue
        left_unit, right_unit = units[left_id], units[right_id]
        left_best = unique_best(left_unit, by_id[right_id]["source_system"], right_unit)
        right_best = unique_best(right_unit, by_id[left_id]["source_system"], left_unit)
        if not left_best or not right_best:
            candidate["evidence"].append("Competing candidates are tied, closer than the configured margin, or stronger.")
            # A weaker alternative does not undo a convincing accepted match;
            # tied/near-best candidates do leave their own observations in review.
            for record_id, unit, target_source in (
                (left_id, left_unit, by_id[right_id]["source_system"]),
                (right_id, right_unit, by_id[left_id]["source_system"]),
            ):
                options = best_options.get((unit, target_source), {})
                if options and max(options.values()) - candidate["score"] < minimum_margin + 1e-12:
                    uncertain.add(record_id)
            continue
        left_root, right_root = clusters.find(left_id), clusters.find(right_id)
        if left_root != right_root:
            # Without a shared known DOB, a bridge must not collapse independent
            # identities from the same source into one person.
            left_sources = {by_id[r]["source_system"] for r in clusters.members[left_root]}
            right_sources = {by_id[r]["source_system"] for r in clusters.members[right_root]}
            shared_dob = bool(clusters.dobs[left_root] and clusters.dobs[left_root] == clusters.dobs[right_root])
            if left_sources & right_sources and not shared_dob:
                candidate["evidence"].append("A transitive bridge would collapse independent same-source identities without a corroborating DOB.")
                uncertain.update((left_id, right_id))
                continue
        if not clusters.join(left_id, right_id):
            candidate["status"] = "rejected"
            candidate["evidence"].append("Cluster-level date-of-birth contradiction prevented transitive merge.")
            uncertain.update((left_id, right_id))
            continue
        candidate["status"] = "accepted"

    components: dict[str, list[str]] = defaultdict(list)
    for record_id in sorted(by_id):
        components[clusters.find(record_id)].append(record_id)
    anchor_source = config.get("anchor_source", "core_hr")
    anchor_components: dict[str, set[str]] = defaultdict(set)
    for root, members in components.items():
        for record_id in members:
            record = by_id[record_id]
            if record["source_system"] == anchor_source and record.get("source_id"):
                anchor_components[str(record["source_id"])].add(root)
    accepted_by_record: dict[str, list[dict]] = defaultdict(list)
    review_by_record: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        for record_id in (candidate["record_id_a"], candidate["record_id_b"]):
            if candidate["status"] == "accepted":
                accepted_by_record[record_id].append(candidate)
            elif candidate["score"] >= review_score:
                review_by_record[record_id].append(candidate)
    assignments = {}
    for root, members in sorted(components.items()):
        anchor_ids = {str(by_id[r]["source_id"]) for r in members
                      if by_id[r]["source_system"] == anchor_source and by_id[r].get("source_id")}
        defensible_anchor = len(anchor_ids) == 1 and len(anchor_components[next(iter(anchor_ids))]) == 1
        if defensible_anchor:
            signature = f"anchor:{anchor_source}:{next(iter(anchor_ids))}"
        else:
            signature = "cluster:" + "|".join(members)
        person_id = "PERSON-" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20]
        component_uncertain = any(record_id in uncertain for record_id in members)
        component_scores = [candidate["score"] for record_id in members
                            for candidate in accepted_by_record[record_id]]
        for record_id in members:
            evidence = []
            for candidate in accepted_by_record[record_id]:
                other_id = candidate["record_id_b"] if candidate["record_id_a"] == record_id else candidate["record_id_a"]
                evidence.append(f"Accepted identity evidence with {other_id}: " + " ".join(candidate["evidence"]))
            if component_uncertain or (len(members) == 1 and review_by_record[record_id]):
                status = "review_required"
                evidence.append("Identity remains provisional: competing, contradictory, or insufficiently corroborated evidence requires review.")
            elif len(members) > 1:
                status = "linked"
            else:
                status = "single_source"
                evidence.append("Observation retained as a separate person; no sufficiently supported cross-record identity link was found.")
            if defensible_anchor:
                evidence.append(f"Person identifier anchored to complete {anchor_source} source identifier; it does not use row order or a numeric suffix.")
            else:
                evidence.append("Person identifier uses this unresolved cluster signature and can change if cluster membership or raw content changes.")
            if record_id in crowded:
                evidence.append("A high-cardinality mailbox or identifier block exceeded the safe matching limit and requires review.")
            score = min(component_scores) if component_scores else max(
                [candidate["score"] for candidate in review_by_record[record_id]], default=0.0)
            assignments[record_id] = {
                "person_id": person_id, "status": status, "score": round(score, 6),
                "evidence": evidence,
            }
    return MatchResult(assignments=assignments, candidates=candidates)
