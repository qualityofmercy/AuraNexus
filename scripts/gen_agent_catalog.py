"""Regenerate docs/agents.md from skills/**/SKILL.md (the single source of truth).

    python scripts/gen_agent_catalog.py            # write
    python scripts/gen_agent_catalog.py --check    # CI: fail if docs/agents.md is stale
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from auranexus.agents.registry import SkillRegistry  # noqa: E402

PHASES = [("prepare", "Prepare"), ("design", "Design (Imagine)"), ("build", "Build"), ("test", "Test"), ("run", "Run (Deploy / Hypercare)")]


def render() -> str:
    reg = SkillRegistry.load(ROOT / "skills")
    out = ["# Agent catalog", "", "Generated from `skills/**/SKILL.md` by `scripts/gen_agent_catalog.py`. Do not edit by hand.", ""]
    for key, title in PHASES:
        specs = sorted((s for s in reg.specs.values() if s.phase.value == key), key=lambda s: s.agent_id)
        out += [f"## {title}", "", "| Agent | Mode | Triggers | Output kinds | Checkpoint | Approver roles | Tier |", "|---|---|---|---|---|---|---|"]
        for s in specs:
            cp = s.checkpoint + (f" ({', '.join(f'{k}: {v}' for k, v in s.checkpoint_by_kind.items())})" if s.checkpoint_by_kind else "")
            out.append(
                f"| `{s.agent_id}` {s.title} | {s.mode} | {', '.join(f'`{t}`' for t in s.triggers)} | "
                f"{', '.join(f'`{k}`' for k in s.output_kinds) or '-'} | {cp} | "
                f"{', '.join(r.value for r in s.approver_roles) or '-'} | {s.tier if s.needs_checkpoint else '-'} |"
            )
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    target = ROOT / "docs" / "agents.md"
    text = render()
    if "--check" in sys.argv:
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            sys.exit("docs/agents.md is stale: run python scripts/gen_agent_catalog.py")
    else:
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {target}")
