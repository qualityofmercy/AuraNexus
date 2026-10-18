---
name: execution-monitor
agent_id: run.execution_monitor
phase: run
title: Execution Monitor Agent
triggers:
- rehearsal.actuals.updated
- schedule.hourly
mode: deterministic
tool: run_execution_monitor
auto_send: true
requires_evidence: false
---

Deterministic and read-only: planned-vs-actual variance, critical path recalculation, blocked tasks, missing owners/actuals, early warnings. Immediate alerts only for critical-path or window risk.
