# Issue lists

These are complete, unchanged exports from the current synthetic analyses. They are not the official judge test set and do not establish compatibility with an unpublished scoring schema.

| File | Use | Findings | Proposed fixes | Investigation only |
| --- | --- | ---: | ---: | ---: |
| issues_validation_synthetic.csv | Current synthetic validation/test-profile results | 196 | 132 | 64 |
| issues_development_synthetic.csv | Demonstration dataset used by the video script | 495 | 339 | 156 |

Both use reference date **2026-10-01** and policy **demo-2026-10-v2**. Priority is sorted from highest to lowest; larger scores mean higher priority. P0 is most urgent, followed by P1, P2 and P3.

## Fields to use

- `issue_id`, `record_id`, `source_system`, `source_id`, `person_id`: finding and source/person references. Source IDs are local to their system.
- `field`, `issue_type`, `observed_value`, `normalized_value`: affected field, category and values.
- `suggested_value`, `recommendation_status`: proposed replacement, or a blank replacement with `investigate` when evidence is insufficient. Blank suggestions must not be converted into source-clearing instructions.
- `priority_score`, `priority_band`, `priority_reasons`: ranking and the contributions behind it. Scores are capped at 100.
- `evidence`, `rule_id`, `policy_version`: plain-language explanation, source references, matching evidence and determination logic. JSON objects/lists are encoded inside quoted CSV cells.
- `measured_impact`, `dependencies`: calculated report effects versus declared potential exposure.
- `match_confidence`, `issue_confidence`, `fix_confidence`, `confidence_kind`: rule evidence scores, not calibrated probabilities.
- `status`: analysis finding state. Human decisions are recorded separately; no correction is executed.

The validation list includes all predictions without removing known evaluation errors. It has 194 matched planted issues, two false positives and ten missed planted issues. Of 132 suggestions, 130 are supported by the current synthetic answer key. No answer-key values or labels are included in these files.

When the official unlabelled pack arrives, confirm mappings, valid codes, source grain, authority and dependencies; run analysis using only its input files; and adapt the export to the official scoring schema. Do not reuse these synthetic results as the official submission.

These two explicitly labelled synthetic prediction exports accompany the judge submission. Input packs, evaluator answer keys and local review histories are excluded. Organiser data was unavailable at preparation time; these are not official-set predictions.
