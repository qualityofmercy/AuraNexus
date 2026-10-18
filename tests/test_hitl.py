from datetime import timedelta

import pytest

from auranexus.core.hitl import Conflict, InvalidDecision, NotAuthorized
from auranexus.domain.models import DecisionOutcome as O
from auranexus.domain.models import Proposal, ProposalStatus, Role, utcnow

from .conftest import PID, TENANT


def submit(h, kind="requirement_entry", payload=None, tier=1, roles=(Role.WORKSHOP_LEAD,), src="evt1"):
    p = Proposal(tenant_id=TENANT, project_id=PID, agent_id="a.b", phase="prepare", kind=kind, title="T",
                 payload=payload or {"id": "REQ-1", "as_is": "x"}, source_event_id=src)
    return h.c.hitl.submit(p, "CP1", list(roles), tier)


def decide(h, p, outcome=O.APPROVE, roles=(Role.WORKSHOP_LEAD,), user="lead@x", **kw):
    return h.c.hitl.decide(TENANT, p.checkpoint_id, user, list(roles), outcome, **kw)


def test_agent_output_never_reaches_register_until_approved(h):
    p = submit(h)
    assert h.c.repo.register_list(TENANT, PID, "requirement_entry") == []
    decide(h, p)
    reg = h.c.repo.register_list(TENANT, PID, "requirement_entry")
    assert reg[0]["id"] == "REQ-1" and reg[0]["validated"] is True and reg[0]["decided_by"] == ["lead@x"]


def test_wrong_role_and_admin_cannot_decide(h):
    p = submit(h)
    with pytest.raises(NotAuthorized):
        decide(h, p, roles=(Role.TESTER,))
    with pytest.raises(NotAuthorized):
        decide(h, p, roles=(Role.ADMIN,))
    with pytest.raises(NotAuthorized):
        decide(h, p, roles=(Role.VIEWER,))


def test_reason_required_for_reject_modify_defer(h):
    p = submit(h)
    for o in (O.REJECT, O.DEFER):
        with pytest.raises(InvalidDecision):
            decide(h, p, o)
    with pytest.raises(InvalidDecision):
        decide(h, p, O.MODIFY, reason="fix", modified_payload=None)


def test_modify_applies_edited_payload(h):
    p = submit(h)
    decide(h, p, O.MODIFY, reason="owner was wrong", modified_payload={"id": "REQ-1", "owner": "Bob"})
    assert h.c.repo.register_list(TENANT, PID, "requirement_entry")[0]["owner"] == "Bob"


def test_reject_records_learning_and_dismisses_flag(h):
    p = submit(h, kind="cross_team_flag", payload={"id": "F1", "target_area": "FI-AR"}, roles=(Role.PM,))
    decide(h, p, O.REJECT, roles=(Role.PM,), reason="already covered by session 4")
    flag = h.c.repo.register_get(TENANT, "cross_team_flag", "F1")
    assert flag["status"] == "dismissed" and "session 4" in flag["dismissal_reason"]
    assert h.c.repo.register_list(TENANT, PID, "rejection")
    assert h.c.repo.get_proposal(TENANT, p.id).status == ProposalStatus.REJECTED


def test_double_decision_conflicts(h):
    p = submit(h)
    decide(h, p)
    with pytest.raises(Conflict):
        decide(h, p)


def test_tier3_needs_two_distinct_users_and_roles(h):
    p = submit(h, kind="guideline_change", payload={"id": "G1", "change_type": "new_rule"}, tier=3, roles=(Role.PM,))
    cp = h.c.repo.get_checkpoint(TENANT, p.checkpoint_id)
    assert cp.required_approvals == 2 and Role.TECHNICAL_LEAD in cp.approver_roles
    both = (Role.PM, Role.TECHNICAL_LEAD)
    decide(h, p, roles=both, user="pm@x")
    assert h.c.repo.register_list(TENANT, PID, "guideline_version") == []  # one vote is not enough
    with pytest.raises(Conflict):
        decide(h, p, roles=both, user="pm@x")  # same person twice
    with pytest.raises(Conflict):
        decide(h, p, roles=(Role.PM,), user="pm2@x")  # same role twice
    decide(h, p, roles=both, user="tl@x")
    v = h.c.repo.register_list(TENANT, PID, "guideline_version")[0]
    assert v["version"] == "1.1.0" and set(v["approvers"]) == {"pm@x", "tl@x"}


def test_defer_extends_deadline_and_keeps_open(h):
    p = submit(h)
    before = h.c.repo.get_checkpoint(TENANT, p.checkpoint_id).due_at
    decide(h, p, O.DEFER, reason="waiting for client")
    cp = h.c.repo.get_checkpoint(TENANT, p.checkpoint_id)
    assert cp.status.value == "open" and cp.due_at > before + timedelta(hours=20)
    decide(h, p)  # still decidable afterwards
    assert h.c.repo.get_proposal(TENANT, p.id).status == ProposalStatus.APPLIED


def test_overdue_checkpoint_escalates_to_pm_then_steering(h):
    p = submit(h)
    h.c.hitl.clock = lambda: utcnow() + timedelta(hours=100)
    assert len(h.c.hitl.sweep(TENANT)) == 1
    cp = h.c.repo.get_checkpoint(TENANT, p.checkpoint_id)
    assert cp.escalation_level == 1 and Role.PM in cp.approver_roles
    decide(h, p, roles=(Role.PM,), user="pm@x")  # PM can now decide it
    assert h.c.repo.get_proposal(TENANT, p.id).status == ProposalStatus.APPLIED


def test_template_change_bumps_version_major_for_split(h):
    p = submit(h, kind="template_change", payload={"change_type": "add_column", "proposed": "x"}, roles=(Role.PM,))
    decide(h, p, roles=(Role.PM,))
    p2 = submit(h, kind="template_change", payload={"change_type": "split_column", "proposed": "y"}, roles=(Role.PM,), src="e2")
    decide(h, p2, roles=(Role.PM,))
    versions = sorted(h.c.repo.register_list(TENANT, PID, "template_version"), key=lambda v: v["seq"])
    assert [v["version"] for v in versions] == ["v1.1", "v2.0"] and versions[1]["major"]


def test_merge_keeps_originals_visible(h):
    for rid in ("R1", "R2"):
        h.c.repo.register_put(TENANT, PID, "requirement_entry", rid, {"as_is": "same"})
    p = submit(h, kind="merge_proposal", payload={"master_id": "M1", "master": {"as_is": "same"}, "source_ids": ["R1", "R2"]}, roles=(Role.PM,))
    decide(h, p, roles=(Role.PM,))
    assert h.c.repo.register_get(TENANT, "requirement_entry", "R1")["duplicate_of"] == "M1"
    assert h.c.repo.register_get(TENANT, "requirement_entry", "M1")["merged_from"] == ["R1", "R2"]


def test_conflict_closure_requires_owner_and_resolution(h):
    h.c.repo.register_put(TENANT, PID, "conflict", "C1", {"status": "open"})
    p = submit(h, kind="conflict_resolution", payload={"conflict_id": "C1", "resolution": "use O2C owner"}, roles=(Role.PM,))
    with pytest.raises(InvalidDecision):
        decide(h, p, roles=(Role.PM,))
    assert h.c.repo.register_get(TENANT, "conflict", "C1")["status"] == "open"
    assert h.c.repo.get_checkpoint(TENANT, p.checkpoint_id).status.value == "open"  # re-opened for retry


def test_batch_validated_emitted_when_last_checkpoint_decided(h):
    p1, p2 = submit(h, src="batch"), submit(h, payload={"id": "REQ-2"}, src="batch")
    decide(h, p1)
    assert not [e for e in h.c.bus.published if e.type == "register.batch_validated"]
    decide(h, p2)
    ev = [e for e in h.c.bus.published if e.type == "register.batch_validated"]
    assert len(ev) == 1 and ev[0].payload["kinds"] == ["requirement_entry"]


def test_audit_chain_is_intact_and_detects_tampering(h):
    p = submit(h)
    decide(h, p)
    assert h.c.repo.audit.verify(TENANT) == (True, None)
    h.c.repo.store._audit[TENANT][0]["actor"] = "mallory"
    ok, bad = h.c.repo.audit.verify(TENANT)
    assert not ok and bad == 1
