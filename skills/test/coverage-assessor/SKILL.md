---
name: coverage-assessor
agent_id: test.coverage_assessor
phase: test
title: Coverage and Readiness Assessor
triggers:
- test.assess.requested
mode: deterministic
tool: test_coverage
checkpoint: T-ASM
approver_roles:
- test_lead
- pm
tier: 2
output_kinds:
- phase_assessment
requires_evidence: false
---

Deterministic: requirement-to-test traceability (Full/Partial/None with quality-of-coverage categories), per-scenario coverage, and the mid-phase (progress vs plan, pass/fail, defect aging, blocked, scenarios at risk) or end-phase (exit criteria, residual risk, go/no-go input) assessment.
