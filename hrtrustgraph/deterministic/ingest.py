"""Policy-driven CSV ingestion without external dependencies.

``source_hashes`` identify the exact input bytes. The logical snapshot and row
identifiers are independent of CSV row order. Identical rows receive occurrence
suffixes: they are distinguishable as a multiset, but their physical identities
cannot survive deletion/insertion of an indistinguishable duplicate.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

from .models import Snapshot


SEMANTIC_FIELDS = (
    "name", "email", "birth_date", "employment_id", "department", "job_code",
    "employment_status", "payroll_status", "account_status", "location",
    "hire_date", "termination_date", "effective_from", "effective_to",
    "updated_at", "is_primary", "access_exempt_until",
)
DATE_FIELDS = frozenset({
    "birth_date", "hire_date", "termination_date", "effective_from",
    "effective_to", "updated_at", "access_exempt_until",
})
CODE_FIELDS = frozenset({"department", "job_code", "employment_status", "payroll_status",
                         "account_status", "location", "is_primary"})


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def raw_fingerprint(raw: dict) -> str:
    """Public serialization contract shared with the separate truth evaluator."""
    return hashlib.sha256(_canonical_json(raw).encode("utf-8")).hexdigest()


def _header(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"[^\w]+", "_", value).strip("_")


def _aliases(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return list(value or [])


def _code_key(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"[\s_]+", "_", value)


def _date_value(value: str, formats: list[str]) -> str | None:
    for pattern in formats:
        try:
            parsed = datetime.strptime(value, pattern)
            # strptime alone accepts e.g. 2026-1-2 for %Y-%m-%d. Require the
            # declared representation, rather than guessing ambiguous dates.
            if parsed.strftime(pattern) == value:
                return parsed.date().isoformat()
        except (ValueError, TypeError):
            continue
    return None


def _normalise_values(raw: dict, mappings: dict, source_policy: dict) -> tuple[dict, dict]:
    values = {field: None for field in SEMANTIC_FIELDS}
    invalid: dict = {}
    null_values = {str(x).strip() for x in source_policy.get("null_values", [""])}
    value_maps = source_policy.get("value_maps", {})
    domains = source_policy.get("domains", {})
    configured_formats = source_policy.get("date_formats", ["%Y-%m-%d"])
    for field, columns in mappings.items():
        if len(columns) > 1:
            values[field] = None
            invalid[field] = {"reason": "ambiguous_columns", "raw_values": {c: raw.get(c) for c in columns}}
            continue
        original = raw.get(columns[0]) if columns else None
        text = str(original).strip() if original is not None else ""
        if not text or text in null_values:
            values[field] = None
            continue
        mapping = value_maps.get(field, {})
        mapped_options = {None if canonical is None else str(canonical)
                          for original_key, canonical in mapping.items()
                          if _code_key(original_key) == _code_key(text)}
        if len(mapped_options) > 1:
            values[field] = None
            invalid[field] = {"reason": "ambiguous_value_mapping", "raw_value": original}
            continue
        mapped = next(iter(mapped_options)) if mapped_options else text
        text = str(mapped).strip() if mapped is not None else ""
        if not text:
            values[field] = None
            continue
        if field in DATE_FIELDS:
            if isinstance(configured_formats, dict):
                formats = configured_formats.get(field, ["%Y-%m-%d"])
            else:
                formats = configured_formats
            formats = [formats] if isinstance(formats, str) else list(formats)
            normalised = _date_value(text, formats)
            if normalised is None:
                values[field] = None
                invalid[field] = {"reason": "invalid_date", "raw_value": original,
                                  "expected_formats": formats}
                continue
            text = normalised
        if field in domains:
            domain_matches = [str(value) for value in domains[field] if _code_key(value) == _code_key(text)]
            if text in {str(value) for value in domains[field]}:
                pass
            elif len(domain_matches) == 1:
                text = domain_matches[0]
            else:
                values[field] = None
                invalid[field] = {"reason": "invalid_code" if not domain_matches else "ambiguous_domain_value",
                                  "raw_value": original, "mapped_value": text,
                                  "allowed_values": list(domains[field])}
                continue
        elif field in CODE_FIELDS:
            text = _code_key(text).upper()
        elif field == "email":
            text = unicodedata.normalize("NFKC", text).casefold()
        values[field] = text
    return values, invalid


def load_snapshot(directory: str | Path, policy: dict) -> Snapshot:
    """Read configured CSV sources, preserving raw evidence and schema failures.

    Missing required *columns* are source-level diagnostics; an optional absent
    column does not create a quality issue for every employee. Required cell
    validation belongs to the rule layer, where applicability is known.
    """
    directory = Path(directory)
    records: list[dict] = []
    diagnostics: list[dict] = []
    source_hashes: dict[str, str] = {}
    logical_sources: dict = {}
    for source, source_policy in sorted(policy.get("sources", {}).items()):
        filename = source_policy.get("filename", f"{source}.csv")
        path = directory / filename
        try:
            content = path.read_bytes()
        except OSError as exc:
            diagnostics.append({"source_system": source, "code": "missing_source",
                                "filename": str(filename), "message": str(exc), "severity": "error"})
            logical_sources[source] = {"missing_source": str(filename)}
            continue
        source_hashes[source] = hashlib.sha256(content).hexdigest()
        try:
            reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
            headers = reader.fieldnames or []
            raw_rows = list(reader)
        except (UnicodeError, csv.Error) as exc:
            diagnostics.append({"source_system": source, "code": "unreadable_source",
                                "filename": str(filename), "message": str(exc), "severity": "error"})
            logical_sources[source] = {"unreadable_hash": source_hashes[source]}
            continue
        # Mixed None/string keys can occur in malformed DictReader rows. Store
        # the complete row as a key-value list for the logical snapshot hash.
        row_signatures = [_canonical_json(sorted(row.items(), key=lambda item: str(item[0]))) for row in raw_rows]
        logical_sources[source] = {"headers": sorted(headers), "rows": sorted(row_signatures)}
        duplicate_headers = sorted(h for h, n in Counter(headers).items() if n > 1)
        if duplicate_headers:
            diagnostics.append({"source_system": source, "code": "duplicate_headers",
                                "fields": duplicate_headers, "severity": "error",
                                "message": "Repeated CSV headers would discard values; source was not ingested."})
            continue
        configured = dict(source_policy.get("fields", {}))
        if "source_id" not in configured and "employee_id" in configured:
            configured["source_id"] = configured.pop("employee_id")
        mappings = {}
        for field, aliases in configured.items():
            names = {_header(alias) for alias in _aliases(aliases)}
            mappings[field] = [column for column in headers if _header(column) in names]
        required = source_policy.get("required", [])
        for field in required:
            if field == "employee_id":
                field = "source_id"
            if not mappings.get(field):
                diagnostics.append({"source_system": source, "code": "missing_required_field",
                                    "field": field, "severity": "error",
                                    "message": f"Required configured field '{field}' has no source column."})
        for field, columns in mappings.items():
            if len(columns) > 1:
                diagnostics.append({"source_system": source, "code": "ambiguous_field_mapping",
                                    "field": field, "columns": sorted(columns), "severity": "error"})
        occurrences: Counter = Counter()
        for row_number, raw in enumerate(raw_rows, start=2):
            if None in raw or any(value is None for value in raw.values()):
                diagnostics.append({"source_system": source, "code": "malformed_row",
                                    "row_number": row_number, "severity": "error",
                                    "message": "CSV row length differs from the header; row was not ingested."})
                continue
            fingerprint = raw_fingerprint(raw)
            occurrences[fingerprint] += 1
            values, invalid = _normalise_values(raw, mappings, source_policy)
            records.append({
                "record_id": f"{source}:{fingerprint[:20]}:{occurrences[fingerprint]}",
                "source_system": source,
                "source_id": values.get("source_id"),
                "raw": dict(raw),
                "raw_fingerprint": fingerprint,
                "field_columns": {field: list(columns) for field, columns in mappings.items()},
                "values": values,
                "invalid_fields": invalid,
            })
    records.sort(key=lambda record: record["record_id"])
    # A repeated human review does not change the meaning of the same frozen
    # inputs and definitions. Keep review events in the saved policy, while
    # binding logical identity to the document content and compiled settings.
    logical_policy = policy
    if policy.get("reference_import"):
        logical_policy = {**policy, "reference_import": {
            key: value for key, value in policy["reference_import"].items()
            if key not in {"reviewed", "reviewed_at", "review_method"}
        }}
    logical_payload = {"sources": logical_sources, "policy": logical_policy}
    snapshot_id = "SNAP-" + hashlib.sha256(_canonical_json(logical_payload).encode("utf-8")).hexdigest()[:24]
    return Snapshot(snapshot_id=snapshot_id, records=records,
                    diagnostics=diagnostics, source_hashes=source_hashes)
