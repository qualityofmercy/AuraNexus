"""Skill specs: one SKILL.md per agent (YAML frontmatter + instruction body)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from ..domain.models import Phase, Role


class SkillSpec(BaseModel):
    name: str
    agent_id: str
    phase: Phase
    title: str
    mode: Literal["llm", "deterministic"] = "llm"
    triggers: list[str]
    emits: list[str] = Field(default_factory=list)  # events published when the run completes
    checkpoint: str = "none"  # CP code, or "none" for informational output
    approver_roles: list[Role] = Field(default_factory=list)
    tier: int = 1
    output_kinds: list[str] = Field(default_factory=list)
    requires_evidence: bool = True
    evidence_optional_kinds: list[str] = Field(default_factory=list)
    source_field: str = ""  # event payload field holding the text quotes are verified against
    context: list[str] = Field(default_factory=list)  # register kinds loaded into the prompt
    report_context: list[str] = Field(default_factory=list)  # report kinds loaded into the prompt
    proposal_context: list[str] = Field(default_factory=list)  # proposal kinds from the triggering batch (pending or decided)
    checkpoint_by_kind: dict[str, str] = Field(default_factory=dict)  # override the checkpoint code per output kind
    when_kinds: list[str] = Field(default_factory=list)  # for events carrying kind(s): only run when they intersect
    tools: list[str] = Field(default_factory=list)  # deterministic pre-processing (facts for the prompt)
    postprocess: list[str] = Field(default_factory=list)  # deterministic post-processing of LLM items
    tool: str = ""  # deterministic agents: the tool that produces the drafts
    auto_send: bool = False  # notifications may be sent without approval (low-risk handoffs only)
    body: str = ""
    path: str = ""

    @property
    def needs_checkpoint(self) -> bool:
        return self.checkpoint.lower() != "none"


def parse_skill(path: Path) -> SkillSpec:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing YAML frontmatter")
    _, fm, body = text.split("---", 2)
    meta: dict[str, Any] = yaml.safe_load(fm) or {}
    spec = SkillSpec(**meta, body=body.strip(), path=str(path))
    if spec.needs_checkpoint and not spec.approver_roles:
        raise ValueError(f"{path}: checkpoint {spec.checkpoint} requires approver_roles")
    if spec.mode == "deterministic" and not spec.tool:
        raise ValueError(f"{path}: deterministic skill requires 'tool'")
    return spec
