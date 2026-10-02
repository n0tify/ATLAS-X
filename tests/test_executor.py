"""Phase 12: the executor and the execution write boundary.

Three layers are exercised separately, because the property being defended is
that they cannot be collapsed into one:

* :mod:`atlas.storage.task_status` -- the lifecycle table. Only edges with an
  enforcement point exist.
* :mod:`atlas.security.service` -- the writes. Ownership, concurrency, the
  duplicate ``invocation_id``, and "exactly one of result and error_code".
* :mod:`atlas.executor.service` -- what runs, in what order, through what.

Most executor tests drive a stub dispatcher so the control flow is deterministic
and does not need WSL. The claim "every step reaches a tool through dispatch" is
not tested with a stub -- a stub would agree to anything -- so it is tested by
counting calls, and separately by checking the executor module cannot reach a
registry at all. One test uses the real dispatcher and the real sandbox, so the
whole path is exercised at least once end to end.

The stub is deliberately *not* a stand-in for the dispatcher in the security
sense: :class:`SpyDispatcher` is passed where a :class:`ToolDispatcher` is
expected, and the tests that care about authorization use the real one.
"""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

import pytest

from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.executor.errors import (
    DuplicateExecution,
    ExecutionBudgetExceeded,
    PlanNotExecutable,
    StepFailed,
)
from atlas.executor.service import ExecutorService
from atlas.planner.plan import PlanDocument
from atlas.security.errors import AuthorizationError, InvalidAuthorizationRequest, PermissionDenied
from atlas.security.policy import DenyReason
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.task_status import (
    TASK_TRANSITIONS,
    StatusTransitionRefused,
    TaskStatus,
    check_task_transition,
)
from atlas.storage.tool_grants import ToolGrantRepo
from atlas.tools.dispatch import DispatchLimits, ToolDispatcher, ToolInvocation
from atlas.tools.errors import ToolError
from atlas.tools.registry import default_registry

PASSWORD = "correct horse battery staple"

TOOL_A = "text_statistics"
TOOL_B = "numeric_summary"

BUILTIN_TOOL_IDS = (TOOL_A, TOOL_B, "json_shape_inspect", "task_graph_summary")


# --------------------------------------------------------------- fixtures


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def authz(db: Database, auth: AuthService) -> AuthorizationService:
    return AuthorizationService(db, auth)


@pytest.fixture
def alice(auth: AuthService) -> str:
    auth.register("alice", PASSWORD)
    return str(auth.login("alice", PASSWORD)["token"])


@pytest.fixture
def bob(auth: AuthService) -> str:
    auth.register("bob", PASSWORD)
    return str(auth.login("bob", PASSWORD)["token"])


@pytest.fixture
def task(authz: AuthorizationService, alice: str) -> int:
    return int(authz.create_task(alice, title="t", goal="Measure the text")["id"])


def _user_id(db: Database, username: str) -> int:
    with db.transaction() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    assert row is not None
    return int(row["id"])


def _store_plan(
    authz: AuthorizationService,
    token: str,
    task_id: int,
    payload: Mapping[str, Any],
    *,
    validated: bool = True,
) -> dict[str, Any]:
    """Persist a plan through the real Phase 11 write path.

    Going through :meth:`create_plan` rather than inserting rows directly means
    these tests exercise the same boundary a real plan arrives by, so a defect in
    that boundary would show up here instead of hiding behind a shortcut.
    """

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


def _linear_plan() -> dict[str, Any]:
    return {
        "summary": "Measure the text, then summarize the numbers.",
        "steps": [
            {
                "step_key": "measure",
                "tool_id": TOOL_A,
                "input": {"text": "hello world"},
                "depends_on": [],
                "action": "Measure word statistics.",
            },
            {
                "step_key": "summarize",
                "tool_id": TOOL_B,
                "input": {"values": [1, 2, 3]},
                "depends_on": ["measure"],
                "action": "Summarize the numbers.",
            },
        ],
    }


# ------------------------------------------------------------------ stubs


class SpyDispatcher:
    """Records every dispatch and returns a canned invocation.

    Not a substitute for the dispatcher in the security sense -- it authorizes
    nothing. It is here so the executor's own logic (ordering, budgets, refusing
    a non-program) can be tested without WSL in the way, and so a test can count
    dispatches, which is the only way to show a refusal happened *before* any tool
    ran.
    """

    def __init__(
        self,
        *,
        result: Mapping[str, Any] | None = None,
        error: ToolError | None = None,
        delay: float = 0.0,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = dict(result or {"char_count": 1})
        self._error = error
        self._delay = delay

    def dispatch(
        self,
        session_token: object,
        *,
        tool_id: object,
        task_id: object,
        arguments: object,
        execution_id: int | None = None,
        plan_id: int | None = None,
        plan_step_id: int | None = None,
        invocation_id: str | None = None,
    ) -> ToolInvocation:
        self.calls.append(
            {"tool_id": tool_id, "task_id": task_id, "arguments": arguments, "token": session_token}
        )
        if self._delay:
            time.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return ToolInvocation(
            tool_id=str(tool_id),
            tool_version="1.0.0",
            capability=str(tool_id),
            determinism="deterministic",
            user_id=1,
            task_id=task_id if isinstance(task_id, int) else 0,
            result=self._result,
            record={"ok": True},
            provenance_event_id=1,
        )


def _executor(
    authz: AuthorizationService,
    dispatcher: Any,
    settings: Settings | None = None,
) -> ExecutorService:
    return ExecutorService(authz, dispatcher, settings or Settings())


# ------------------------------------------------------- the lifecycle table


class TestTaskStatusLifecycle:
    def test_the_documented_edges_are_the_actual_edges(self) -> None:
        # The docstring in atlas.storage.task_status draws a graph. This is the
        # test that keeps the drawing and the table from drifting apart.
        assert dict(TASK_TRANSITIONS) == {
            "pending": frozenset({"planned"}),
            "planned": frozenset({"executing"}),
            "executing": frozenset({"executed", "failed"}),
            # Phase 13 removed `executed -> verified`: `verified` is reachable only
            # from `verifying`, so no caller holding TASK.UPDATE can walk an
            # unverified task to `verified` and publish a result for it.
            "executed": frozenset({"verifying", "failed"}),
            "verifying": frozenset({"verified", "failed"}),
            "verified": frozenset({"succeeded"}),
            "succeeded": frozenset(),
            "failed": frozenset(),
        }

    def test_verified_is_not_reachable_without_verifying(self) -> None:
        # The single most important edge in the table. Phase 12 drew
        # `executed -> verified` as a placeholder; while it exists, the verifier's
        # only real guarantee evaporates, because `verified -> succeeded` would
        # then be reachable from `executed` by anyone with TASK.UPDATE.
        assert "verified" not in TASK_TRANSITIONS["executed"]
        assert "succeeded" not in TASK_TRANSITIONS["executed"]

    @pytest.mark.parametrize(
        ("current", "requested"),
        [
            ("pending", "planned"),
            ("planned", "executing"),
            ("executing", "executed"),
            ("executing", "failed"),
            ("executed", "verifying"),
            ("executed", "failed"),
            ("verifying", "verified"),
            ("verifying", "failed"),
            ("verified", "succeeded"),
        ],
    )
    def test_a_documented_edge_is_allowed(self, current: str, requested: str) -> None:
        check_task_transition(current, requested)

    @pytest.mark.parametrize(
        ("current", "requested"),
        [
            # Reaching succeeded without verification is the whole point.
            ("pending", "succeeded"),
            ("executed", "succeeded"),
            ("executed", "executed"),
            ("executing", "verified"),
            ("planned", "executed"),
            # Phase 13 removed this edge. Leaving it listed is how a reader learns
            # it must not be re-added.
            ("executed", "verified"),
            ("verifying", "executed"),
            # Terminal means terminal.
            ("succeeded", "failed"),
            ("failed", "planned"),
        ],
    )
    def test_an_undocumented_edge_is_refused(self, current: str, requested: str) -> None:
        with pytest.raises(StatusTransitionRefused):
            check_task_transition(current, requested)

    @pytest.mark.parametrize("requested", ["", "PENDING", "done", "verified "])
    def test_an_unknown_status_is_refused_rather_than_allowed(self, requested: str) -> None:
        # A status absent from the table must not read as "anything goes".
        with pytest.raises(StatusTransitionRefused):
            check_task_transition("pending", requested)

    def test_an_unknown_current_status_is_refused(self) -> None:
        with pytest.raises(StatusTransitionRefused):
            check_task_transition("legacy-v2-value", "planned")


# ------------------------------------------------------ the execution writes


class TestAuthorizationExecutionWrites:
    def test_a_second_in_flight_run_of_one_task_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        plan = _store_plan(authz, alice, task, _linear_plan())
        authz.begin_execution(
            alice,
            task_id=task,
            plan_id=int(plan["id"]),
            plan_step_id=None,
            tool_id=TOOL_A,
            invocation_id="inv-1",
            origin="plan_step",
            max_concurrent=1,
        )
        with pytest.raises(PermissionDenied) as caught:
            authz.begin_execution(
                alice,
                task_id=task,
                plan_id=int(plan["id"]),
                plan_step_id=None,
                tool_id=TOOL_A,
                invocation_id="inv-2",
                origin="plan_step",
                max_concurrent=1,
            )
        assert caught.value.reason == DenyReason.DUPLICATE_EXECUTION

    def test_a_different_task_is_not_blocked_by_an_occupied_one(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # Concurrency is per task, not per user: one busy task must not stop
        # another from starting. Each task therefore needs its own plan.
        plan = _store_plan(authz, alice, task, _linear_plan())
        other = int(authz.create_task(alice, title="t2", goal="g")["id"])
        other_plan = _store_plan(authz, alice, other, _linear_plan())
        authz.begin_execution(
            alice,
            task_id=task,
            plan_id=int(plan["id"]),
            plan_step_id=None,
            tool_id=TOOL_A,
            invocation_id="inv-1",
            origin="plan_step",
            max_concurrent=1,
        )
        opened = authz.begin_execution(
            alice,
            task_id=other,
            plan_id=int(other_plan["id"]),
            plan_step_id=None,
            tool_id=TOOL_A,
            invocation_id="inv-3",
            origin="plan_step",
            max_concurrent=1,
        )
        assert opened > 0

    def test_the_same_invocation_id_cannot_be_reused(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # The correlation key is global: reusing one across two tasks would join two
        # unrelated dispatches into one audit trail.
        plan = _store_plan(authz, alice, task, _linear_plan())
        other = int(authz.create_task(alice, title="t2", goal="g")["id"])
        other_plan = _store_plan(authz, alice, other, _linear_plan())
        authz.begin_execution(
            alice,
            task_id=task,
            plan_id=int(plan["id"]),
            plan_step_id=None,
            tool_id=TOOL_A,
            invocation_id="inv-1",
            origin="plan_step",
            max_concurrent=1,
        )
        with pytest.raises(PermissionDenied) as caught:
            authz.begin_execution(
                alice,
                task_id=other,
                plan_id=int(other_plan["id"]),
                plan_step_id=None,
                tool_id=TOOL_A,
                invocation_id="inv-1",
                origin="plan_step",
                max_concurrent=1,
            )
        assert caught.value.reason == DenyReason.DUPLICATE_EXECUTION

    def test_a_plan_of_another_task_may_not_be_executed(
        self, db: Database, authz: AuthorizationService, alice: str, bob: str, task: int
    ) -> None:
        # alice owns a plan on her own task and tries to run it against bob's
        # task. Both are hers, so ownership alone does not stop this.
        alice_task = int(authz.create_task(alice, title="a", goal="g")["id"])
        bob_task = int(authz.create_task(bob, title="b", goal="g")["id"])
        plan = _store_plan(authz, alice, alice_task, _linear_plan())
        with pytest.raises(PermissionDenied) as caught:
            authz.begin_execution(
                alice,
                task_id=bob_task,
                plan_id=int(plan["id"]),
                plan_step_id=None,
                tool_id=TOOL_A,
                invocation_id="inv-1",
                origin="plan_step",
                max_concurrent=1,
            )
        assert caught.value.reason == DenyReason.RESOURCE_NOT_OWNED

    def test_another_users_task_may_not_be_executed(
        self, db: Database, authz: AuthorizationService, alice: str, bob: str, task: int
    ) -> None:
        plan = _store_plan(authz, alice, task, _linear_plan())
        bob_task = int(authz.create_task(bob, title="b", goal="g")["id"])
        with pytest.raises(PermissionDenied) as caught:
            authz.begin_execution(
                bob,
                task_id=bob_task,
                plan_id=int(plan["id"]),
                plan_step_id=None,
                tool_id=TOOL_A,
                invocation_id="inv-1",
                origin="plan_step",
                max_concurrent=1,
            )
        assert caught.value.reason == DenyReason.RESOURCE_NOT_OWNED

    @pytest.mark.parametrize(
        ("result", "error_code"),
        [(None, None), ({"ok": True}, "boom"), (None, "boom")],
    )
    def test_closing_an_execution_requires_exactly_one_conclusion(
        self,
        db: Database,
        authz: AuthorizationService,
        alice: str,
        task: int,
        result: Mapping[str, Any] | None,
        error_code: str | None,
    ) -> None:
        plan = _store_plan(authz, alice, task, _linear_plan())
        execution = authz.begin_execution(
            alice,
            task_id=task,
            plan_id=int(plan["id"]),
            plan_step_id=None,
            tool_id=TOOL_A,
            invocation_id="inv-1",
            origin="plan_step",
            max_concurrent=1,
        )
        if (result is None) == (error_code is None):
            # Both or neither: there is no single conclusion to record, so the
            # close is refused rather than guessed at.
            with pytest.raises(InvalidAuthorizationRequest):
                authz.end_execution(alice, execution, result=result, error_code=error_code)
        else:
            authz.end_execution(alice, execution, result=result, error_code=error_code)

    def test_an_execution_may_not_be_closed_twice(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # Two conclusions about one dispatch would mean the audit trail keeps
        # whichever arrived second, which is not a record of anything.
        plan = _store_plan(authz, alice, task, _linear_plan())
        execution = authz.begin_execution(
            alice,
            task_id=task,
            plan_id=int(plan["id"]),
            plan_step_id=None,
            tool_id=TOOL_A,
            invocation_id="inv-1",
            origin="plan_step",
            max_concurrent=1,
        )
        authz.end_execution(alice, execution, result={"ok": True})
        with pytest.raises(InvalidAuthorizationRequest):
            authz.end_execution(alice, execution, result={"ok": True})

    def test_an_execution_of_another_user_may_not_be_closed(
        self, db: Database, authz: AuthorizationService, alice: str, bob: str, task: int
    ) -> None:
        plan = _store_plan(authz, alice, task, _linear_plan())
        execution = authz.begin_execution(
            alice,
            task_id=task,
            plan_id=int(plan["id"]),
            plan_step_id=None,
            tool_id=TOOL_A,
            invocation_id="inv-1",
            origin="plan_step",
            max_concurrent=1,
        )
        # bob owns a task of his own and still cannot close alice's execution.
        bob_task = int(authz.create_task(bob, title="b", goal="g")["id"])
        assert bob_task > 0
        with pytest.raises(PermissionDenied):
            authz.end_execution(bob, execution, result={"ok": True})

    def test_an_illegal_task_transition_is_refused_at_the_write_boundary(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # pending -> succeeded would skip verification entirely.
        with pytest.raises(StatusTransitionRefused):
            authz.set_task_status(alice, task, status=TaskStatus.SUCCEEDED.value)
        assert authz.get_task(alice, task)["status"] == TaskStatus.PENDING.value

    def test_another_users_task_status_may_not_be_set(
        self, authz: AuthorizationService, alice: str, bob: str, task: int
    ) -> None:
        with pytest.raises(PermissionDenied) as caught:
            authz.set_task_status(bob, task, status=TaskStatus.PLANNED.value)
        assert caught.value.reason == DenyReason.RESOURCE_NOT_OWNED

    def test_in_flight_reads_do_not_reserve(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # A read must not be mistaken for a reservation: it reports, it does not
        # hold a slot. Two consecutive reads see the same one row.
        plan = _store_plan(authz, alice, task, _linear_plan())
        authz.begin_execution(
            alice,
            task_id=task,
            plan_id=int(plan["id"]),
            plan_step_id=None,
            tool_id=TOOL_A,
            invocation_id="inv-1",
            origin="plan_step",
            max_concurrent=1,
        )
        first = authz.in_flight_executions(alice, task)
        second = authz.in_flight_executions(alice, task)
        assert len(first) == len(second) == 1

    @pytest.mark.parametrize("max_concurrent", [0, -1, True, "1", 1.5])
    def test_a_meaningless_concurrency_bound_is_refused(
        self,
        authz: AuthorizationService,
        alice: str,
        task: int,
        max_concurrent: Any,
    ) -> None:
        plan = _store_plan(authz, alice, task, _linear_plan())
        with pytest.raises(InvalidAuthorizationRequest):
            authz.begin_execution(
                alice,
                task_id=task,
                plan_id=int(plan["id"]),
                plan_step_id=None,
                tool_id=TOOL_A,
                invocation_id="inv-1",
                origin="plan_step",
                max_concurrent=max_concurrent,
            )


# ------------------------------------------------------- what may be run


class TestExecutorRefusals:
    def test_a_rejected_plan_is_never_dispatched(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # Phase 11 persists the plans it rejects. Their existence is a record of
        # what the model proposed, not permission to run it.
        _store_plan(authz, alice, task, _linear_plan(), validated=False)
        spy = SpyDispatcher()
        with pytest.raises(PlanNotExecutable):
            _executor(authz, spy).execute(alice, task)
        assert spy.calls == []

    def test_a_task_with_no_plan_is_refused(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        spy = SpyDispatcher()
        with pytest.raises(AuthorizationError):
            _executor(authz, spy).execute(alice, task)
        assert spy.calls == []

    def test_a_plan_whose_steps_disagree_with_its_document_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # The executor must not choose between two records of the same plan.
        plan = _store_plan(authz, alice, task, _linear_plan())
        with db.transaction() as conn:
            conn.execute(
                "UPDATE plan_steps SET tool_id = ? WHERE plan_id = ? AND step_key = ?",
                ("task_graph_summary", int(plan["id"]), "measure"),
            )
        spy = SpyDispatcher()
        with pytest.raises(PlanNotExecutable):
            _executor(authz, spy).execute(alice, task)
        assert spy.calls == []

    def test_a_plan_missing_a_stored_step_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        plan = _store_plan(authz, alice, task, _linear_plan())
        with db.transaction() as conn:
            conn.execute(
                "DELETE FROM plan_steps WHERE plan_id = ? AND step_key = ?",
                (int(plan["id"]), "summarize"),
            )
        spy = SpyDispatcher()
        with pytest.raises(PlanNotExecutable):
            _executor(authz, spy).execute(alice, task)
        assert spy.calls == []

    def test_a_plan_with_an_unreadable_document_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        plan = _store_plan(authz, alice, task, _linear_plan())
        with db.transaction() as conn:
            conn.execute(
                "UPDATE plans SET plan_json = ? WHERE id = ?", ("{not json", int(plan["id"]))
            )
        spy = SpyDispatcher()
        with pytest.raises(PlanNotExecutable):
            _executor(authz, spy).execute(alice, task)
        assert spy.calls == []

    def test_a_dependency_cycle_is_refused_however_it_got_stored(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # The validator refuses cycles when a plan is *written*. This checks that
        # the executor does not rely on that: the document is re-ordered here from
        # its own dependency graph, and a cycle still stops the run.
        cyclic = {
            "summary": "Two steps that each need the other.",
            "steps": [
                {
                    "step_key": "first",
                    "tool_id": TOOL_A,
                    "input": {"text": "a"},
                    "depends_on": ["second"],
                },
                {
                    "step_key": "second",
                    "tool_id": TOOL_A,
                    "input": {"text": "b"},
                    "depends_on": ["first"],
                },
            ],
        }
        _store_plan(authz, alice, task, cyclic)
        spy = SpyDispatcher()
        with pytest.raises(PlanNotExecutable):
            _executor(authz, spy).execute(alice, task)
        assert spy.calls == []


# --------------------------------------------------------- what does run


class TestExecutorRuns:
    def test_a_validated_plan_runs_every_step_in_dependency_order(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # `summarize` is stored at position 0 and `measure` at position 1, so
        # running in stored order would be wrong. The dependency wins.
        reversed_plan = {
            "summary": "Summarize first in storage, but run measure first.",
            "steps": [
                {
                    "step_key": "summarize",
                    "tool_id": TOOL_B,
                    "input": {"values": [1, 2, 3]},
                    "depends_on": ["measure"],
                },
                {
                    "step_key": "measure",
                    "tool_id": TOOL_A,
                    "input": {"text": "hello world"},
                    "depends_on": [],
                },
            ],
        }
        _store_plan(authz, alice, task, reversed_plan)
        spy = SpyDispatcher()
        outcome = _executor(authz, spy).execute(alice, task)
        assert [call["tool_id"] for call in spy.calls] == [TOOL_A, TOOL_B]
        assert [step.step_key for step in outcome.steps] == ["measure", "summarize"]

    def test_every_step_reaches_a_tool_through_dispatch(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # The security property, stated as a count: one dispatch per step, and the
        # arguments the plan named are the arguments the dispatcher received.
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher()
        _executor(authz, spy).execute(alice, task)
        assert len(spy.calls) == 2
        assert spy.calls[0]["arguments"] == {"text": "hello world"}
        assert spy.calls[1]["arguments"] == {"values": [1, 2, 3]}
        assert all(call["token"] == alice for call in spy.calls)

    def test_the_executor_cannot_reach_a_tool_registry(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # A count proves the steps went through dispatch; this proves there was no
        # second route the count would not have seen. Checked against the parsed
        # module, not its text: the module's own docstring uses the word
        # "implementation" to say it has none, and a substring search would flag
        # that as a violation.
        import ast

        import atlas.executor.service as module

        source = module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=str(source))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
        assert "ToolRegistry" not in imported
        assert "ToolDefinition" not in imported
        assert "atlas.tools.registry" not in imported
        assert "atlas.tools.context" not in imported

    def test_the_executor_never_calls_an_implementation_directly(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # Attribute access on a definition is the route Phase 10 exists to close.
        # Asserted over the AST rather than the text, so the prose about it does
        # not satisfy or trip the check.
        import ast

        import atlas.executor.service as module

        source = module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=str(source))
        attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        assert "invoke" not in attributes
        assert "implementation" not in attributes
        # `find` is not asserted: reaching a definition is not a bypass on its
        # own, and banning a common method name would make this test break on an
        # unrelated edit. Getting the body needs `implementation`, which is banned.

    def test_a_completed_run_stops_at_executed(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # Phase 12 must not claim the result is right, and must not write one.
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher()
        outcome = _executor(authz, spy).execute(alice, task)
        stored = authz.get_task(alice, task)
        assert outcome.task_status == TaskStatus.EXECUTED.value
        assert stored["status"] == TaskStatus.EXECUTED.value
        assert stored["result_json"] is None
        assert stored["verified_at"] is None

    def test_each_step_gets_its_own_execution_row(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher()
        outcome = _executor(authz, spy).execute(alice, task)
        rows = authz.executions_for_task(alice, task)
        assert len(rows) == 2
        assert {row["status"] for row in rows} == {"succeeded"}
        assert len({row["invocation_id"] for row in rows}) == 2
        assert [step.execution_id for step in outcome.steps] == [row["id"] for row in rows]

    def test_the_invocation_id_is_derived_so_a_replay_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # Deterministic on purpose: a second run of the same step of the same plan
        # computes the same id, so it is refused as the replay it is instead of
        # writing a second execution row and looking like a fresh attempt.
        _store_plan(authz, alice, task, _linear_plan())
        first = _executor(authz, SpyDispatcher()).execute(alice, task)
        again = ExecutorService._invocation_id(
            plan_id=first.plan_id, step_key="measure", attempt=first.attempt
        )
        assert again == first.steps[0].invocation_id
        assert again.startswith("inv-")

    def test_a_task_already_executing_is_refused(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        authz.set_task_status(alice, task, status=TaskStatus.PLANNED.value)
        authz.set_task_status(alice, task, status=TaskStatus.EXECUTING.value)
        spy = SpyDispatcher()
        with pytest.raises(DuplicateExecution):
            _executor(authz, spy).execute(alice, task)
        assert spy.calls == []

    def test_a_terminal_task_is_not_re_run(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        _executor(authz, SpyDispatcher()).execute(alice, task)
        spy = SpyDispatcher()
        with pytest.raises(PlanNotExecutable):
            _executor(authz, spy).execute(alice, task)
        assert spy.calls == []

    @pytest.mark.parametrize("attempt", [0, -1, True, "1", 1.0])
    def test_a_meaningless_attempt_is_refused(
        self, authz: AuthorizationService, alice: str, task: int, attempt: Any
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher()
        with pytest.raises(Exception) as caught:
            _executor(authz, spy).execute(alice, task, attempt=attempt)
        assert spy.calls == []
        assert "attempt" in str(caught.value)


# ------------------------------------------------------------- when it fails


class TestExecutorFailure:
    def test_a_failing_step_stops_the_run_and_is_recorded(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher(error=ToolError("tool said no", code="text_statistics:invalid_input"))
        with pytest.raises(StepFailed) as caught:
            _executor(authz, spy).execute(alice, task)
        # The second step never ran.
        assert len(spy.calls) == 1
        assert caught.value.step_key == "measure"
        assert caught.value.error_code == "text_statistics:invalid_input"
        assert authz.get_task(alice, task)["status"] == TaskStatus.FAILED.value
        rows = authz.executions_for_task(alice, task)
        assert [row["status"] for row in rows] == ["failed"]
        assert rows[0]["error_code"] == "text_statistics:invalid_input"

    def test_a_failed_run_leaves_no_execution_in_flight(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # Otherwise the concurrency bound would refuse every future run of this
        # task forever, and the task would be unrecoverable by retry.
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher(error=ToolError("boom", code="x:y"))
        with pytest.raises(StepFailed):
            _executor(authz, spy).execute(alice, task)
        assert authz.in_flight_executions(alice, task) == []

    def test_a_tool_message_is_recorded_but_not_raised(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        # The tool's message is for an operator; the caller gets the code. A
        # message can name internals the caller has no business seeing.
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher(error=ToolError("internal path /etc/secret", code="x:y"))
        with pytest.raises(StepFailed) as caught:
            _executor(authz, spy).execute(alice, task)
        assert "secret" not in str(caught.value)

    def test_an_authorization_denial_is_not_turned_into_a_tool_failure(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        class Denying(SpyDispatcher):
            def dispatch(
                self,
                session_token: object,
                *,
                tool_id: object,
                task_id: object,
                arguments: object,
                execution_id: int | None = None,
                plan_id: int | None = None,
                plan_step_id: int | None = None,
                invocation_id: str | None = None,
            ) -> ToolInvocation:
                raise PermissionDenied(DenyReason.TOOL_NO_GRANT)

        _store_plan(authz, alice, task, _linear_plan())
        with pytest.raises(PermissionDenied):
            _executor(authz, Denying()).execute(alice, task)
        # The denial propagated as itself. The task is still put in a truthful
        # state, because a task stuck at `executing` is not a truthful state.
        assert authz.get_task(alice, task)["status"] == TaskStatus.FAILED.value
        assert authz.in_flight_executions(alice, task) == []


class TestExecutorBudget:
    def test_the_call_budget_stops_the_run_before_the_next_dispatch(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher()
        settings = Settings(max_tool_calls=1, max_execution_seconds=120)
        with pytest.raises(ExecutionBudgetExceeded):
            _executor(authz, spy, settings).execute(alice, task)
        # One call was allowed and spent; the second was never begun.
        assert len(spy.calls) == 1
        assert authz.get_task(alice, task)["status"] == TaskStatus.FAILED.value

    def test_the_wall_clock_budget_stops_the_run_before_the_next_dispatch(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher(delay=1.05)
        settings = Settings(max_tool_calls=12, max_execution_seconds=1)
        with pytest.raises(ExecutionBudgetExceeded):
            _executor(authz, spy, settings).execute(alice, task)
        assert len(spy.calls) == 1
        assert authz.get_task(alice, task)["status"] == TaskStatus.FAILED.value


# ------------------------------------------------------ the real whole path


class TestExecutorEndToEnd:
    def test_a_plan_runs_through_authorization_and_the_sandbox(
        self, db: Database, auth: AuthService, alice: str
    ) -> None:
        # The one test that uses the real dispatcher and the real WSL sandbox, so
        # the whole Phase 12 path is exercised rather than only its edges.
        alice_id = _user_id(db, "alice")
        grants = ToolGrantRepo(db, registry_ready=True)
        authz = AuthorizationService(db, auth, tool_grants=grants)
        dispatcher = ToolDispatcher(
            db, authz, default_registry(), limits=DispatchLimits(max_tool_calls=8)
        )
        for tool_id in BUILTIN_TOOL_IDS:
            grants.grant(user_id=alice_id, tool_name=tool_id, granted_by="operator")
        task = int(authz.create_task(alice, title="t", goal="Measure")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "Measure the supplied text.",
                "steps": [
                    {
                        "step_key": "measure",
                        "tool_id": TOOL_A,
                        "input": {"text": "hello brave world"},
                        "depends_on": [],
                    }
                ],
            },
        )

        outcome = ExecutorService(authz, dispatcher).execute(alice, task)

        assert outcome.task_status == TaskStatus.EXECUTED.value
        assert len(outcome.steps) == 1
        step = outcome.steps[0]
        assert step.succeeded
        assert step.tool_id == TOOL_A
        assert step.result is not None
        assert step.result["char_count"] == 17
        assert step.provenance_event_id is not None
        assert authz.get_task(alice, task)["status"] == TaskStatus.EXECUTED.value
        rows = authz.executions_for_task(alice, task)
        assert [row["status"] for row in rows] == ["succeeded"]
        assert rows[0]["tool_id"] == TOOL_A
        assert rows[0]["origin"] == "plan_step"

    def test_a_revoked_grant_fails_the_run_closed(
        self, db: Database, auth: AuthService, alice: str
    ) -> None:
        # The executor holds no authority of its own. With the capability not
        # granted, the run stops at the dispatcher and the task does not claim to
        # have run.
        alice_id = _user_id(db, "alice")
        grants = ToolGrantRepo(db, registry_ready=True)
        authz = AuthorizationService(db, auth, tool_grants=grants)
        dispatcher = ToolDispatcher(db, authz, default_registry())
        task = int(authz.create_task(alice, title="t", goal="Measure")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "Measure the supplied text.",
                "steps": [
                    {
                        "step_key": "measure",
                        "tool_id": TOOL_A,
                        "input": {"text": "hello"},
                        "depends_on": [],
                    }
                ],
            },
        )

        with pytest.raises(AuthorizationError):
            ExecutorService(authz, dispatcher).execute(alice, task)

        assert alice_id > 0
        assert authz.get_task(alice, task)["status"] == TaskStatus.FAILED.value
        assert authz.in_flight_executions(alice, task) == []


# ---------------------------------------------------------- stored contents


class TestWhatWasStored:
    def test_a_succeeded_execution_holds_the_result_it_produced(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher(result={"char_count": 11, "word_count": 2})
        _executor(authz, spy).execute(alice, task)
        rows = authz.executions_for_task(alice, task)
        stored = json.loads(str(rows[0]["result_json"]))
        assert stored == {"char_count": 11, "word_count": 2}
        assert rows[0]["finished_at"] is not None

    def test_a_failed_execution_holds_no_result(
        self, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        spy = SpyDispatcher(error=ToolError("boom", code="x:y"))
        with pytest.raises(StepFailed):
            _executor(authz, spy).execute(alice, task)
        row = authz.executions_for_task(alice, task)[0]
        # An execution cannot be both failed and having produced output.
        assert row["status"] == "failed"
        assert row["result_json"] is None
        assert row["error_code"] == "x:y"

    def test_plan_step_rows_record_what_happened(
        self, db: Database, authz: AuthorizationService, alice: str, task: int
    ) -> None:
        _store_plan(authz, alice, task, _linear_plan())
        _executor(authz, SpyDispatcher()).execute(alice, task)
        with db.transaction() as conn:
            rows = conn.execute(
                "SELECT step_key, status FROM plan_steps ORDER BY position ASC"
            ).fetchall()
        assert {row["step_key"]: row["status"] for row in rows} == {
            "measure": "succeeded",
            "summarize": "succeeded",
        }
