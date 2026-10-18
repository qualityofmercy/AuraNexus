---
name: test-starter
agent_id: test.test_starter
phase: test
title: TestStarter
triggers:
- test.scripts.received
mode: deterministic
tool: test_starter
checkpoint: T-TRK
approver_roles:
- test_lead
tier: 1
output_kinds:
- test_tracker
requires_evidence: false
---

Deterministic: builds the tracking workbook rows (identification, execution, dependency, defect groups) from payload.scripts, validating ids, owners and predecessors. Approved rows are written to the register; export with the xlsx endpoint.
