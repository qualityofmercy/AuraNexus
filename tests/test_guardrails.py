from auranexus.agents.spec import SkillSpec
from auranexus.core.guardrails import apply_guardrails, quote_in_source
from auranexus.domain.models import AgentItem, Evidence

SPEC = SkillSpec(name="x", agent_id="x.y", phase="prepare", title="X", triggers=["t"], output_kinds=["requirement_entry", "estimate"],
                 checkpoint="CP1", approver_roles=["pm"])
SRC = "We process about 2000 orders per day. The credit check is manual and slow!"


def it(kind="requirement_entry", quote="", **kw):
    ev = [Evidence(quote=quote, speaker="A", timestamp="0:01")] if quote else []
    return AgentItem(kind=kind, title="t", evidence=ev, **kw)


def test_no_evidence_is_dropped():
    r = apply_guardrails(SPEC, [it()], SRC)
    assert not r.kept and r.dropped[0]["reason"] == "no_evidence"


def test_verified_quote_kept_unverified_downgraded():
    r = apply_guardrails(SPEC, [it(quote="about 2000 orders per day", confidence=0.9),
                                it(quote="we ship 9000 parcels", confidence=0.9)], SRC)
    assert len(r.kept) == 2
    assert not r.kept[0].inferred and r.kept[0].confidence == 0.9
    assert r.kept[1].inferred and r.kept[1].confidence <= 0.4
    assert "quote_not_verified" in r.flags[1]


def test_ellipsis_quote_fragments_in_order():
    assert quote_in_source("credit check ... manual and slow", "the credit check is manual and slow")
    assert not quote_in_source("manual ... credit check", "the credit check is manual")


def test_forbidden_and_unlisted_kinds_dropped():
    r = apply_guardrails(SPEC, [it(kind="signoff_received", quote="credit check"), it(kind="other", quote="credit check")], SRC)
    assert not r.kept and {d["reason"] for d in r.dropped} == {"kind_not_permitted_for_agent"}


def test_estimate_must_be_a_range_with_basis():
    bad = it(kind="estimate", quote="credit check", payload={"low": 5, "likely": 3, "high": 9, "basis": "ref1", "confidence_level": "low"})
    ok = it(kind="estimate", quote="credit check", payload={"low": 3, "likely": 5, "high": 9, "basis": "ref1", "confidence_level": "low"})
    r = apply_guardrails(SPEC, [bad, ok], SRC)
    assert len(r.kept) == 1 and len(r.dropped) == 1


def test_person_attribution_removed():
    r = apply_guardrails(SPEC, [it(quote="credit check", payload={"urgency": "High", "speaker_urgency": "Anna"})], SRC)
    p = r.kept[0].payload
    assert "speaker_urgency" not in p and p["urgency_inferred"] is True
    assert "person_attribution_removed" in r.flags[0]
