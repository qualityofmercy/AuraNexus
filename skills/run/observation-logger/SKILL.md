---
name: observation-logger
agent_id: run.observation_logger
phase: run
title: Observation Logger
triggers:
- rehearsal.notes.received
mode: llm
checkpoint: none
output_kinds:
- observation
source_field: notes
context:
- rehearsal_task
report_context:
- execution_status
---

From the bridge-call notes (<source>) and task actuals in <register> (rehearsal_task) record findings, positives as deliberately as problems. One `observation` per finding: {id, rehearsal_id, task_id, what_happened, classification (smooth|watch|problem), category (sequencing_dependencies|duration_estimates|handoffs_ownership|technical_system|data_quality_migration|interfaces_integration|communication_governance|rollback_contingency), impact, suggested_follow_up}. Evidence: verbatim note text with timestamp, or log/ticket reference. No guessing; if evidence is missing, do not log it.
