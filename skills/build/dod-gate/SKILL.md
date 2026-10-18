---
name: dod-gate
agent_id: build.dod_gate
phase: build
title: Definition of Done Gate
triggers:
- dod.requested
mode: deterministic
tool: build_dod_gate
checkpoint: B-DOD
approver_roles:
- pm
- technical_lead
tier: 1
output_kinds:
- dod_verdict
requires_evidence: false
---

Deterministic readiness check before a RICEFW object moves to SIT: FS/TS approved, review verdict, ATC clean, unit tests with coverage threshold, rubric score, transport notes, traceability chain, cutover tasks with owners and durations.
