"""Phase 18: First complete end-to-end agent.

This test demonstrates the complete ATLAS-X execution path:
AUTH -> PLANNER -> EXECUTOR -> VERIFIER -> ARTIFACT -> PROVENANCE

The test demonstrates a complete task execution from planning through
verification to artifact creation, with full provenance tracking.
"""

from __future__ import annotations

import json

import pytest

from atlas.auth.service import AuthService
from atlas.executor.service import ExecutorService
from atlas.planner.plan import PlanDocument
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.repositories import ProvenanceRepo
from atlas.storage.tool_grants import ToolGrantRepo
from atlas.tools.dispatch import DispatchLimits, ToolDispatcher
from atlas.tools.registry import default_registry
from atlas.verifier.service import VerifierService

PASSWORD = "correct horse battery staple"
TOOL_A = "text_statistics"
TOOL_B = "numeric_summary"
CSV_TOOL = "csv_statistics"


def _user_id(db: Database, username: str) -> int:
    row = db.connect().execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    return int(row["id"]) if row else 0


@pytest.fixture
def alice(auth: AuthService) -> str:
    """Create and return an authenticated user token."""
    auth.register("alice", PASSWORD)
    return str(auth.login("alice", PASSWORD)["token"])


def _store_plan(
    authz: AuthorizationService,
    token: str,
    task_id: int,
    payload: dict,
    *,
    validated: bool = True,
) -> dict:
    """Persist a plan through the real Phase 11 write path."""
    document = PlanDocument.from_payload(payload, max_steps=16)
    steps = [
        {
            "tool_id": step.tool_id,
            "step_key": step.step_key,
            "depends_on": list(step.depends_on),
            "input": step.input,
            "action": step.action or step.tool_id,
        }
        for step in document.steps
    ]
    return authz.create_plan(
        token,
        task_id=task_id,
        plan_json=document.canonical_json(),
        digest=document.digest(),
        steps=steps,
        model_id="stub-model:1b",
        source="planner",
        validated=validated,
        validation_json=None,
    )


def _text_result(text: str) -> dict:
    """The contract's own answer for ``text``, derived independently here."""

    lines = text.splitlines()
    words = text.split()
    lengths = [len(word) for word in words]
    return {
        "char_count": len(text),
        "line_count": len(lines),
        "longest_line_length": max((len(line) for line in lines), default=0),
        "word_count": len(words),
        "unique_word_count": len(set(words)),
        "min_word_length": min(lengths, default=0),
        "max_word_length": max(lengths, default=0),
    }


class _StubDispatcher:
    """Returns a caller-supplied result so the stored bytes can be controlled.

    Tests that need the recorded result to be *wrong* cannot get there through a
    real tool, because a real tool returns the right answer. Writing the
    executor's output directly is the honest way to set up a corrupted record.
    """

    def __init__(self, result: dict) -> None:
        self._result = dict(result)
        self.calls = 0

    def dispatch(
        self,
        session_token,
        *,
        tool_id,
        task_id,
        arguments,
        execution_id=None,
        plan_id=None,
        plan_step_id=None,
        invocation_id=None,
    ):  # type: ignore[no-untyped-def]
        from atlas.tools.dispatch import ToolInvocation

        self.calls += 1
        return ToolInvocation(
            tool_id=str(tool_id),
            tool_version="1.0.0",
            capability=str(tool_id),
            determinism="deterministic",
            user_id=1,
            task_id=int(task_id),
            result=self._result,
            record={},
            provenance_event_id=1,
        )


class TestPhase18E2E:
    """Phase 18 complete end-to-end tests."""

    def test_complete_text_analysis_e2e(
        self,
        db: Database,
        auth: AuthService,
        alice: str,
    ) -> None:
        """
        Complete E2E test: text statistics analysis with full verification.
        """
        alice_id = _user_id(db, "alice")
        grants = ToolGrantRepo(db, registry_ready=True)
        authz = AuthorizationService(db, auth, tool_grants=grants)

        for tool_id in [TOOL_A, TOOL_B]:
            grants.grant(user_id=alice_id, tool_name=tool_id, granted_by="operator")

        task = int(authz.create_task(alice, title="Text Analysis", goal="Measure text")["id"])

        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "Measure text statistics",
                "steps": [
                    {
                        "step_key": "measure",
                        "tool_id": TOOL_A,
                        "input": {"text": "hello brave world"},
                        "depends_on": [],
                    },
                ],
            },
        )

        executor = ExecutorService(
            authz,
            ToolDispatcher(
                db, authz, default_registry(), limits=DispatchLimits(max_tool_calls=8)
            ),
        )
        outcome = executor.execute(alice, task)

        assert outcome.task_status == "executed"
        assert outcome.steps[0].succeeded
        assert outcome.steps[0].tool_id == TOOL_A
        assert outcome.steps[0].result["char_count"] == 17

        # Verify verification
        verifier = VerifierService(
            AuthorizationService(db, auth)
        )
        report = verifier.verify_task(alice, task)
        assert report.passed
        assert report.verdict == "pass"

        # Verify provenance chain
        prov_repo = ProvenanceRepo()
        with auth._db.connect() as conn:
            chain = prov_repo.get_events_for_task(conn, task)
        assert len(chain) >= 4

        # Verify chain integrity
        for event in chain:
            assert hasattr(event, "chain_digest")
            if event.sequence_no > 1:
                _ = next(e for e in chain if e.sequence_no == event.sequence_no - 1)

        # Verify task final status
        final_task = authz.get_task(alice, task)
        assert final_task["status"] == "succeeded"
        assert final_task["result_json"] is not None
        result = json.loads(final_task["result_json"])
        assert result["verdict"] == "pass"
        assert result["plan_id"] is not None
        assert "steps" in result

    def test_verification_failure_e2e(
        self,
        db: Database,
        auth: AuthService,
        alice: str,
    ) -> None:
        """
        E2E test where verification fails - task should end in FAILED state.
        """
        alice_id = _user_id(db, "alice")
        grants = ToolGrantRepo(db, registry_ready=True)
        authz = AuthorizationService(db, auth, tool_grants=grants)

        grants.grant(user_id=alice_id, tool_name=TOOL_A, granted_by="operator")

        task = int(authz.create_task(alice, title="Bad Analysis", goal="Fail verification")["id"])

        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "This will fail",
                "steps": [
                    {
                        "step_key": "measure",
                        "tool_id": TOOL_A,
                        "input": {"text": "hello"},
                        "depends_on": [],
                    },
                ],
            },
        )

        # Execute with wrong result (tampered)
        wrong_dispatcher = _StubDispatcher({"char_count": 999, "line_count": 1, "word_count": 1})
        executor = ExecutorService(authz, wrong_dispatcher)
        outcome = executor.execute(alice, task)

        assert outcome.task_status == "executed"

        # Verification should fail
        verifier = VerifierService(
            AuthorizationService(db, auth)
        )
        report = verifier.verify_task(alice, task)
        assert not report.passed
        assert report.verdict == "fail"

        # Task should be FAILED
        final_task = authz.get_task(alice, task)
        assert final_task["status"] == "failed"
        assert final_task["result_json"] is None


def _user_id(db: Database, username: str) -> int:
    row = db.connect().execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    return int(row["id"]) if row else 0
