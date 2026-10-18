---
name: dependency-sequencer
agent_id: test.dependency_sequencer
phase: test
title: Dependency and Sequencer
triggers:
- test.tracker.created
mode: llm
checkpoint: T-DEP
approver_roles:
- test_lead
tier: 1
output_kinds:
- test_dependency
- blocker_risk
- tester_briefing
postprocess:
- test_waves
context:
- test_case
- interface
- test_data
---

For the test scripts in <register> (kind test_case; payload may carry script text) identify dependencies of five types: data (master data, transactional documents from earlier steps, load/migration status), technical (interfaces, IDocs, APIs, batch jobs, transports, authorization roles), cross_team, sequence (output of A is input to B), environment_time (period-end locks, batch windows, shared client).
Emit `test_dependency`: {test_id, predecessor_id (when sequence), type, what_needed, provided_by, needed_by, risk_if_missing, documented (bool)}. Mark inferred=true and documented=false when you infer rather than read it. Also emit `blocker_risk` items and `tester_briefing` {tester, scripts, what_to_prepare, timing}. The platform adds the critical path and execution waves deterministically (scripts without dependencies run first). Evidence = test ids and the script text reference.
