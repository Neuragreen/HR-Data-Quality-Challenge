"""Compile explicit Markdown declarations into a reviewable policy overlay.

This is a bounded document reader, not a natural-language policy interpreter.
Unsupported or conflicting table declarations are blocking errors. Narrative
context is retained in the original documents; it does not silently become a
business rule. The caller must retain those bytes and obtain review of a ready
preview before using the returned policy.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime

from .ingest import SEMANTIC_FIELDS


DOCUMENT_NAMES = ("data_dictionary.md", "dependencies.md")
MAX_DOCUMENT_BYTES = 1024 * 1024
_SOURCE_LABELS = {"core_hr": ("core hr", "main hr", "core hr system"),
                  "payroll": ("payroll", "payroll system"),
                  "learning": ("learning", "learning system", "lms"),
                  "access_directory": ("access directory", "directory", "directory system")}
_REPORT_LABELS = {
    "active_headcount_dubai": ("dubai active headcount report", "active headcount dubai", "active employees in dubai"),
    "leaver_enabled_accounts": ("leaver enabled account report", "leavers with enabled accounts", "leaver enabled accounts"),
    "payroll_reconciliation": ("payroll reconciliation report", "payroll reconciliation exceptions", "payroll reconciliation"),
}
_COLUMNS = {
    "source": {"source", "source_system", "system", "application"},
    "field": {"semantic_field", "canonical_field", "field", "canonical", "field_name"},
    "columns": {"source_columns", "source_column", "column", "columns", "source_field", "source_field_name", "raw_field"},
    "required": {"required", "mandatory", "is_required"},
    "values": {"valid_values", "valid_codes", "allowed_values", "allowed_codes", "code_list", "values", "codes"},
    "description": {"description", "definition", "meaning", "field_definition"},
    "upstream": {"upstream_field", "upstream", "from", "source", "source_field", "upstream_system", "source_system"},
    "downstream": {"downstream_field_or_report", "downstream_field", "downstream", "to", "target", "target_field", "downstream_system", "target_system", "report", "report_or_field"},
}


def _plain(value):
    return re.sub(r"[*`]", "", str(value)).strip()


def _key(value):
    return re.sub(r"[^\w]+", "_", _plain(value).casefold()).strip("_")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _source(value, policy):
    candidate = _key(str(value).removesuffix(".csv"))
    if candidate in policy.get("sources", {}):
        return candidate
    configured_labels = [source for source, config in policy.get('sources', {}).items()
                         if config.get('display_name') and candidate == _key(config['display_name'])]
    if configured_labels:
        return configured_labels[0] if len(configured_labels) == 1 else None
    for source, labels in _SOURCE_LABELS.items():
        if source in policy.get("sources", {}) and candidate in {_key(label) for label in labels}:
            return source
    return None


def _split_values(value):
    """Explicit comma, semicolon, <br>, or JSON-array lists only."""
    value = _plain(value)
    if not value or value in {"—", "-"}:
        return []
    if value.startswith("["):
        parsed = json.loads(value)
        if not isinstance(parsed, list) or not all(isinstance(item, str) and item.strip() for item in parsed):
            raise ValueError("Expected a JSON array of nonempty strings")
        parts = [item.strip() for item in parsed]
    else:
        parts = [_plain(part) for part in re.split(r",|;|<br\s*/?>", value, flags=re.I)]
    if any(not item for item in parts):
        raise ValueError("A list contains an empty value")
    if any(re.search(r"\betc\.?\b|\.\.\.|…", item, re.I) for item in parts):
        raise ValueError("List all values explicitly; open-ended code lists are ambiguous")
    if len(set(parts)) != len(parts):
        raise ValueError("A list contains duplicate values")
    return parts


def _table_cells(line):
    # Escaped pipes are allowed inside descriptions. Backtick quoting does not
    # change Markdown table cell boundaries.
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", line)]


def _is_separator(cells):
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _tables_and_lines(text):
    """Yield (line number, line, headers or None, row cells or None)."""
    lines = text.splitlines()
    headers = None
    for index, line in enumerate(lines):
        if "|" not in line or line.lstrip().startswith("#"):
            headers = None
            yield index + 1, line, None, None
            continue
        cells = _table_cells(line)
        if _is_separator(cells):
            continue
        if index + 1 < len(lines) and _is_separator(_table_cells(lines[index + 1])):
            headers = [_key(cell) for cell in cells]
            yield index + 1, line, headers, None
        elif headers is not None:
            yield index + 1, line, headers, cells
        else:
            yield index + 1, line, None, None


def _positions(headers, kinds):
    result = {}
    for kind in kinds:
        hits = [index for index, header in enumerate(headers) if header in _COLUMNS[kind]]
        if len(hits) > 1:
            raise ValueError(f"Multiple columns mean '{kind}'; use one unambiguous column")
        if hits:
            result[kind] = hits[0]
    return result


def _dates(value):
    representations = {"YYYY-MM-DD": "%Y-%m-%d", "DD/MM/YYYY": "%d/%m/%Y", "DD-Mon-YYYY": "%d-%b-%Y"}
    parts = _split_values(value.rstrip("."))
    result = []
    for part in parts:
        pattern = representations.get(part, part)
        if "%" not in pattern or not all(token in pattern for token in ("%Y", "%d")) or not any(token in pattern for token in ("%m", "%b", "%B")):
            raise ValueError(f"Date format '{part}' must declare year, month and day")
        # strftime may preserve unknown directives; strptime rejects them.
        sample = datetime(2024, 12, 23).strftime(pattern)
        datetime.strptime(sample, pattern)
        result.append(pattern)
    if not result:
        raise ValueError("Declare at least one date format")
    return result


def _read_dictionary(text, policy, errors, warnings):
    definitions, seen, formats, mappings = [], {}, {}, {}
    context = None
    context_label = None
    for number, line, headers, cells in _tables_and_lines(text):
        prefix = f"data_dictionary.md:{number}"
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            context_label = _plain(heading[1])
            context = _source(context_label, policy)
            continue
        try:
            if "|" in line and headers is None and line.lstrip().startswith("|"):
                raise ValueError("Unrecognized table row; include a header and a Markdown separator row")
            if cells is not None or headers is not None:
                positions = _positions(headers, ("source", "field", "columns", "required", "values", "description"))
                if "field" not in positions or "columns" not in positions:
                    raise ValueError("Use a dictionary table with Semantic field and Source columns; optional columns: Source, Required, Valid values, Description")
                if cells is None:
                    ignored = [header for index, header in enumerate(headers) if index not in positions.values()]
                    if ignored:
                        warnings.append(f"{prefix}: table columns {', '.join(ignored)} are retained in the original document but are not executable declarations.")
                    continue
                if len(cells) != len(headers):
                    raise ValueError("Table row has a different number of cells than its header")
                source_label = cells[positions["source"]] if "source" in positions else context_label
                source = _source(source_label, policy) if source_label else context
                if not source:
                    raise ValueError(f"Unknown source '{source_label or '(missing source heading)'}'")
                field = _key(cells[positions["field"]])
                if field not in {*SEMANTIC_FIELDS, "source_id"}:
                    raise ValueError(f"Unknown semantic field '{field}'; choose a supported employee field")
                columns = _split_values(cells[positions["columns"]])
                if not columns:
                    raise ValueError(f"{source}.{field} needs at least one source column")
                required_text = _key(cells[positions["required"]]) if "required" in positions else ""
                if "required" in positions and required_text not in {"yes", "true", "required", "1", "no", "false", "optional", "0"}:
                    raise ValueError(f"{source}.{field}: Required must be Yes or No")
                required = required_text in {"yes", "true", "required", "1"} if required_text else field in policy["sources"][source].get("required", [])
                if "required" not in positions:
                    warnings.append(f"{prefix}: {source}.{field} retains its Required setting from the base policy.")
                valid_values = _split_values(cells[positions["values"]]) if "values" in positions else []
                description = _plain(cells[positions["description"]]) if "description" in positions else ""
                item = {"source": source, "field": field, "columns": columns, "required": required,
                        "valid_values": valid_values, "description": description, "line": number}
                signature = {key: value for key, value in item.items() if key != "line"}
                previous = seen.get((source, field))
                if previous:
                    if previous != signature:
                        raise ValueError(f"Conflicting definitions for {source}.{field}")
                    warnings.append(f"{prefix}: repeated identical definition for {source}.{field} was deduplicated.")
                    continue
                seen[source, field] = signature
                definitions.append(item)
                continue
            date_match = re.search(r"\bDates?\s*:\s*(.+)", line, re.I)
            if date_match:
                if not context:
                    raise ValueError("Place Dates: under a recognized source heading")
                parsed = _dates(date_match[1])
                if context in formats and formats[context] != parsed:
                    raise ValueError(f"Conflicting date formats for {context}")
                formats[context] = parsed
            map_match = re.match(r"\s*Value mappings\s*:\s*(.+)", line, re.I)
            if map_match:
                if not context:
                    raise ValueError("Place Value mappings: under a recognized source heading")
                raw_json = map_match[1].strip().rstrip(".").strip().strip("`")
                parsed = json.loads(raw_json)
                if not isinstance(parsed, dict) or any(not isinstance(value, dict) for value in parsed.values()):
                    raise ValueError("Value mappings must be a JSON object of field-to-value-map objects")
                if context in mappings and mappings[context] != parsed:
                    raise ValueError(f"Conflicting value mappings for {context}")
                mappings[context] = parsed
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"{prefix}: {exc}")
    if not definitions:
        errors.append("data_dictionary.md: No supported field definitions found. Use Markdown tables with Semantic field and Source columns under source headings.")
    by_source = {}
    for definition in definitions:
        by_source.setdefault(definition["source"], []).append(definition)
    for source, source_policy in policy["sources"].items():
        if source not in by_source:
            warnings.append(f"No field table for {source}; its mappings and code lists remain inherited from the base policy.")
            continue
        rows = by_source[source]
        fields = {row["field"]: row["columns"] for row in rows}
        if "source_id" not in fields:
            errors.append(f"data_dictionary.md: {source} needs a source_id mapping to preserve source-record evidence.")
        source_policy["fields"] = fields
        source_policy["required"] = [row["field"] for row in rows if row["required"]]
        source_policy["domains"] = {row["field"]: row["valid_values"] for row in rows if row["valid_values"]}
        source_policy["field_definitions"] = {row["field"]: {"description": row["description"], "document": "data_dictionary.md", "line": row["line"]} for row in rows}
        if source in formats:
            source_policy["date_formats"] = formats[source]
        else:
            warnings.append(f"No Dates: declaration for {source}; date formats remain inherited from the base policy.")
        explicit_maps = mappings.get(source)
        original_maps = source_policy.get("value_maps", {})
        source_policy["value_maps"] = {}
        for field, mapping in (explicit_maps if explicit_maps is not None else original_maps).items():
            if field not in fields:
                if explicit_maps is not None:
                    errors.append(f"data_dictionary.md: Value mappings refer to undefined field {source}.{field}.")
                continue
            if not isinstance(mapping, dict) or any(not isinstance(key, str) or not isinstance(value, (str, type(None))) for key, value in mapping.items()):
                errors.append(f"data_dictionary.md: Value mappings for {source}.{field} require string keys and string/null values.")
                continue
            normalized_keys = {}
            conflicting_keys = False
            for raw_value, target in mapping.items():
                normalized_key = re.sub(r"[\s_]+", "_", raw_value.casefold().strip())
                if normalized_key in normalized_keys and normalized_keys[normalized_key] != target:
                    errors.append(f"data_dictionary.md: {source}.{field} has conflicting value mappings for equivalent code '{raw_value}'.")
                    conflicting_keys = True
                normalized_keys[normalized_key] = target
            if conflicting_keys:
                continue
            domain = source_policy["domains"].get(field)
            invalid_targets = [value for value in mapping.values() if value is not None and domain is not None and value not in domain]
            if invalid_targets:
                if explicit_maps is not None:
                    errors.append(f"data_dictionary.md: {source}.{field} value mappings point outside the declared code list: {invalid_targets}.")
                else:
                    warnings.append(f"Removed inherited value mappings for {source}.{field}: target values are outside the imported code list.")
                continue
            source_policy["value_maps"][field] = mapping
        if explicit_maps is None and source_policy["value_maps"]:
            warnings.append(f"{source} retains compatible value mappings from the base policy; they were not declared by this document.")
    return definitions


def _node(value, policy):
    value = _plain(value)
    if value.startswith("report:"):
        identifier = value[7:]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]*", identifier):
            raise ValueError(f"Invalid report identifier '{value}'")
        return value
    for report, labels in _REPORT_LABELS.items():
        if _key(value) in {_key(report), *(_key(label) for label in labels)}:
            return "report:" + report
    if "." in value:
        source_label, field_label = value.rsplit(".", 1)
        source = _source(source_label, policy)
        if not source:
            raise ValueError(f"Unknown source in dependency '{value}'")
        fields = policy["sources"][source]["fields"]
        field = _key(field_label)
        allowed = set(fields) | {_key(alias) for aliases in fields.values() for alias in aliases}
        if field not in allowed:
            raise ValueError(f"Unknown field in dependency '{value}'; add it to the dictionary first")
        # Keep source-column nodes intact; dependencies_for starts with both
        # canonical and source-column spellings.
        return source + "." + field
    source = _source(value, policy)
    if source:
        return source
    raise ValueError(f"Unknown dependency node '{value}'; use source.field, a known system, or an explicit report:name")


def _read_dependencies(text, policy, errors, warnings):
    dependencies, seen = [], set()
    for number, line, headers, cells in _tables_and_lines(text):
        prefix = f"dependencies.md:{number}"
        try:
            values = None
            if "|" in line and headers is None and line.lstrip().startswith("|"):
                raise ValueError("Unrecognized table row; include a header and a Markdown separator row")
            if headers is not None:
                positions = _positions(headers, ("upstream", "downstream"))
                if not {"upstream", "downstream"} <= set(positions):
                    raise ValueError("Use a dependency table with Upstream field and Downstream field or report")
                if cells is None:
                    ignored = [header for index, header in enumerate(headers) if index not in positions.values()]
                    if ignored:
                        warnings.append(f"{prefix}: table columns {', '.join(ignored)} are retained in the original document but are not executable declarations.")
                    continue
                if len(cells) != len(headers):
                    raise ValueError("Table row has a different number of cells than its header")
                values = cells[positions["upstream"]], cells[positions["downstream"]]
            elif re.search(r"->|→", line):
                stripped = re.sub(r"^\s*[-*+]\s+", "", line).strip()
                # An inline example inside a narrative sentence is context,
                # not a declaration. A fully quoted arrow line is supported.
                quoted_examples = re.findall(r"`[^`]*(?:->|→)[^`]*`", stripped)
                if quoted_examples and stripped != quoted_examples[0]:
                    continue
                parts = re.split(r"\s*(?:->|→)\s*", stripped)
                if len(parts) != 2:
                    raise ValueError("Declare one upstream and one downstream node per arrow line")
                values = parts
            if values is None:
                continue
            source, target = (_node(value, policy) for value in values)
            if source.startswith("report:"):
                # Report-to-report dependencies are legitimate potential paths.
                warnings.append(f"{prefix}: report-to-report path is declared exposure; no additional report formula is inferred.")
            if source == target:
                raise ValueError("A dependency cannot point to itself")
            if (source, target) in seen:
                continue
            seen.add((source, target))
            dependencies.append({"source": source, "target": target, "line": number})
            if "." not in source and not source.startswith("report:") or "." not in target and not target.startswith("report:"):
                warnings.append(f"{prefix}: system-level path has no field scope and indicates potential exposure only.")
            if target.startswith("report:") and target[7:] not in _REPORT_LABELS:
                warnings.append(f"{prefix}: {target} is a declared report dependency; its numerical calculation is not implemented.")
        except ValueError as exc:
            errors.append(f"{prefix}: {exc}")
    if not dependencies:
        errors.append("dependencies.md: No supported dependencies found. Use an Upstream field / Downstream field or report table, or one source.field -> target node per line.")
    policy["dependencies"] = [{"source": row["source"], "target": row["target"]} for row in dependencies]
    return dependencies


def preview_references(base_policy: dict, documents: dict[str, str]) -> dict:
    """Return a deterministic candidate; never mutate inputs or execute fixes."""
    policy = copy.deepcopy(base_policy)
    errors, warnings, changes = [], [], []
    metadata, definitions, dependencies = [], [], []
    if not isinstance(documents, dict) or set(documents) != set(DOCUMENT_NAMES):
        errors.append("Provide exactly data_dictionary.md and dependencies.md together.")
        documents = documents if isinstance(documents, dict) else {}
    valid = True
    for name in DOCUMENT_NAMES:
        text = documents.get(name)
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{name}: provide a nonempty UTF-8 Markdown document.")
            valid = False
            continue
        try:
            content = text.encode("utf-8")
        except UnicodeError:
            errors.append(f"{name}: document is not valid UTF-8.")
            valid = False
            continue
        if len(content) > MAX_DOCUMENT_BYTES:
            errors.append(f"{name}: document exceeds the 1 MB limit.")
            valid = False
            continue
        metadata.append({"filename": name, "sha256": hashlib.sha256(content).hexdigest(), "line_count": len(text.splitlines()), "bytes": len(content)})
    digest = hashlib.sha256(_canonical({"base_policy": base_policy, "documents": documents}).encode("utf-8")).hexdigest()
    if valid and len(metadata) == 2:
        definitions = _read_dictionary(documents[DOCUMENT_NAMES[0]], policy, errors, warnings)
        dependencies = _read_dependencies(documents[DOCUMENT_NAMES[1]], policy, errors, warnings)
        for source, config in policy["sources"].items():
            for section in ("fields", "required", "domains", "date_formats", "value_maps"):
                previous = base_policy["sources"][source].get(section)
                if previous != config.get(section):
                    changes.append({"source": source, "section": section, "before": previous, "after": config.get(section)})
        if base_policy.get("dependencies") != policy.get("dependencies"):
            changes.append({"section": "dependencies", "before": base_policy.get("dependencies", []), "after": policy.get("dependencies", [])})
    inherited = ["authority", "matching", "timing", "reports", "priority", "record grains and identifier scopes", "freshness and duplicate-profile rules"]
    warnings.insert(0, "Only structured field tables, Dates:, Value mappings: JSON and explicit dependency declarations are interpreted. Narrative text does not approve authority, status meanings, report formulas or timing rules.")
    warnings.append("Authority, matching, report formulas, timing, priority and record-grain rules remain inherited from the selected base policy and require business review. Imported documents do not approve report definitions.")
    policy.setdefault("reports", {})["definitions_approved"] = False
    base_version = str(base_policy.get("policy_version", "policy")).split("+refs-", 1)[0]
    policy["policy_version"] = base_version + "+refs-" + digest[:12]
    policy["reference_import"] = {"digest": digest, "documents": metadata, "definitions": definitions,
                                  "dependencies": dependencies, "warnings": list(dict.fromkeys(warnings)),
                                  "inherited_policy_sections": inherited, "base_policy_version": base_policy.get("policy_version"),
                                  "reader": "markdown-declarations-v1"}
    return {"policy": policy, "digest": digest, "ready": not errors, "errors": list(dict.fromkeys(errors)),
            "warnings": list(dict.fromkeys(warnings)), "changes": changes, "documents": metadata,
            "definitions": definitions, "dependencies": dependencies}
