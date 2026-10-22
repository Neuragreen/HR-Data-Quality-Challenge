"""Versioned, explicit business policies; no inferred production definitions."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path


DATE_FIELDS = frozenset({"birth_date", "hire_date", "termination_date", "effective_from", "effective_to", "updated_at", "access_exempt_until"})
IDENTITY_FIELDS = frozenset({"source_id", "name", "email", "birth_date", "employment_id"})


def load_policy(path=None) -> dict:
    target = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "demo_policy.json"
    policy = json.loads(target.read_text(encoding="utf-8"))
    return validate_policy(policy)


def validate_policy(policy: dict) -> dict:
    """Validate uploaded or compiled configuration before creating input files."""
    if not isinstance(policy, dict):
        raise ValueError("A reviewed policy must be a JSON object")
    if not policy.get("policy_version") or not policy.get("sources"):
        raise ValueError("Policy requires policy_version and explicit source definitions")
    if not isinstance(policy["sources"], dict):
        raise ValueError("Policy sources must be a named object")
    filenames = set()
    for name, source in policy["sources"].items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError("Source names must start with a lowercase letter and contain only lowercase letters, digits and underscores")
        if not isinstance(source, dict) or not source.get("filename") or not source.get("fields"):
            raise ValueError(f"Source {name} requires a filename and field mappings")
        if not isinstance(source["filename"], str) or not isinstance(source["fields"], dict):
            raise ValueError(f"Source {name} requires a relative filename and a field mapping object")
        path_part = Path(source["filename"])
        if path_part.is_absolute() or ".." in path_part.parts:
            raise ValueError("Source filenames must be relative paths inside the input directory")
        if path_part.suffix.lower() != ".csv" or str(path_part) in filenames:
            raise ValueError("Each source requires its own CSV filename")
        filenames.add(str(path_part))
        label = source.get("display_name")
        if label is not None and (not isinstance(label, str) or not label.strip() or len(label) > 120):
            raise ValueError(f"Source {name} needs a nonempty display name of at most 120 characters")
        from .ingest import SEMANTIC_FIELDS
        for field, aliases in source['fields'].items():
            if field not in {*SEMANTIC_FIELDS, 'source_id'}:
                raise ValueError(f"Source {name} uses unsupported employee field '{field}'")
            aliases = [aliases] if isinstance(aliases, str) else aliases
            if not isinstance(aliases, list) or not aliases or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
                raise ValueError(f"Source {name}.{field} needs one or more CSV column names")
            source['fields'][field] = aliases
        if not isinstance(source.get('required', []), list) or any(field not in source['fields'] for field in source.get('required', [])):
            raise ValueError(f"Source {name} required fields must refer to its mapped employee fields")
    return policy


def iso_date(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def dependencies_for(policy: dict, source: str, field: str) -> list[str]:
    """Traverse declared edges; system edges express broad potential exposure.

    A field can reach an explicitly declared system-wide feed. Reaching a
    system never implies any particular target field or a calculated effect.
    """
    node_key = lambda name: re.sub(r"[^\w]+", "_", name.casefold()).strip("_")
    aliases = policy.get("sources", {}).get(source, {}).get("fields", {}).get(field, [])
    aliases = [aliases] if isinstance(aliases, str) else aliases
    queue = [source, f"{source}.{field}"] + [f"{source}.{node_key(alias)}" for alias in aliases]
    seen = set(queue)
    found = set()
    while queue:
        node = queue.pop()
        source_node, separator, column = node.partition(".")
        if separator and source_node in policy.get("sources", {}):
            equivalents = {source_node}
            for canonical, columns in policy["sources"][source_node]["fields"].items():
                columns = [columns] if isinstance(columns, str) else columns
                names = [canonical, *columns]
                if node_key(column) in {node_key(name) for name in names}:
                    equivalents.update(f"{source_node}.{node_key(name)}" for name in names)
            for equivalent in equivalents - seen:
                seen.add(equivalent)
                queue.append(equivalent)
        for edge in policy.get("dependencies", []):
            if edge["source"] == node and edge["target"] not in seen:
                seen.add(edge["target"])
                found.add(edge["target"])
                queue.append(edge["target"])
                parent = edge["target"].split(".", 1)[0]
                if parent in policy.get("sources", {}) and parent not in seen:
                    seen.add(parent)
                    queue.append(parent)
    return sorted(found)
