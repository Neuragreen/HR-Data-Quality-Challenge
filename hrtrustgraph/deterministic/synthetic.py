"""Seeded synthetic worlds and source projections, independent of the detector.

Only ``input/`` is intended for analysis. ``truth/`` is evaluator material and is
withheld by workflow, not a secure enclave. All names and addresses are invented.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

DEFAULT_AS_OF = "2026-10-01"
GENERATOR_VERSION = "synthetic-world-v1.2"
SYSTEMS = ("core_hr", "payroll", "learning", "access_directory")
SOURCE_IDS = {"core_hr": "employee_id", "payroll": "emp_id", "learning": "person_id", "access_directory": "staff_id"}
HEADERS = {
    "core_hr": ["employee_id", "name", "email", "birth_date", "employment_id", "department", "job_code", "employment_status", "location", "hire_date", "termination_date", "effective_from", "effective_to", "updated_at", "is_primary"],
    "payroll": ["emp_id", "employee_name", "work_email", "birth_date", "employment_id", "dept", "position_code", "payroll_status", "office_location", "start_date", "end_date", "updated_at"],
    "learning": ["person_id", "full_name", "email_address", "birth_date", "employment_id", "department_code", "job_code", "location", "updated_at"],
    "access_directory": ["staff_id", "worker_name", "email", "birth_date", "account_status", "work_location", "last_updated"],
}
DEPARTMENTS = ("FIN-01", "OPS-01", "HR-01", "IT-01", "ENG-01")
JOBS = ("ANALYST", "MANAGER", "ENGINEER", "HRBP", "SPECIALIST")
LOCATIONS = ("DUBAI", "ABU_DHABI", "LONDON", "SINGAPORE")
FIRST_NAMES = ("Amina", "Arjun", "Bilal", "Chen", "David", "Elena", "Fatima", "Hana", "Ibrahim", "Jia", "Karim", "Lina", "Maya", "Nadia", "Omar", "Priya", "Ravi", "Sara", "Tariq", "Yara")
LAST_NAMES = ("Abbas", "Al Nouri", "Basu", "Chen", "Das", "Fernandes", "Gupta", "Hassan", "Iyer", "Jones", "Khan", "Li", "Malik", "Nair", "Patel", "Rahman", "Shah", "Tan", "Wong", "Zaman")
PROFILES = {
    "development": {"coverage": (1.0, .98, .94, .97), "rate": .012, "missing_email": .08, "alias_email": .10, "missing_birth": .03},
    "validation": {"coverage": (1.0, .96, .90, .96), "rate": .016, "missing_email": .13, "alias_email": .16, "missing_birth": .08},
    "final": {"coverage": (1.0, .97, .91, .95), "rate": .020, "missing_email": .17, "alias_email": .20, "missing_birth": .13},
}


def fingerprint(raw: dict) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _write_csv(path: Path, rows: list[dict], headers: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _reference_markdown(policy=None):
    """Describe the synthetic schema; never consult generated labels or records."""
    from .policy import load_policy

    policy = policy or load_policy()
    dictionary = [
        "# Provisional synthetic data dictionary", "",
        "**Synthetic demo definitions only; these are not official Emirates policy.**", "",
        "Keep ../truth separate from the analysis pipeline. Source and employment IDs are opaque, source-local values; never join their suffixes.", "",
    ]
    for source, config in policy["sources"].items():
        dictionary.extend([
            f"### {source}", "",
            config.get("record_grain", "One configured source observation") + ". Dates: " + ", ".join(config.get("date_formats", [])) + ".", "",
            "| Semantic field | Source columns | Required | Valid values |",
            "| --- | --- | --- | --- |",
        ])
        for field, aliases in config["fields"].items():
            required = "Yes" if field in config.get("required", []) else "No"
            dictionary.append(f"| {field} | {', '.join(aliases)} | {required} | {', '.join(config.get('domains', {}).get(field, []))} |")
        dictionary.extend(["", "Value mappings: `" + json.dumps(config.get("value_maps", {}), ensure_ascii=False, sort_keys=True) + "`.", ""])
    dictionary.extend([
        "## Interpretation requiring business review", "",
        "Optional blanks may be legitimate: active employments can have no termination date, and an open assignment interval can have no effective_to date. A blank required field is missing.", "",
        "Employment status, payroll status and account status have distinct meanings. A final settlement after termination is legitimate. Rehires and concurrent employments are legitimate; an old employment alone is not a duplicate employee.", "",
        "Source-local identifiers are unique within the demo snapshot except planted collisions. Names may collide or use reordered tokens, initials and punctuation. Birth date is optional, not a unique key.", "",
        "Authority, source grain, age thresholds, grace periods, report calculations and timing allowances are retained from the selected base policy and still need business review. Demo employment termination is inclusive; effective_to is exclusive. Demo headcount includes ACTIVE and ON_LEAVE primary employment.", "",
    ])
    dependencies = [
        "# Provisional synthetic field dependencies", "",
        "**Declared demo dependencies, not verified production lineage.**", "",
        "| Upstream field | Downstream field or report |", "| --- | --- |",
    ]
    dependencies.extend(f"| {edge['source']} | {edge['target']} |" for edge in policy.get("dependencies", []))
    dependencies.extend([
        "", "These are declared report inputs and potential downstream paths. No propagation or live updates are executed. Only the three implemented reports have calculated numeric impact.", "",
        "Examples of these paths are `core_hr.department -> payroll.dept`, `payroll.department -> Payroll Reconciliation Report` and `core_hr.effective_to -> Dubai Active Headcount Report`.", "",
        "Payroll reconciliation counts established same-employment profile discrepancies. Unknown authoritative values remain unresolved; no monetary loss is estimated. Report definitions still require business approval.", "",
    ])
    return "\n".join(dictionary), "\n".join(dependencies)


def _opaque(rng: random.Random, prefix: str) -> str:
    return prefix + "-" + format(rng.getrandbits(80), "020x")


def _world(n: int, rng: random.Random, as_of: date) -> list[dict]:
    people = []
    for index in range(n):
        hire = as_of - timedelta(days=rng.randint(400, 5200))
        status = "TERMINATED" if index % 10 == 0 else ("ON_LEAVE" if index % 13 == 0 else "ACTIVE")
        termination = as_of - timedelta(days=rng.randint(45, 300)) if status == "TERMINATED" else None
        employment = {"key": _opaque(rng, "W"), "department": rng.choice(DEPARTMENTS), "job_code": rng.choice(JOBS), "employment_status": status,
                      "location": rng.choice(LOCATIONS), "hire_date": hire.isoformat(), "termination_date": termination.isoformat() if termination else "", "is_primary": "true"}
        person = {"person_id": _opaque(rng, "TRUTH"), "name": rng.choice(FIRST_NAMES) + " " + rng.choice(LAST_NAMES),
                  "birth_date": (hire - timedelta(days=rng.randint(22 * 365, 50 * 365))).isoformat(),
                  "email": _opaque(rng, "u").lower() + "@synthetic.example", "employments": [employment]}
        # Correct hard negatives: a historical employment and a current rehire
        # are the same person, while their employment facts need not agree.
        if index and index % 47 == 0 and status != "TERMINATED":
            historical = dict(employment)
            historical.update(key=_opaque(rng, "W"), department=rng.choice(DEPARTMENTS), job_code=rng.choice(JOBS), employment_status="TERMINATED",
                              hire_date=(hire - timedelta(days=1400)).isoformat(), termination_date=(hire - timedelta(days=90)).isoformat(), is_primary="false")
            person["employments"].append(historical)
        # Concurrent assignments remain distinct employment observations.
        if index and index % 61 == 0 and status != "TERMINATED":
            secondary = dict(employment)
            secondary.update(key=_opaque(rng, "W"), department=rng.choice(DEPARTMENTS), job_code=rng.choice(JOBS), is_primary="false")
            person["employments"].append(secondary)
        people.append(person)
    return people


def _project(people: list[dict], rng: random.Random, as_of: date, profile: dict) -> dict[str, list[dict]]:
    projected = {system: [] for system in SYSTEMS}
    for person in people:
        for system_index, system in enumerate(SYSTEMS):
            if rng.random() > profile["coverage"][system_index]:
                continue
            jobs = person["employments"] if system in ("core_hr", "payroll") else person["employments"][:1]
            for employment in jobs:
                updated = (as_of - timedelta(days=rng.randint(0, 60))).isoformat()
                email = person["email"]
                noise = rng.random()
                if noise < profile["missing_email"]:
                    email = ""
                elif noise < profile["missing_email"] + profile["alias_email"]:
                    email = _opaque(rng, "alias").lower() + "@synthetic.example"
                name = person["name"].upper() if rng.random() < .25 else person["name"]
                local_employment = _opaque(rng, "ASSIGN")
                if system == "core_hr":
                    raw = {"employee_id": _opaque(rng, "HR"), "name": name, "email": email, "birth_date": person["birth_date"], "employment_id": local_employment,
                           **{field: employment[field] for field in ("department", "job_code", "employment_status", "location", "hire_date", "termination_date", "is_primary")},
                           "effective_from": employment["hire_date"], "effective_to": (date.fromisoformat(employment["termination_date"]) + timedelta(days=1)).isoformat() if employment["termination_date"] else "", "updated_at": updated}
                elif system == "payroll":
                    # Retained historical FINAL_SETTLEMENT rows do not imply a
                    # payment at the current report date or contradictory status.
                    payroll_status = (rng.choice(("FINAL_SETTLEMENT", "INACTIVE")) if employment["employment_status"] == "TERMINATED" else "ELIGIBLE")
                    raw = {"emp_id": _opaque(rng, "PAY"), "employee_name": name, "work_email": email, "birth_date": person["birth_date"], "employment_id": local_employment,
                           "dept": employment["department"], "position_code": employment["job_code"], "payroll_status": payroll_status, "office_location": employment["location"],
                           "start_date": employment["hire_date"], "end_date": employment["termination_date"], "updated_at": updated}
                elif system == "learning":
                    raw = {"person_id": _opaque(rng, "LMS"), "full_name": name, "email_address": email, "birth_date": person["birth_date"], "employment_id": local_employment,
                           "department_code": employment["department"], "job_code": employment["job_code"], "location": employment["location"], "updated_at": updated}
                else:
                    raw = {"staff_id": _opaque(rng, "DIR"), "worker_name": name, "email": email, "birth_date": person["birth_date"],
                           "account_status": "DISABLED" if employment["employment_status"] == "TERMINATED" else rng.choices(("ENABLED", "DISABLED"), weights=(.98, .02))[0],
                           "work_location": employment["location"], "last_updated": updated}
                # Optional matching attributes may be absent in otherwise valid
                # records. Some true identities are deliberately not inferable.
                if rng.random() < profile["missing_birth"]:
                    raw["birth_date"] = ""
                projected[system].append({"raw": raw, "person": person, "employment": employment, "issues": [], "touched": set()})
    return projected


def _label(item: dict, raw_field: str, field: str, kind: str, observed: str, expected: str = "", reason: str = "", severity: str = "medium") -> bool:
    if raw_field in item["touched"]:
        return False
    item["touched"].add(raw_field)
    item["raw"][raw_field] = observed
    item["issues"].append({"field": field, "issue_type": kind, "expected_value": expected,
                           "suggestion_expected": "true" if expected else "false", "reason": reason, "severity": severity})
    return True


def _corrupt(projected: dict, rng: random.Random, as_of: date, n: int, profile_name: str) -> None:
    count = max(1, round(n * PROFILES[profile_name]["rate"]))
    payroll = projected["payroll"]
    learning = projected["learning"]
    core = projected["core_hr"]
    eligible = lambda rows: [item for item in rows if len(item["person"]["employments"]) == 1]

    def mutate(rows, raw_field, field, kind, transform, reason, severity="medium"):
        pool = [item for item in eligible(rows) if raw_field not in item["touched"]]
        rng.shuffle(pool)
        for item in pool[:count]:
            correct = item["raw"][raw_field]
            _label(item, raw_field, field, kind, transform(correct), correct, reason, severity)

    mutate(payroll, "dept", "department", "missing_value", lambda _: "", "Required payroll department removed from the source projection.")
    invalid = {"development": "UNKNOWN_JOB", "validation": "JOB-999", "final": "UNMAPPED/ROLE"}[profile_name]
    mutate(learning, "job_code", "job_code", "invalid_code", lambda _: invalid, "Job code replaced with a value outside the declared domain.")
    bad_date = {"development": "2026-02-31", "validation": "31/31/2026", "final": "not-a-calendar-date"}[profile_name]
    mutate(payroll, "start_date", "hire_date", "invalid_date", lambda _: bad_date, "Hire date replaced with an impossible or malformed date.")
    conflict_source = payroll if profile_name != "validation" else learning
    conflict_raw = "dept" if profile_name != "validation" else "department_code"
    mutate(conflict_source, conflict_raw, "department", "cross_system_conflict", lambda value: rng.choice([x for x in DEPARTMENTS if x != value]), "Valid department changed from the underlying employment fact.", "high")
    mutate(learning, "job_code", "job_code", "cross_system_conflict", lambda value: rng.choice([x for x in JOBS if x != value]), "Valid job code changed from the underlying employment fact.", "high")
    mutate(learning, "updated_at", "updated_at", "out_of_date_record", lambda _: (as_of - timedelta(days=1100)).isoformat(), "Record age exceeds the demo 730-day review threshold.")
    # Do not infer the correct timestamp simply from other source timestamps.
    for item in learning:
        for issue in item["issues"]:
            if issue["issue_type"] == "out_of_date_record":
                issue.update(expected_value="", suggestion_expected="false")
    leavers = [item for item in projected["access_directory"] if item["employment"]["employment_status"] == "TERMINATED"]
    rng.shuffle(leavers)
    for item in leavers[:count]:
        _label(item, "account_status", "account_status", "possible_ghost_access", "ENABLED", "DISABLED", "Enabled directory account beyond the provisional leaver grace period.", "critical")
    # A date-order error is separate from an ordinary value disagreement. Do
    # not label the legitimate historical/rehire rows as temporal errors.
    terminated = [item for item in eligible(core) if item["employment"]["employment_status"] == "TERMINATED"]
    rng.shuffle(terminated)
    for item in terminated[:max(1, count // 2)]:
        bad = (date.fromisoformat(item["raw"]["hire_date"]) - timedelta(days=10)).isoformat()
        _label(item, "termination_date", "termination_date", "temporal_inconsistency", bad, "", "Termination precedes hire; automatic repair is unsafe.", "high")
        item["raw"]["effective_to"] = (date.fromisoformat(bad) + timedelta(days=1)).isoformat()
    # Identifier collisions: both rows are affected, but the truth identity
    # remains their independently generated underlying person identity.
    pool = [item for item in eligible(payroll) if not item["issues"]]
    rng.shuffle(pool)
    for offset in range(0, min(2 * max(1, count // 2), len(pool) - 1), 2):
        first, second = pool[offset:offset + 2]
        duplicate_id = first["raw"]["emp_id"]
        for item in (first, second):
            _label(item, "emp_id", "source_id", "duplicate_identifier", duplicate_id, "", "One source-local identifier is used by two distinct employees.", "high")


def _render_source_variants(projected: dict, rng: random.Random) -> None:
    """Vary presentation after corruption; labels retain canonical ISO values."""
    date_fields = {
        "payroll": ("birth_date", "start_date", "end_date", "updated_at"),
        "learning": ("birth_date", "updated_at"),
        "access_directory": ("birth_date", "last_updated"),
    }
    name_fields = {"core_hr": "name", "payroll": "employee_name", "learning": "full_name", "access_directory": "worker_name"}
    month_names = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    for system in SYSTEMS:
        for item in projected[system]:
            raw = item["raw"]
            for field in date_fields.get(system, ()):
                try:
                    parsed = date.fromisoformat(raw[field])
                except ValueError:
                    continue  # missing values and deliberately invalid dates
                if system == "payroll" or (system == "access_directory" and rng.random() < .3):
                    raw[field] = f"{parsed.day:02d}/{parsed.month:02d}/{parsed.year:04d}"
                elif system == "learning":
                    raw[field] = f"{parsed.day:02d}-{month_names[parsed.month - 1]}-{parsed.year:04d}"
            field = name_fields[system]
            tokens = raw[field].split()
            choice = rng.random()
            if len(tokens) >= 2 and choice < .14:
                raw[field] = " ".join(tokens[1:]) + ", " + tokens[0]
            elif len(tokens) >= 2 and choice < .22:
                raw[field] = "-".join(tokens)
            elif len(tokens) >= 2 and choice < .26:
                raw[field] = tokens[0][0] + ". " + " ".join(tokens[1:])


def generate_pack(destination, n: int = 5000, seed: int = 20261001, as_of: str = DEFAULT_AS_OF, profile: str = "development", overwrite: bool = False) -> dict:
    """Create deterministic ``input/`` and separately held ``truth/`` files.

    Labels come from mutations of the underlying world, never detector output.
    Profiles vary coverage, alias availability, corruption rate and mechanisms;
    this is a reproducible benchmark, not a claim of unbiased external accuracy.
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError("n must be a positive integer")
    if profile not in PROFILES:
        raise ValueError("profile must be development, validation or final")
    report_date = date.fromisoformat(str(as_of))
    destination = Path(destination)
    if (destination / "manifest.json").exists() and not overwrite:
        raise FileExistsError("A frozen pack already exists at this destination. Choose a new directory or explicitly request overwrite.")
    input_dir, truth_dir = destination / "input", destination / "truth"
    input_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    people = _world(n, random.Random(f"world:{seed}:{profile}"), report_date)
    projected = _project(people, random.Random(f"projection:{seed}:{profile}"), report_date, PROFILES[profile])
    _corrupt(projected, random.Random(f"corruption:{seed}:{profile}"), report_date, n, profile)
    _render_source_variants(projected, random.Random(f"presentation:{seed}:{profile}"))
    identity, issues, corrections = [], [], []
    for system in SYSTEMS:
        rows = [item["raw"] for item in projected[system]]
        _write_csv(input_dir / f"{system}.csv", rows, HEADERS[system])
        occurrences = {}
        for item in projected[system]:
            raw = item["raw"]
            raw_hash = fingerprint(raw)
            occurrences[raw_hash] = occurrences.get(raw_hash, 0) + 1
            record_id = f"{system}:{raw_hash[:20]}:{occurrences[raw_hash]}"
            key = {"record_id": record_id, "source_system": system, "source_id": raw[SOURCE_IDS[system]], "raw_fingerprint": raw_hash}
            identity.append({**key, "person_id": item["person"]["person_id"], "employment_truth_id": item["employment"]["key"] if system != "access_directory" else ""})
            for issue in item["issues"]:
                labelled = {**key, **issue}
                issues.append(labelled)
                if issue["suggestion_expected"] == "true":
                    corrections.append(labelled)
    identity_headers = ["record_id", "source_system", "source_id", "raw_fingerprint", "person_id", "employment_truth_id"]
    issue_headers = ["record_id", "source_system", "source_id", "raw_fingerprint", "field", "issue_type", "expected_value", "suggestion_expected", "reason", "severity"]
    _write_csv(truth_dir / "identity.csv", identity, identity_headers)
    _write_csv(truth_dir / "issues.csv", issues, issue_headers)
    _write_csv(truth_dir / "corrections.csv", corrections, issue_headers)
    dictionary, dependencies = _reference_markdown()
    (input_dir / "data_dictionary.md").write_text(dictionary, encoding="utf-8")
    (input_dir / "dependencies.md").write_text(dependencies, encoding="utf-8")
    name_counts = {}
    for person in people:
        name_counts[person["name"]] = name_counts.get(person["name"], 0) + 1
    issue_counts = {}
    for issue in issues:
        issue_counts[issue["issue_type"]] = issue_counts.get(issue["issue_type"], 0) + 1
    manifest = {"schema_version": "1.0", "generator_version": GENERATOR_VERSION, "synthetic_only": True, "n_people": n, "seed": seed, "as_of": report_date.isoformat(), "profile": profile,
                "input_directory": "input", "evaluator_only_directory": "truth", "source_rows": {system: len(projected[system]) for system in SYSTEMS},
                "truth_issue_count": len(issues), "truth_correction_count": len(corrections),
                "truth_issue_counts": issue_counts,
                "legitimate_world_cases": {"people_with_multiple_employments": sum(len(person["employments"]) > 1 for person in people),
                                           "people_with_colliding_display_names": sum(count for count in name_counts.values() if count > 1),
                                           "source_local_identifiers": True, "optional_missing_birth_dates": True},
                "identity_label_method": "Underlying world membership before source projection and corruption; no detector consulted.",
                "issue_label_method": "Planted primary issue categories; redundant invalid-value conflicts are not separately labelled.",
                "limitations": ["Synthetic generator labels are not external validation or a judge answer key.", "Truth is withheld by workflow only; it is not access-controlled.", "Profiles vary mechanisms but remain one generator family.", "A planted true value need not be safely inferable; correction coverage is reported separately from accuracy."],
                "input_sha256": {system: hashlib.sha256((input_dir / f"{system}.csv").read_bytes()).hexdigest() for system in SYSTEMS},
                "truth_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(truth_dir.glob("*.csv"))}}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
