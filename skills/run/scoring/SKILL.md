---
name: scoring
agent_id: run.scoring
phase: run
title: Scoring Agent
triggers:
- rehearsal.completed
mode: deterministic
tool: run_scoring
checkpoint: R-SCORE
approver_roles:
- pm
- cutover_manager
tier: 2
output_kinds:
- scorecard
requires_evidence: false
---

Deterministic: scores the rehearsal or production run on the frozen cutover rubric (schedule, execution quality, data integrity, issues, handoffs, rollback), applies override rules (data breach, untested rollback, open critical defect), explains the top drivers, trends versus the previous rehearsal and states missing data and confidence. The rubric weights freeze at the first scored rehearsal.
