# Proposed pilot plan

This is a planning document for the challenge, not a confirmed Emirates engagement. No team names, availability, internal approvals or delivery dates have been supplied. The phases below are relative to an agreed kickoff; they do not promise a next-quarter deployment.

## Proposed scope

Begin with the four supplied synthetic extracts, their reviewed dictionary and dependencies, and the three existing report calculations. Run inside an approved internal environment. Findings, suggested corrections and impact previews remain advisory; no source-system write-back is included.

An independent synthetic acceptance set should be used before considering any operational data. The challenge prototype remains synthetic-only. Any later change to data scope requires a separate decision by the relevant owners.

## Ownership to confirm

| Role | Responsibility | Current commitment |
| --- | --- | --- |
| Business sponsor / HR data owner | Scope, success measures and decision to continue | Unassigned |
| HR data steward | Issue triage, evidence review and correction acceptance | Unassigned |
| HR analytics lead | Definitions, report reconciliation and publication decisions | Unassigned |
| HR systems owner | Source access, mappings, dependencies and downstream review | Unassigned |
| Engineering owner | Deployment, source onboarding, reliability and support | Unassigned |
| Security / infrastructure owner | Internal identity, permissions, protected storage and environment approval | Unassigned |

Roles may be combined where capacity and approval allow. The submission must identify the actual team and their availability; this table is not evidence of staffing.

## Proposed phases and exit evidence

| Phase | Indicative window | Work | Evidence required before progressing |
| --- | --- | --- | --- |
| Agree scope and definitions | Weeks 1–2 | Confirm source grain, field authority, codes, regional meanings, report formulas, freshness, access exceptions and priority weights. Agree evaluation thresholds before examining acceptance results. | Named owners, reviewed policy and dependencies, versioned acceptance measures, approved synthetic inputs. |
| Prepare internal environment | Weeks 3–4 | Deploy in an approved host/container; integrate appropriate reviewer identity, permissions, protected audit storage and retention. Establish read-only input access and approved egress settings. | Environment approval, reproducible setup, access checks, audit/recovery checks and an agreed data lifecycle. |
| Run supervised evaluation | Weeks 5–6 | Process independent synthetic cases. Stewards review findings and rank disagreements; analytics and systems owners validate report effects. Demonstrate adding one extra source with different headers/codes. | Matching and detection precision/recall, correction precision/coverage, abstentions, source onboarding steps, report reconciliation and reviewed error examples. |
| Decide whether to extend | Weeks 7–8 | Compare results and review effort with agreed acceptance measures; record limitations and support needs. | Signed review by accountable owners, measured review-time baseline/comparison, assigned support capacity and an explicit continue/stop decision. |

The schedule is an initial estimate, not evidence that access or enterprise integrations can be completed in these windows. Replan around actual approvals, source complexity and available capacity.

## Measures to agree before evaluation

- Matching precision/recall, with ambiguous identities and incorrect merges shown separately.
- Issue precision/recall by family; false positives and missed issues retained for review.
- Correction precision and coverage, with abstentions visible.
- Agreement between steward priority and tool ranking, especially access and payroll cases.
- Reconciliation of the three report results and single-fix previews against owner-approved calculations.
- Time spent investigating and deciding a reviewed sample, compared with an agreed baseline.
- Effort required to onboard an extra source and identify unsupported field/report semantics.
- Evidence that input bytes remain unchanged, decisions are attributable, and retained files follow the agreed lifecycle.

No pass threshold is invented here: business and technical owners must agree it before acceptance testing. Passing a score threshold does not automatically approve a fix or publication of a report.

The [five-source benefits example](SOURCE_ONBOARDING.md) now demonstrates source reuse in the prototype. The pilot should still confirm onboarding against its own reviewed source definitions and independent acceptance cases.

## Pilot entry conditions still open

Named people and capacity, business sponsorship, the approved environment, internal access/integration approvals and an independent acceptance dataset remain unconfirmed. These are the outstanding readiness items for the 10% team/pilot criterion.
