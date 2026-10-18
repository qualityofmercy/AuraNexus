"""Deterministic guardrails applied to every LLM item before it can become a proposal.

Enforced here (not just in prompts): no entry without evidence, quote verification against the
source text, inferred labelling, low-confidence flagging, kind whitelisting and per-kind validators.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..agents.spec import SkillSpec
from ..domain.models import AgentItem

# Kinds no agent may ever emit: these are human acts.
FORBIDDEN_KINDS = {
    "signoff_received",
    "scope_frozen",
    "estimate_committed",
    "decision_final",
    "template_version",
    "guideline_version",
}

LOW_CONFIDENCE = 0.5
UNVERIFIED_QUOTE_CAP = 0.4


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def quote_in_source(quote: str, source_norm: str) -> bool:
    """Quote may contain '...' gaps; every fragment must appear in the source, in order."""
    parts = [p for p in re.split(r"\.\.\.|…", quote) if _norm(p)]
    pos = 0
    for part in parts:
        idx = source_norm.find(_norm(part), pos)
        if idx < 0:
            return False
        pos = idx + len(_norm(part))
    return bool(parts)


@dataclass
class GuardrailResult:
    kept: list[AgentItem] = field(default_factory=list)
    flags: dict[int, list[str]] = field(default_factory=dict)  # index in kept -> flags
    dropped: list[dict] = field(default_factory=list)


def _validate_estimate(p: dict) -> list[str]:
    errs = []
    try:
        low, likely, high = float(p["low"]), float(p["likely"]), float(p["high"])
        if not (low <= likely <= high):
            errs.append("estimate must satisfy low <= likely <= high")
    except (KeyError, TypeError, ValueError):
        errs.append("estimate requires numeric low, likely and high (ranges, never single numbers)")
    if not p.get("basis"):
        errs.append("estimate requires a basis (reference projects or drivers)")
    if not p.get("confidence_level"):
        errs.append("estimate requires a confidence_level")
    return errs


def _validate_review_finding(p: dict) -> list[str]:
    errs = []
    if p.get("severity") not in {"Critical", "Blocker", "Major", "Minor"}:
        errs.append("finding severity must be Critical, Blocker, Major or Minor")
    if not p.get("rule_id"):
        errs.append("finding requires a rule_id")
    return errs


def _validate_observation(p: dict) -> list[str]:
    return [] if p.get("classification") in {"smooth", "watch", "problem"} else ["classification must be smooth|watch|problem"]


def _validate_duration(p: dict) -> list[str]:
    changes = p.get("changes") or {}
    if "duration_hours_likely" in changes and not p.get("basis"):
        return ["duration changes require a basis"]
    return []


KIND_VALIDATORS = {
    "estimate": _validate_estimate,
    "review_finding": _validate_review_finding,
    "observation": _validate_observation,
    "cutover_plan_update": _validate_duration,
}


def apply_guardrails(spec: SkillSpec, items: list[AgentItem], source_text: str | None = None) -> GuardrailResult:
    res = GuardrailResult()
    source_norm = _norm(source_text) if source_text else None
    allowed = set(spec.output_kinds)

    for it in items:
        if it.kind in FORBIDDEN_KINDS or (allowed and it.kind not in allowed):
            res.dropped.append({"title": it.title, "kind": it.kind, "reason": "kind_not_permitted_for_agent"})
            continue

        flags: list[str] = []
        ev = [e for e in it.evidence if (e.quote or e.source_ref).strip()]
        evidence_required = spec.requires_evidence and it.kind not in spec.evidence_optional_kinds
        if evidence_required and not ev:
            res.dropped.append({"title": it.title, "kind": it.kind, "reason": "no_evidence"})
            continue
        it = it.model_copy(update={"evidence": ev, "confidence": max(0.0, min(1.0, it.confidence))})

        if source_norm is not None:
            bad = [e for e in ev if e.quote and not quote_in_source(e.quote, source_norm)]
            if bad:
                flags.append("quote_not_verified")
                it = it.model_copy(update={"inferred": True, "confidence": min(it.confidence, UNVERIFIED_QUOTE_CAP)})

        if it.inferred:
            flags.append("inferred")
        if it.confidence < LOW_CONFIDENCE:
            flags.append("low_confidence")

        payload = dict(it.payload)
        # urgency describes a pain point, never a person
        if "urgency" in payload:
            payload["urgency_inferred"] = True
        for banned in ("speaker_urgency", "urgency_by_speaker", "person_score"):
            if banned in payload:
                payload.pop(banned)
                flags.append("person_attribution_removed")
        it = it.model_copy(update={"payload": payload})

        validator = KIND_VALIDATORS.get(it.kind)
        errs = validator(payload) if validator else []
        if errs:
            res.dropped.append({"title": it.title, "kind": it.kind, "reason": "; ".join(errs)})
            continue

        res.kept.append(it)
        if flags:
            res.flags[len(res.kept) - 1] = flags
    return res
