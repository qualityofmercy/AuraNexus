# Agent catalog

Generated from `skills/**/SKILL.md` by `scripts/gen_agent_catalog.py`. Do not edit by hand.

## Prepare

| Agent | Mode | Triggers | Output kinds | Checkpoint | Approver roles | Tier |
|---|---|---|---|---|---|---|
| `prepare.capture_extraction` Capture & Extraction Agent | llm | `transcript.received` | `requirement_entry`, `unclassified_item` | CP1 | workshop_lead | 1 |
| `prepare.consolidation_conflict` Consolidation & Conflict Agent | llm | `register.batch_validated` | `merge_proposal`, `conflict`, `requirement_link` | CP4 | workshop_lead, pm | 2 |
| `prepare.cross_process_impact` Cross-Process Impact Agent | llm | `extraction.completed` | `cross_team_flag` | CP3 | pm | 1 |
| `prepare.monitor_quality` Monitor & Quality Agent (Prepare) | deterministic | `schedule.weekly`, `template.version_changed` | `weekly_summary`, `rebaseline_decision` | CP5 (rebaseline_decision: CP6) | pm | 1 |
| `prepare.template_steward` Template Steward Agent | llm | `extraction.completed`, `rejection.recorded` | `template_change` | CP2 | pm, solution_architect | 2 |
| `prepare.workshop_prep` Workshop Prep Agent | llm | `workshop.scheduled` | `workshop_briefing` | CP0 | facilitator | 1 |

## Design (Imagine)

| Agent | Mode | Triggers | Output kinds | Checkpoint | Approver roles | Tier |
|---|---|---|---|---|---|---|
| `design.build_sequencer` Build Sequencer and Test Planner | deterministic | `estimates.reviewed` | `build_plan` | D-SEQ | pm, technical_lead | 2 |
| `design.cross_functional_sentinel` Cross-Functional Sentinel | llm | `design.extraction.completed` | `sentinel_flag`, `signoff_requirement`, `object_dependency` | D-SENT | pm | 2 |
| `design.design_scribe` Design Scribe | llm | `design.transcript.received` | `decision`, `assumption`, `risk`, `dev_object`, `action_item`, `open_issue`, `recap_draft` | D-SCRIBE | workshop_lead | 1 |
| `design.monitor_readiness` Monitor, Re-planner and Readiness Gate | deterministic | `schedule.weekly`, `gate.design_readiness.requested`, `gate.scope_freeze.requested` | `gate_decision` | D-GATE | pm | 2 |
| `design.scope_coverage_assessor` Scope Coverage Assessor | deterministic | `scope.finalized` | `scope_coverage_report` | D-SCOPE | pm, solution_architect | 2 |
| `design.skills_estimation` Skills and Estimation Advisor | llm | `scope.reviewed` | `skills_matrix`, `estimate`, `resource_plan` | D-EST | pm, delivery_lead | 2 |
| `design.workshop_planner` Workshop Planner and Prep | llm | `design.plan.requested`, `design.workshop.scheduled` | `workshop_plan`, `workshop_brief` | D-PLAN | pm, workshop_lead | 2 |

## Build

| Agent | Mode | Triggers | Output kinds | Checkpoint | Approver roles | Tier |
|---|---|---|---|---|---|---|
| `build.change_impact` Change Impact Analyzer | deterministic | `change.requested` | - | none | - | - |
| `build.cutover_agent` Cutover Agent (task register) | llm | `schedule.sprint_end`, `cutover.review.requested` | `cutover_task_change` | B-CUT | pm, cutover_lead | 1 |
| `build.dod_gate` Definition of Done Gate | deterministic | `dod.requested` | `dod_verdict` | B-DOD | pm, technical_lead | 1 |
| `build.fs_agent` FS Gap Analyzer and FS Starter | llm | `fs.requested` | `fs_draft`, `fs_gap_report` | B-FS | functional_lead | 1 |
| `build.quality_monitor` Quality Monitor and Learning Loop | llm | `schedule.sprint_end`, `quality.requested`, `lessons.received` | `quality_score`, `revision_suggestion`, `guideline_change` | B-QM | pm, technical_lead | 2 |
| `build.requirement_intake` Requirement Intake (Meeting-to-Spec) | llm | `build.requirements.received` | `requirement` | B-REQ | functional_lead | 1 |
| `build.review_agent` Review Agent (FS, TS, Code) | llm | `review.requested` | `review_finding`, `review_verdict` | B-REV | technical_lead, functional_lead | 1 |
| `build.test_case_generator` Test Case (TUT) Generator and Coverage Checker | llm | `tests.requested` | `unit_test_case`, `coverage_gap` | B-TUT | functional_lead, technical_lead | 1 |
| `build.ts_designer` TS Designer | llm | `ts.requested` | `ts_design`, `poc_trigger` | B-TS | technical_lead | 2 |

## Test

| Agent | Mode | Triggers | Output kinds | Checkpoint | Approver roles | Tier |
|---|---|---|---|---|---|---|
| `test.coverage_assessor` Coverage and Readiness Assessor | deterministic | `test.assess.requested` | `phase_assessment` | T-ASM | test_lead, pm | 2 |
| `test.cutover_plan_sync` Cutover Plan Sync Agent | llm | `defect.changed`, `transport.changed`, `cutover.sync.requested` | `cutover_plan_update` | T-CUT | cutover_manager | 2 |
| `test.dependency_sequencer` Dependency and Sequencer | llm | `test.tracker.created` | `test_dependency`, `blocker_risk`, `tester_briefing` | T-DEP | test_lead | 1 |
| `test.handoff_orchestrator` Handoff and Progress Orchestrator | deterministic | `test.status.updated`, `schedule.hourly` | `test_resequence`, `test_escalation` | T-OPS | test_lead | 1 |
| `test.test_starter` TestStarter | deterministic | `test.scripts.received` | `test_tracker` | T-TRK | test_lead | 1 |

## Run (Deploy / Hypercare)

| Agent | Mode | Triggers | Output kinds | Checkpoint | Approver roles | Tier |
|---|---|---|---|---|---|---|
| `run.cutover_planner` Cutover Planner Agent | llm | `cutover.plan.requested` | `cutover_task_change`, `cutover_plan_draft` | R-PLAN | cutover_manager, pm | 2 |
| `run.execution_monitor` Execution Monitor Agent | deterministic | `rehearsal.actuals.updated`, `schedule.hourly` | - | none | - | - |
| `run.executive_summary` Executive Summary Agent | llm | `project.closed` | `retrospective_report` | R-RETRO | pm | 1 |
| `run.hypercare_classifier` Hypercare Ticket Classifier | llm | `ticket.received` | `hypercare_classification` | R-HYP | cutover_lead | 1 |
| `run.observation_logger` Observation Logger | llm | `rehearsal.notes.received` | `observation` | none | - | - |
| `run.refinement_advisor` Refinement Advisor Agent | llm | `rehearsal.scored` | `refinement_proposal` | R-REF | cutover_lead, cutover_manager, pm | 2 |
| `run.scoring` Scoring Agent | deterministic | `rehearsal.completed` | `scorecard` | R-SCORE | pm, cutover_manager | 2 |
