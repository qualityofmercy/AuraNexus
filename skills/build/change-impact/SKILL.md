---
name: change-impact
agent_id: build.change_impact
phase: build
title: Change Impact Analyzer
triggers:
- change.requested
mode: deterministic
tool: build_change_impact
requires_evidence: false
---

Deterministic: walks the traceability chain from a changed requirement and lists affected FS sections, TS components, code objects, test cases and cutover tasks with re-review and re-test lists; requests a cutover review when deployed objects are affected.
