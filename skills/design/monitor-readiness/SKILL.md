---
name: monitor-readiness
agent_id: design.monitor_readiness
phase: design
title: Monitor, Re-planner and Readiness Gate
triggers:
- schedule.weekly
- gate.design_readiness.requested
- gate.scope_freeze.requested
mode: deterministic
tool: design_gates
checkpoint: D-GATE
approver_roles:
- pm
tier: 2
output_kinds:
- gate_decision
requires_evidence: false
---

Deterministic: dashboard (coverage, sign-offs with aging, assumptions, conflicts, stakeholder fatigue) and the Design-readiness and Scope-freeze gate checks with blocking items listed.
