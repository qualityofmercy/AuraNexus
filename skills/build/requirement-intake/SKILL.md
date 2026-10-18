---
name: requirement-intake
agent_id: build.requirement_intake
phase: build
title: Requirement Intake (Meeting-to-Spec)
triggers:
- build.requirements.received
mode: llm
checkpoint: B-REQ
approver_roles:
- functional_lead
tier: 1
output_kinds:
- requirement
source_field: text
context:
- requirement
---

Convert the supplied workshop notes / design documents (<source>) into structured requirement statements, kind `requirement`, payload: {id (REQ-nnn, continue the numbering in <register>), statement, ricefw_category (R|I|C|E|F|W), process_area, standard_or_custom_candidate (standard|configuration|key_user_extensibility|developer_extensibility|custom), assumptions, ambiguity_flags (words like should, etc., as applicable, similar to), conflicts_with}. Evidence: verbatim quote from <source> with its location in source_ref. Flag ambiguous or conflicting statements; list assumptions and open questions. Never invent requirements.
