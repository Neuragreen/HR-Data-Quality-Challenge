"""Local append-only decision history; tamper-evident, not an authenticated ledger."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _digest(event):
    return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def verify_events(events):
    previous = "0" * 64
    for sequence, event in enumerate(events, 1):
        signed = {key: value for key, value in event.items() if key != "event_hash"}
        if signed.get("sequence") != sequence or signed.get("previous_hash") != previous or event.get("event_hash") != _digest(signed):
            raise ValueError("Decision history integrity check failed")
        previous = event["event_hash"]
    return previous


def record_decision(directory, issue_id, decision, reviewer, reason):
    if decision not in {"approve", "reject", "investigate"}:
        raise ValueError("Decision must be approve, reject or investigate")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("A reviewer and decision reason are required")
    directory = Path(directory)
    issues = json.loads((directory / "issues.json").read_text(encoding="utf-8"))
    issue = next((i for i in issues if i["issue_id"] == issue_id), None)
    if issue is None:
        raise ValueError("Unknown issue identifier in this analysis")
    if decision == "approve" and issue["recommendation_status"] != "proposed":
        raise ValueError("An unresolved investigation cannot be approved as a correction")
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    path = directory / "decisions.jsonl"
    with path.open("a+", encoding="utf-8") as handle:
        # Serialize writers on supported local Unix hosts; this is not identity authentication.
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        events = [json.loads(line) for line in handle if line.strip()]
        previous = verify_events(events)
        event = {"sequence": len(events) + 1, "previous_hash": previous, "recorded_at": datetime.now(timezone.utc).isoformat(), "snapshot_id": summary["snapshot_id"], "policy_version": summary["policy_version"], "issue_id": issue_id, "reviewer": reviewer.strip(), "decision": decision, "reason": reason.strip(), "proposed_value": issue["suggested_value"], "write_back_performed": False}
        event["event_hash"] = _digest(event)
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        import os
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return event
