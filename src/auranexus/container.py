"""Composition root: wires store, LLM, bus, HITL, runner, registry and orchestrator."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .agents.registry import SkillRegistry
from .agents.runner import AgentRunner
from .config import Settings
from .core.analytics import AnalyticsSink, build_sink
from .core.bus import EventBus, InMemoryBus, PubSubBus
from .core.hitl import HITLPolicy, HITLService
from .core.llm import LLMClient, build_llm
from .core.repo import Repo
from .core.store import MemoryStore, Store
from .domain.models import Event
from .orchestrator.router import Orchestrator, TransientFailure

log = logging.getLogger("auranexus")


@dataclass
class Container:
    settings: Settings
    repo: Repo
    hitl: HITLService
    runner: AgentRunner
    registry: SkillRegistry
    orchestrator: Orchestrator
    bus: EventBus
    analytics: AnalyticsSink


def build_store(settings: Settings) -> Store:
    if settings.store_backend == "postgres":
        from .core.pg_store import PostgresStore  # optional 'gcp' extra

        return PostgresStore(settings.database_url)
    return MemoryStore()


def build_bus(settings: Settings) -> EventBus:
    return PubSubBus(settings) if settings.bus_backend == "pubsub" else InMemoryBus()


def build_container(
    settings: Settings,
    store: Store | None = None,
    llm: LLMClient | None = None,
    bus: EventBus | None = None,
    analytics: AnalyticsSink | None = None,
) -> Container:
    settings.validate_for_runtime()
    repo = Repo(store or build_store(settings))
    bus = bus or build_bus(settings)
    registry = SkillRegistry.load(settings.skills_dir)
    problems = registry.validate()
    if problems:
        raise RuntimeError("invalid skills: " + "; ".join(problems))
    sink = analytics or build_sink(settings)
    hitl = HITLService(repo, HITLPolicy.load(settings.config_dir / "hitl_policy.yaml"), bus, analytics=sink)
    runner = AgentRunner(repo, hitl, llm or build_llm(settings), bus, settings, analytics=sink)
    orch = Orchestrator(repo, hitl, runner, registry, bus, settings)
    if isinstance(bus, InMemoryBus):  # local mode: dispatch inline; on GCP the worker consumes Pub/Sub pushes

        def _inline(event: Event) -> None:
            try:
                orch.handle(event)
            except TransientFailure as exc:
                log.warning("transient agent failure (inline mode, not retried): %s", exc)

        bus.subscribe(_inline)
    return Container(settings, repo, hitl, runner, registry, orch, bus, sink)
