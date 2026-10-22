"""End-to-end checks against independently labelled synthetic source projections."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from hrtrustgraph.deterministic.__main__ import main
from hrtrustgraph.deterministic.evaluation import evaluate_analysis
from hrtrustgraph.deterministic.pipeline import analyze
from hrtrustgraph.deterministic.policy import load_policy
from hrtrustgraph.deterministic.synthetic import generate_pack


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        generate_pack(self.base / "pack", n=90, seed=20261022, profile="development")
        self.source = self.base / "pack" / "input"
        self.output = self.base / "analysis"

    def test_end_to_end_preserves_inputs_and_exports_evaluable_results(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir() if p.is_file()}
        result = analyze(self.source, as_of="2026-10-01", output_directory=self.output, simulation_limit=2)
        after = {p.name: p.read_bytes() for p in self.source.iterdir() if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(result["summary"]["ai_used"])
        self.assertGreater(len(result["issues"]), 0)
        self.assertTrue(all(i["evidence"]["source_record_ids"] for i in result["issues"]))
        evaluation = evaluate_analysis(self.output, self.base / "pack" / "truth")
        self.assertEqual(evaluation["matching"]["record_coverage"], 1.0)
        self.assertGreater(evaluation["matching"]["cross_system_pairs"]["precision"], .95)
        self.assertGreater(evaluation["issues"]["overall"]["precision"], .85)

    def test_source_missing_column_is_diagnostic_not_row_flood(self):
        content = (self.source / "learning.csv").read_text()
        lines = content.splitlines()
        # Removing a column through csv avoids altering adjacent raw values.
        import csv
        rows = list(csv.DictReader(io.StringIO(content)))
        headers = [key for key in rows[0] if key != "department_code"]
        with (self.source / "learning.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        result = analyze(self.source, as_of="2026-10-01", simulation_limit=0)
        self.assertFalse(result["summary"]["input_complete"])
        self.assertTrue(any(d.get("field") == "department" for d in result["snapshot"].diagnostics))
        self.assertFalse(any(i["source_system"] == "learning" and i["field"] == "department" and i["issue_type"] == "missing_value" for i in result["issues"]))

    def test_output_inside_source_tree_is_rejected(self):
        with self.assertRaises(ValueError):
            analyze(self.source, as_of="2026-10-01", output_directory=self.source / "results", simulation_limit=0)

    def test_question_rejects_unsupported_meaning(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            main(["question", "--analysis", str(self.output), "--text", "How many inactive employees in Dubai?"])
        self.assertEqual(result.exception.code, 2)

    def test_simulation_cannot_overwrite_analysis_or_source_files(self):
        result = analyze(self.source, as_of="2026-10-01", output_directory=self.output, simulation_limit=0)
        issue = next(i for i in result["issues"] if i["recommendation_status"] == "proposed")
        before = (self.output / "snapshot.json").read_bytes()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["simulate", "--analysis", str(self.output), "--issue-id", issue["issue_id"], "--output", str(self.output / "snapshot.json")])
        self.assertEqual((self.output / "snapshot.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
