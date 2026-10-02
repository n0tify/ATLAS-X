"""Configuration model, validation, and bounded resource limits.

All limits have conservative defaults, are strictly positive, and carry an
upper bound so that a misconfiguration cannot silently become "unlimited".
Security-critical settings fail closed at validation time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SECRET_FIELDS = {"application_secret_key"}

_ALLOWED_ENVIRONMENTS = frozenset({"development", "production"})

#: Endpoints the planner is allowed to talk to. See ``_loopback_http_url``.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
    # A local model on CPU is not fast: llama3.1:8b measured 94s to answer a plan
    # prompt on the development machine (~1900 prompt tokens, ~80 generated). The
    # previous 60s default therefore made ATLAS-X unable to plan with its own
    # default model, which is a broken default rather than a strict one. 300s
    # accommodates a CPU-only 8B model while staying bounded; the refusal on
    # timeout is unchanged and still fails closed.
    model_timeout_seconds: int = Field(default=300, gt=0, le=3_600)
    model_context_tokens: int = Field(default=4_096, gt=0, le=131_072)
    # Local model endpoint (Phase 11). Loopback-only and plain HTTP, because the
    # requirement is a model that runs on this machine: there is no credential to
    # hold, no account, and no request that leaves the host. ``_loopback_http_url``
    # refuses anything else at validation time, so a configuration error cannot
    # turn "talk to a local model" into "post the task and the catalogue to a
    # remote service".
    model_base_url: str = Field(default="http://127.0.0.1:11434", min_length=1, max_length=256)
    model_name: str = Field(default="llama3.1:8b", min_length=1, max_length=64)
    #: Hard ceiling on the prompt the planner will send. Bounds the request the
    #: local daemon has to hold, and therefore the memory a long task can cost.
    #: The default has to exceed the *whole registry* rendered into one prompt:
    #: five tools with their declared input and output schemas come to roughly
    #: 7k characters, and a default below that would mean ATLAS-X cannot plan a
    #: task with its own tool set without configuration changes.
    model_max_prompt_chars: int = Field(default=32_000, gt=0, le=200_000)
    #: Hard ceiling on the model's reply, enforced by reading at most this many
    #: bytes. A reply that exceeds it is a failure, never silently truncated into
    #: a shorter plan that still parses.
    model_max_response_bytes: int = Field(default=64 * 1024, ge=1024, le=4 * 1024 * 1024)

    cpu_limit_cores: float | None = Field(default=None, gt=0)
    memory_limit_mb: int | None = Field(default=None, gt=0)

    @field_validator("environment")
    @classmethod
    def _environment_must_be_allowed(cls, value: str) -> str:
        if value not in _ALLOWED_ENVIRONMENTS:
            raise ValueError(f"environment must be one of {sorted(_ALLOWED_ENVIRONMENTS)}")
        return value

    @field_validator("model_base_url")
    @classmethod
    def _loopback_http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "http":
            raise ValueError("model_base_url must use http on loopback; no TLS endpoint exists")
        if parts.username or parts.password:
            raise ValueError("model_base_url must not carry credentials")
        # ``localhost`` is admitted because it is what an operator types, and it
        # resolves through the hosts file rather than DNS. Anything that is not a
        # loopback literal or that name is refused: a planner must not be
        # reconfigurable into sending the task and the tool catalogue off-host.
        if parts.hostname not in _LOOPBACK_HOSTS:
            raise ValueError(
                f"model_base_url host must be a loopback address, got {parts.hostname!r}"
            )
        return value.rstrip("/")

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
