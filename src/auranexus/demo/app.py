"""Sandbox demo service: the real API plus a guided scenario and a browser UI.

Safety: in-memory store, scripted LLM, no database, no GCP permissions. ``Settings.demo_mode`` refuses any other
combination. Run with ``uvicorn auranexus.demo.app:create_app --factory``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..api.app import create_app as create_api_app
from ..config import Settings
from ..container import Container, build_container
from ..core.hitl import HITLError
from ..domain.models import CheckpointStatus
from . import dataset as D
from .llm import DemoLLM
from .steps import PERSONAS, STEP_BY_ID, STEPS, P, T, seed

log = logging.getLogger("auranexus.demo")
UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def demo_settings() -> Settings:
    return Settings(env="dev", auth_mode="dev", demo_mode=True, store_backend="memory", llm_backend="fake",
                    bus_backend="memory", analytics_backend="null", internal_service_accounts=[], enable_internal=False)


def fresh_container(settings: Settings) -> Container:
    c = build_container(settings, llm=DemoLLM())
    seed(c)
    return c


# ----------------------------------------------------------------------------------------- snapshots / views

def _snapshot(c: Container) -> dict[str, Any]:
    r = c.repo
    return {
        "proposals": {p.id for p in r.list_proposals(T, P)},
        "reports": {f"{d['kind']}:{d['id']}" for d in r.report_list(T, P)},
        "notifications": {d["id"] for d in r.list_notifications(T, P)},
        "runs": {d["id"] for d in r.list_runs(T, P)},
        "audit": len(r.store.list_audit(T, P, 100000)),
    }


def _delta(c: Container, before: dict[str, Any]) -> dict[str, Any]:
    r = c.repo
    return {
        "proposals": [p.model_dump(mode="json") for p in r.list_proposals(T, P) if p.id not in before["proposals"]],
        "reports": [d for d in r.report_list(T, P) if f"{d['kind']}:{d['id']}" not in before["reports"]],
        "notifications": [d for d in r.list_notifications(T, P) if d["id"] not in before["notifications"]],
        "runs": [d for d in r.list_runs(T, P) if d["id"] not in before["runs"]],
        "audit_added": len(r.store.list_audit(T, P, 100000)) - before["audit"],
    }


def _view(c: Container) -> dict[str, Any]:
    r = c.repo
    ok, bad = r.audit.verify(T)
    audit = r.store.list_audit(T, P, 100000)
    return {
        "checkpoints": c.orchestrator.open_checkpoints(T, P),
        "proposals": [p.model_dump(mode="json") for p in r.list_proposals(T, P)],
        "reports": r.report_list(T, P),
        "notifications": r.list_notifications(T, P),
        "register": {k: len(r.register_list(T, P, k)) for k in sorted({d["kind"] for d in r.register_list(T, P)})},
        "register_items": r.register_list(T, P),
        "audit": audit[-60:],
        "audit_total": len(audit),
        "audit_ok": ok,
        "audit_bad_seq": bad,
        "runs": r.list_runs(T, P),
    }


def _thread(c: Container) -> list[dict[str, Any]]:
    """Follow REQ-FI-019 through every phase from what the platform actually recorded."""
    r, req = c.repo, D.THREAD_REQ
    props = r.list_proposals(T, P)

    def find(kind: str, pid: str):
        return next((p for p in props if p.kind == kind and p.payload.get("id") == pid), None)

    def node(phase: str, title: str, state: str, detail: str) -> dict[str, Any]:
        return {"phase": phase, "title": title, "state": state, "detail": detail}

    # Prepare
    cp1 = find("requirement_entry", req)
    rej = next((d for d in r.register_list(T, P, "rejection") if cp1 and d["id"] == cp1.id), None)
    if not cp1:
        prep = node("Prepare", "Captured from garbled audio, then rejected at CP1", "none", "Not yet extracted.")
    elif rej:
        prep = node("Prepare", "Captured from garbled audio, then rejected at CP1", "miss",
                    f"Extracted at {round(cp1.confidence * 100)}% confidence. Rejected by {rej['rejected_by']}: \"{rej['reason']}\"")
    else:
        prep = node("Prepare", "Captured from garbled audio, then rejected at CP1", "ok",
                    f"Extracted at {round(cp1.confidence * 100)}% confidence; awaiting CP1.")

    # Design
    kdd = r.register_get(T, "decision", "KDD-FI-09")
    design = node("Design", "KDD-FI-09 approved with a missed impact", "miss" if kdd else "none",
                  f"{kdd.get('approval_note') or 'Approved.'} Assumption A-01 (zero minor-currency discrepancies) is still open."
                  if kdd else "Design not run yet.")

    # Build
    fs = find("fs_gap_report", "FSGAP-01")
    build_fs = node("Build (FS)", "Requirement unmapped in the FS", "miss" if fs else "none",
                    "FS review lists REQ-FI-019 as 'Unmapped (Missed)'; the report was accepted without an assigned action."
                    if fs else "FS review not run yet.")
    rev3 = find("review_finding", "REV-03")
    build_code = node("Build (code)", "REV-03 critical finding deferred", "miss" if rev3 else "none",
                      f"Hardcoded currency conversion flagged Critical. Decision: {rev3.status.value}." if rev3 else "Code review not run yet.")

    # Test
    cases = r.register_list(T, P, "test_case")
    test = node("Test", "No test ever linked to the requirement", "miss" if cases else "none",
                f"Tracker has {len(cases)} cases; none is linked to {req} (TC-FI-09 does not exist)." if cases else "Tracker not created yet.")

    # Run
    t112 = r.register_get(T, "rehearsal_task", "DR1:TSK-FI-112")
    sc = next(iter(r.report_list(T, P, "scorecard")), None) or next((p.payload for p in props if p.kind == "scorecard"), None)
    score_txt = f"; scorecard {sc.get('rating')} {sc.get('total')}" if sc else ""
    run = node("Run (Dry Run 1)", "Defect surfaces: reconciliation fails", "caught" if t112 else "none",
               f"TSK-FI-112 {t112['status']} (variance INR 1,420,000, ERR-FIN-99){score_txt}." if t112 else "Dry run not executed yet.")

    # Learn
    ref = next((p for p in props if p.kind == "refinement_proposal"), None)
    gv = r.register_list(T, P, "guideline_version")
    back = r.register_get(T, "requirement_entry", req)
    closed = bool(back and back.get("status") == "reinstated" and gv)
    if closed and ref:
        learn = node("Learn", "Feedback loop: requirement reinstated, guideline published", "ok",
                     f"{ref.payload.get('proposal_id')} approved by two roles. {req} re-injected; guideline library now at v{gv[-1]['version']}.")
    elif ref:
        learn = node("Learn", "Feedback loop: requirement reinstated, guideline published", "pending",
                     f"{ref.payload.get('proposal_id')} awaiting tier-3 approval (PM + Steering Committee).")
    else:
        learn = node("Learn", "Feedback loop: requirement reinstated, guideline published", "none", "No refinement proposal yet.")
    return [prep, design, build_fs, build_code, test, run, learn]


# ----------------------------------------------------------------------------------------- app

def create_app() -> FastAPI:
    settings = demo_settings()
    settings.validate_for_runtime()
    app = create_api_app(settings, fresh_container(settings))
    app.state.demo = {"done": {}, "delta": {}}
    router = APIRouter(prefix="/demo")

    def c_(request: Request) -> Container:
        return request.app.state.container

    def _remember(request: Request, step_id: str, result: dict[str, Any]) -> None:
        """Keep each step's results server-side so a browser refresh mid-recording loses nothing."""
        store = request.app.state.demo["delta"]
        prev = store.get(step_id, {})
        merged = {**prev, **{k: v for k, v in result.items() if k not in ("proposals", "reports", "notifications", "runs", "audit_added")}}
        for k in ("proposals", "reports", "notifications", "runs"):
            merged[k] = [*prev.get(k, []), *result.get(k, [])]
        merged["audit_added"] = prev.get("audit_added", 0) + result.get("audit_added", 0)
        store[step_id] = merged

    @router.get("/script")
    def script(request: Request) -> dict[str, Any]:
        return {
            "project": {"id": P, "tenant": T, "name": D.PROJECT_NAME},
            "personas": [{"key": p.key, "name": p.name, "title": p.title, "email": p.email, "roles": [r.value for r in p.roles]} for p in PERSONAS.values()],
            "steps": [{"id": s.id, "phase": s.phase, "title": s.title, "story": s.story, "agents": s.agents, "run_label": s.run_label,
                       "human_label": s.human_label, "insight": s.insight,
                       "human": [{"persona": h.persona, "kind": h.kind, "outcome": h.outcome.value, "pid": h.pid, "note": h.note, "reason": h.reason} for h in s.human]}
                      for s in STEPS],
            "done": request.app.state.demo["done"],
        }

    @router.post("/steps/{step_id}/run")
    def run_step(step_id: str, request: Request) -> dict[str, Any]:
        s = STEP_BY_ID.get(step_id)
        if not s or not s.run:
            raise HTTPException(404, "no runnable action for this step")
        c = c_(request)
        before = _snapshot(c)
        try:
            s.run(c)
        except Exception as exc:  # surfaced in the UI rather than a blank failure
            log.exception("demo step %s failed", step_id)
            raise HTTPException(500, f"step failed: {exc}") from exc
        request.app.state.demo["done"].setdefault(step_id, {})["ran"] = True
        result = _delta(c, before)
        _remember(request, step_id, result)
        return result

    @router.post("/steps/{step_id}/human")
    def human_step(step_id: str, request: Request) -> dict[str, Any]:
        s = STEP_BY_ID.get(step_id)
        if not s or not s.human:
            raise HTTPException(404, "no suggested human action for this step")
        c = c_(request)
        before = _snapshot(c)
        performed, skipped = [], []
        for h in s.human:
            persona = PERSONAS[h.persona]
            match = None
            for cp in c.repo.list_checkpoints(T, P, status=CheckpointStatus.OPEN.value):
                prop = c.repo.get_proposal(T, cp.proposal_id)
                if prop and prop.kind == h.kind and (not h.pid or prop.payload.get("id") == h.pid):
                    already = any(a.decided_by == persona.email for a in cp.approvals)
                    if not already:
                        match = (cp, prop)
                        break
            if not match:
                skipped.append({"kind": h.kind, "pid": h.pid, "why": "no open checkpoint (run the step first or already decided)"})
                continue
            cp, prop = match
            try:
                c.hitl.decide(T, cp.id, persona.email, list(persona.roles), h.outcome, h.reason,
                              {**prop.payload, **h.changes} if h.changes else None, acting_role=persona.roles[0])
            except HITLError as exc:
                skipped.append({"kind": h.kind, "pid": h.pid, "why": str(exc)})
                continue
            performed.append({"persona": persona.name, "title": persona.title, "kind": h.kind, "item": prop.title, "outcome": h.outcome.value,
                              "reason": h.reason})
        request.app.state.demo["done"].setdefault(step_id, {})["human"] = bool(performed)
        result = {"performed": performed, "skipped": skipped, **_delta(c, before)}
        _remember(request, step_id, result)
        return result

    @router.get("/view")
    def view(request: Request) -> dict[str, Any]:
        return {**_view(c_(request)), "done": request.app.state.demo["done"], "deltas": request.app.state.demo["delta"]}

    @router.get("/thread")
    def thread(request: Request) -> list[dict[str, Any]]:
        return _thread(c_(request))

    @router.post("/reset")
    def reset(request: Request) -> dict[str, str]:
        request.app.state.container = fresh_container(settings)
        request.app.state.demo = {"done": {}, "delta": {}}
        return {"status": "reset"}

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/ui/")

    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
    return app

