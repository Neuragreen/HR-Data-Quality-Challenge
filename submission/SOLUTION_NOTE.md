# HR TrustGraph: solution note

Employee data reconciliation with evidence, prioritisation and impact previews.

Repository: https://github.com/Neuragreen/HR-Data-Quality-Challenge

## Users and scope

HR TrustGraph gives stewards a ranked issue queue, analytics leads traceable reports, and systems owners impact previews before approval. The browser and Python engine process synthetic HR data locally without external packages, API keys or AI services. Source data stays unchanged. The repository includes setup instructions.

## Data model, imports and matching

People, employments and accounts remain separate. Configured adapters retain raw observations and normalise codes and strict dates. Upload controls follow the selected source configuration. Structured dictionary/dependency imports expose mappings, required fields, valid codes, paths, line evidence and file hashes; ambiguous declarations block import. Authority, source grain, timing and report meanings still require business review. Matching corroborates names, emails and birth dates, checks contradictions and retains uncertain identities. IDs stay source-local; scores are evidence, not probabilities. Legitimate history and concurrent employments are retained.

## Determination and prioritisation

Valid authoritative observations can support a proposed value for the same employment. Missing, invalid, stale or conflicting authority requires investigation without silent fallback. Findings cover duplicates, conflicts, missing values, invalid codes/dates, contradictory periods, old records and potential enabled leaver accounts. Each finding exposes observed/proposed values, source records, matching evidence, rule and policy version. Priority combines business severity, bounded dependency reach and measured report consequences. Unsupported corrections remain investigations.

## Impact and reporting trust

An isolated scenario validates its expected current value and proposed domain/date before recalculating Dubai active headcount, leaver enabled accounts and payroll reconciliation. It shows before/after/delta, changed contributors and unresolved cases. Other dependency paths are potential exposure, not calculated effects. Application propagation and monetary payroll effects are not simulated. Report trust measures assessed-case coverage; field trust uses validity, issue-free fraction and required-field completeness. Optional unobserved fields and unavailable populations have no invented score. Readiness remains separate from input availability.

### Demonstration impact

| Calculated report | Before | After |
| --- | ---: | ---: |
| Dubai active headcount | 1,166 | 1,166 |
| Leaver enabled-account exceptions | 51 | 51 |
| Payroll reconciliation discrepancies | 169 | 168 |

An isolated proposal fills one missing payroll department with OPS-01. Source files remain unchanged.

## Responsible AI and security

The prototype uses no AI or RAG. Every correction requires a human decision and rationale; approval records a decision only. A future AI explanation layer must use approved local services, cite the same evidence and preserve human control. Synthetic input packs and run history stay local. Two explicitly labelled synthetic issue exports are included for judge review; no official-pack results are claimed. No external AI or telemetry calls are made. Review history records issue, time, reviewer, snapshot, policy and proposed value using locking and a hash chain. Reviewer names are not authenticated and the log is not immutable enterprise storage. Uncertain identities remain for review; cross-script transliteration is not inferred.

## Reuse and deployment inside Emirates

The four challenge sources are the default. A fifth synthetic benefits system is demonstrated through configuration-driven upload, matching, findings, impact preview and export: 27 records, seven findings and three supported proposals. Its benefits-report path is potential exposure without a calculator; existing report totals stay unchanged. New fields, formats or report formulas may require extensions. Deploy Python 3.10+ or the supplied container on an approved internal host with read-only inputs, separate run/audit storage and approved egress controls. Business owners must confirm policy semantics. A pilot needs named owners, capacity, enterprise identity/permissions, protected audit storage, retention controls and approved connectors. These integrations and commitments are not confirmed.

## Validation and limits

The repository passed 140 automated checks, including reference imports, fifth-source onboarding, abstention, source preservation, exports and impact. The small benefits example demonstrates reuse, not independent accuracy. Development and validation populations share one synthetic generator family. Validation produced two false positives and missed ten planted issues; suggestion precision was 98.48% and end-to-end correct-correction coverage 90.28%. The final-reserved pack remains unanalysed. Official-pack accuracy and internal deployment remain unverified.

| Synthetic pack | People | Issue precision / recall | Cross-system matching precision / recall |
| --- | ---: | --- | --- |
| Development | 5,000 | 100.00% / 97.06% | 100.00% / 96.83% |
| Validation | 1,500 | 98.98% / 95.10% | 99.95% / 92.42% |

Evidence: local deterministic exports as of 1 October 2026, policy demo-2026-10-v2; implementation commit 543c92f. Prepared 23 October 2026.
