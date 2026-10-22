"""Local browser workbench backed by the deterministic engine. No external services."""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import mimetypes
import secrets
import threading
from copy import deepcopy
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .audit import record_decision, verify_events
from .models import MatchResult, Snapshot
from .pipeline import analyze
from .policy import load_policy, validate_policy
from .reference_docs import preview_references
from .questions import answer_question
from .scenario import simulate_patch


PROJECT = Path(__file__).resolve().parents[2]
STATIC = PROJECT / "ui"
SOURCE_NAMES = {"core_hr": "Core HR", "payroll": "Payroll", "learning": "Learning", "access_directory": "Access directory"}
REPORT_NAMES = {"active_headcount_dubai": "Active employees in Dubai", "leaver_enabled_accounts": "Leavers with enabled accounts", "payroll_reconciliation": "Payroll reconciliation exceptions"}
DOWNLOADS = {"issues.csv", "employees.csv", "field_trust.csv", "impact_simulations.json", "review.md", "reports.json", "decisions.jsonl", "policy.json", "reference_import.json", "reference_documents/data_dictionary.md", "reference_documents/dependencies.md"}
BUILTIN_PACKS = {"development": {"n": 5000, "seed": 401}, "validation": {"n": 1500, "seed": 902}, "onboarding": None}


def ensure_builtin_pack(project, mode):
    """Prepare local demo inputs on a clean checkout without replacing a pack."""
    if mode not in BUILTIN_PACKS:
        raise ValueError("Unknown built-in synthetic pack")
    root = Path(project) / "datasets" / mode
    if mode == 'onboarding':
        required = [root / 'input' / filename for filename in ('core_hr.csv', 'payroll.csv', 'learning.csv', 'access_directory.csv', 'benefits.csv', 'data_dictionary.md', 'dependencies.md')]
        required.append(root / 'policy.json')
        if all(path.is_file() for path in required):
            return
        if root.exists() and any(root.iterdir()):
            raise ValueError('The onboarding pack is incomplete. Existing files were preserved; restore the missing files or use a fresh pack directory.')
        from .onboarding import generate_onboarding_pack
        generate_onboarding_pack(root)
        return
    names = ("core_hr.csv", "payroll.csv", "learning.csv", "access_directory.csv")
    if all((root / "input" / name).is_file() for name in names):
        return
    if any((root / "input" / name).exists() for name in names):
        raise ValueError("The built-in pack is incomplete. Existing source files were preserved; restore the missing files or use a fresh pack directory.")
    from .synthetic import generate_pack
    generate_pack(root, profile=mode, **BUILTIN_PACKS[mode])


def source_descriptors(policy):
    return [{"source_system": key, "name": config.get('display_name') or SOURCE_NAMES.get(key, key.replace('_', ' ').title()),
             "filename": config['filename'], "mapping": config['fields']}
            for key, config in policy['sources'].items()]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def paginate(rows, params):
    size = max(1, min(100, int(params.get("size", "25"))))
    pages = max(1, (len(rows) + size - 1) // size)
    page = max(1, min(pages, int(params.get("page", "1"))))
    return {"items": rows[(page - 1) * size:page * size], "total": len(rows), "page": page, "pages": pages, "size": size}


class AnalysisContext:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.summary = read_json(self.directory / "summary.json")
        self.policy = read_json(self.directory / "policy.json")
        self.snapshot = Snapshot(**read_json(self.directory / "snapshot.json"))
        self.matches = MatchResult(**read_json(self.directory / "identity.json"))
        self.issues = read_json(self.directory / "issues.json")
        self.reports = read_json(self.directory / "reports.json")
        self.resolutions = read_json(self.directory / "resolved_fields.json")
        self.by_id = {r["record_id"]: r for r in self.snapshot.records}
        self.issue_by_id = {r["issue_id"]: r for r in self.issues}
        self.people = defaultdict(list)
        self.source_rows = defaultdict(list)
        for row in self.snapshot.records:
            self.people[self.matches.assignments[row["record_id"]]["person_id"]].append(row)
            self.source_rows[row["source_system"]].append(row)
        self.person_summaries = {}
        issue_counts = Counter(i["person_id"] for i in self.issues)
        for person_id, rows in self.people.items():
            representative = next((r for r in rows if r["source_system"] == "core_hr"), rows[0])
            statuses = {self.matches.assignments[r["record_id"]]["status"] for r in rows}
            status = "review_required" if "review_required" in statuses else "linked" if "linked" in statuses else "single_source"
            self.person_summaries[person_id] = {"person_id": person_id, "name": representative["values"].get("name") or "Unnamed profile", "sources": sorted({r["source_system"] for r in rows}), "record_count": len(rows), "status": status, "issue_count": issue_counts[person_id], "source_ids": [r["source_id"] for r in rows if r["source_id"]], "location": representative["values"].get("location")}

    def events(self):
        path = self.directory / "decisions.jsonl"
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
        verify_events(events)
        return events

    def latest_decisions(self):
        return {event["issue_id"]: event for event in self.events()}

    def issue_view(self, issue, decisions=None):
        view = dict(issue)
        person = self.person_summaries.get(issue["person_id"], {})
        view["employee_name"] = person.get("name", "Unnamed profile")
        event = (decisions if decisions is not None else self.latest_decisions()).get(issue["issue_id"])
        view["review_status"] = event["decision"] if event else "open"
        view["last_decision"] = event
        return view

    def issues_list(self, params):
        decisions = self.latest_decisions()
        search = params.get("q", "").casefold()
        rows = []
        for issue in self.issues:
            view = self.issue_view(issue, decisions)
            if any(params.get(key) and str(view.get(key)) != params[key] for key in ("source_system", "issue_type", "priority_band", "review_status", "recommendation_status")):
                continue
            if search and search not in " ".join(str(view.get(key, "")) for key in ("employee_name", "source_id", "issue_id", "field", "issue_type")).casefold():
                continue
            rows.append(view)
        return paginate(rows, params)

    def issue_detail(self, issue_id):
        issue = self.issue_by_id.get(issue_id)
        if not issue:
            raise KeyError("Issue not found")
        ids = issue["evidence"]["source_record_ids"]
        # Include the other matched observations so comparison evidence is inspectable.
        records = self.people.get(issue["person_id"], [])
        return {"issue": self.issue_view(issue), "records": [{**row, "assignment": self.matches.assignments[row["record_id"]], "supports_issue": row["record_id"] in ids} for row in records], "resolutions": [r for r in self.resolutions if r["person_id"] == issue["person_id"] and r["field"] == issue["field"]], "authority": self.policy.get("authority", {}).get(issue["field"]), "policy_version": self.policy["policy_version"]}

    def simulate(self, issue_id):
        issue = self.issue_by_id.get(issue_id)
        if not issue or issue["recommendation_status"] != "proposed":
            raise ValueError("This issue needs investigation; there is no supported correction to simulate.")
        row = self.by_id[issue["record_id"]]
        patch = {"record_id": row["record_id"], "field": issue["field"], "expected_value": row["values"].get(issue["field"]), "value": issue["suggested_value"]}
        return simulate_patch(self.snapshot, self.matches, self.policy, self.summary["as_of"], patch)

    def overview(self):
        decisions = self.latest_decisions()
        with (self.directory / "field_trust.csv").open(newline="", encoding="utf-8") as handle:
            trust = list(csv.DictReader(handle))
        reports = {key: {k: v for k, v in value.items() if k not in {"contributors", "people", "unresolved", "cases"}} | {"unresolved_count": len(value["unresolved"]), "contributor_count": len(value["contributors"])} for key, value in self.reports.items()}
        return {"summary": self.summary, "reports": reports, "sources": self.sources(), "priority_counts": dict(Counter(i["priority_band"] for i in self.issues)), "business_counts": dict(Counter(i["business_impact"] for i in self.issues)), "open_count": sum(i["issue_id"] not in decisions for i in self.issues), "decision_counts": dict(Counter(e["decision"] for e in decisions.values())), "top_issues": [self.issue_view(i, decisions) for i in self.issues[:6]], "recent_decisions": self.events()[-5:][::-1], "trust": trust}

    def sources(self):
        issue_counts = Counter(i["source_system"] for i in self.issues)
        result = []
        for source, config in self.policy["sources"].items():
            rows = self.source_rows[source]
            diagnostics = [d for d in self.snapshot.diagnostics if d.get("source_system") == source]
            definitions = [d for d in self.policy.get("reference_import", {}).get("definitions", []) if d.get("source") == source]
            result.append({"source_system": source, "name": config.get("display_name") or SOURCE_NAMES.get(source, source.replace("_", " ").title()), "filename": config["filename"], "records": len(rows), "fields": len(rows[0]["raw"]) if rows else 0, "issues": issue_counts[source], "diagnostics": diagnostics, "date_formats": config.get("date_formats", []), "mapping": config["fields"], "required": config.get("required", []), "definitions": definitions, "record_grain": config.get("record_grain", "Configured source observation"), "sample": [r["raw"] for r in rows[:5]], "status": "needs_review" if diagnostics else "loaded" if rows else "missing"})
        return result


class Workspace:
    def __init__(self, project=PROJECT):
        self.project = Path(project).resolve()
        self.csrf = secrets.token_hex(24)
        self.cache = {}
        self.lock = threading.RLock()
        self.jobs = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hr-analysis")

    def runs(self):
        runs = []
        for key, label in (("development", "Development · 5,000 people"), ("validation", "Validation · 1,500 people")):
            directory = self.project / "analysis_outputs" / key
            if (directory / "summary.json").is_file():
                summary = read_json(directory / "summary.json")
                runs.append({"id": key, "label": label, "as_of": summary["as_of"], "records": summary["source_record_count"]})
        for directory in sorted((self.project / ".ui_runs").glob("run-*/analysis"), reverse=True):
            if (directory / "summary.json").is_file():
                summary = read_json(directory / "summary.json")
                metadata_path = directory.parent / 'run.json'
                metadata = read_json(metadata_path) if metadata_path.is_file() else {}
                runs.append({"id": directory.parent.name, "label": metadata.get('label') or "New analysis · " + directory.parent.name[4:12], "as_of": summary["as_of"], "records": summary["source_record_count"]})
        return runs

    def directory(self, key):
        if key in {"development", "validation"}:
            return self.project / "analysis_outputs" / key
        if key.startswith("run-") and len(key) == 20 and all(c in "0123456789abcdef" for c in key[4:]):
            return self.project / ".ui_runs" / key / "analysis"
        raise ValueError("Unknown analysis run. The reserved final pack is not exposed in this workbench.")

    def context(self, key):
        directory = self.directory(key)
        with self.lock:
            if key not in self.cache:
                self.cache[key] = AnalysisContext(directory)
            return self.cache[key]

    def preview_references(self, payload):
        supplied = payload.get("policy")
        base = validate_policy(deepcopy(supplied)) if supplied is not None else load_policy(self.project / "config" / "demo_policy.json")
        preview = preview_references(base, payload.get("reference_documents"))
        if preview["ready"]:
            validate_policy(preview["policy"])
        return preview

    def source_configuration(self, payload):
        supplied = payload.get('policy')
        policy = validate_policy(deepcopy(supplied)) if supplied is not None else load_policy(self.project / 'config' / 'demo_policy.json')
        return {'policy_version': policy['policy_version'], 'sources': source_descriptors(policy)}

    def start_analysis(self, payload):
        if payload.get("synthetic_confirmed") is not True:
            raise ValueError("Confirm that the input contains synthetic employee data only.")
        as_of = payload.get("as_of", "2026-10-01")
        date.fromisoformat(as_of)
        with self.lock:
            if any(job["status"] == "running" for job in self.jobs.values()):
                raise ValueError("An analysis is already running. Please wait for it to finish.")
            key = "run-" + secrets.token_hex(8)
            root = self.project / ".ui_runs" / key
            root.mkdir(parents=True)
            mode = payload.get("mode", "development")
            if mode in {"development", "validation"}:
                input_dir = self.project / "datasets" / mode / "input"
                policy = load_policy(self.project / "config" / "demo_policy.json")
            elif mode == 'onboarding':
                ensure_builtin_pack(self.project, mode)
                pack = self.project / 'datasets' / mode
                input_dir = pack / 'input'
                documents = {name: (input_dir / name).read_bytes().decode('utf-8') for name in ('data_dictionary.md', 'dependencies.md')}
                preview = preview_references(load_policy(pack / 'policy.json'), documents)
                if not preview['ready']:
                    raise ValueError('Onboarding references need correction: ' + '; '.join(preview['errors']))
                policy = preview['policy']
                policy['reference_import'].update(reviewed=False, review_method='provisional_synthetic_demo')
                reference_root = root / 'reference_documents'
                reference_root.mkdir()
                for filename, content in documents.items():
                    (reference_root / filename).write_bytes(content.encode('utf-8'))
            elif mode == "upload":
                supplied_policy = payload.get("policy")
                if supplied_policy is not None and not isinstance(supplied_policy, dict):
                    raise ValueError("A reviewed policy must be a JSON object")
                policy = validate_policy(deepcopy(supplied_policy)) if supplied_policy is not None else load_policy(self.project / "config" / "demo_policy.json")
                documents = payload.get("reference_documents")
                if documents is not None:
                    preview = self.preview_references(payload)
                    if not preview["ready"]:
                        raise ValueError("Reference files need correction: " + "; ".join(preview["errors"]))
                    if payload.get("references_reviewed") is not True:
                        raise ValueError("Preview and review the extracted definitions and dependencies before analysis.")
                    if payload.get("reference_digest") != preview["digest"]:
                        raise ValueError("Reference files or the base policy changed. Preview and review them again.")
                    policy = preview["policy"]
                    policy["reference_import"].update(reviewed=True, reviewed_at=datetime.now(timezone.utc).isoformat(), review_method="local_browser_confirmation")
                    reference_root = root / "reference_documents"
                    reference_root.mkdir()
                    for filename, content in documents.items():
                        (reference_root / filename).write_bytes(content.encode("utf-8"))
                (root / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
                input_dir = root / "input"
                input_dir.mkdir()
                files = payload.get("files", {})
                if set(files) != set(policy["sources"]):
                    raise ValueError("Provide exactly one CSV for every source in the selected policy.")
                for source, config in policy["sources"].items():
                    content = base64.b64decode(files[source], validate=True)
                    if not content or len(content) > 12 * 1024 * 1024:
                        raise ValueError("Each CSV must be nonempty and no larger than 12 MB.")
                    target = input_dir / config["filename"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            else:
                raise ValueError("Choose a supported dataset or upload synthetic sources.")
            self.jobs[key] = {"id": key, "status": "running", "stage": "Preparing source files", "error": None}
            label = 'Five-source demo · Benefits administration' if mode == 'onboarding' else None
            (root / 'run.json').write_text(json.dumps({'mode': mode, 'label': label}))
        def work():
            try:
                def progress(stage):
                    with self.lock:
                        self.jobs[key]["stage"] = stage
                if mode in BUILTIN_PACKS:
                    progress("Preparing built-in synthetic data locally")
                    ensure_builtin_pack(self.project, mode)
                analyze(input_dir, policy, as_of, root / "analysis", simulation_limit=3, progress=progress)
                reference_root = root / "reference_documents"
                if reference_root.is_dir():
                    archived = root / "analysis" / "reference_documents"
                    archived.mkdir()
                    for document in reference_root.iterdir():
                        (archived / document.name).write_bytes(document.read_bytes())
                with self.lock:
                    self.jobs[key].update(status="complete", stage="Analysis complete", run=key)
            except Exception as exc:
                with self.lock:
                    self.jobs[key].update(status="failed", stage="Analysis could not complete", error=str(exc))
        self.executor.submit(work)
        return dict(self.jobs[key])


class Handler(BaseHTTPRequestHandler):
    server_version = "HRTrustGraph/1.0"

    @property
    def workspace(self):
        return self.server.workspace

    def log_message(self, fmt, *args):
        # No employee values or uploaded contents are logged.
        if args and str(args[0]).startswith("POST"):
            return

    def send_content(self, content, content_type="application/json; charset=utf-8", status=200, headers=None):
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False).encode("utf-8")
        elif isinstance(content, str):
            content = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def check_host(self):
        host = self.headers.get("Host", "")
        return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def do_GET(self):
        try:
            if not self.check_host():
                raise PermissionError("This workbench accepts local browser connections only.")
            parsed = urlsplit(self.path)
            params = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
            path = parsed.path
            if path in {"/", "/index.html", "/app.js", "/styles.css"}:
                filename = "index.html" if path in {"/", "/index.html"} else path[1:]
                self.send_content((STATIC / filename).read_bytes(), mimetypes.guess_type(filename)[0] or "text/plain")
                return
            if path == "/api/health":
                self.send_content({"status": "ok", "ai_used": False})
                return
            if path == "/api/bootstrap":
                self.send_content({"csrf": self.workspace.csrf, "runs": self.workspace.runs(), "source_names": SOURCE_NAMES, "report_names": REPORT_NAMES, "upload_sources": source_descriptors(load_policy(self.workspace.project / 'config' / 'demo_policy.json'))})
                return
            if path == "/api/job":
                with self.workspace.lock:
                    job = self.workspace.jobs.get(params.get("id"))
                    if not job:
                        raise KeyError("Analysis job not found")
                    self.send_content(dict(job))
                return
            context = self.workspace.context(params.get("run", "development"))
            if path == "/api/overview":
                result = context.overview()
            elif path == "/api/issues":
                result = context.issues_list(params)
            elif path == "/api/issue":
                result = context.issue_detail(params.get("id"))
            elif path == "/api/employees":
                rows = list(context.person_summaries.values())
                query, status = params.get("q", "").casefold(), params.get("status")
                rows = [r for r in rows if (not status or r["status"] == status) and (not query or query in (r["name"] + " " + r["person_id"] + " " + " ".join(r["source_ids"])).casefold())]
                rows.sort(key=lambda r: (r["name"].casefold(), r["person_id"]))
                result = paginate(rows, params)
            elif path == "/api/employee":
                person_id = params.get("id")
                if person_id not in context.people:
                    raise KeyError("Employee group not found")
                records = context.people[person_id]
                ids = {r["record_id"] for r in records}
                candidates = [c for c in context.matches.candidates if c["record_id_a"] in ids or c["record_id_b"] in ids]
                result = {"employee": context.person_summaries[person_id], "records": [{**r, "assignment": context.matches.assignments[r["record_id"]]} for r in records], "candidates": sorted(candidates, key=lambda c: -c["score"])[:30], "resolutions": [r for r in context.resolutions if r["person_id"] == person_id], "issues": [context.issue_view(i) for i in context.issues if i["person_id"] == person_id]}
            elif path == "/api/reports":
                result = {key: {**report, "cases": report.get("cases", [])[:100], "contributors": report["contributors"][:100], "unresolved": report["unresolved"][:100], "contributor_count": len(report["contributors"]), "unresolved_count": len(report["unresolved"])} for key, report in context.reports.items()}
                for report in result.values():
                    report["contributor_details"] = [{"record_id": rid, "source_system": context.by_id[rid]["source_system"], "source_id": context.by_id[rid]["source_id"], "person_id": context.matches.assignments[rid]["person_id"], "name": context.by_id[rid]["values"].get("name")} for rid in report["contributors"]]
            elif path == "/api/sources":
                result = {"sources": context.sources(), "policy": context.policy, "reference_import": context.policy.get("reference_import"), "diagnostics": context.snapshot.diagnostics}
            elif path == "/api/audit":
                result = {"events": context.events()[::-1], "integrity": "verified", "source_files_changed": False}
            elif path == "/api/download":
                name = params.get("file")
                if name not in DOWNLOADS:
                    raise ValueError("This file is not available for export")
                if name == "decisions.jsonl":
                    context.events()
                target = context.directory / name
                if not target.is_file():
                    raise ValueError("This export is not available for the selected analysis.")
                self.send_content(target.read_bytes(), mimetypes.guess_type(name)[0] or "application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{target.name}"'})
                return
            else:
                raise KeyError("Page not found")
            self.send_content(result)
        except PermissionError as exc:
            self.send_content({"error": str(exc)}, status=403)
        except (ValueError, TypeError) as exc:
            self.send_content({"error": str(exc)}, status=400)
        except (KeyError, FileNotFoundError) as exc:
            self.send_content({"error": str(exc).strip("'")}, status=404)
        except Exception:
            self.send_content({"error": "This view could not be loaded. Check that the analysis files are complete."}, status=500)

    def do_POST(self):
        try:
            if not self.check_host() or self.headers.get("X-HR-Workspace") != self.workspace.csrf:
                raise PermissionError("Refresh the workbench before submitting this request.")
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://localhost:{self.server.server_port}", f"http://127.0.0.1:{self.server.server_port}"}:
                raise PermissionError("Requests must come from this local workbench.")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 64 * 1024 * 1024:
                raise ValueError("Request size is outside the supported limit")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Request must contain a JSON object")
            path = urlsplit(self.path).path
            if path == "/api/analyze":
                result = self.workspace.start_analysis(data)
            elif path == "/api/references/preview":
                result = self.workspace.preview_references(data)
            elif path == '/api/sources/preview':
                result = self.workspace.source_configuration(data)
            else:
                context = self.workspace.context(data.get("run", "development"))
                if path == "/api/simulate":
                    result = context.simulate(data.get("issue_id"))
                elif path == "/api/decision":
                    if data.get("decision") == "approve":
                        context.simulate(data.get("issue_id"))
                    result = record_decision(context.directory, data.get("issue_id"), data.get("decision"), str(data.get("reviewer", "")), str(data.get("reason", "")))
                elif path == "/api/question":
                    result = answer_question(context.reports, data.get("question", ""))
                else:
                    raise KeyError("Action not found")
            self.send_content(result)
        except PermissionError as exc:
            self.send_content({"error": str(exc)}, status=403)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self.send_content({"error": str(exc).strip("'")}, status=400)
        except Exception:
            self.send_content({"error": "The action could not complete. Please refresh and check the selected analysis."}, status=500)


def create_server(project=PROJECT, port=8765, host="127.0.0.1"):
    server = ThreadingHTTPServer((host, port), Handler)
    server.workspace = Workspace(project)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description="Open the local HR TrustGraph workbench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", type=Path, default=PROJECT, help="Local pack and analysis-history directory; defaults to this checkout")
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1", help="Use 0.0.0.0 only inside an isolated container; the default is local-only")
    args = parser.parse_args()
    project = args.workspace.resolve()
    if not (project / "config" / "demo_policy.json").is_file():
        parser.error("The workspace must contain config/demo_policy.json")
    if not (project / "datasets" / "development" / "input" / "core_hr.csv").is_file():
        print("Preparing the built-in synthetic data pack…", flush=True)
        ensure_builtin_pack(project, "development")
    server = create_server(project=project, port=args.port, host=args.host)
    print(f"HR TrustGraph is ready at http://127.0.0.1:{server.server_port}", flush=True)
    print("Synthetic data only. Source data is read-only. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.workspace.executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
