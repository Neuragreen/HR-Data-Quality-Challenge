"""Browser API behavior without opening sockets or changing demonstration decisions."""
import base64
import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from hrtrustgraph.deterministic.pipeline import analyze
from hrtrustgraph.deterministic.policy import load_policy
from hrtrustgraph.deterministic.synthetic import generate_pack
from hrtrustgraph.deterministic.web import Handler, Workspace, ensure_builtin_pack


class MemorySocket:
    def __init__(self, incoming):
        self.incoming = incoming
        self.output = io.BytesIO()

    def makefile(self, mode, *args):
        return io.BytesIO(self.incoming)

    def sendall(self, content):
        self.output.write(content)


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        (self.root / "config").mkdir()
        (self.root / "config" / "demo_policy.json").write_text(json.dumps(load_policy()))
        generate_pack(self.root / "datasets" / "development", n=120, seed=704)
        self.source = self.root / "datasets" / "development" / "input"
        self.output = self.root / "analysis_outputs" / "development"
        analyze(self.source, as_of="2026-10-01", output_directory=self.output, simulation_limit=1)
        self.workspace = Workspace(self.root)
        self.addCleanup(lambda: self.workspace.executor.shutdown(wait=True))
        self.context = self.workspace.context("development")
        self.server = SimpleNamespace(workspace=self.workspace, server_port=8765)

    def request(self, path, body=None, token=True, origin=None, host="127.0.0.1:8765"):
        method = "POST" if body is not None else "GET"
        payload = json.dumps(body).encode() if body is not None else b""
        headers = [f"{method} {path} HTTP/1.0", f"Host: {host}"]
        if body is not None:
            headers += ["Content-Type: application/json", f"Content-Length: {len(payload)}"]
            if token:
                headers += ["X-HR-Workspace: " + self.workspace.csrf]
            if origin:
                headers += ["Origin: " + origin]
        request = ("\r\n".join(headers) + "\r\n\r\n").encode() + payload
        sock = MemorySocket(request)
        Handler(sock, ("127.0.0.1", 12345), self.server)
        head, data = sock.output.getvalue().split(b"\r\n\r\n", 1)
        status = int(head.split(b" ")[1])
        return status, data, head

    def json_request(self, path, body=None, **kwargs):
        status, data, headers = self.request(path, body, **kwargs)
        return status, json.loads(data), headers

    def test_overview_is_the_engine_result_and_exposes_uncertainty(self):
        status, result, headers = self.json_request("/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(result["summary"]["issue_count"], len(self.context.issues))
        self.assertEqual(len(result["sources"]), 4)
        self.assertIn("unresolved_count", result["reports"]["active_headcount_dubai"])
        self.assertIn(b"Content-Security-Policy", headers)

    def test_issue_filter_and_detail_include_real_source_evidence(self):
        _, queue, _ = self.json_request("/api/issues?source_system=payroll&size=5")
        self.assertTrue(queue["items"])
        self.assertTrue(all(i["source_system"] == "payroll" for i in queue["items"]))
        issue = queue["items"][0]
        status, detail, _ = self.json_request("/api/issue?" + urlencode({"id": issue["issue_id"]}))
        self.assertEqual(status, 200)
        self.assertTrue(detail["records"])
        self.assertTrue(detail["issue"]["evidence"]["source_record_ids"])
        self.assertTrue(all("raw" in row and "assignment" in row for row in detail["records"]))

    def test_reports_expose_readiness_and_contributors_that_open_real_employee_evidence(self):
        status, reports, _ = self.json_request("/api/reports")
        self.assertEqual(status, 200)
        self.assertIn("payroll_reconciliation", reports)
        head = reports["active_headcount_dubai"]
        self.assertEqual(head["assurance"]["readiness"], "review_required")
        self.assertEqual(head["sources"], ["core_hr"])
        contributor = head["contributor_details"][0]
        status, employee, _ = self.json_request("/api/employee?" + urlencode({"id": contributor["person_id"]}))
        self.assertEqual(status, 200)
        self.assertIn(contributor["record_id"], {r["record_id"] for r in employee["records"]})
        self.assertEqual(contributor["source_id"], self.context.by_id[contributor["record_id"]]["source_id"])

    def test_impact_preview_does_not_change_snapshot_or_source_files(self):
        issue = next(i for i in self.context.issues if i["issue_type"] == "possible_ghost_access")
        before = copy.deepcopy(self.context.snapshot)
        source_bytes = {p.name: p.read_bytes() for p in self.source.glob("*.csv")}
        status, result, _ = self.json_request("/api/simulate", {"issue_id": issue["issue_id"]})
        self.assertEqual(status, 200)
        self.assertEqual(result["reports"]["leaver_enabled_accounts"]["delta"], -1)
        self.assertEqual(result["reports"]["active_headcount_dubai"]["delta"], 0)
        self.assertEqual(before, self.context.snapshot)
        self.assertEqual(source_bytes, {p.name: p.read_bytes() for p in self.source.glob("*.csv")})

    def test_mutations_require_local_origin_and_workspace_token(self):
        status, _, _ = self.json_request("/api/decision", {}, token=False)
        self.assertEqual(status, 403)
        status, _, _ = self.json_request("/api/decision", {}, origin="https://untrusted.example")
        self.assertEqual(status, 403)
        status, _, _ = self.json_request("/api/overview", host="untrusted.example:8765")
        self.assertEqual(status, 403)

    def test_human_decision_is_durable_and_never_applies_a_fix(self):
        issue = next(i for i in self.context.issues if i["recommendation_status"] == "proposed")
        before = copy.deepcopy(self.context.snapshot)
        status, event, _ = self.json_request("/api/decision", {"issue_id": issue["issue_id"], "decision": "approve", "reviewer": "Automated test fixture", "reason": "Disposable test case; no source updates"})
        self.assertEqual(status, 200)
        self.assertFalse(event["write_back_performed"])
        self.assertEqual(before, self.context.snapshot)
        _, audit, _ = self.json_request("/api/audit")
        self.assertEqual(audit["integrity"], "verified")
        self.assertEqual(len(audit["events"]), 1)
        _, detail, _ = self.json_request("/api/issue?" + urlencode({"id": issue["issue_id"]}))
        self.assertEqual(detail["issue"]["review_status"], "approve")

    def test_investigation_cannot_be_approved_as_a_correction(self):
        issue = next(i for i in self.context.issues if i["recommendation_status"] != "proposed")
        status, _, _ = self.json_request("/api/decision", {"issue_id": issue["issue_id"], "decision": "approve", "reviewer": "Test fixture", "reason": "Unsupported correction"})
        self.assertEqual(status, 400)
        self.assertFalse((self.output / "decisions.jsonl").exists())

    def test_question_is_source_grounded_and_rejects_other_meanings(self):
        status, answer, _ = self.json_request("/api/question", {"question": "How many active employees in Dubai?"})
        self.assertEqual(status, 200)
        self.assertEqual(answer["answer"], self.context.reports["active_headcount_dubai"]["value"])
        self.assertEqual(answer["sources"], ["core_hr"])
        self.assertFalse(answer["language_model_used"])
        status, _, _ = self.json_request("/api/question", {"question": "How many inactive employees in Dubai?"})
        self.assertEqual(status, 400)

    def test_final_pack_and_arbitrary_files_are_not_exposed(self):
        status, _, _ = self.json_request("/api/overview?run=final_reserved")
        self.assertEqual(status, 400)
        status, _, _ = self.json_request("/api/download?file=../../truth/identity.csv")
        self.assertEqual(status, 400)
        status, _, _ = self.json_request("/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertTrue(all(r["id"] != "final_reserved" for r in self.workspace.runs()))

    def test_supported_export_is_a_real_analysis_file(self):
        status, data, headers = self.request("/api/download?file=issues.csv")
        self.assertEqual(status, 200)
        self.assertEqual(data, (self.output / "issues.csv").read_bytes())
        self.assertIn(b"attachment", headers)

    def test_upload_requires_synthetic_confirmation(self):
        status, _, _ = self.json_request("/api/analyze", {"mode": "upload", "files": {}})
        self.assertEqual(status, 400)

    def test_uploaded_files_run_through_the_actual_analysis_pipeline(self):
        files = {key: base64.b64encode((self.source / value["filename"]).read_bytes()).decode() for key, value in self.context.policy["sources"].items()}
        status, job, _ = self.json_request("/api/analyze", {"mode": "upload", "as_of": "2026-10-01", "synthetic_confirmed": True, "files": files})
        self.assertEqual(status, 200)
        self.workspace.executor.shutdown(wait=True)
        completed = self.workspace.jobs[job["id"]]
        self.assertEqual(completed["status"], "complete", completed)
        new_context = self.workspace.context(completed["run"])
        self.assertEqual(new_context.summary["source_record_count"], self.context.summary["source_record_count"])
        self.assertEqual(len(new_context.issues), len(self.context.issues))
        self.assertNotEqual(new_context.directory, self.output)

    def test_missing_builtin_validation_pack_is_generated_locally_before_analysis(self):
        self.assertFalse((self.root / "datasets" / "validation").exists())
        status, job, _ = self.json_request("/api/analyze", {"mode": "validation", "as_of": "2026-10-01", "synthetic_confirmed": True})
        self.assertEqual(status, 200)
        self.workspace.executor.shutdown(wait=True)
        completed = self.workspace.jobs[job["id"]]
        self.assertEqual(completed["status"], "complete", completed)
        context = self.workspace.context(completed["run"])
        self.assertEqual(len(context.snapshot.records), 5815)
        self.assertEqual(len(context.issues), 196)

    def test_incomplete_builtin_pack_never_overwrites_existing_sources(self):
        source = self.root / "datasets" / "validation" / "input"
        source.mkdir(parents=True)
        path = source / "core_hr.csv"
        path.write_bytes(b"synthetic placeholder to preserve\n")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            ensure_builtin_pack(self.root, "validation")
        self.assertEqual(path.read_bytes(), b"synthetic placeholder to preserve\n")
        self.assertFalse((source / "payroll.csv").exists())

    def test_invalid_json_shape_is_rejected(self):
        status, _, _ = self.json_request("/api/simulate", ["invalid"])
        self.assertEqual(status, 400)

    def reference_documents(self):
        project = Path(__file__).resolve().parents[1]
        return {name: (project / "data" / name).read_text(encoding="utf-8") for name in ("data_dictionary.md", "dependencies.md")}

    def upload_payload(self, documents, preview):
        return {"mode": "upload", "as_of": "2026-10-01", "synthetic_confirmed": True,
                "files": {key: base64.b64encode((self.source / value["filename"]).read_bytes()).decode() for key, value in self.context.policy["sources"].items()},
                "reference_documents": documents, "reference_digest": preview["digest"], "references_reviewed": True}

    def test_references_preview_works_before_an_analysis_and_needs_local_token(self):
        payload = {"reference_documents": self.reference_documents(), "run": "not_an_existing_run"}
        status, result, _ = self.json_request("/api/references/preview", payload)
        self.assertEqual(status, 200)
        self.assertTrue(result["ready"], result["errors"])
        self.assertGreater(len(result["definitions"]), 40)
        self.assertTrue(result["dependencies"])
        self.assertTrue(all(row["line"] for row in result["definitions"]))
        status, _, _ = self.json_request("/api/references/preview", payload, token=False)
        self.assertEqual(status, 403)

    def test_reference_import_requires_review_of_unchanged_files_and_base_policy(self):
        documents = self.reference_documents()
        preview = self.workspace.preview_references({"reference_documents": documents})
        payload = self.upload_payload(documents, preview)
        payload["references_reviewed"] = False
        with self.assertRaisesRegex(ValueError, "review"):
            self.workspace.start_analysis(payload)
        payload["references_reviewed"] = True
        payload["reference_documents"] = {**documents, "dependencies.md": documents["dependencies.md"] + "\nChanged reference.\n"}
        with self.assertRaisesRegex(ValueError, "changed"):
            self.workspace.start_analysis(payload)
        payload["reference_documents"] = documents
        payload["policy"] = copy.deepcopy(self.context.policy)
        payload["policy"]["timing"]["source_lag_days"]["payroll"] = 6
        with self.assertRaisesRegex(ValueError, "changed"):
            self.workspace.start_analysis(payload)
        self.assertFalse(self.workspace.jobs)

    def test_imported_mapping_codes_and_paths_drive_real_results_and_preserve_originals(self):
        documents = self.reference_documents()
        documents["data_dictionary.md"] = documents["data_dictionary.md"].replace(
            "| department | dept | Yes | FIN-01, OPS-01, HR-01, IT-01, ENG-01 |",
            "| department | division | Yes | NEW-DEPT |")
        documents["dependencies.md"] = "# Dependencies\n\n| Upstream field | Downstream field or report |\n| --- | --- |\n| payroll.department | report:pilot_department_summary |\n"
        preview = self.workspace.preview_references({"reference_documents": documents})
        self.assertTrue(preview["ready"], preview["errors"])
        payload = self.upload_payload(documents, preview)
        rows = list(csv.DictReader(io.StringIO((self.source / "payroll.csv").read_text())))
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=["division" if key == "dept" else key for key in rows[0]])
        writer.writeheader()
        writer.writerows({("division" if key == "dept" else key): value for key, value in row.items()} for row in rows)
        payload["files"]["payroll"] = base64.b64encode(buffer.getvalue().encode()).decode()
        before = {p.name: p.read_bytes() for p in self.source.glob("*.csv")}
        job = self.workspace.start_analysis(payload)
        self.workspace.executor.shutdown(wait=True)
        completed = self.workspace.jobs[job["id"]]
        self.assertEqual(completed["status"], "complete", completed)
        context = self.workspace.context(completed["run"])
        self.assertEqual(context.policy["sources"]["payroll"]["domains"]["department"], ["NEW-DEPT"])
        payroll_rows = context.source_rows["payroll"]
        self.assertTrue(all(row["field_columns"]["department"] == ["division"] for row in payroll_rows))
        invalid = [i for i in context.issues if i["source_system"] == "payroll" and i["field"] == "department" and i["issue_type"] == "invalid_code"]
        self.assertTrue(invalid)
        self.assertTrue(all(i["recommendation_status"] == "investigate" for i in invalid))
        self.assertTrue(all(i["dependencies"] == ["report:pilot_department_summary"] for i in invalid))
        self.assertTrue(all(i["priority_base_score"] == 77 for i in invalid))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.glob("*.csv")})
        imported = json.loads((context.directory / "reference_import.json").read_text())
        self.assertTrue(imported["reviewed"])
        self.assertEqual(imported["digest"], preview["digest"])
        self.assertFalse(context.policy["reports"]["definitions_approved"])
        for name, content in documents.items():
            self.assertEqual((context.directory / "reference_documents" / name).read_bytes(), content.encode())
            status, data, _ = self.request("/api/download?" + urlencode({"run": completed["run"], "file": "reference_documents/" + name}))
            self.assertEqual(status, 200)
            self.assertEqual(data, content.encode())

    def test_unsupported_reference_files_block_analysis_instead_of_using_demo_rules(self):
        documents = {"data_dictionary.md": "# Dictionary\nAsk someone which system to trust.", "dependencies.md": "# Dependencies\nVarious systems depend on one another."}
        preview = self.workspace.preview_references({"reference_documents": documents})
        self.assertFalse(preview["ready"])
        status, error, _ = self.json_request("/api/analyze", self.upload_payload(documents, preview))
        self.assertEqual(status, 400)
        self.assertIn("Reference files need correction", error["error"])
        self.assertFalse(self.workspace.jobs)


if __name__ == "__main__":
    unittest.main()
