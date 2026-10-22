# HR TrustGraph
<img width="2538" height="1274" alt="image" src="https://github.com/user-attachments/assets/94e78186-fbca-43d9-b39e-80f0cc1dccc7" />



A local website for matching employee records, finding and ranking data inconsistencies, explaining suggested fixes, and previewing report impact before human review.

**Submission status (23 October 2026):** organiser data had not been received at preparation time. This submission uses synthetic data only. Included issue lists are synthetic development/validation predictions, not predictions on an official test set. A demonstration video is included in `demo-video/demo.mp4` (2 minutes 55 seconds). It is within the three-minute limit; the presenter may replace it with the final recorded walkthrough before submission.

## Run the website locally

Requires **Python 3.10+ on macOS or Linux**. No package installation, API key, cloud account or data download is needed. Review logging uses Unix file locking; Windows users should use WSL or Docker.

```bash
git clone https://github.com/Neuragreen/HR-Data-Quality-Challenge.git
cd HR-Data-Quality-Challenge
python3 run_ui.py
```

Open **http://127.0.0.1:8765** in your browser. The website generates and analyses its synthetic development pack on first use; wait for the overview to appear. Use report date **2026-10-01** for the examples. Stop the server with Ctrl+C. If the port is occupied, use `python3 run_ui.py --port 8766` and open that port instead.

## Suggested five-minute review

1. **Overview:** inspect 19,756 source records, 495 findings and 339 supported proposals in the development run.
2. **Sources & analysis:** inspect different headers, mappings and sample records. Custom uploads accept CSVs, a structured `data_dictionary.md`, `dependencies.md` and an optional reviewed JSON policy.
3. **Employee matching:** search `PAY-95bf6224d89115793561` to inspect Priya Hassan across four systems.
4. **Issue queue:** search the same ID, open the missing payroll department, and inspect the proposed `OPS-01`, authority evidence and priority reasons.
5. **Impact preview:** calculate the isolated scenario. Payroll discrepancies change from 169 to 168; headcount and access results stay unchanged.
6. **Review decision:** enter your name and rationale to record approval, rejection or investigation. Approval never updates a source. Inspect **Decisions & exports**.
7. **Reports & data trust:** inspect definitions, unresolved cases and source-attributed questions.
8. **Sources & analysis:** run **Five-source onboarding demo**, date 2026-10-01. This separate benefits example has 27 records, seven findings and three proposals. Its benefits-report dependency is potential exposure, without a numerical calculator.

## Submission files

- [Two-page solution note PDF](submission/SOLUTION_NOTE.pdf) and [editable text](submission/SOLUTION_NOTE.md): approach, responsible AI, internal deployment and limitations. The editable note covers the required approach and responsible-AI statement.
- [Demonstration video](demo-video/demo.mp4): 2 minutes 55 seconds, within the three-minute limit.
- [Validation issue list](submission/issues_validation_synthetic.csv): 196 findings, including 132 proposals.
- [Development issue list](submission/issues_development_synthetic.csv): 495 findings, including 339 proposals.
- [Issue-list guide](submission/ISSUE_LIST_GUIDE.md): columns, evidence and evaluation boundaries.
- [Technical guide](docs/TECHNICAL_GUIDE.md), [reference import format](docs/REFERENCE_IMPORT.md), [source onboarding](docs/SOURCE_ONBOARDING.md), [requirements](REQUIREMENTS.md), [judging review](docs/JUDGING_REVIEW.md), [proposed pilot](docs/PILOT_PLAN.md).

## Evidence and limitations

The existing suite contains 140 automated checks. Run `python3 -m unittest discover -s tests -v`. Synthetic validation issue precision/recall was 98.98% / 95.10%; matching precision/recall was 99.95% / 92.42%. Development and validation share one generator family; these are not official-pack accuracy claims. Known errors remain in the exported issue list.

## Data handling and human control

The engine is deterministic and uses no AI/RAG, external telemetry, remote fonts or external processing services. Uploaded files stay on the local machine and require a synthetic-data declaration. Every proposal includes sources and rule logic; insufficient evidence remains an investigation. Impact scenarios use isolated copies. No live connector or source-system write-back exists.

Reviewer names are local entries, not authenticated identities. The hash-chained review history is not protected enterprise audit storage. An Emirates pilot needs approved internal hosting, identity/permissions, protected storage, retention, reviewed business definitions and read-only connectors. See the solution note and pilot plan.

Runtime packs and review history are generated locally in ignored directories. The only committed CSVs are the two explicitly labelled synthetic submission exports. Historical work and recovery archives are kept outside this repository.

## Optional container

```bash
docker build -t hr-trustgraph .
docker run --rm -p 127.0.0.1:8765:8765 -v hr-trustgraph-reviews:/app/.ui_runs hr-trustgraph
```

The container deployment has not been verified inside Emirates. The direct Python launch is the primary local review path.
