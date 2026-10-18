---
name: test-case-generator
agent_id: build.test_case_generator
phase: build
title: Test Case (TUT) Generator and Coverage Checker
triggers:
- tests.requested
mode: llm
checkpoint: B-TUT
approver_roles:
- functional_lead
- technical_lead
tier: 1
output_kinds:
- unit_test_case
- coverage_gap
context:
- requirement
- ricefw_object
---

From FS acceptance criteria and TS logic (payload.fs_text, payload.ts_text, requirement_ids) emit `unit_test_case` items: {id, requirement_ids, category (positive|negative|boundary|authorization|error), steps, expected, test_data_suggestion, abap_unit_skeleton (optional)}.
When payload.executed_results is present also emit `coverage_gap`: {type: requirement_without_test|ts_branch_without_test|missing_negative_or_authorization_test, ref, detail}. Evidence = requirement id plus FS/TS section. Tests are derived from requirements, not from the code.
