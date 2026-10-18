---
name: build-sequencer
agent_id: design.build_sequencer
phase: design
title: Build Sequencer and Test Planner
triggers:
- estimates.reviewed
mode: deterministic
tool: build_sequencer
checkpoint: D-SEQ
approver_roles:
- pm
- technical_lead
tier: 2
output_kinds:
- build_plan
requires_evidence: false
---

Deterministic: orders in-scope objects into build waves from the dependency register, finds the critical path, circular dependencies and unavailable/unsigned prerequisites, defines wave entry and exit criteria and derives end-to-end and integration test candidates.
