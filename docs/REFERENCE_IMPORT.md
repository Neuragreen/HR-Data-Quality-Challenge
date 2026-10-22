# Importing the challenge reference files

The prototype reads `data_dictionary.md` and `dependencies.md` locally. A deterministic parser extracts explicit structured declarations. No file is sent to a language model or external service. The examples under [`data/`](../data/) and newly generated synthetic packs use the supported format.

## Browser workflow

In **Sources & analysis → Run a new analysis**, select upload mode. If adding a system, load its reviewed source configuration first; the CSV controls follow the source list, with four sources in the default policy. Add one synthetic CSV for each listed system and both Markdown files, then preview the reference files. The preview shows fields and their source columns, required values, valid codes, dependency paths and the corresponding document lines. Correct any errors and review the retained policy assumptions. Confirm the review before starting the analysis. Selecting a different reference file or policy requires a fresh preview.

The Markdown changes are executable: imported aliases control how CSV columns are read, required flags and valid code lists control validation, and imported dependency paths control declared downstream exposure and its contribution to priority. The parser does not discover data lineage by inspecting application code. Only the three implemented report calculations have measured numeric effects; other declared report paths show potential exposure.

If the references use an unsupported layout or include ambiguous declarations, the preview reports errors. Convert the declarations into the documented tables, preserving their meaning, or supply a reviewed base policy for unfamiliar source or field mappings. The import is not a general natural-language interpreter.

## Dictionary structure

Use a heading for each configured source and a Markdown field table. The semantic field names must be supported by the employee model; the base policy can configure source names and aliases. `Source columns` lists exact CSV headers, separated by commas. `Required` uses `Yes` or `No`. Valid values are comma-separated exact codes; an empty cell means no enumerated domain. A description is optional.

```markdown
### payroll

Dates: %d/%m/%Y, %Y-%m-%d.

| Semantic field | Source columns | Required | Valid values | Description |
| --- | --- | --- | --- | --- |
| source_id | emp_id | Yes | | Payroll-local observation identifier |
| name | employee_name | Yes | | Display name |
| department | dept | Yes | FIN-01, OPS-01, HR-01 | Payroll department code |
| payroll_status | payroll_status | Yes | ELIGIBLE, FINAL_SETTLEMENT, INACTIVE | Payroll processing state |
| location | office_location | Yes | DUBAI, LONDON | Work location |

Value mappings: `{"location": {"DXB": "DUBAI"}}`.
```

Include the full field table for every source being redefined: a source table replaces its prior aliases, required list and code domains. Preserve identity and report inputs you still need. Explicit value mappings are JSON objects from source presentations to canonical codes. Date formats use Python `strptime` notation. Unknown sources, unknown semantic fields, contradictory declarations and invalid code definitions require review rather than silently applying partial results.

Plain explanatory prose is retained with the source files but is not interpreted as authority, report logic, source grain or timing policy. The preview discloses which business rules remain inherited from the selected base policy. Importing references keeps report definitions provisional; it does not certify a report for publication.

## Dependency structure

Use explicit fields and known report identifiers. A field can use a canonical name or its configured source alias. Prefix report identifiers with `report:`.

```markdown
| Upstream field | Downstream field or report |
| --- | --- |
| core_hr.department | payroll.dept |
| core_hr.employment_status | report:active_headcount_dubai |
| payroll.department | report:payroll_reconciliation |
```

Standalone arrow declarations are also supported:

```text
core_hr.department -> payroll.dept
access_directory.account_status -> report:leaver_enabled_accounts
```

The imported graph replaces the prior graph. Omitted paths are not assumed to exist. A new explicit `report:identifier` may be shown as a potential dependency, but it does not add a new report calculator.

## Command-line workflow

Preview first; the optional candidate output must be a new JSON file:

```bash
python3 -m hrtrustgraph.deterministic import-references --dictionary INPUT/data_dictionary.md --dependencies INPUT/dependencies.md --output candidate-policy.json
```

The command prints changes, source lines, document hashes and retained assumptions without reading employee CSVs. It refuses a candidate output if parsing is incomplete or ambiguous. The candidate is for inspection; it is not evidence that a business owner approved the semantics.

After review, execute:

```bash
python3 -m hrtrustgraph.deterministic analyze --input INPUT --output OUTPUT --as-of 2026-10-01 --dictionary INPUT/data_dictionary.md --dependencies INPUT/dependencies.md --accept-reference-import
```

Use `--policy reviewed-policy.json` in both commands when adapting the base business rules. Both Markdown files are required for this workflow. `--accept-reference-import` records the caller's explicit confirmation; it does not authenticate their identity or approve employee corrections.

Outputs include `policy.json`, `reference_import.json` and the original Markdown copies under `reference_documents/`. The input bytes remain unchanged. Keep these outputs and challenge documents local with the synthetic CSVs; do not force-add them to Git.
