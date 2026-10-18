"""Skill registry: loads every skills/**/SKILL.md and indexes agents by event trigger."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .spec import SkillSpec, parse_skill


class SkillRegistry:
    def __init__(self, specs: list[SkillSpec]) -> None:
        ids = [s.agent_id for s in specs]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate agent ids: {sorted(dupes)}")
        self.specs = {s.agent_id: s for s in specs}
        self._by_trigger: dict[str, list[SkillSpec]] = defaultdict(list)
        for s in specs:
            for t in s.triggers:
                self._by_trigger[t].append(s)

    @classmethod
    def load(cls, skills_dir: Path) -> SkillRegistry:
        return cls([parse_skill(p) for p in sorted(skills_dir.rglob("SKILL.md"))])

    def for_event(self, event_type: str) -> list[SkillSpec]:
        return list(self._by_trigger.get(event_type, []))

    def get(self, agent_id: str) -> SkillSpec:
        return self.specs[agent_id]

    def validate(self) -> list[str]:
        """Static checks used by CI: every tool referenced exists, every emitted event is consumed or terminal."""
        from ..tools import DET_TOOLS, POST_TOOLS, PRE_TOOLS

        problems: list[str] = []
        for s in self.specs.values():
            for t in s.tools:
                if t.split(":")[0] not in PRE_TOOLS:
                    problems.append(f"{s.agent_id}: unknown pre tool {t}")
            for t in s.postprocess:
                if t not in POST_TOOLS:
                    problems.append(f"{s.agent_id}: unknown postprocess {t}")
            if s.mode == "deterministic" and s.tool not in DET_TOOLS:
                problems.append(f"{s.agent_id}: unknown deterministic tool {s.tool}")
            if s.mode == "llm" and not s.output_kinds:
                problems.append(f"{s.agent_id}: llm skills must whitelist output_kinds")
            if s.mode == "llm" and not s.body:
                problems.append(f"{s.agent_id}: empty instructions")
        return problems
