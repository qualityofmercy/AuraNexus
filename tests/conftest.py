from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from auranexus.api.app import create_app
from auranexus.config import Settings
from auranexus.container import Container, build_container
from auranexus.core.llm import FakeLLM
from auranexus.domain.models import Project, ProjectType

TENANT = "acme"
PID = "prj1"


class Harness:
    """Container + FakeLLM whose canned answers are registered per agent title."""

    def __init__(self, project_type: ProjectType = ProjectType.GREENFIELD) -> None:
        self.answers: dict[str, dict] = {}
        self.llm = FakeLLM(self._handler)
        self.settings = Settings(env="local")
        self.c: Container = build_container(self.settings, llm=self.llm)
        self.c.repo.register_tenant(TENANT)
        self.c.repo.put_project(Project(id=PID, tenant_id=TENANT, name="Demo", project_type=project_type))

    def _handler(self, system: str, user: str) -> dict:
        for title, ans in self.answers.items():
            if f"SKILL: {title}" in system:
                return ans
        return {"items": [], "open_questions": [], "notes": ""}

    def answer(self, title: str, items: list[dict], questions: list[str] | None = None) -> None:
        self.answers[title] = {"items": items, "open_questions": questions or [], "notes": ""}

    def client(self, roles: str, user: str = "u@x.com") -> TestClient:
        app = create_app(self.settings, self.c)
        return TestClient(app, headers={"X-Tenant-Id": TENANT, "X-Dev-User": user, "X-Dev-Roles": roles})


def item(kind: str, title: str, payload: dict | None = None, quote: str = "", speaker: str = "Anna", ts: str = "00:01:00",
         ref: str = "", confidence: float = 0.8, inferred: bool = False) -> dict:
    import json

    ev = [{"quote": quote, "timestamp": ts, "speaker": speaker, "source_ref": ref}] if (quote or ref) else []
    return {"kind": kind, "title": title, "payload_json": json.dumps(payload or {}), "evidence": ev,
            "confidence": confidence, "inferred": inferred}


@pytest.fixture
def h() -> Harness:
    return Harness()
