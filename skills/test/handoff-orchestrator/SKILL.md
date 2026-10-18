---
name: handoff-orchestrator
agent_id: test.handoff_orchestrator
phase: test
title: Handoff and Progress Orchestrator
triggers:
- test.status.updated
- schedule.hourly
mode: deterministic
tool: test_handoff
checkpoint: T-OPS
approver_roles:
- test_lead
tier: 1
auto_send: true
output_kinds:
- test_resequence
- test_escalation
requires_evidence: false
---

Deterministic: on a confirmed completion verifies the successor's prerequisites, marks it Ready and notifies the next tester (auto-sent handoff); on Failed/Blocked notifies downstream testers and drafts a resequencing proposal; hourly it nudges delayed starts and escalates. Resequencing and escalation need the test lead.
