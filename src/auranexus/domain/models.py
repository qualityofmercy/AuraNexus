"""Domain model shared by every agent, the HITL service and the API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


class Phase(StrEnum):
    PREPARE = "prepare"
    DESIGN = "design"
    BUILD = "build"
    TEST = "test"
    RUN = "run"


class ProjectType(StrEnum):
    GREENFIELD = "greenfield"
    BROWNFIELD = "brownfield"


class Role(StrEnum):
    VIEWER = "viewer"
    FACILITATOR = "facilitator"
    WORKSHOP_LEAD = "workshop_lead"
    FUNCTIONAL_LEAD = "functional_lead"
    TECHNICAL_LEAD = "technical_lead"
    SOLUTION_ARCHITECT = "solution_architect"
    DELIVERY_LEAD = "delivery_lead"
    TEST_LEAD = "test_lead"
    TESTER = "tester"
    CUTOVER_LEAD = "cutover_lead"
    CUTOVER_MANAGER = "cutover_manager"
    PM = "pm"
    STEERING = "steering"
    ADMIN = "admin"


class Project(BaseModel):
    id: str
    tenant_id: str
    name: str
    project_type: ProjectType
    phase: Phase = Phase.PREPARE
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class Evidence(BaseModel):
    """Every agent assertion must point at evidence (principle: evidence first)."""

    quote: str = ""
    timestamp: str = ""
    speaker: str = ""
    source_ref: str = ""  # workshop id, test id, log/ticket/transport, FS section, ...


class Event(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt_"))
    tenant_id: str
    project_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    depth: int = 0
    parent_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ProposalStatus(StrEnum):
    PENDING = "pending"  # waiting for a human
    APPLIED = "applied"  # approved (or modified) and written to the register
    REJECTED = "rejected"
    DEFERRED = "deferred"
    DRAFT = "draft"  # informational output, no decision required (checkpoint: none)


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prp_"))
    tenant_id: str
    project_id: str
    agent_id: str
    phase: Phase
    kind: str
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = 0.5
    inferred: bool = False
    flags: list[str] = Field(default_factory=list)  # guardrail annotations
    tier: int = 1
    status: ProposalStatus = ProposalStatus.PENDING
    checkpoint_id: str | None = None
    source_event_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    applied_at: datetime | None = None


class DecisionOutcome(StrEnum):
    APPROVE = "approve"
    MODIFY = "modify"
    REJECT = "reject"
    DEFER = "defer"


class Decision(BaseModel):
    outcome: DecisionOutcome
    reason: str = ""
    decided_by: str
    role: Role
    modified_payload: dict[str, Any] | None = None
    decided_at: datetime = Field(default_factory=utcnow)


class CheckpointStatus(StrEnum):
    OPEN = "open"
    DECIDED = "decided"


class Checkpoint(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cp_"))
    tenant_id: str
    project_id: str
    code: str  # CP0..CP6, DOD, ...
    proposal_id: str
    approver_roles: list[Role]
    tier: int = 1
    required_approvals: int = 1
    approvals: list[Decision] = Field(default_factory=list)  # approve/modify votes so far
    status: CheckpointStatus = CheckpointStatus.OPEN
    escalation_level: int = 0
    rev: int = 0  # optimistic-concurrency counter
    due_at: datetime
    source_event_id: str | None = None
    decision: Decision | None = None  # final decision
    created_at: datetime = Field(default_factory=utcnow)


class AuditEntry(BaseModel):
    seq: int
    tenant_id: str
    project_id: str | None = None
    ts: datetime = Field(default_factory=utcnow)
    actor: str  # agent id, user email, or "system"
    actor_type: str  # agent | human | system
    action: str
    entity_type: str
    entity_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str = ""
    hash: str = ""


# --- Agent I/O ----------------------------------------------------------------------------


class AgentItem(BaseModel):
    kind: str
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = 0.5
    inferred: bool = False


class AgentOutput(BaseModel):
    items: list[AgentItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    notes: str = ""


class Notification(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ntf_"))
    tenant_id: str
    project_id: str
    channel: str = "default"
    recipient: str  # role or person
    subject: str
    body: str
    severity: str = "info"
    created_by: str
    status: str = "sent"  # sent | drafted (agent may not send; a human releases it)
    created_at: datetime = Field(default_factory=utcnow)
