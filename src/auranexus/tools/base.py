"""Tool plumbing. Tools are deterministic Python: math, graphs, rule checks. They never call the LLM.

* ``@pre_tool``   returns facts injected into an LLM agent's prompt (so the model interprets, not computes)
* ``@det_tool``   is the whole agent for deterministic skills: returns drafts/reports/notifications
* ``@post_tool``  post-processes validated LLM items (e.g. weighted totals, tier classification)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..core.repo import Repo
from ..domain.models import AgentItem, Event, Notification, Project, ProposalStatus


@dataclass
class ToolContext:
    repo: Repo
    project: Project
    event: Event
    settings: Settings
    arg: str = ""

    @property
    def tenant(self) -> str:
        return self.project.tenant_id

    @property
    def pid(self) -> str:
        return self.project.id

    def register(self, kind: str) -> list[dict[str, Any]]:
        return self.repo.register_list(self.tenant, self.pid, kind)

    def reports(self, kind: str) -> list[dict[str, Any]]:
        return self.repo.report_list(self.tenant, self.pid, kind)

    def proposals(self, kind: str, *statuses: ProposalStatus) -> list[Any]:
        out = self.repo.list_proposals(self.tenant, self.pid, kind=kind)
        return [p for p in out if not statuses or p.status in statuses]


@dataclass
class ToolOutput:
    items: list[AgentItem] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)  # {kind, id, data}
    notifications: list[Notification] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # follow-on events
    # Mechanically derived state only (e.g. a successor test becoming Ready); audited, never a decision.
    derived_writes: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)  # (kind, id, data)


Tool = Callable[[ToolContext], ToolOutput]
PostTool = Callable[[ToolContext, list[AgentItem]], list[AgentItem]]

DERIVED_KINDS = {"test_case"}

PRE_TOOLS: dict[str, Tool] = {}
DET_TOOLS: dict[str, Tool] = {}
POST_TOOLS: dict[str, PostTool] = {}


def pre_tool(name: str) -> Callable[[Tool], Tool]:
    def deco(fn: Tool) -> Tool:
        PRE_TOOLS[name] = fn
        return fn

    return deco


def det_tool(name: str) -> Callable[[Tool], Tool]:
    def deco(fn: Tool) -> Tool:
        DET_TOOLS[name] = fn
        return fn

    return deco


def post_tool(name: str) -> Callable[[PostTool], PostTool]:
    def deco(fn: PostTool) -> PostTool:
        POST_TOOLS[name] = fn
        return fn

    return deco


# ---- helpers ------------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


def overlap(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def filled(v: Any) -> bool:
    return v not in (None, "", [], {})


def pct(n: float, d: float, default: float = 100.0) -> float:
    return round(100.0 * n / d, 1) if d else default


def draft(kind: str, title: str, payload: dict[str, Any], confidence: float = 1.0) -> AgentItem:
    """A deterministic draft. Evidence is the computation basis recorded in the payload."""
    return AgentItem(kind=kind, title=title, payload=payload, confidence=confidence, inferred=False)
