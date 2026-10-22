"""Small shared contracts for the deterministic analysis pipeline."""

from dataclasses import dataclass, field


@dataclass
class Snapshot:
    """A frozen logical input set; callers must not mutate baseline records."""

    snapshot_id: str
    records: list[dict]
    diagnostics: list[dict] = field(default_factory=list)
    source_hashes: dict[str, str] = field(default_factory=dict)


@dataclass
class MatchResult:
    """All row assignments plus retained accepted/review/rejected candidates."""

    assignments: dict[str, dict]
    candidates: list[dict] = field(default_factory=list)
