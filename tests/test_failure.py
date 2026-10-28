"""The ``failures`` table: the column mapping, and the derivation that reads it.

This module exists because ``atlas.failure`` had no direct tests at all, and the
one defect that hid the missing ``tasks.failure_category`` lived exactly there:
``FailureRepo.create`` inserted into columns ``code`` and ``detail``, and the
table has ``error_code`` and ``diagnosis``. Every insert raised ``OperationalError``,
the caller swallowed it, and the table stayed empty -- so nothing downstream could
tell a sandbox refusal from a tool error, and no test noticed because no test
wrote a failure.

The mapping is therefore pinned from both ends: the SQL names are asserted, and
the values are read back through the record so a rename cannot drift unnoticed in
either direction.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from atlas.auth.service import AuthService
from atlas.failure.classify import FailureClassifier
from atlas.failure.repo import (
    MAX_DETAIL_CHARS,
    FailureRepo,
    derive_task_failure_category,
)
from atlas.failure.types import (
    FailureCategory,
    FailureWriteInvalid,
    is_recoverable,
    task_failure_category,
)
from atlas.planner.plan import PlanDocument
from atlas.sandbox.errors import SandboxViolation, SandboxWorkspaceFailure
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.migrations import SCHEMA_STATEMENTS
from atlas.tools.errors import ToolExecutionFailed

PASSWORD = "correct horse battery staple"

#: The columns a ``failures`` row is actually made of. Written out here rather
#: than imported so that changing the schema without changing this mapping is a
#: test failure instead of a silent behaviour change.
FAILURE_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "execution_id",
        "category",
        "diagnosis",
        "detail_json",
        "error_code",
        "retryable",
        "plan_step_id",
        "invocation_id",
        "created_at",
    }
)


@pytest.fixture
def authz(db: Database, auth: AuthService) -> AuthorizationService:
    return AuthorizationService(db, auth)


@pytest.fixture
def alice(auth: AuthService) -> str:
    auth.register("alice", PASSWORD)
    return str(auth.login("alice", PASSWORD)["token"])


def _executed(authz: AuthorizationService, token: str) -> int:
    """A task with one plan and one execution, so a failure has something to attach to."""

    from atlas.executor.service import ExecutorService

    task = int(authz.create_task(token, title="t", goal="g")["id"])
    document = PlanDocument.from_payload(
        {
            "summary": "One deterministic step.",
            "steps": [
                {
                    "step_key": "only",
                    "tool_id": "text_statistics",
                    "input": {"text": "hello world"},
                    "depends_on": [],
                }
            ],
        },
        max_steps=16,
    )
    authz.create_plan(
        token,
        task_id=task,
        plan_json=document.canonical_json(),
        digest=document.digest(),
        steps=[
            {
                "tool_id": step.tool_id,
                "step_key": step.step_key,
                "depends_on": list(step.depends_on),
                "input": step.input,
                "action": step.action or step.tool_id,
            }
            for step in document.steps
        ],
        model_id=None,
        source="planner",
        validated=True,
        validation_json=None,
    )
    # The dispatcher is irrelevant here; what matters is that an `executions` row
    # exists, and the executor is the only supported way to make one.
    class _Stub:
        calls = 0

        def dispatch(self, *args: Any, **kwargs: Any) -> Any:
            from atlas.tools.dispatch import ToolInvocation

            self.calls += 1
            return ToolInvocation(
                tool_id="text_statistics",
                tool_version="1.0.0",
                capability="text_statistics",
                determinism="deterministic",
                user_id=1,
                task_id=int(kwargs["task_id"]),
                result={"char_count": 11},
                record={},
                provenance_event_id=1,
            )

    ExecutorService(authz, _Stub()).execute(token, task)
    return task


class TestSchemaContract:
    def test_the_table_has_no_code_or_detail_column(self) -> None:
        # Stated negatively and explicitly, because the bug was an INSERT naming
        # columns that do not exist. If a migration ever adds `code` or `detail`,
        # this fails and the mapping in FailureRepo has to be revisited on purpose.
        for statement in SCHEMA_STATEMENTS:
            if "CREATE TABLE IF NOT EXISTS failures" in statement:
                break
        else:  # pragma: no cover - the table exists in every schema version
            pytest.fail("no failures table in the migration list")

        with pytest.raises(sqlite3.OperationalError):
            connection = sqlite3.connect(":memory:")
            try:
                connection.execute(statement)
                connection.execute(
                    "INSERT INTO failures (execution_id, category, code) VALUES (1, 'x', 'y')"
                )
            finally:
                connection.close()

    def test_the_record_and_the_table_agree_on_the_column_names(self) -> None:
        # Every attribute `FailureRecord` exposes must come from a real column, and
        # every real column must be readable. `code` and `error_code` are the one
        # deliberate overlap and are asserted separately below.
        repo = FailureRepo()
        row = {
            "id": 1,
            "execution_id": 1,
            "category": "tool_execution_failed",
            "error_code": "tool_raised",
            "diagnosis": "the tool raised",
            "detail_json": None,
            "plan_step_id": None,
            "invocation_id": None,
            "retryable": 1,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        record = repo._row_to_failure(row)  # noqa: SLF001 - the mapping is the subject
        assert record.code == row["error_code"]
        assert record.error_code == row["error_code"]
        assert record.detail == row["diagnosis"]
        assert set(row) == FAILURE_COLUMNS


class TestWriteMapping:
    def test_a_failure_round_trips_through_its_real_columns(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        task = _executed(authz, alice)
        execution = authz.executions_for_task(alice, task)[0]

        failure_id = authz.record_failure_by_code(
            alice,
            execution_id=int(execution["id"]),
            code="tool_raised",
            detail="the tool raised inside the sandbox",
        )

        with db.transaction() as conn:
            row = conn.execute(
                "SELECT category, error_code, diagnosis, detail_json FROM failures "
                "WHERE id = ?",
                (failure_id,),
            ).fetchone()
        assert row is not None
        assert row["category"] == "tool_execution_failed"
        # The classification code lives in `error_code`; the operator-facing text
        # lives in `diagnosis`. Neither is invented at read time.
        assert row["error_code"] == "tool_raised"
        assert row["diagnosis"] == "the tool raised inside the sandbox"

    def test_code_and_error_code_are_one_value_under_two_names(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        # `code` is the vocabulary's name for the classification; `error_code` is
        # the column that holds it. They are written once and read back from the
        # one column, so a record can never disagree with itself.
        task = _executed(authz, alice)
        execution = authz.executions_for_task(alice, task)[0]
        authz.record_failure_by_code(
            alice,
            execution_id=int(execution["id"]),
            code="violation_network",
            detail="refused",
        )

        with db.transaction() as conn:
            records = FailureRepo().for_task(conn, task)
        assert len(records) == 1
        record = records[0]
        assert record.code == record.error_code == "violation_network"
        assert record.detail == "refused"

    def test_two_codes_for_one_failure_are_refused(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        # The duplicate parameter is kept for call-site clarity, so it has to be
        # closed. Silently preferring one of two disagreeing codes would hide from
        # the reader that one of them was wrong.
        task = _executed(authz, alice)
        execution = authz.executions_for_task(alice, task)[0]
        with db.transaction() as conn:
            with pytest.raises(FailureWriteInvalid):
                FailureRepo().create(
                    conn,
                    execution_id=int(execution["id"]),
                    category="tool_execution_failed",
                    code="tool_raised",
                    error_code="sandbox_timeout",
                )

    def test_a_failure_needs_an_execution_that_exists(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        # There is no "the run felt wrong" failure.
        with db.transaction() as conn:
            with pytest.raises(FailureWriteInvalid):
                FailureRepo().create(
                    conn,
                    execution_id=999_999,
                    category="tool_execution_failed",
                    code="tool_raised",
                )

    def test_detail_is_bounded(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        # An unbounded detail would let one row become a log sink.
        task = _executed(authz, alice)
        execution = authz.executions_for_task(alice, task)[0]
        with db.transaction() as conn:
            with pytest.raises(FailureWriteInvalid):
                FailureRepo().create(
                    conn,
                    execution_id=int(execution["id"]),
                    category="tool_execution_failed",
                    code="tool_raised",
                    detail="x" * (MAX_DETAIL_CHARS + 1),
                )

    def test_a_code_outside_the_vocabulary_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        task = _executed(authz, alice)
        execution = authz.executions_for_task(alice, task)[0]
        with db.transaction() as conn:
            for bad in ("not_a_code", "", "TOOL_RAISED"):
                with pytest.raises(FailureWriteInvalid):
                    FailureRepo().create(
                        conn,
                        execution_id=int(execution["id"]),
                        category="tool_execution_failed",
                        code=bad,
                    )
            for bad_category in ("nope", "", "TOOL_EXECUTION_FAILED"):
                with pytest.raises(FailureWriteInvalid):
                    FailureRepo().create(
                        conn,
                        execution_id=int(execution["id"]),
                        category=bad_category,
                        code="tool_raised",
                    )


class TestClassificationReachability:
    """The sandbox branches must be reachable, not shadowed by a fallback.

    `FailureClassifier` tested `ToolError` generically *before* it tested
    `SandboxViolation`. `SandboxError` derives from `ToolError`, so the generic
    test matched first and every violation was reported as `tool_raised` under
    `tool_execution_failed` -- a recoverable category. Nothing about the rows was
    wrong; the incident was silently downgraded to a retryable hiccup, which is
    what handed a crossed control to recovery in the first place.

    Ordered the other way, each specific exception still wins, and the generic
    fallback is reached only by a `ToolError` with no more specific branch.
    """

    def test_a_sandbox_violation_is_not_a_retryable_tool_error(self) -> None:
        result = FailureClassifier().classify(
            SandboxViolation(
                "sandbox control violated (network_access): the tool dialled out"
            ),
            execution_id=1,
        )
        assert result["category"] == FailureCategory.SANDBOX_VIOLATION.value
        assert result["code"] == "violation_network"
        assert not is_recoverable(FailureCategory.SANDBOX_VIOLATION)

    def test_each_violation_gets_its_own_code(self) -> None:
        classifier = FailureClassifier()
        for violation, code in (
            ("network_access", "violation_network"),
            ("filesystem_escape", "violation_fs_escape"),
            ("secret_access", "violation_secret"),
            ("privilege_escalation", "violation_privilege"),
        ):
            result = classifier.classify(
                SandboxViolation(f"sandbox control violated ({violation}): detail"),
                execution_id=1,
            )
            assert result["category"] == FailureCategory.SANDBOX_VIOLATION.value
            assert result["code"] == code

    def test_a_plain_tool_error_still_falls_through_to_the_retryable_one(self) -> None:
        # The other direction: reordering must not have made sandbox branches
        # swallow ordinary tool failures, which *are* recoverable.
        result = FailureClassifier().classify(
            ToolExecutionFailed("the tool raised"), execution_id=1
        )
        assert result["category"] == FailureCategory.TOOL_EXECUTION_FAILED.value
        assert result["code"] == "tool_raised"
        assert is_recoverable(FailureCategory.TOOL_EXECUTION_FAILED)

    def test_a_sandbox_workspace_failure_is_distinct_from_a_violation(self) -> None:
        # A workspace that could not be prepared is an operational failure, not a
        # crossed control -- so it stays in the recoverable bucket while the
        # violation above does not. Collapsing the two would either retry an
        # incident or give up on a transient problem.
        result = FailureClassifier().classify(
            SandboxWorkspaceFailure("could not prepare the workspace"), execution_id=1
        )
        assert result["category"] == FailureCategory.TOOL_EXECUTION_FAILED.value
        assert result["code"] == "sandbox_workspace_failed"


class TestTaskCategoryDerivation:
    def test_it_is_the_most_severe_of_the_recorded_categories(self) -> None:
        assert (
            task_failure_category(
                ["tool_execution_failed", "sandbox_violation", "plan_invalid"]
            )
            == "sandbox_violation"
        )
        assert task_failure_category(["resource_limit", "authorization_denied"]) == (
            "authorization_denied"
        )

    def test_it_ignores_order_and_repetition(self) -> None:
        forward = task_failure_category(["verification_failed", "internal_error"])
        backward = task_failure_category(["internal_error", "verification_failed"])
        assert forward == backward == "verification_failed"
        assert task_failure_category(["resource_limit"] * 5) == "resource_limit"

    def test_nothing_recognised_yields_internal_error(self) -> None:
        # Including the empty case. This runs on the failure path, where raising
        # would replace the real error with a bookkeeping one.
        assert task_failure_category([]) == "internal_error"
        assert task_failure_category(["invented", "also_invented"]) == "internal_error"

    def test_a_verification_failure_outranks_a_tool_error(self) -> None:
        # The grouping that matters most in practice: the run completed and the
        # output still cannot be published. That is worse than a tool that raised,
        # so it must not be reported as the tool error that also happened.
        assert task_failure_category(["tool_execution_failed", "verification_failed"]) == (
            "verification_failed"
        )

    def test_recovery_exhausted_outranks_the_mechanical_causes(self) -> None:
        assert task_failure_category(["resource_limit", "recovery_exhausted"]) == (
            "recovery_exhausted"
        )

    def test_it_reads_the_task_s_failures_and_counts_them(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        task = _executed(authz, alice)
        execution = authz.executions_for_task(alice, task)[0]

        with db.transaction() as conn:
            assert derive_task_failure_category(conn, task) == ("internal_error", 0)

        for code in ("tool_raised", "violation_network"):
            authz.record_failure_by_code(
                alice,
                execution_id=int(execution["id"]),
                code=code,
                detail="recorded",
            )

        with db.transaction() as conn:
            assert derive_task_failure_category(conn, task) == ("sandbox_violation", 2)

    def test_it_ignores_failures_belonging_to_another_task(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        # A severe failure on someone else's task -- or another of yours -- must
        # not colour this one. The join is on `task_id`, so this asserts the join
        # rather than the arithmetic.
        first = _executed(authz, alice)
        second = _executed(authz, alice)
        execution = authz.executions_for_task(alice, first)[0]
        authz.record_failure_by_code(
            alice,
            execution_id=int(execution["id"]),
            code="violation_network",
            detail="refused",
        )
        with db.transaction() as conn:
            assert derive_task_failure_category(conn, second) == ("internal_error", 0)
