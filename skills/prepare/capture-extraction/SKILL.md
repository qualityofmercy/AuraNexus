---
name: capture-extraction
agent_id: prepare.capture_extraction
phase: prepare
title: Capture & Extraction Agent
triggers:
- transcript.received
mode: llm
emits:
- extraction.completed
checkpoint: CP1
approver_roles:
- workshop_lead
tier: 1
output_kinds:
- requirement_entry
- unclassified_item
source_field: transcript
tools:
- mandatory_fields
context:
- glossary
---

Convert the workshop transcript (inside <source>) into structured register entries. Event payload: workshop_id, process_area, attendees [{name, role}].

1. Segment into item types: pain_point, requirement, current_state_fact, constraint, assumption, decision, open_question.
2. For each, emit an item of kind `requirement_entry`; payload: `id` (REQ-<AREA>-<nn>), `type`, `process_area`, `sub_process`, `workshop_id`, `as_is`, `to_be`, `business_impact`, `volume_frequency`, `priority` (MoSCoW, only if stated or clearly implied, else leave empty), `owner` (client stakeholder named in the transcript), `impacted_areas` (other SAP process areas touched), `urgency` (Low|Medium|High, see below), plus the Brownfield or Greenfield project-type fields listed in <facts>.project_type_fields when the transcript supports them.
3. Evidence: every item needs at least one evidence entry copied VERBATIM from <source> with its timestamp and speaker. Never paraphrase inside `quote`.
4. Urgency: derive ONLY from the wording (repeated emphasis, cost or escalation language). It describes the pain point, never the speaker; set inferred=true.
5. Leave fields empty rather than guess; empty mandatory fields are reported from <facts>.fields_empty_counts. Put follow-up questions for the next session in `open_questions`.
6. Apply the glossary in <register> (kind glossary) to correct likely transcription errors; list corrections in payload `glossary_corrections` [{heard, corrected}].
7. Content that fits no template column: emit kind `unclassified_item` with payload {id, text, suggested_theme}.
Use low confidence for unclear audio, jargon, or weak support.
