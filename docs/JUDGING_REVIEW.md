# Review against the judging criteria

Reviewed on 23 October 2026. This is an evidence map, not an estimate of the judges' score. A passing implementation check does not establish official-pack accuracy or enterprise readiness.

| Criterion | Weight | Current evidence | Remaining evidence or work |
| --- | ---: | --- | --- |
| Detection and matching accuracy | 30% | Conservative matching, explicit abstention, all requested issue families, evaluator and independent synthetic development/validation populations. The current suite passes 140 checks. | Evaluate the unseen official pack when supplied. Known validation failures remain. The reserved final pack has not been analysed or scored. |
| Explanation and prioritisation | 25% | Findings retain original values, source records, identity evidence, authority logic and policy version. Priority includes business severity, declared exposure and measured report consequences. Three reports have isolated before/after calculations. | Business owners must confirm authority, report definitions, grace periods and priority weights. Other report paths indicate potential exposure, not calculated business effects. Monetary payroll impact is not estimated. |
| Responsible AI and security | 20% | Synthetic local inputs, no external AI/telemetry calls, no write-back, review decisions with rationale, snapshot/policy binding and hash-chained local history. Imported references retain their original bytes, hashes and line evidence. | Reviewer names are not authenticated identities. The hash chain is not protected immutable storage. Internal identity, permissions, audit storage, retention and deployment controls need owner approval before an operational pilot. |
| Deployability and reuse | 15% | Runnable Python repository, browser UI, setup steps, container configuration and Markdown imports. A fifth synthetic benefits system has been exercised through configuration-driven upload, matching, findings, field trust, impact and CSV export. Local data and artifacts are excluded from Git and container builds. | Unfamiliar fields/reports may still require model, adapter or calculator changes. Container build and deployment inside Emirates have not been verified. The five-source example demonstrates reuse within the existing employee model. |
| Team and pilot readiness | 10% | A working prototype, evidence exports, solution note, demo script and a proposed pilot plan. | Named team members, capacity, sponsor, internal host and pilot dates are not confirmed. A plan is not a booked or approved pilot. |

## Accuracy evidence and its limits

These are saved results for `demo-2026-10-v2`, checked against the local evaluation reports. They describe one known synthetic generator family. Development/validation separation does not make this an independent external benchmark.

| Validation measure | Result |
| --- | ---: |
| Issue precision | 98.98% |
| Issue recall | 95.10% |
| Cross-system pair matching precision | 99.95% |
| Cross-system pair matching recall | 92.42% |
| Suggestion precision against planted labels | 98.48% |
| End-to-end correct-correction coverage | 90.28% |

The validation pack contains 204 planted issues. The engine predicts 196: 194 true positives, two false positives and ten missed issues. Of 132 proposed values, 130 correspond to supported labelled corrections; the other two arise from unsupported issue predictions. This is different from claiming that all 132 suggestions are established fixes. Correctness against generator labels also does not, by itself, prove sufficient source evidence for a recommendation.

Saved evidence is local under `analysis_outputs/validation/evaluation.json`; it is deliberately not published with employee-data exports. Known weak areas include cross-system conflict recall and potential ghost-account cases. Do not change the rules solely to fit these cases or inspect the reserved final pack while tuning.

## Review outcome

The prototype implements the main detection and review workflow, and a fifth-source onboarding example is demonstrated end to end. The criteria are not all fully evidenced: official accuracy, unfamiliar source families, enterprise integration and committed team capacity remain open. The next-quarter pilot should be presented as a proposal until its owners, environment and acceptance measures are agreed. See the [source-onboarding evidence](SOURCE_ONBOARDING.md).

See [the proposed pilot plan](PILOT_PLAN.md), [implementation acceptance map](../REQUIREMENTS.md).
