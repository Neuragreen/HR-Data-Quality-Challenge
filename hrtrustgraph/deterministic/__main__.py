"""Run with python3 -m hrtrustgraph.deterministic --help."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .audit import record_decision
from .models import MatchResult, Snapshot
from .pipeline import analyze, write_json
from .policy import load_policy
from .scenario import simulate_patch
from .questions import answer_question
from .reference_docs import preview_references


def _load(directory):
    directory = Path(directory)
    read = lambda name: json.loads((directory / name).read_text(encoding="utf-8"))
    return Snapshot(**read("snapshot.json")), MatchResult(**read("identity.json")), read("policy.json"), read("summary.json")


def _reference_documents(dictionary, dependencies):
    if not dictionary or not dependencies:
        raise ValueError("Provide both --dictionary and --dependencies for a reference import")
    return {
        "data_dictionary.md": Path(dictionary).read_bytes().decode("utf-8"),
        "dependencies.md": Path(dependencies).read_bytes().decode("utf-8"),
    }


def _reference_preview(policy, documents):
    preview = preview_references(policy, documents)
    if not preview["ready"]:
        raise ValueError("Reference import needs correction: " + "; ".join(preview["errors"]))
    return preview


def _validate_reference_output(output, dictionary, dependencies, documents):
    output = Path(output).resolve()
    for source in (dictionary, dependencies):
        source = Path(source).resolve()
        if source == output or output in source.parents:
            raise ValueError("Analysis outputs must not contain the supplied reference files")
    archive = output / "reference_documents"
    if output not in archive.resolve().parents:
        raise ValueError("Reference archives must remain inside the analysis output directory")
    for filename, content in documents.items():
        target = archive / filename
        if target.is_symlink() or (target.exists() and target.read_bytes() != content.encode("utf-8")):
            raise ValueError("Use a new analysis output directory; its reference archive already contains different files")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deterministic HR analysis. Offline, synthetic data only, no write-back.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("analyze", help="Read source files and export evidence, issues, reports and impact previews")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--as-of", required=True)
    run.add_argument("--policy")
    run.add_argument("--dictionary", help="Synthetic data_dictionary.md with structured field definitions")
    run.add_argument("--dependencies", help="Synthetic dependencies.md with explicit field paths")
    run.add_argument("--accept-reference-import", action="store_true", help="Confirm you reviewed the reference preview and retained policy assumptions")
    run.add_argument("--simulation-limit", type=int, default=10)
    references = sub.add_parser("import-references", help="Preview Markdown definitions and dependencies without analysing employee records")
    references.add_argument("--dictionary", required=True)
    references.add_argument("--dependencies", required=True)
    references.add_argument("--policy", help="Reviewed base policy; defaults to provisional demo assumptions")
    references.add_argument("--output", help="Optional NEW candidate policy JSON; never overwrites an existing file")
    sim = sub.add_parser("simulate", help="Preview a proposed issue correction or explicit patch")
    sim.add_argument("--analysis", required=True)
    choice = sim.add_mutually_exclusive_group(required=True)
    choice.add_argument("--issue-id")
    choice.add_argument("--patch-file")
    sim.add_argument("--output")
    review = sub.add_parser("review", help="Record a human decision only; never apply a fix")
    review.add_argument("--analysis", required=True)
    review.add_argument("--issue-id", required=True)
    review.add_argument("--decision", required=True, choices=["approve", "reject", "investigate"])
    review.add_argument("--reviewer", required=True)
    review.add_argument("--reason", required=True)
    question = sub.add_parser("question", help="Answer a supported question from an already calculated report")
    question.add_argument("--analysis", required=True)
    question.add_argument("--text", required=True)
    question.add_argument("--include-records", action="store_true", help="Include every contributing source record; the default shows a sample and evidence-file reference")
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            if args.simulation_limit < 0:
                raise ValueError("simulation-limit must be non-negative")
            policy = load_policy(args.policy)
            documents = None
            preview = None
            if args.dictionary or args.dependencies or args.accept_reference_import:
                documents = _reference_documents(args.dictionary, args.dependencies)
                preview = _reference_preview(policy, documents)
                if not args.accept_reference_import:
                    raise ValueError("Preview the files with import-references, then confirm your review with --accept-reference-import")
                policy = preview["policy"]
                policy["reference_import"]["reviewed"] = True
                policy["reference_import"]["review_method"] = "cli_explicit_flag"
                _validate_reference_output(args.output, args.dictionary, args.dependencies, documents)
            result = analyze(args.input, policy, args.as_of, args.output, args.simulation_limit)["summary"]
            if documents is not None:
                reference_directory = Path(args.output) / "reference_documents"
                reference_directory.mkdir(parents=True, exist_ok=True)
                for filename, content in documents.items():
                    target = reference_directory / filename
                    if not target.exists():
                        with target.open("xb") as handle:
                            handle.write(content.encode("utf-8"))
        elif args.command == "import-references":
            documents = _reference_documents(args.dictionary, args.dependencies)
            result = _reference_preview(load_policy(args.policy), documents)
            if args.output:
                target = Path(args.output)
                if target.suffix != ".json":
                    raise ValueError("Candidate policies must use a .json filename")
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x", encoding="utf-8") as handle:
                    handle.write(json.dumps(result["policy"], indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        elif args.command == "simulate":
            snapshot, matches, policy, summary = _load(args.analysis)
            if args.patch_file:
                patch = json.loads(Path(args.patch_file).read_text(encoding="utf-8"))
            else:
                issues = json.loads((Path(args.analysis) / "issues.json").read_text(encoding="utf-8"))
                issue = next((i for i in issues if i["issue_id"] == args.issue_id), None)
                if not issue or issue["recommendation_status"] != "proposed":
                    raise ValueError("Issue must exist and have a supported proposed correction")
                row = next(r for r in snapshot.records if r["record_id"] == issue["record_id"])
                patch = {"record_id": row["record_id"], "field": issue["field"], "expected_value": row["values"].get(issue["field"]), "value": issue["suggested_value"]}
            result = simulate_patch(snapshot, matches, policy, summary["as_of"], patch)
            if args.output:
                target = Path(args.output).resolve()
                safe_directory = (Path(args.analysis) / "scenarios").resolve()
                if safe_directory not in target.parents or target.suffix != ".json":
                    raise ValueError("Scenario exports must be new .json files inside ANALYSIS/scenarios/")
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        elif args.command == "review":
            result = record_decision(args.analysis, args.issue_id, args.decision, args.reviewer, args.reason)
        else:
            reports = json.loads((Path(args.analysis) / "reports.json").read_text(encoding="utf-8"))
            result = answer_question(reports, args.text)
            report = reports[result["report_id"]]
            result["policy_version"] = report["policy_version"]
            result["evidence_file"] = str((Path(args.analysis) / "reports.json").resolve())
            if args.include_records:
                result["contributing_records"] = report["contributors"]
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Analysis error: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
