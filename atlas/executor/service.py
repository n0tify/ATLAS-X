"""Phase 12: run a validated plan, one authorized step at a time.

:class:`ExecutorService` is the only component that decides *what runs next*. It
holds no tool implementations and no registry of its own; every step reaches a
tool body through :meth:`~atlas.tools.dispatch.ToolDispatcher.dispatch`, which
authorizes the capability and confines the call. The dependency arrow points one
way on purpose:

.. code-block:: text

    ExecutorService -> AuthorizationService -> ToolDispatcher -> sandbox
             |                                     ^
             +------- status and execution rows ---+

What this class is responsible for, and why each part is here rather than in
storage:

* **Choosing the plan.** Only the head plan of the task is a candidate, and only
  if it carries ``status = 'validated'``. Phase 11 persists rejected plans too --
  they are a record of what the model proposed -- so a plan's existence is not
  evidence that it may run. This check is the reason a rejected plan can never
  reach a tool.
* **Ordering.** The stored ``plan_json`` is re-parsed here and its ``depends_on``
  graph is sorted independently, rather than trusting that Phase 11 already
  validated it. The validator rejected cycles when the plan was *written*; this is
  the check that matters when the plan is *run*, and the storage in between is
  another writer. A cycle found here stops the run rather than looping it.
* **Reconciling the two records.** ``plans.plan_json`` and ``plan_steps`` are two
  copies of one plan. If they disagree about a step's tool, the executor refuses
  instead of picking one: the choice would be arbitrary, and an arbitrary choice
  is how a plan runs a tool its author did not name.
* **Budget.** Wall clock and call count are enforced *before* each dispatch, and
  both count across the whole run. The dispatcher's own per-task budget is a
  second, independent bound counted from the provenance log; neither replaces the
  other, because one bounds this run and the other bounds the task.

Three things this class will not do, each of which is a Phase boundary rather than
a missing feature:

* It does not mark a task ``verified`` or ``succeeded``. The furthest it moves a
  task is ``executed``, which means "every step dispatched and closed as
  succeeded" and says nothing about whether the result is right. Phase 13
  decides that.
* It does not write ``tasks.result_json``. A result is written when verification
  passes, so no consumer can read an unverified output as if it were the answer.
* It does not convert an authorization denial into a tool failure. A
  :class:`~atlas.security.errors.AuthorizationError` propagates unchanged after
  the dispatch row is closed, because a caller that cannot tell "you may not"
  from "the tool broke" cannot fail closed on the first.

Known gap, deliberately left for Phase 14 rather than quietly omitted: the
``executions`` row and the ``provenance_events`` the dispatcher writes are not yet
joined. :meth:`~atlas.tools.dispatch.ToolDispatcher.dispatch` records
``provenance_events.execution_id`` as NULL, because it is Phase 10 code and
``atlas.security`` holds no write permission on the provenance table. So a
dispatch is currently correlated to its execution row only by
``invocation_id`` and by position, not by a foreign key. Closing that is the
provenance chain's work, and doing it here would mean granting the tool layer a
write on the audit trail.

Ordering of a failure is deliberate too: the execution row is always closed
before the error propagates. A run that raised and left a ``running`` row would
make the task look busy forever, and :meth:`begin_execution` would then refuse
every future run of it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from atlas.config.settings import Settings
from atlas.executor.errors import (
    DuplicateExecution,
    ExecutionBudgetExceeded,
    ExecutionError,
    PlanNotExecutable,
    StepFailed,
)
from atlas.planner.errors import PlanError
from atlas.planner.plan import PlanDocument
from atlas.security.errors import AuthorizationError, PermissionDenied
from atlas.security.policy import DenyReason
from atlas.security.service import AuthorizationService
from atlas.storage.execution_repo import ORIGIN_PLAN_STEP
from atlas.storage.task_status import PlanStatus, TaskStatus
from atlas.tools.dispatch import ToolDispatcher
from atlas.tools.errors import ToolError

logger = logging.getLogger(__name__)

#: Bound on the stored ``plan_json`` re-parsed here. Phase 11 caps the document
#: it writes; this is the independent check on what storage handed back, so a plan
#: row written by anything else cannot make the executor parse an unbounded blob.
MAX_PLAN_JSON_BYTES = 1024 * 1024

#: Upper bound on steps re-parsed from a stored plan. Deliberately far above the
#: count Phase 11 will write: a valid plan is never refused for being large, while
#: an absurd one still is.
MAX_REPARSE_STEPS = 256


def _canonical(value: object) -> str:
    """Sorted, whitespace-free JSON, so two copies compare by content.

    Two records are only equal if their JSON is byte-identical after
    normalization, so ``1`` and ``1.0`` -- which Python compares equal -- are
    correctly treated as different here. Reconciliation compares stored text
    against a document, and that comparison should be about bytes.
    """

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class StepOutcome:
    """What happened to one step of a run."""

    step_key: str
    tool_id: str
    execution_id: int
    invocation_id: str
    provenance_event_id: int | None = None
    result: Mapping[str, Any] | None = None
    error_code: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_code is None


@dataclass(frozen=True)
class ExecutionOutcome:
    """The result of a completed run. Reached only when every step succeeded."""

    task_id: int
    plan_id: int
    attempt: int
    task_status: str
    steps: tuple[StepOutcome, ...] = ()
    elapsed_seconds: float = 0.0

    @property
    def tool_calls(self) -> int:
        return len(self.steps)


class ExecutorService:
    """Runs a validated plan through the dispatch boundary."""

    def __init__(
        self,
        authorization: AuthorizationService,
        dispatcher: ToolDispatcher,
        settings: Settings | None = None,
    ) -> None:
        self._auth = authorization
        self._dispatcher = dispatcher
        self._settings = settings or Settings()
        # Normalized once so the bound cannot change mid-run and so a caller that
        # passes a Settings-shaped object with a string gets the same refusal.
        self._max_tool_calls = int(self._settings.max_tool_calls)
        self._max_execution_seconds = int(self._settings.max_execution_seconds)
        self._max_concurrent = int(self._settings.max_concurrent_executions)

    def execute(
        self, session_token: object, task_id: object, *, attempt: int = 1
    ) -> ExecutionOutcome:
        """Run the task's head plan and return what each step produced.

        Raises :class:`PlanNotExecutable` before anything is dispatched if the
        plan may not run, :class:`DuplicateExecution` if the task is already being
        run, :class:`ExecutionBudgetExceeded` if a bound stops the run, and
        :class:`StepFailed` if a tool call fails. The first three are refusals to
        start; only :class:`StepFailed` means work was done.
        """

        task_id = self._as_task_id(task_id)
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise ExecutionError("attempt must be a positive integer")
        started = time.monotonic()

        plan = self._auth.plan_head(session_token, task_id)
        ordered = self._executable_steps(session_token, plan)

        self._enter_running(session_token, task_id)
        outcomes: list[StepOutcome] = []
        try:
            for index, step in enumerate(ordered):
                self._check_budget(index, started)
                outcomes.append(
                    self._run_step(
                        session_token,
                        task_id=task_id,
                        plan=plan,
                        step=step,
                        attempt=attempt,
                    )
                )
        except (ExecutionError, AuthorizationError):
            # A step that raised has already been recorded as failed by
            # _run_step; this also covers a denial and a refusal raised between
            # steps, where the task is genuinely mid-run and must not be left
            # `executing`. An authorization denial is still re-raised unchanged --
            # the task is put in a truthful state, the error is not relabelled.
            self._fail_task(session_token, task_id)
            raise

        status = TaskStatus.EXECUTED.value
        self._auth.set_task_status(session_token, task_id, status=status)
        return ExecutionOutcome(
            task_id=task_id,
            plan_id=int(plan["id"]),
            attempt=attempt,
            task_status=status,
            steps=tuple(outcomes),
            elapsed_seconds=time.monotonic() - started,
        )

    # -- plan selection and ordering -------------------------------------

    def _executable_steps(
        self, session_token: object, plan: Mapping[str, Any]
    ) -> list[Mapping[str, Any]]:
        """The step rows to run, in the order they must run.

        Both halves of the plan's "may run" evidence are required: ``validated``
        and ``status = 'validated'``. Requiring both is not redundancy for its own
        sake -- Phase 11 writes them together, but nothing in the schema forces
        them to agree, and a row where only one says yes is exactly the ambiguous
        case worth stopping on.
        """

        if int(plan["validated"] or 0) != 1 or str(plan["status"]) != PlanStatus.VALIDATED:
            raise PlanNotExecutable(
                f"plan {plan['id']} is not validated and will not be run "
                f"(status={plan['status']!r})"
            )
        document = self._parse_plan(plan["plan_json"], plan_id=int(plan["id"]))
        stored = self._auth.plan_steps(session_token, int(plan["id"]))
        by_key = self._reconcile(document, stored, plan_id=int(plan["id"]))
        if not by_key:
            raise PlanNotExecutable(f"plan {plan['id']} has no steps to run")
        return self._ordered_steps(document, by_key, plan_id=int(plan["id"]))

    @staticmethod
    def _parse_plan(plan_json: object, *, plan_id: int) -> PlanDocument:
        if not isinstance(plan_json, str):
            raise PlanNotExecutable(f"plan {plan_id} has no readable plan document")
        if len(plan_json.encode("utf-8", errors="replace")) > MAX_PLAN_JSON_BYTES:
            raise PlanNotExecutable(f"plan {plan_id} document is too large to parse")
        try:
            payload = json.loads(plan_json)
            return PlanDocument.from_payload(payload, max_steps=MAX_REPARSE_STEPS)
        except (PlanError, ValueError) as exc:
            # A plan the executor cannot parse is not a plan the executor can run.
            # The detail is logged and the caller gets the class, because the
            # parse message describes stored data rather than instructing anyone.
            logger.warning("plan %s is not parsable: %s", plan_id, exc)
            raise PlanNotExecutable(f"plan {plan_id} document could not be parsed") from exc

    @staticmethod
    def _reconcile(
        document: PlanDocument, stored: Sequence[Mapping[str, Any]], *, plan_id: int
    ) -> dict[str, Mapping[str, Any]]:
        """Match the plan document to its stored step rows, or refuse.

        A step that exists in one record and not the other means the two are no
        longer the same plan. Running the document's version would dispatch a tool
        the step rows do not name, and running the rows' version would execute
        something the validated document never authorized. Refusing is the only
        answer that does not pick one arbitrarily.

        Each returned row is the stored row plus an ``arguments`` mapping parsed
        from ``input_json``. The parse happens here rather than at dispatch because
        a row whose input will not parse as a JSON object is as unusable as one
        whose tool disagrees, and finding out before the first step runs is the
        difference between a clean refusal and a partial run.
        """

        rows: dict[str, Mapping[str, Any]] = {}
        for row in stored:
            key = row.get("step_key")
            if not isinstance(key, str) or not key:
                raise PlanNotExecutable(f"plan {plan_id} has a stored step with no key")
            if key in rows:
                raise PlanNotExecutable(f"plan {plan_id} stores step {key!r} twice")
            rows[key] = row

        plan_steps = {step.step_key: step for step in document.steps}
        if set(rows) != set(plan_steps):
            raise PlanNotExecutable(
                f"plan {plan_id} document and step rows disagree on which steps exist"
            )

        ready: dict[str, Mapping[str, Any]] = {}
        for key, step in plan_steps.items():
            row = rows[key]
            stored_tool = row.get("tool_id")
            if stored_tool is not None and stored_tool != step.tool_id:
                raise PlanNotExecutable(
                    f"plan {plan_id} step {key!r} names {stored_tool!r} in storage and "
                    f"{step.tool_id!r} in the document"
                )
            arguments = ExecutorService._parse_arguments(row, plan_id=plan_id, step_key=key)
            if _canonical(arguments) != _canonical(step.input):
                raise PlanNotExecutable(
                    f"plan {plan_id} step {key!r} has different input in storage and in "
                    "the document"
                )
            ready[key] = {**row, "arguments": arguments}
        return ready

    @staticmethod
    def _parse_arguments(
        row: Mapping[str, Any], *, plan_id: int, step_key: str
    ) -> Mapping[str, Any]:
        """The step's input as a mapping, or refuse.

        ``plan_steps.input_json`` holds JSON *text*, not a mapping. Handing that
        text straight to the dispatcher would be a schema violation reported as a
        tool input error, which blames the tool for how the row was stored.
        """

        raw = row.get("input_json")
        if not isinstance(raw, str):
            raise PlanNotExecutable(
                f"plan {plan_id} step {step_key!r} has no stored input"
            )
        if len(raw.encode("utf-8", errors="replace")) > MAX_PLAN_JSON_BYTES:
            raise PlanNotExecutable(
                f"plan {plan_id} step {step_key!r} input is too large to parse"
            )
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise PlanNotExecutable(
                f"plan {plan_id} step {step_key!r} input is not readable JSON"
            ) from exc
        if not isinstance(parsed, Mapping):
            raise PlanNotExecutable(
                f"plan {plan_id} step {step_key!r} input is not a JSON object"
            )
        return dict(parsed)

    @staticmethod
    def _ordered_steps(
        document: PlanDocument,
        by_key: Mapping[str, Mapping[str, Any]],
        *,
        plan_id: int,
    ) -> list[Mapping[str, Any]]:
        """Order steps so every step follows the steps it declares it needs.

        Reads ``depends_on`` from the parsed document and sorts here rather than
        using the stored ``position``, because position is a proposal about order
        and this list is the order. Ties are broken by position so that the same
        plan produces the same sequence on every run -- a run whose order varied
        would make its own provenance unreproducible.

        Kahn's algorithm, and a leftover node means a cycle. A cycle in a plan
        that was already validated should be impossible; refusing it here is the
        point of checking at run time rather than trusting write time.
        """

        remaining = {step.step_key: step for step in document.steps}
        ordered: list[Mapping[str, Any]] = []
        done: set[str] = set()
        while remaining:
            ready = sorted(
                (
                    key
                    for key, step in remaining.items()
                    if all(dep in done for dep in step.depends_on)
                ),
                key=lambda key: by_key[key]["position"],
            )
            if not ready:
                raise PlanNotExecutable(
                    f"plan {plan_id} has a dependency cycle among {sorted(remaining)} "
                    "and cannot be ordered"
                )
            for key in ready:
                ordered.append(by_key[key])
                done.add(key)
                del remaining[key]
        return ordered

    # -- running ---------------------------------------------------------

    def _run_step(
        self,
        session_token: object,
        *,
        task_id: int,
        plan: Mapping[str, Any],
        step: Mapping[str, Any],
        attempt: int,
    ) -> StepOutcome:
        """Dispatch one step, closing its execution row however it ends."""

        step_key = str(step["step_key"])
        tool_id = str(step["tool_id"])
        invocation_id = self._invocation_id(
            plan_id=int(plan["id"]), step_key=step_key, attempt=attempt
        )
        execution_id = self._begin(
            session_token,
            task_id=task_id,
            plan=plan,
            step=step,
            tool_id=tool_id,
            invocation_id=invocation_id,
            attempt=attempt,
        )
        self._auth.mark_plan_step(session_token, int(step["id"]), status="running")
        try:
            invocation = self._dispatcher.dispatch(
                session_token,
                tool_id=tool_id,
                task_id=task_id,
                arguments=step["arguments"],
            )
        except ToolError as exc:
            # The tool's own code, never its message: the message is written for an
            # operator and the plan step row is read by callers who have no
            # business seeing it.
            self._close(
                session_token,
                execution_id,
                error_code=exc.code,
                error=str(exc),
            )
            self._auth.mark_plan_step(
                session_token, int(step["id"]), status="failed"
            )
            raise StepFailed(
                f"step {step_key!r} failed with {exc.code}",
                step_key=step_key,
                error_code=exc.code,
            ) from exc
        except AuthorizationError as exc:
            # Closed so the task is not left permanently busy, then re-raised
            # unchanged: a capability refusal is not an execution failure and must
            # not be laundered into one.
            self._close(
                session_token,
                execution_id,
                error_code=getattr(exc, "reason", None) or AuthorizationError.__name__,
            )
            self._auth.mark_plan_step(session_token, int(step["id"]), status="failed")
            raise

        self._close(session_token, execution_id, result=invocation.result)
        self._auth.mark_plan_step(session_token, int(step["id"]), status="succeeded")
        return StepOutcome(
            step_key=step_key,
            tool_id=tool_id,
            execution_id=execution_id,
            invocation_id=invocation_id,
            provenance_event_id=invocation.provenance_event_id,
            result=invocation.result,
        )

    def _begin(
        self,
        session_token: object,
        *,
        task_id: int,
        plan: Mapping[str, Any],
        step: Mapping[str, Any],
        tool_id: str,
        invocation_id: str,
        attempt: int,
    ) -> int:
        """Open the dispatch row, translating a concurrency refusal."""

        try:
            return self._auth.begin_execution(
                session_token,
                task_id=task_id,
                plan_id=int(plan["id"]),
                plan_step_id=int(step["id"]),
                tool_id=tool_id,
                invocation_id=invocation_id,
                origin=ORIGIN_PLAN_STEP,
                max_concurrent=self._max_concurrent,
                attempt=attempt,
            )
        except PermissionDenied as exc:
            # The authorization layer refuses a second concurrent run of this task
            # with DUPLICATE_EXECUTION; that is a refusal to start, which is a
            # different thing from a step failing, so it gets its own class.
            if getattr(exc, "reason", None) == DenyReason.DUPLICATE_EXECUTION:
                raise DuplicateExecution(
                    f"task {task_id} already has an execution in flight"
                ) from exc
            raise

    def _close(
        self,
        session_token: object,
        execution_id: int,
        *,
        result: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        error: str | None = None,
    ) -> None:
        """Close an execution row, never raising over the failure that caused it.

        Called from the error paths, where the interesting exception is already in
        flight. Losing the record would leave the task permanently busy, which
        would be worse than the missing note -- but neither is worth replacing a
        real failure with a bookkeeping one, so the error is logged and the
        original failure continues.
        """

        try:
            self._auth.end_execution(
                session_token,
                execution_id,
                result=result,
                error_code=error_code,
                error=error,
            )
        except (AuthorizationError, ExecutionError):
            logger.exception(
                "could not close execution %s; the task may appear busy", execution_id
            )

    # -- lifecycle --------------------------------------------------------

    def _enter_running(self, session_token: object, task_id: int) -> None:
        """Move the task to ``executing`` from wherever it legitimately is.

        ``pending`` is a task with no plan yet in this build's history, but a
        Phase 11 plan can be created against a ``pending`` task, so the edge is
        real. ``executing`` is already running and is refused here rather than
        re-entered, which is the duplicate case the concurrency bound would catch
        anyway -- catching it at the lifecycle says *why* sooner.
        """

        task = self._auth.get_task(session_token, task_id)
        current = str(task["status"])
        if current == TaskStatus.EXECUTING.value:
            raise DuplicateExecution(f"task {task_id} is already executing")
        if current == TaskStatus.PLANNED.value:
            self._auth.set_task_status(
                session_token, task_id, status=TaskStatus.EXECUTING.value
            )
            return
        if current == TaskStatus.PENDING.value:
            self._auth.set_task_status(
                session_token, task_id, status=TaskStatus.PLANNED.value
            )
            self._auth.set_task_status(
                session_token, task_id, status=TaskStatus.EXECUTING.value
            )
            return
        # planned -> executing was the only legal edge here, so reaching this line
        # means the task is failed, executed, verified, or succeeded. Phase 16 may
        # add a documented reopen; until then a re-run is refused, not permitted.
        raise PlanNotExecutable(
            f"task {task_id} is {current!r} and cannot be run again in this phase"
        )

    def _fail_task(self, session_token: object, task_id: int) -> None:
        """Move a task that started running to ``failed``, best effort."""

        try:
            task = self._auth.get_task(session_token, task_id)
            current = str(task["status"])
            if current in {TaskStatus.EXECUTING.value, TaskStatus.EXECUTED.value}:
                self._auth.set_task_status(
                    session_token, task_id, status=TaskStatus.FAILED.value
                )
        except Exception:
            # The originating failure is what the caller needs. A task left
            # `executing` is recoverable by a human reading the row; losing the
            # tool error to a status-write error is not.
            logger.exception("could not mark task %s failed", task_id)

    def _check_budget(self, completed: int, started: float) -> None:
        """Refuse to start another step if either bound is spent.

        Checked before the dispatch, so the bound is a limit on work *begun*.
        Checking afterwards would only report an overrun that has already cost a
        tool call, which is the opposite of a budget.
        """

        if completed >= self._max_tool_calls:
            raise ExecutionBudgetExceeded(
                f"run exceeded its budget of {self._max_tool_calls} tool calls"
            )
        elapsed = time.monotonic() - started
        if elapsed > self._max_execution_seconds:
            raise ExecutionBudgetExceeded(
                f"run exceeded its budget of {self._max_execution_seconds} seconds"
            )

    @staticmethod
    def _invocation_id(*, plan_id: int, step_key: str, attempt: int) -> str:
        """A deterministic correlation id for one dispatch of one step.

        Derived from the plan, the step, and the attempt rather than generated, so
        that re-running the same step of the same plan produces the *same* id and
        is refused by the unique index as the replay it is. A random id would make
        the replay look like a fresh run and write a second execution row for it.

        The digest also keeps the id inside the 128-character bound, which a raw
        concatenation of a long step key would not.
        """

        payload = f"{plan_id}\x00{step_key}\x00{attempt}"
        return f"inv-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:40]}"

    @staticmethod
    def _as_task_id(task_id: object) -> int:
        if isinstance(task_id, bool) or not isinstance(task_id, int):
            raise ExecutionError("task_id must be an integer row id")
        return task_id


#: Upper bound on steps re-parsed from a stored plan. Phase 11 caps what it will
#: *write*; this caps what storage may hand back, and is deliberately generous so
#: a valid plan is never refused for being large while an absurd one still is.
PLAN_STEP_KEY_LIMIT = 256
