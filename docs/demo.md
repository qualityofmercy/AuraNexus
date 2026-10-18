# Guided demo

A browser walkthrough of all five phases using the synthetic Acme dataset (Brownfield S/4HANA conversion). One defect,
**REQ-FI-019 (multi-currency tax translation rounding)**, is lost in Prepare and travels, undetected, to the Dry Run.

## Open it

```bash
gcloud run services proxy auranexus-demo --region asia-south1 --project auranexus-511908 --port 8080
# then browse http://localhost:8080/   (first use installs the small cloud-run-proxy gcloud component)
```

Service: `https://auranexus-demo-743456781789.asia-south1.run.app` (IAM-protected; only the listed invoker can open it).
To share a public link: `gcloud run services add-iam-policy-binding auranexus-demo --region asia-south1 --project auranexus-511908 --member=allUsers --role=roles/run.invoker`
(safe for this sandbox: see below). Redeploy after code changes with `scripts/deploy_demo.sh <project> <invoker> [region]`.

Locally: `uvicorn auranexus.demo.app:create_app --factory --port 8099`, then http://localhost:8099/.

## What is real and what is scripted

| Real platform code | Replayed from the dataset |
|---|---|
| Event routing, agent runner, schema normalisation | The model's output for each LLM agent (`demo/llm.py`) |
| Guardrails: evidence required, quote verification, kind whitelists | |
| Deterministic tools: quality score, readiness / DoD gates, test handoffs, execution monitor, scoring with override rules | |
| HITL: roles, reasons, defer, modify, tier-3 two-role approval, escalation | |
| Appliers writing the register, hash-chained audit log, tenant model | |

So the recording is repeatable (no model variance) while every control you show is the production code path. Say this on the
recording if asked; the first line of the UI badge reads "Demo sandbox".

## Recording flow (20 steps, ~12 min)

Use the left-hand step list. Each step has **Run** (triggers agents) and a green **suggested human action** button that
performs the decision as the correct persona; you can instead switch persona (top right) and click Approve / Modify / Reject /
Defer yourself. Buttons are disabled when the acting persona lacks the checkpoint's role, which is itself worth showing.

| # | Phase | Show | Say |
|---|---|---|---|
| 1-2 | Prepare | Briefing; transcript becomes 4 entries with verbatim quotes | REQ-FI-019 arrives at 64% confidence from garbled audio |
| 3 | Prepare | Workshop lead approves 3, rejects REQ-FI-019 with a reason | The requirement silently leaves the project |
| 4 | Prepare | PM raises FLG-01, dismisses FLG-02 and FLG-03 | FLG-03 is a premature dismissal |
| 5 | Prepare | Weekly quality score | Scores reflect only what is in the register |
| 6-9 | Design | Scribe, Sentinel, modify KDD-FI-09, readiness gate | Sentinel catches the dunning/shipping conflict but the gate says GO |
| 10-13 | Build | FS review, code review (REV-03 deferred), tests, DoD gate | Critical finding deferred; DoD blocks the object it can see |
| 14-16 | Test | Tracker, handoffs and nudges, assessment | No test ever links to REQ-FI-019 |
| 17-19 | Run | Dry Run actuals and alert, observations, Red scorecard | Data-integrity override caps the rating |
| 20 | Run | PM then Steering approve CP-DR1-014 | Tier 3 needs two roles; guideline v1.1.0 published, requirement re-injected |

Finish with **Defect trace** (REQ-FI-019 across phases) and **Audit trail** (hash chain verified). **Reset** (top right)
returns to the starting state; browser refresh keeps progress (state lives in the service).

Deep links: `/ui/#p3-review`, `/ui/#trace`, `/ui/#audit`.

## Notes on how the dataset was modelled

* Brownfield profile (the dataset mentions system conversion), so Run scoring uses Brownfield weights.
* REV-03 is **deferred** by the technical lead so the hardcoded conversion survives to Dry Run 1. The dataset says the finding
  existed and the defect later traced to it; the deferral is the demo's explanation for why it was not fixed.
* "Critical" is accepted as a review severity (the spec uses Blocker/Major/Minor).
* Tier 3 approvers include the Steering Committee (`config/hitl_policy.yaml`); the dataset names "PM and Steering Committee".
  Proposal numbering continues from 14 (`refinement_seq_start` project setting) to match CP-DR1-014.
* Values the dataset did not give (reconciliation 96.8%, attendee names, session timings, Dry Run window of 2 h) are invented
  to make the scoring and monitor tools run; change them in `demo/steps.py` and `demo/dataset.py`.

## Sandbox guarantees

`demo_mode` is refused unless the store is in-memory, the LLM is the scripted fake and the environment is not prod. The Cloud
Run service uses a service account with no roles, no VPC and no database, and runs exactly one instance (state is in memory;
a restart resets it).
