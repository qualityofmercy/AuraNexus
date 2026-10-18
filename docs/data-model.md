# Data model

All collections are JSON documents scoped by `tenant_id` (table `records`, plus `audit_log`). Typed models live in
`domain/models.py`; the register kinds below are conventions shared by agents, tools and appliers.

## Collections

| Collection | Written by | Content |
|---|---|---|
| `proposals` / `checkpoints` | agents via `HITLService.submit` | the ledger of everything agents proposed and humans decided |
| `register` | **appliers** (after approval) or **human record endpoint** | decided project state |
| `reports` | agents (informational) | draft output with no decision effect: dashboards, nudges, observations, workshop quality, change impact |
| `agent_runs`, `events`, `notifications` | runner / orchestrator | operations |
| `audit_log` | everything | hash-chained, append-only |
| `members`, `projects`, `tenants` | API | access and tenancy |

## Register kinds

| Kind | Written by | Key fields |
|---|---|---|
| `requirement_entry` | CP1 approval | id, type, process_area, as_is, to_be, business_impact, volume_frequency, priority, owner, urgency (inferred), evidence, validated |
| `template_version` | CP2 approval | version (minor for add_column/add_dropdown_value, major for split/rename/retire), changes, affected_workshops |
| `cross_team_flag`, `workshop_request` | CP3 approval | target_area, why, risk_if_not_discussed, status raised/dismissed |
| `conflict` | CP4 approval | statements side by side, status open/resolved (closing needs owner + resolution) |
| `decision`, `assumption`, `dev_object`, `object_dependency`, `signoff_requirement` | Design checkpoints | KDD fields, validation due, object type/complexity, dependency type/strength |
| `signoff` | **human endpoint only** (pm) | decision_id, stakeholder, status |
| `estimate`, `skills_matrix`, `build_plan`, `scope_coverage_report`, `gate_decision` | Design checkpoints | ranges + basis + confidence; waves, critical path, issues |
| `requirement`, `ricefw_object`, `fs_draft`, `ts_design`, `review_finding`, `dod_verdict` | Build | traceability chain fields: requirement_ids, fs_ids, ts_ids, code_objects, test_case_ids |
| `cutover_task` | cutover-change approvals (Build, Test, Run) | task_id, state (New/Confirmed/Changed/Obsolete), owner, duration_hours_likely, predecessors, verification, version, change_log |
| `guideline_version` | tier-3 approval | semver, change, approvers, linked proposal |
| `test_case` | tracker approval; status via human record + derived `Ready` | test_id, scenario, predecessor_ids, status, step_owner |
| `test_dependency`, `phase_assessment` | Test checkpoints | dependency type, documented flag; coverage Full/Partial/None, exit criteria |
| `rehearsal`, `rehearsal_task`, `reconciliation`, `defect` | **human endpoint** (cutover roles) | planned/actual times, predecessors, reconciliation %, severity |
| `scorecard`, `rubric_freeze` | R-SCORE approval / first scoring | weighted total, rating, overrides, drivers; frozen weights hash |
| `refinement_proposal`, `plan_change`, `retrospective_report` | Run checkpoints | CP-DRn-nnn id, tier, repeat flag; evidence-based AI value |

## Evidence

`Evidence {quote, timestamp, speaker, source_ref}`: required for every LLM item. Quotes are checked against the source
text; failures are flagged `quote_not_verified`, marked inferred and capped at confidence 0.4 (`core/guardrails.py`).

## Traceability chain (Build)

`requirement → FS section → TS component → code object → test case → cutover task` is stored on `ricefw_object`
(`requirement_ids`, `fs_ids`, `ts_ids`, `code_objects`, `test_case_ids`) plus `cutover_task.object_ids`.
The DoD gate fails on any missing link; Change Impact walks the same links.
