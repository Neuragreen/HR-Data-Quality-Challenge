# Demonstrating a fifth HR source

The optional synthetic benefits-administration example demonstrates adding a source through configuration. It reuses the existing employee model, matching, determination, issue rules and impact calculations. Those engine modules do not contain benefits-specific logic. The source configuration and synthetic generator supply the new system's presentation and provisional business assumptions.

## Run from the browser

1. Open **Sources & analysis**.
2. Under **Run a new analysis**, choose **Five-source onboarding demo**.
3. Use report date **1 October 2026**, then select **Run analysis**.
4. On Overview, inspect **27 source records**, **5 connected source extracts**, **7 findings** and **3 supported proposals**.
5. Open **Issue queue**, select **Benefits administration** in the source filter, and inspect Laila Mansour's missing department.
6. Evidence shows benefits alongside Core HR, payroll, learning and the directory. Core HR supports `ENG-01` for the same employment.
7. Calculate the impact preview, then inspect the declared benefits report separately from the three calculated report effects. No decision or source update is performed by running this demo.

The pack is generated locally under `datasets/onboarding/` on first use. Existing and incomplete packs are preserved rather than overwritten. The built-in example imports its references with human review explicitly **not recorded**; its policy remains provisional.

## Exercise custom upload with a new source

After preparing the built-in example:

1. Choose **Upload synthetic CSVs** on Sources & analysis.
2. Load `datasets/onboarding/policy.json` in the optional source configuration control. The form changes from four CSV inputs to five, adding Benefits administration.
3. Select the five CSVs under `datasets/onboarding/input/`. Existing selections are retained for sources whose keys and configured filenames are unchanged.
4. Select that folder's `data_dictionary.md` and `dependencies.md`, preview **54 field definitions and 34 paths**, and inspect the inherited business assumptions.
5. Confirm the reference review and synthetic-data declaration, then run analysis.
6. Inspect source cards, filtering, employee evidence, field trust, suggested fixes, impact previews and the issue CSV export for the new source.

For a fresh copy of the example files without starting analysis:

```bash
python3 generate_onboarding_demo.py --output datasets/onboarding
```

Use a new output directory if the pack already exists. This script creates local CSVs and reference documents; it does not upload them or read an evaluation answer key.

## What differs in the new source

| Property | Benefits presentation |
| --- | --- |
| Identifier | Independent opaque `benefit_member_no` values |
| Name | `member_full_name`, including reordered name tokens |
| Department | `cost_centre` |
| Job | `plan_job` |
| Location | `service_city`, including `DXB_BEN` and `LON_BEN` translations |
| Dates | `YYYY/MM/DD`, including `joined_on` and `record_refreshed_on` |
| Profile grain | One benefit membership per employment; duplicate identifiers still require review |
| Field authority | Core HR, with benefits added explicitly as a comparable source for applicable fields |
| Dependency | `report:benefits_eligibility_summary`, declared potential exposure only |

## Expected evidence

Five anchor people have observations in all five systems. A sixth person exists only in benefits and remains a separate identity. There are seven benefits observations because one membership is duplicated. The six issue cases below produce seven finding rows:

| Case | Finding | Expected outcome |
| --- | --- | --- |
| Laila Mansour | Missing department | Propose `ENG-01` with Core HR evidence |
| Omar Haddad | Invalid job code | Propose `ANALYST` with Core HR evidence |
| Sara Nasser | Conflicting location | Propose `DUBAI` with Core HR evidence |
| Maya Salim | Duplicate membership identifier on two rows | Two findings requiring investigation; no guessed deletion |
| Ravi Mehta | Old record update date | Investigate; age alone does not establish a replacement |
| Nora Faris | Missing department without an authoritative employee match | Investigate without a guessed value |

The Laila scenario has zero delta in the three implemented reports: Dubai headcount remains 4, enabled-leaver accounts remain 0, and payroll discrepancies remain 0. The benefits eligibility report is shown as potential exposure **without an executable calculation**. This is not a claim that the proposed fix has no effect in the benefits application. No application propagation or monetary estimate is inferred.

## Reuse boundary

For another source using the supported employee fields, configure a stable source key, display name, unique CSV filename, field aliases, required fields, date formats, code lists, value translations, row grain and freshness policy. Add it to applicable authority comparison lists, timing allowances and declared dependencies. The upload form, source cards, filters and evidence derive from that configuration.

Unfamiliar business fields, report formulas, file types or live APIs may still require an adapter, model extension or calculator. The example establishes reuse for another CSV source within the current employee model; it does not establish support for every HR application or independent detection accuracy.
