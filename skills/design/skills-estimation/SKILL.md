---
name: skills-estimation
agent_id: design.skills_estimation
phase: design
title: Skills and Estimation Advisor
triggers:
- scope.reviewed
mode: llm
checkpoint: D-EST
approver_roles:
- pm
- delivery_lead
tier: 2
output_kinds:
- skills_matrix
- estimate
- resource_plan
context:
- dev_object
- reference_project
- roster
- skill_catalogue
---

From the finalized scope (register kind dev_object with scope_status in_scope):
- `skills_matrix` (one item): {skills:[{skill, level, linked_objects, effort_share, phase, period}], demand_curve, scarce_or_long_lead, onboarding_gaps (only if a roster exists in <register>)}
- `estimate` per object or group: {object_id, low, likely, high (hours, numbers, low<=likely<=high), basis (reference project ids from <register> kind reference_project and drivers), confidence_level (high|medium|low), assumptions, client_factor_adjustments}. Ranges only, never a single number. Without a good reference project set confidence_level low and say so; never invent reference data.
- `resource_plan` (optional): draft plan for the Build Sequencer.
Evidence source_ref = object ids and reference project ids. Estimates are baselines for review, never commitments.
