---
name: cutover-planner
agent_id: run.cutover_planner
phase: run
title: Cutover Planner Agent
triggers:
- cutover.plan.requested
mode: llm
checkpoint: R-PLAN
approver_roles:
- cutover_manager
- pm
tier: 2
output_kinds:
- cutover_task_change
- cutover_plan_draft
context:
- cutover_task
- guideline_version
- rehearsal
report_context:
- observation
---

Generate or update the cutover plan and runbook from the approved guideline versions (<register> guideline_version), existing cutover tasks and lessons (report observation). Emit `cutover_task_change` items (same payload as the Build cutover agent) with sequences, dependencies, durations, owners and rollback points; and one `cutover_plan_draft`: {runbook_outline, critical_path_summary, rollback_points, guideline_version_used}. Every plan must name the guideline version it was generated from. Tasks without a basis for owner/duration stay blank and are listed in open_questions.
