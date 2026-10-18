---
name: monitor-quality
agent_id: prepare.monitor_quality
phase: prepare
title: Monitor & Quality Agent (Prepare)
triggers:
- schedule.weekly
- template.version_changed
mode: deterministic
tool: prepare_monitor
checkpoint: CP5
approver_roles:
- pm
tier: 1
checkpoint_by_kind:
  rebaseline_decision: CP6
output_kinds:
- weekly_summary
- rebaseline_decision
requires_evidence: false
---

Deterministic: scores each workshop out of 100 with the Prepare rubric, builds the weekly summary, applies the re-baseline rules and estimates reprocessing effort.
