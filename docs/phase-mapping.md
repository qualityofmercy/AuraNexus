# Specification → implementation map

Status: **Done** = implemented and covered by tests; **Partial** = implemented with a stated limit; **Not yet** = not built.

## Prepare (v2.0 spec)

| Spec item | Status | Where / note |
|---|---|---|
| Agents 0-5 + orchestrator | Done | `skills/prepare/*`, `orchestrator/router.py` |
| Evidence on every entry, inferred labelled, hallucination control | Done | `core/guardrails.py` |
| Glossary correction | Partial | Glossary is register kind `glossary` passed to the LLM; corrections listed in payload |
| Urgency signal on the pain point, not the speaker | Done | guardrail strips person attribution |
| Template Steward: park, cluster, impact, versioning, change log | Done | `unclassified_item` → `template_change` → `template_version` applier (major/minor) |
| Cross-process flags grouped by team, status tracking, request on accept | Done | `cross_team_flag` applier creates `workshop_request` |
| Duplicates (merge keeps sources, originals visible), contradictions, resolution needs owner | Done | `merge_proposal`, `conflict`, `conflict_resolution` |
| Quality score (8 dimensions, weights 20/15/15/10×5) + re-baseline triggers + effort estimate | Done | `tools/prepare.py`; weights in `config/rubrics/prepare_quality.yaml` |
| Weekly summary (10 sections) | Partial | Sections 1-9 computed; section 10 lists next workshops, briefings are generated on `workshop.scheduled` |
| Step 8 traceability export to Explore/Realize | Not yet | `handoff_readiness_pct` is computed; export file not built |
| Connectors (Teams/Zoom transcripts, Jira/SharePoint register) | Not yet | Ingest via `POST /events`; notifications published to a Pub/Sub topic for a connector |

## Design

| Spec item | Status | Note |
|---|---|---|
| Planner (plan, coverage report, stakeholder load, briefs) | Done | LLM skill; unmapped/overloaded/missing roles reported in payload |
| Scribe with mandatory-field check, assumptions as tracked entries, recap draft | Done | `design_mandatory` post-tool |
| Sentinel (conflicts, cross-track impact, sign-off requirements, object dependencies) | Done | LLM skill |
| Readiness gate (6 checks) and scope-freeze gate (5 checks) | Done | `tools/design.py`, tested |
| Scope Coverage Assessor, 3 gap types, ranked | Done | deterministic |
| Skills & Estimation: ranges only, basis, confidence | Done | estimate validator rejects single numbers / no basis |
| Build Sequencer: waves, critical path, cycles, unsigned/out-of-scope prerequisites, E2E candidates | Done | `tools/graph.py` |
| Re-plan pending workshops only; assumption aging | Partial | Overdue critical assumptions block the gate; automatic re-plan proposals not built |
| Completed workshops never edited | Done | no code path rewrites decided records; changes are new proposals |

## Build

| Spec item | Status | Note |
|---|---|---|
| Requirement Intake, FS starter/review, TS options with POC triggers, Review (severity/rule/evidence/verdict), TUT generator | Done | LLM skills with validators (`review_finding`) |
| Reuse Finder | Partial | Token-overlap search over `past_ricefw` records; no vector index |
| Quality rubric + learning loop with two approvals | Done | `apply_rubric`; `guideline_change` is tier 3 |
| Cutover Agent: incremental register, checks, Changed/Obsolete states, change log | Done | applier keeps versions and change log |
| DoD gate, Change Impact Analyzer | Done | deterministic over the traceability chain |
| ATC / abapGit integration | Not yet | tool results are passed in the event payload (`tool_results`) |
| PM dashboard | Partial | data lands in BigQuery (`agent_runs`, `hitl_decisions`, `quality_scores`) + `dashboard` reports; no Looker/Jira UI |

## Test

| Spec item | Status | Note |
|---|---|---|
| TestStarter workbook | Done | `exports/xlsx.py` (tracker, roster, dashboard with formulas and chart) |
| Dependency types (5), waves, critical path, inferred flagged | Done | LLM classifies; waves deterministic |
| Coverage Full/Partial/None with quality-of-coverage; mid and end assessments with exit criteria | Done | `tools/testing.py` |
| Handoffs, delay nudges, escalation, failure fan-out + resequencing | Done | notification channel = Pub/Sub topic (`*-notifications`); Teams/Slack connector not built |
| Cutover Plan Sync (task/duration/owner/sequence, evidence, impact, approval, version history) | Done | only the cutover manager's approval changes the plan |
| Daily digest, delay prediction, pre-flight check, risk-based prioritisation | Not yet | listed as Phase-5 ideas in the spec |

## Run

| Spec item | Status | Note |
|---|---|---|
| Execution Monitor (variance, critical path recalculation, early warnings, read-only) | Done | alert-fatigue guard: immediate alerts only for critical path / window risk |
| Observation Logger, categories, evidence | Done | `observation` validator |
| Scoring: 6 dimensions, profile weights, overrides, trend, drivers, missing data, frozen rubric | Done | `tools/run.py`; freeze enforced, re-freeze is a PM action |
| Refinement Advisor: Appendix B fields, CP-DRn-nnn ids, tiering, repeat issues | Done | `refinement_post` |
| HITL Gatekeeper / Guideline Steward as workflow | Done | `HITLService` + appliers; guideline versions with approvers and linked proposal |
| Executive Summary with measured AI value | Partial | metrics from register/ledger; effort-saved needs baselines that must be entered, never estimated |
| Hypercare classifier | Done | LLM skill |
| Live bridge-call assistant, cross-project anonymised library | Not yet | |
