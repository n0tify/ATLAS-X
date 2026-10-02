"""Configuration layer tests (Phase 5 prerequisites)."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.config.settings import Settings
from atlas.security.logging import SecretsRedactionFilter


def test_defaults_are_bounded_and_positive() -> None:
    settings = Settings()
    dump = settings.safe_dump()
    bounded_fields = [
        "auth_session_ttl_minutes",
        "auth_max_login_attempts",
        "auth_lockout_minutes",
        "max_task_chars",
        "max_plan_steps",
        "max_tool_calls",
        "max_recovery_attempts",
        "max_execution_seconds",
        "max_subprocess_seconds",
        "max_artifact_bytes",
        "max_input_dataset_bytes",
        "max_output_chars",
        "max_log_bytes",
        "max_concurrent_executions",
        "model_timeout_seconds",
        "model_context_tokens",
    ]
    for field in bounded_fields:
        assert dump[field] > 0, f"{field} must be strictly positive"
    assert settings.max_plan_steps <= 50
    assert settings.max_recovery_attempts <= 10


def test_from_environ_overrides_values() -> None:
    settings = Settings.from_environ(
        {
            "ATLAS_ENVIRONMENT": "development",
            "ATLAS_DATABASE_PATH": "tmp/test.db",
            "ATLAS_MAX_PLAN_STEPS": "7",
            "ATLAS_AUTH_SESSION_TTL_MINUTES": "30",
        }
    )
    assert settings.database_path == Path("tmp/test.db")
    assert settings.max_plan_steps == 7
    assert settings.auth_session_ttl_minutes == 30


def test_unknown_env_key_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.from_environ({"ATLAS_DATABASE_PATH": "x.db", "ATLAS_BOGUS": "1"})


def test_production_requires_secret_key() -> None:
    with pytest.raises(ValidationError, match="application_secret_key"):
        Settings(environment="production")
    ok = Settings(environment="production", application_secret_key="a-long-random-value")
    assert ok.environment == "production"


def test_invalid_environment_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")


def test_zero_and_negative_limits_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(max_plan_steps=0)
    with pytest.raises(ValidationError):
        Settings(max_tool_calls=-1)


def test_excessive_value_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(max_plan_steps=10_000)


def test_negative_cpu_limit_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(cpu_limit_cores=-1.0)


def test_safe_dump_excludes_secrets() -> None:
    settings = Settings(application_secret_key="hunter2-super-secret")
    dump = settings.safe_dump()
    assert "application_secret_key" not in dump
    assert "hunter2-super-secret" not in repr(dump)
    assert settings.secret_values() == ["hunter2-super-secret"]


def test_secret_values_never_reach_log_output() -> None:
    secret = "hunter2-super-secret"
    settings = Settings(application_secret_key=secret)
    logger = logging.getLogger("atlas.tests.redaction")
    logger.handlers.clear()
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretsRedactionFilter(settings.secret_values()))
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    logger.error("bad things happened near %s", secret)
    logger.info("no secret in this line")

    text = stream.getvalue()
    assert secret not in text
    assert "[REDACTED]" in text
    assert "no secret in this line" in text
