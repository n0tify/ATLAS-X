"""Configuration model, validation, and bounded resource limits.

All limits have conservative defaults, are strictly positive, and carry an
upper bound so that a misconfiguration cannot silently become "unlimited".
Security-critical settings fail closed at validation time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SECRET_FIELDS = {"application_secret_key"}

_ALLOWED_ENVIRONMENTS = frozenset({"development", "production"})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str = Field(default="development")
    database_path: Path = Field(default=Path("data/atlas.db"))

    # Sandbox confinement (Phase 10B). Every tool invocation runs as an
    # unprivileged Linux process inside a WSL guest, so these are not tuning
    # knobs for an optional feature: they are the bounds that get applied. There
    # is deliberately no ``sandbox_enabled`` flag, because a switch that turns the
    # confinement off is a trusted bypass, and the requirement is that every tool
    # goes through the sandbox. Availability is reported by
    # ``SandboxSupervisor.health()`` instead, and an unavailable guest fails the
    # call rather than running the tool in-process.
    sandbox_distribution: str = Field(default="Ubuntu-24.04", min_length=1, max_length=64)
    sandbox_memory_mb: int = Field(default=1024, ge=64, le=4096)
    sandbox_pids_max: int = Field(default=256, ge=8, le=4096)
    sandbox_cpu_cores: float = Field(default=1.0, gt=0, le=8)
    sandbox_max_output_bytes: int = Field(default=1024 * 1024, ge=1024, le=4 * 1024 * 1024)
    sandbox_max_artifact_bytes: int = Field(default=16 * 1024 * 1024, ge=1024)
    #: Extra seconds the supervisor waits past the invocation's own bound before
    #: giving up on the guest. The guest enforces the real limit; this only covers
    #: the gap between the guest's kill and its report arriving.
    sandbox_launcher_timeout_seconds: int = Field(default=20, ge=1, le=300)

    application_secret_key: str | None = Field(default=None)

    auth_session_ttl_minutes: int = Field(default=60, gt=0, le=24 * 60)
    auth_max_login_attempts: int = Field(default=5, gt=0, le=50)
    auth_lockout_minutes: int = Field(default=15, gt=0, le=24 * 60)
    auth_failure_delay_seconds: float = Field(default=0.1, ge=0.0, le=10.0)

    max_task_chars: int = Field(default=4_000, gt=0, le=100_000)
    max_plan_steps: int = Field(default=10, gt=0, le=50)
    max_tool_calls: int = Field(default=12, gt=0, le=100)
    max_recovery_attempts: int = Field(default=2, gt=0, le=10)
    max_execution_seconds: int = Field(default=120, gt=0, le=3_600)
    max_subprocess_seconds: int = Field(default=30, gt=0, le=600)
    max_artifact_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_input_dataset_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    max_output_chars: int = Field(default=20_000, gt=0, le=1_000_000)
    max_log_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    max_concurrent_executions: int = Field(default=1, gt=0, le=16)
    model_timeout_seconds: int = Field(default=60, gt=0, le=3_600)
    model_context_tokens: int = Field(default=4_096, gt=0, le=131_072)

    cpu_limit_cores: float | None = Field(default=None, gt=0)
    memory_limit_mb: int | None = Field(default=None, gt=0)

    @field_validator("environment")
    @classmethod
    def _environment_must_be_allowed(cls, value: str) -> str:
        if value not in _ALLOWED_ENVIRONMENTS:
            raise ValueError(f"environment must be one of {sorted(_ALLOWED_ENVIRONMENTS)}")
        return value

    @model_validator(mode="after")
    def _fail_closed_in_production(self) -> Settings:
        if self.environment == "production" and not self.application_secret_key:
            raise ValueError(
                "application_secret_key is required when environment='production'"
            )
        return self

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> Settings:
        source = dict(os.environ if environ is None else environ)
        prefix = "ATLAS_"
        kwargs: dict[str, Any] = {}
        for key, value in source.items():
            if key.startswith(prefix):
                kwargs[key[len(prefix) :].lower()] = value
        return cls(**kwargs)

    def safe_dump(self) -> dict[str, Any]:
        return self.model_dump(exclude=_SECRET_FIELDS)

    def secret_values(self) -> list[str]:
        values = []
        for field in _SECRET_FIELDS:
            value = getattr(self, field, None)
            if value:
                values.append(str(value))
        return values
