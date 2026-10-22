# HR Data Quality Challenge — HR TrustGraph

The current implementation is an offline, deterministic analysis and determination engine. It uses Python 3.10+ standard libraries only. It needs no API key, external service, model or package installation. All generated demo inputs are synthetic. This repository contains source code and a local data generator; employee datasets, answer keys, analysis outputs and data-bearing screenshots are excluded from Git.

## Open the browser UI

```bash
git clone https://github.com/Neuragreen/HR-Data-Quality-Challenge.git
cd HR-Data-Quality-Challenge
python3 run_ui.py
```

Open **http://127.0.0.1:8765**. No package installation or API key is needed. `python3 app.py` launches the same workbench. The first launch generates the development pack locally and runs its analysis from the browser. The validation pack is generated locally when first selected. No data download is needed.

The UI includes an overview, a filterable issue queue, source evidence and original observations, an isolated impact preview, human review decisions, employee matching, report contributors and uncertainty, field-quality indicators, source mappings, CSV and Markdown reference upload, new-analysis progress and audit/export views. It is responsive and works in a narrow browser panel or a full browser window.

To demonstrate adding a system, choose **Sources & analysis → Five-source onboarding demo → Run analysis** with report date 1 October 2026. It adds a synthetic benefits-administration source, producing 27 source records, seven findings and three supported proposals. Custom upload fields follow the selected source configuration, including added systems. See the [repeatable fifth-source walkthrough](SOURCE_ONBOARDING.md). This small example demonstrates source reuse, not independent matching or detection accuracy.

Use **Sources & analysis → Run a new analysis** to select a built-in pack or upload all four synthetic CSVs, `data_dictionary.md` and `dependencies.md`. Preview the extracted fields, valid codes and downstream paths, then confirm your review before analysing the uploaded references. A reviewed JSON policy is optional for other business rules. Uploads and generated results remain in `.ui_runs/` on this machine. The reserved final pack is not exposed in the UI. Approving a proposal records a decision; it never changes source data.

Each analysis has its own persistent, hash-chained review history. Reviewer names identify local decisions but are not authenticated enterprise identities. The server binds to the local loopback interface by default. Stop it with Ctrl+C in its terminal.

When updating the source checkout, `python3 run_ui.py --workspace /path/to/existing-workspace` can reuse local packs and analysis history without copying them into the repository. That workspace must contain `config/demo_policy.json`.

Keep the source checkout as the single project folder. Local datasets belong in `datasets/`, saved analyses in `analysis_outputs/` and browser runs in `.ui_runs/`. Judge deliverables are in `submission/`. Private recording scripts, prior artifacts and recovery archives are kept in a separate local folder outside this repository. Generated working directories are excluded from Git and the container build.

For an isolated Docker run:

```bash
docker build -t hr-trustgraph .
docker run --rm -p 127.0.0.1:8765:8765 -v hr-trustgraph-reviews:/app/.ui_runs hr-trustgraph
```

## Run the engine directly

From this project directory:

```bash
python3 generate_synthetic.py --output datasets/development --n 5000 --seed 401 --profile development
python3 -m hrtrustgraph.deterministic analyze --input datasets/development/input --output analysis_outputs/development --as-of 2026-10-01
```

Skip the generation command if that frozen pack already exists; generation deliberately refuses to overwrite it without an explicit flag.

The locally generated development pack represents 5,000 invented people across four HR sources, including additional legitimate employment history. Results include:

- `review.md`: readable overview, highest-priority issues and report availability.
- `issues.csv` and `issues.json`: full ranked issue queue, supported proposed values, evidence and rules.
- `employees.csv`, `identity.json` and `candidate_links.csv`: identity groups, matching evidence and unresolved candidates.
- `resolved_fields.json`: per-employment field determinations, including abstentions.
- `reports.json`: distinct-person Dubai headcount, leaver enabled-account exceptions and payroll reconciliation exceptions, with source contributors and unresolved cases.
- `impact_simulations.json`: calculated before/after results for the first ten proposed corrections. Any proposed correction can be simulated separately.
- `field_trust.csv`: observed completeness, validity, issue-free fractions and a transparent field trust score.
- `diagnostics.json`, `snapshot.json`, `policy.json` and `summary.json`: source-quality diagnostics and reproducible analysis context.

The engine detects duplicate identifiers, duplicate profiles under different IDs within a declared source grain, missing values, invalid codes, malformed dates, temporal contradictions, cross-system conflicts, records beyond a configured age threshold and possible leaver access. Explanations use evidence templates. Uncertain employee identities or authoritative values require investigation instead of a guessed correction.

## Reporting readiness and trust

Every report separates input availability from reporting readiness. A trust score measures evidence coverage: `100 × assessed cases / source cases`. Missing inputs or an empty population have no score. Unresolved cases require review, and provisional demo definitions keep readiness at **Review required** even when coverage is 100. After a business owner confirms the definitions in the policy, complete results may pass the configured checks; publication is still a human decision. Field scores use the minimum validity and issue-free percentage, with completeness included for required fields only. Optional fields with no observations are not scored. Neither score is a correctness probability.

Ranking combines business severity, declared dependency reach and the measured change in the three executable reports. Every supported fix is measured against a frozen identity grouping; shared source-key peers are included. Priority reasons and CSV exports show the calculation. A payroll exception is a profile discrepancy, not an inferred monetary loss.

## Preview one proposed correction

Choose an `issue_id` from `issues.csv` whose `recommendation_status` is `proposed`:

```bash
python3 -m hrtrustgraph.deterministic simulate --analysis analysis_outputs/development --issue-id ISSUE_ID
```

This recalculates the three implemented reports using one isolated in-memory patch. Declared downstream paths are shown separately from calculated effects. No update is propagated into another application. For an optional saved preview, use a new JSON file inside `analysis_outputs/development/scenarios/` with `--output`.

## Record a human decision

```bash
python3 -m hrtrustgraph.deterministic review --analysis analysis_outputs/development --issue-id ISSUE_ID --decision approve --reviewer "Reviewer name" --reason "Evidence and lifecycle exception checked"
```

Decisions can be `approve`, `reject` or `investigate`. Approval records a decision only. It never executes a correction. The local JSONL history is locked, flushed to disk and hash chained. It is tamper-evident against accidental editing, not an authenticated or immutable enterprise audit service. Decision recording uses Unix file locking on macOS/Linux.

## Ask a supported report question

```bash
python3 -m hrtrustgraph.deterministic question --analysis analysis_outputs/development --text "How many active employees in Dubai?"
python3 -m hrtrustgraph.deterministic question --analysis analysis_outputs/development --text "How many leavers have enabled accounts?"
```

Three report meanings are supported: Dubai active headcount, leaver enabled accounts and payroll reconciliation. These are deterministic questions. Answers disclose sources, the report definition, date, contributing records and unresolved-case count. Other question meanings are rejected rather than guessed.

```bash
python3 -m hrtrustgraph.deterministic question --analysis analysis_outputs/development --text "How many payroll profiles have conflicts?"
```

## Generate and evaluate synthetic packs

The source files are under each pack's `input/`; answer keys live separately under `truth/`. Only pass `input/` to the analyser.

```bash
python3 generate_synthetic.py --output datasets/validation --n 1500 --seed 902 --profile validation
python3 evaluate_analysis.py --output analysis_outputs/development --truth datasets/development/truth --report analysis_outputs/development/evaluation.json
```

Generation starts from people/employments, projects legitimate system differences and then plants controlled errors. IDs are independent opaque source-local values. Source presentations include different headers, names and date formats. The manifest fixes the seed, reference date, generator version and file hashes. Existing packs require an explicit `--overwrite` to regenerate.

`development`, `validation` and `final` profiles use independent populations and different coverage/error mixtures. The original local development workspace also holds a final-reserved pack that has not been used to tune or score this implementation; it is not distributed here. Generate a separate final-profile pack locally and leave it unanalysed while tuning if you want the same evaluation workflow. These are packs from one known generator family, not a genuinely blind external benchmark. Truth separation is a workflow convention, not an access-control boundary. Once test outcomes influence changes, reserve a fresh final pack.

Evaluation reports issue precision/recall by family, identity pair precision/recall and correction precision separately from coverage/abstention. Synthetic scores do not establish accuracy on the official challenge pack.

## Policies and source adaptation

`config/demo_policy.json` owns source mappings, strict date formats, valid values, field ownership, timing allowances, priority weights, measured report-change weights, report definitions and explicit field-level dependencies. Every rule is provisional synthetic policy. Do not infer official Emirates authority from it.

Employment, payroll and directory statuses have separate meanings. Directory account state is never copied from employment status. Source-local employment IDs are not assumed globally shared. Historical and concurrent employments are not automatically employee duplicates.

For this demo, a source-local observation ID is unique within its source snapshot. For a source with repeated person IDs across historical versions, configure `identifier_scope_fields` (for example employment ID and effective-from date) to express the actual row grain.

The app ingests structured Markdown field tables, valid code lists, date formats, value mappings and explicit dependency paths. Imported definitions replace the relevant mappings, required fields and code domains; imported dependencies replace the base graph. A preview exposes source-line evidence, changes, inherited assumptions and errors. Unsupported prose and ambiguous declarations need correction rather than a guessed interpretation. Field authority, source grain, timing and report meanings still require a reviewed base policy. Load the optional source configuration before uploading CSVs to add systems; the upload controls follow its source list and retain selections for unchanged sources. See the [reference-file format and import guide](REFERENCE_IMPORT.md).

To inspect the files without reading employee CSVs:

```bash
python3 -m hrtrustgraph.deterministic import-references --dictionary data/data_dictionary.md --dependencies data/dependencies.md --output candidate-policy.json
```

After reviewing the preview and retained business assumptions, analyse a synthetic pack with its reference files:

```bash
python3 -m hrtrustgraph.deterministic analyze --input datasets/development/input --output analysis_outputs/with_references --as-of 2026-10-01 --dictionary datasets/development/input/data_dictionary.md --dependencies datasets/development/input/dependencies.md --accept-reference-import
```

The original Markdown and CSV files stay unchanged. The analysis saves the compiled policy, reference hashes and source-line evidence, plus copies of the Markdown under `reference_documents/`. Adding an unfamiliar source also requires its filename and applicable authority/report configuration in a reviewed JSON policy. See [the source onboarding guide](SOURCE_ONBOARDING.md).

## Verify the engine

```bash
python3 -m unittest discover -s tests -v
```

These suites cover identity ambiguity and transitive contradictions, date boundaries, multiple employments, abstention, issue evidence, source preservation, report deltas, ingestion diagnostics, audit integrity and evaluator math. The browser API adds tests for real analysis results, filters, evidence, uploads, read-only simulations, local request protection, durable review history and export restrictions.


See [REQUIREMENTS.md](../REQUIREMENTS.md) for the requirement-by-requirement acceptance map.

See [the judging review](JUDGING_REVIEW.md) for evidence and open items against the five weighted criteria, and [the proposed pilot plan](PILOT_PLAN.md) for the staffing, environment and acceptance decisions still needed.

## Repository data boundary

The public repository contains application code, tests, provisional reference documents and the synthetic generator. `.gitignore` and `.dockerignore` exclude input packs, evaluator labels, generated outputs, review history and employee-data screenshots. Keep official challenge packs and any future operational data local; do not force-add them to Git. Tests generate disposable synthetic fixtures locally. The app has no external AI or telemetry service.
