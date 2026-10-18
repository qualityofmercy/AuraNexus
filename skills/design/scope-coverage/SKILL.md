---
name: scope-coverage
agent_id: design.scope_coverage_assessor
phase: design
title: Scope Coverage Assessor
triggers:
- scope.finalized
mode: deterministic
tool: scope_coverage
checkpoint: D-SCOPE
approver_roles:
- pm
- solution_architect
tier: 2
output_kinds:
- scope_coverage_report
requires_evidence: false
---

Deterministic: traces every requirement and decision to a development object, configuration or explicit out-of-scope/deferred entry; reports and ranks the three gap types; brownfield/greenfield disposition checks; unsigned decisions.
