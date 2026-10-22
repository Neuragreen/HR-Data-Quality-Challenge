"""Reference imports are reviewable before analysis and preserve input bytes."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from hrtrustgraph.deterministic.__main__ import main
from hrtrustgraph.deterministic.policy import load_policy
from hrtrustgraph.deterministic.synthetic import generate_pack


class ReferenceCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        generate_pack(self.root / "pack", n=30, seed=804)
        self.inputs = self.root / "pack" / "input"
        self.references = [
            "--dictionary", str(self.inputs / "data_dictionary.md"),
            "--dependencies", str(self.inputs / "dependencies.md"),
        ]

    def invoke(self, arguments):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            main(arguments)
        return json.loads(stdout.getvalue())

    def test_generated_references_preview_without_csvs_or_truth(self):
        for source in load_policy()["sources"]:
            (self.inputs / f"{source}.csv").unlink()
        candidate = self.root / "candidate.json"
        preview = self.invoke(["import-references", *self.references, "--output", str(candidate)])
        self.assertTrue(preview["ready"])
        policy = json.loads(candidate.read_text())
        self.assertEqual(policy["dependencies"], load_policy()["dependencies"])
        for source, config in load_policy()["sources"].items():
            self.assertEqual(policy["sources"][source]["fields"], config["fields"])
            self.assertEqual(policy["sources"][source]["required"], config["required"])
            self.assertEqual(policy["sources"][source]["domains"], config["domains"])
        self.assertEqual(len(preview["documents"]), 2)

    def test_analysis_requires_explicit_reference_review_and_both_files(self):
        output = self.root / "analysis"
        arguments = ["analyze", "--input", str(self.inputs), "--output", str(output), "--as-of", "2026-10-01"]
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main([*arguments, *self.references])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(output.exists())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([*arguments, *self.references[:2], "--accept-reference-import"])
        self.assertFalse(output.exists())

    def test_reviewed_analysis_archives_exact_reference_bytes(self):
        dictionary = self.inputs / "data_dictionary.md"
        dictionary.write_bytes(dictionary.read_bytes().replace(b"\n", b"\r\n"))
        before = {path.name: path.read_bytes() for path in self.inputs.iterdir()}
        output = self.root / "analysis"
        result = self.invoke([
            "analyze", "--input", str(self.inputs), "--output", str(output), "--as-of", "2026-10-01",
            *self.references, "--accept-reference-import", "--simulation-limit", "0",
        ])
        self.assertGreater(result["source_record_count"], 0)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.inputs.iterdir()})
        self.assertEqual((output / "reference_documents" / "data_dictionary.md").read_bytes(), before["data_dictionary.md"])
        self.assertEqual((output / "reference_documents" / "dependencies.md").read_bytes(), before["dependencies.md"])
        policy = json.loads((output / "policy.json").read_text())
        self.assertTrue(policy["reference_import"]["reviewed"])
        self.assertEqual(policy["reference_import"]["review_method"], "cli_explicit_flag")
        self.assertTrue((output / "reference_import.json").is_file())

    def test_candidate_export_never_overwrites_a_file(self):
        candidate = self.root / "candidate.json"
        candidate.write_text("preserve me")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["import-references", *self.references, "--output", str(candidate)])
        self.assertEqual(candidate.read_text(), "preserve me")

    def test_analysis_cannot_write_over_supplied_reference_files(self):
        output = self.root / "analysis"
        output.mkdir()
        dictionary = output / "review.md"
        before = (self.inputs / "data_dictionary.md").read_bytes()
        dictionary.write_bytes(before)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([
                "analyze", "--input", str(self.inputs), "--output", str(output), "--as-of", "2026-10-01",
                "--dictionary", str(dictionary), *self.references[2:], "--accept-reference-import",
            ])
        self.assertEqual(dictionary.read_bytes(), before)
        self.assertFalse((output / "snapshot.json").exists())


if __name__ == "__main__":
    unittest.main()
