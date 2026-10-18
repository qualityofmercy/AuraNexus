"""Runtime settings (env prefix AURANEXUS_)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_home() -> Path:
    env = os.environ.get("AURANEXUS_HOME")
    return Path(env) if env else Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AURANEXUS_", env_file=".env", extra="ignore")

    env: Literal["local", "dev", "prod"] = "local"
    home: Path = Field(default_factory=_default_home)

    # persistence
    store_backend: Literal["memory", "postgres"] = "memory"
    database_url: str = ""  # postgresql+psycopg://user:pass@host/db

    # LLM: Gemini on Vertex AI (default for GCP deployments) or Claude on Vertex AI
    llm_backend: Literal["fake", "gemini", "claude"] = "fake"
    gcp_project: str = ""
    vertex_region: str = "global"
    model: str = ""  # empty = backend default (see llm_model)
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"  # Claude only
    temperature: float = 0.0  # Gemini only
    gemini_default_model: str = "gemini-2.5-pro"
    claude_default_model: str = "claude-sonnet-5-5"
    max_output_tokens: int = 16000
    max_input_chars: int = 400_000

    # events / notifications / analytics
    bus_backend: Literal["memory", "pubsub"] = "memory"
    pubsub_topic_prefix: str = "auranexus-dev"
    analytics_backend: Literal["null", "bigquery"] = "null"
    bigquery_dataset: str = ""

    # auth
    auth_mode: Literal["dev", "oidc"] = "dev"
    oidc_audience: str = ""
    # Extra accepted token audiences, e.g. the gcloud CLI client id so a developer can call dev with their own login.
    oidc_extra_audiences: list[str] = Field(default_factory=list)
    internal_service_accounts: list[str] = Field(default_factory=list)

    # Cloud Run replaces the signature of any Authorization JWT it validated, so the app cannot re-verify it.
    # trust_edge_iam: accept the (unsigned) claims of an IAM-validated caller. ONLY safe on a service whose invokers are
    # exactly the intended internal callers (the worker). enable_internal=false removes /internal/* (the API service).
    trust_edge_iam: bool = False
    enable_internal: bool = True

    # Sandbox demo service: dev header auth allowed outside local, but only with an in-memory store and the
    # scripted LLM, i.e. nothing real can be read or written.
    demo_mode: bool = False

    # orchestration
    max_event_depth: int = 8

    @property
    def llm_model(self) -> str:
        if self.model:
            return self.model
        return self.claude_default_model if self.llm_backend == "claude" else self.gemini_default_model

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    def validate_for_runtime(self) -> None:
        """Fail fast on unsafe production configuration."""
        if self.demo_mode and (self.store_backend != "memory" or self.llm_backend != "fake" or self.env == "prod"):
            raise RuntimeError("demo_mode requires the memory store, the fake LLM and a non-prod env")
        if self.env == "prod":
            problems = []
            if self.auth_mode != "oidc":
                problems.append("auth_mode must be 'oidc' in prod")
            if self.store_backend != "postgres":
                problems.append("store_backend must be 'postgres' in prod")
            if self.llm_backend not in ("gemini", "claude"):
                problems.append("llm_backend must be 'gemini' or 'claude' in prod")
            if problems:
                raise RuntimeError("Unsafe prod configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
