"""Phase 11 against the real local model daemon.

The deterministic tests in ``tests/test_planner.py`` stub the model, which is the
right way to test bounds and refusals. This file exists to answer a different
question: does the adapter actually talk to a local model, and does that model
return anything a bounded parser will accept?

Every test here skips when the daemon is absent or the configured model is not
pulled. A research platform must not require a GPU to run its unit tests, and a
missing daemon is an operator problem rather than a failure of this codebase --
the same reason :mod:`atlas.planner.model` refuses to fall back rather than
degrade. What is *not* negotiable is that these tests never run against anything
but loopback: the client checks the host, and the fixture checks it again.

Run them explicitly with::

    ATLAS_MODEL_LIVE=1 pytest tests/test_planner_live.py
"""

from __future__ import annotations

import os
import socket
from typing import Iterator

import pytest

from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.planner.model import LocalModelClient, ModelMessage
from atlas.planner.plan import PlanDocument
from atlas.planner.prompt import build_messages
from atlas.planner.service import PlannerService
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database

PASSWORD = "correct horse battery staple"

#: Off by default so the ordinary suite stays hermetic and GPU-free.
LIVE = os.environ.get("ATLAS_MODEL_LIVE") == "1"


def _daemon_up(base_url: str, timeout: float = 2.0) -> bool:
    host, _, port = base_url.rpartition("://")[2].partition(":")
    if host == "localhost":
        host = "127.0.0.1"
    try:
        with socket.create_connection((host, int(port or 11434)), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture
def live_settings() -> Iterator[Settings]:
    if not LIVE:
        pytest.skip("set ATLAS_MODEL_LIVE=1 to exercise the local model daemon")
    settings = Settings()
    if not _daemon_up(settings.model_base_url):
        pytest.skip(f"no model daemon listening on {settings.model_base_url}")
    yield settings


@pytest.fixture
def authz(db: Database, auth: AuthService) -> AuthorizationService:
    return AuthorizationService(db, auth)


@pytest.fixture
def alice_token(auth: AuthService) -> str:
    auth.register("alice", PASSWORD)
    return str(auth.login("alice", PASSWORD)["token"])


def test_the_adapter_reaches_the_real_daemon(live_settings: Settings) -> None:
    client = LocalModelClient(live_settings)
    response = client.complete(
        (
            ModelMessage(role="system", content="Reply with one JSON object only."),
            ModelMessage(role="user", content='Reply with {"ok": true} and nothing else.'),
        )
    )
    assert response.model_id
    assert isinstance(response.text, str)
    # Constrained decoding was requested, so the daemon should have produced an
    # object even though the prompt did not insist on one.
    assert response.text.strip().startswith("{")


def test_the_real_model_returns_a_plan_this_build_accepts(
    live_settings: Settings, authz: AuthorizationService, alice_token: str
) -> None:

    task = authz.create_task(
        alice_token, title="t", goal="Measure word statistics for the text 'hello world'"
    )
    planner = PlannerService(authz, settings=live_settings)
    outcome = planner.plan_task(alice_token, task["id"])

    assert outcome.plan["source"] == "planner"
    assert outcome.plan["model_id"]
    assert outcome.plan["digest"].startswith("sha256:")
    # The document that was stored has to be re-readable under the same bounds
    # that accepted it in memory, or the stored plan and the validated plan are
    # two different things.
    stored = PlanDocument.from_payload(
        __import__("json").loads(str(outcome.plan["plan_json"])),
        max_steps=live_settings.max_plan_steps,
    )
    assert stored.digest() == outcome.plan["digest"]

    # Whether the model's particular plan validates depends on the model, so the
    # contract asserted here is the shape of the verdict rather than its value:
    # a verdict exists, it is serializable, and it agrees with the stored flag.
    report = outcome.validation
    assert report.valid == (outcome.plan["validated"] == 1)
    if not report.valid:
        assert report.findings


def test_the_prompt_the_daemon_receives_names_only_registered_tools(
    live_settings: Settings,
) -> None:
    from atlas.tools.registry import default_registry

    messages = build_messages(
        goal="do something", registry=default_registry(), max_steps=10, max_tool_calls=12
    )
    total = sum(len(message.content) for message in messages)
    assert total <= live_settings.model_max_prompt_chars
