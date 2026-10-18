from auranexus.agents.registry import SkillRegistry
from auranexus.api.app import EXTERNAL_EVENTS
from auranexus.config import Settings
from auranexus.core.guardrails import FORBIDDEN_KINDS

# Events produced by appliers, tools and the HITL service (not by skills' `emits`).
INTERNAL = {"template.version_changed", "test.tracker.created", "rehearsal.scored", "register.batch_validated",
            "rejection.recorded", "cutover.review.requested"}
SCHEDULED = {"schedule.hourly", "schedule.weekly", "schedule.sprint_end"}


def registry() -> SkillRegistry:
    return SkillRegistry.load(Settings().skills_dir)


def test_all_phases_covered_and_valid():
    r = registry()
    assert r.validate() == []
    phases = {s.phase.value for s in r.specs.values()}
    assert phases == {"prepare", "design", "build", "test", "run"}
    assert len(r.specs) == 34


def test_every_trigger_is_reachable():
    r = registry()
    emitted = {e for s in r.specs.values() for e in s.emits}
    reachable = EXTERNAL_EVENTS | emitted | INTERNAL | SCHEDULED
    unreachable = {(s.agent_id, t) for s in r.specs.values() for t in s.triggers if t not in reachable}
    assert not unreachable


def test_every_emitted_event_is_consumed():
    r = registry()
    consumed = {t for s in r.specs.values() for t in s.triggers}
    for s in r.specs.values():
        for e in s.emits:
            assert e in consumed, f"{s.agent_id} emits {e} but nobody listens"


def test_no_agent_can_emit_human_acts():
    for s in registry().specs.values():
        assert not set(s.output_kinds) & FORBIDDEN_KINDS


def test_checkpointed_skills_name_human_approvers_and_valid_tiers():
    for s in registry().specs.values():
        assert 1 <= s.tier <= 3
        if s.needs_checkpoint:
            assert s.approver_roles, s.agent_id
            assert "admin" not in [r.value for r in s.approver_roles] and "viewer" not in [r.value for r in s.approver_roles]


def test_unattended_outputs_are_limited_to_non_decisions():
    """Only informational skills may run with checkpoint 'none'."""
    ok = {"run.observation_logger", "run.execution_monitor", "build.change_impact"}
    assert {s.agent_id for s in registry().specs.values() if not s.needs_checkpoint} == ok
