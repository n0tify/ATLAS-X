"""Phase 13: the only component that can decide a task's output is correct.

:class:`VerifierService` answers one question -- "is the recorded result the one
this plan's declared deterministic contract produces from the recorded input?" --
and it answers it from persisted records only.

What it trusts, and what it does not
------------------------------------

Trusted, because it re-derives from them and compares:

* ``plan_steps.input_json`` -- the input a step was authorized with.
* ``executions.result_json`` -- the output a step actually produced.
* ``executions.status`` -- that a dispatch closed rather than still running.

Not trusted, and each for a specific reason:

* **"The tool completed."** A dispatch that closed successfully means the tool
  returned something that passed output validation. It says nothing about whether
  the numbers are right, and treating it as proof is the exact failure this phase
  exists to prevent.
* **The planner.** The planner said the steps were valid; the verifier re-derives
  from the step inputs regardless of who proposed them. A plan that a model
  authored gets no leniency, and a plan a human authored gets none either.
* **The task status.** ``executed`` is a precondition for verifying, not evidence
  that verification will pass. Nothing reads ``executed`` as a claim.
* **The verifier's own previous opinion.** There is no path that carries a verdict
  forward. Re-verifying is refused by the lifecycle, so there is no opportunity to
  reach a cached PASS.

Determinism
-----------

No clock, no randomness, no I/O beyond the database, no model, and no comparison
against wall-clock timing. The only timestamp written is ``created_at``, which is
metadata about when the verdict was recorded and is never an input to the verdict
itself. Verifying the same persisted bytes twice yields the same verdict and the
same evidence -- which is what "repeated verification is deterministic" means, and
what lets the evidence be reproduced by a third party.

What it will not do
-------------------

* It does not repair, re-run, or re-plan anything. A FAIL leaves the records for
  Phase 15 to classify and Phase 16 to recover from.
* It does not write ``tasks.result_json`` on a FAIL, or on a partial pass. The one
  successful result is written by
  :meth:`~atlas.security.service.AuthorizationService.finish_verified_task`, which
  refuses unless the task is already ``verified``.
* It does not mark a plan step's status. ``plan_steps.status`` is a progress
  marker for dispatch; overwriting ``succeeded`` with ``failed`` because
  verification disagreed would destroy the fact that the tool ran and succeeded,
  which is a different and equally important fact. The verdict lives on the
  ``verifications`` row and names its ``plan_step_id``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from atlas.security.service import AuthorizationService
from atlas.storage.execution_repo import EXECUTABLE_PLAN_STATUS
from atlas.storage.task_status import ExecutionStatus, TaskStatus
from atlas.storage.verification_repo import (
    MAX_DETAIL_CHARS,
    RESULT_FAIL,
    RESULT_PASS,
)
from atlas.verifier.errors import VerificationErrorCode, VerificationRefused
from atlas.verifier.rules import (
    CODE_RESULT_UNREADABLE,
    CODE_TOOL_MISMATCH,
    FAIL,
    PASS,
    VERIFIER_NAME,
    RuleOutcome,
    RuleRegistry,
)

logger = logging.getLogger(__name__)

#: Version of this verifier's *procedure*, recorded on every verdict alongside the
#: rule it used. A change to how verdicts are reached -- not to what a rule
#: expects -- bumps this, so evidence stays interpretable after the code moves.
VERIFIER_VERSION = "1"

#: Bound on a stored ``result_json`` the verifier will parse. The dispatcher
#: already bounds outputs; this is the independent check on what storage returned.
MAX_RESULT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class StepEvidence:
    """One plan step, as stored: what it was authorized to run, and on what.

    ``tool_id`` is what the execution *did*; ``plan_tool_id`` is what the step was
    authorized to run. They are normally equal, and :meth:`_step_for` fills this
    in so that a disagreement is visible to whoever reads the evidence. When they
    differ, ``tool_mismatch`` carries the authorized value.
    """

    step_id: int
    step_key: str
    tool_id: str
    plan_tool_id: str
    arguments: Mapping[str, Any]
    tool_mismatch: str | None = None

    @classmethod
    def planned(
        cls,
        *,
        step_id: int,
        step_key: str,
        tool_id: str,
        arguments: Mapping[str, Any],
    ) -> StepEvidence:
        return cls(
            step_id=step_id,
            step_key=step_key,
            tool_id=tool_id,
            plan_tool_id=tool_id,
            arguments=dict(arguments),
        )


@dataclass(frozen=True)
class ExecutionVerdict:
    """One execution's verified result."""

    execution_id: int
    verification_id: int
    plan_step_id: int | None
    tool_id: str
    step_key: str
    passed: bool
    code: str
    detail: str
    result: Mapping[str, Any] | None

    @property
    def verdict_text(self) -> str:
        """``pass`` or ``fail`` in the stored vocabulary."""

        return RESULT_PASS if self.passed else RESULT_FAIL

    @property
    def publishable(self) -> bool:
        """Whether this verdict carries bytes a report may echo.

        False only when the stored result could not be read as a JSON object: the
        output exists but has no content to show, and a report that printed a
        placeholder there would be presenting an absence as an answer. A FAIL from a
        *mismatch* is publishable -- those bytes are readable, and they are exactly
        what Phase 15 needs to explain the failure.
        """

        return self.result is not None


@dataclass(frozen=True)
class TaskVerificationReport:
    """What verification concluded about a whole task.

    Returned for a PASS and for a FAIL alike. A FAIL is an answer, and a caller
    that has to catch an exception to learn that an output was wrong would be
    pushed towards treating the exception as exceptional.
    """

    task_id: int
    plan_id: int
    verdict: str
    task_status: str
    verdicts: tuple[ExecutionVerdict, ...]
    checked: int

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    @property
    def failed_executions(self) -> tuple[ExecutionVerdict, ...]:
        return tuple(v for v in self.verdicts if not v.passed)

    def as_result(self) -> dict[str, Any]:
        """The task result published on a PASS.

        Keyed by ``step_key``, not by ``tool_id``. Two steps may legitimately use
        the same tool -- measure twice, summarize once -- and keying by tool would
        make the second silently overwrite the first, publishing a result that omits
        a step the plan said to run. ``step_key`` is unique per plan by Phase 11's
        validation, so the mapping is lossless.

        Only verdict rows with readable results contribute a ``steps`` entry. On a
        PASS every verdict is readable by construction -- an unreadable one would
        have failed -- so this filter only ever matters for a FAIL report, where
        publishing an unreadable output under its step key would be worse than
        omitting it and reporting the reason in ``verifications`` instead.
        """

        return {
            "verdict": self.verdict,
            "plan_id": self.plan_id,
            "steps": {
                verdict.step_key: dict(verdict.result or {})
                for verdict in self.verdicts
                if verdict.publishable
            },
            "verifications": [
                {
                    "execution_id": verdict.execution_id,
                    "verification_id": verdict.verification_id,
                    "plan_step_id": verdict.plan_step_id,
                    "step_key": verdict.step_key,
                    "tool_id": verdict.tool_id,
                    "result": verdict.verdict_text,
                    "code": verdict.code,
                }
                for verdict in self.verdicts
            ],
        }


class VerifierService:
    """Deterministic verification over persisted execution records."""

    def __init__(
        self,
        authorization: AuthorizationService,
        *,
        rules: RuleRegistry | None = None,
    ) -> None:
        # No settings and no clock. A verifier that took a configuration object
        # would be a verifier whose verdict depends on configuration, and the whole
        # claim of this module is that the same records always give the same answer.
        self._auth = authorization
        self._rules = rules or RuleRegistry()

    @property
    def rules(self) -> RuleRegistry:
        """The rules this verifier judges with, for the Phase 15 evidence report."""

        return self._rules

    def verify_task(self, session_token: object, task_id: object) -> TaskVerificationReport:
        """Verify a task's recorded results, and record the verdict.

        Raises :class:`VerificationRefused` when the task cannot be verified at
        all, and :class:`~atlas.security.errors.AuthorizationError` when the caller
        does not own it. A verification that finds the output wrong returns a
        report whose verdict is ``fail``.
        """

        task_id = self._as_task_id(task_id)
        task = self._auth.get_task(session_token, task_id)
        status = str(task["status"])
        if status != TaskStatus.EXECUTED.value:
            # `verifying`, `verified` and the terminals all land here. Re-verifying
            # is refused rather than treated as a second opinion, because a second
            # opinion about identical bytes can only ever agree, and agreeing twice
            # is how a task ends up with two verdicts and one status.
            already_decided = status in (
                TaskStatus.VERIFYING.value,
                TaskStatus.VERIFIED.value,
                TaskStatus.SUCCEEDED.value,
            )
            raise VerificationRefused(
                f"task {task_id} is {status!r}; only an executed task can be verified",
                code=(
                    VerificationErrorCode.ALREADY_VERIFIED
                    if already_decided
                    else VerificationErrorCode.TASK_NOT_EXECUTED
                ),
            )

        # Every precondition is evaluated before the task leaves `executed`, and
        # before any verdict row exists. A refusal therefore cannot leave a task
        # stranded at `verifying` with half its executions judged: either nothing
        # has been written at all, or every execution has a verdict.
        plan = self._executable_plan(session_token, task_id)
        executions = self._completed_executions(session_token, task_id)
        steps = self._step_inputs(session_token, int(plan["id"]))
        self._reconcile(executions, steps)

        # `verifying` is written once the evidence is known to be complete and
        # self-consistent, so a crash from here leaves a truthful state instead of
        # an `executed` task that looks ready to be checked again.
        self._auth.set_task_status(
            session_token, task_id, status=TaskStatus.VERIFYING.value
        )

        verdicts: list[ExecutionVerdict] = []
        for execution in executions:
            verdicts.append(
                self._verify_execution(session_token, task_id, execution, steps)
            )

        passed = all(verdict.passed for verdict in verdicts)
        if passed:
            self._auth.set_task_status(
                session_token, task_id, status=TaskStatus.VERIFIED.value
            )
            report = TaskVerificationReport(
                task_id=task_id,
                plan_id=int(plan["id"]),
                verdict=PASS,
                task_status=TaskStatus.SUCCEEDED.value,
                verdicts=tuple(verdicts),
                checked=len(verdicts),
            )
            # The only write of a successful task result, in the same call that
            # moves the task out of `verified`. Nothing above this line can produce
            # a `succeeded` task.
            self._auth.finish_verified_task(
                session_token, task_id, result=report.as_result()
            )
            return report

        failed = [verdict for verdict in verdicts if not verdict.passed]
        logger.warning(
            "verification failed task_id=%s plan_id=%s failed_steps=%s codes=%s",
            task_id,
            plan["id"],
            [verdict.execution_id for verdict in failed],
            sorted({verdict.code for verdict in failed}),
        )
        # No result is written and nothing is repaired. Phase 15 classifies from
        # these rows and Phase 16 decides whether a retry is eligible.
        self._auth.set_task_status(session_token, task_id, status=TaskStatus.FAILED.value)
        return TaskVerificationReport(
            task_id=task_id,
            plan_id=int(plan["id"]),
            verdict=FAIL,
            task_status=TaskStatus.FAILED.value,
            verdicts=tuple(verdicts),
            checked=len(verdicts),
        )

    # -- preconditions ---------------------------------------------------

    def _executable_plan(
        self, session_token: object, task_id: int
    ) -> Mapping[str, Any]:
        """The plan head, confirmed to be the one that actually ran.

        Checks the status *and* the ``validated`` flag, matching what
        :class:`~atlas.executor.service.ExecutorService` requires to dispatch.
        Checking only the status would accept a plan whose flag says it was never
        validated, which is a state the executor would refuse to run -- so the
        verifier would certify the output of a run that could not legitimately
        have happened.
        """

        plan = self._auth.plan_head(session_token, task_id)
        status = str(plan["status"])
        if status != EXECUTABLE_PLAN_STATUS or not _is_true(plan.get("validated")):
            # `plan_head` already refused an absent plan. This refuses the case
            # where a task was executed and its plan has since been superseded or
            # marked consumed: the evidence is about a plan that is no longer the
            # one being run, so it is not the right evidence to certify.
            raise VerificationRefused(
                f"plan {plan['id']} is {status!r} "
                f"(validated={plan.get('validated')!r}) and cannot be verified",
                code=VerificationErrorCode.PLAN_NOT_EXECUTABLE,
            )
        return plan

    def _completed_executions(
        self, session_token: object, task_id: int
    ) -> list[Mapping[str, Any]]:
        executions: list[Mapping[str, Any]] = list(
            self._auth.executions_for_task(session_token, task_id)
        )
        if not executions:
            # A task with no dispatch has nothing to verify. Refused rather than
            # passed: "no evidence" is not "evidence of correctness".
            raise VerificationRefused(
                f"task {task_id} has no execution to verify",
                code=VerificationErrorCode.NO_EXECUTION,
            )
        incomplete = [
            int(row["id"])
            for row in executions
            if str(row["status"]) != ExecutionStatus.SUCCEEDED.value
            or row["result_json"] is None
        ]
        if incomplete:
            # A running or failed dispatch has no verified output to certify.
            raise VerificationRefused(
                f"task {task_id} has executions that did not complete: {incomplete}",
                code=VerificationErrorCode.EXECUTION_INCOMPLETE,
            )
        return executions

    def _step_inputs(
        self, session_token: object, plan_id: int
    ) -> dict[int, StepEvidence]:
        """Each plan step's recorded input and tool, keyed by step row id.

        Reads ``plan_steps`` rather than the plan document, so the evidence is
        anchored to the rows the executions actually referenced. Where a step row
        cannot be parsed the whole verification is refused: certifying some steps
        from unreadable inputs would produce a partial PASS, and a partial PASS is
        a success claim about evidence that was never checked.
        """

        steps: dict[int, StepEvidence] = {}
        for row in self._auth.plan_steps(session_token, plan_id):
            step_id = row.get("id")
            step_key = row.get("step_key")
            if not isinstance(step_id, int):
                raise VerificationRefused(
                    f"plan {plan_id} has a step with no id",
                    code=VerificationErrorCode.STEP_UNREADABLE,
                )
            if not isinstance(step_key, str) or not step_key:
                # Not cosmetic: `as_result` publishes steps keyed by this, so a
                # missing key would either lose an output or collide with another.
                raise VerificationRefused(
                    f"plan {plan_id} step {step_id} has no step key",
                    code=VerificationErrorCode.STEP_UNREADABLE,
                )
            steps[step_id] = StepEvidence.planned(
                step_id=step_id,
                step_key=step_key,
                tool_id="" if row.get("tool_id") is None else str(row["tool_id"]),
                arguments=_parse_json_object(
                    row.get("input_json"),
                    what=f"plan {plan_id} step {step_id}",
                    code=VerificationErrorCode.STEP_UNREADABLE,
                ),
            )
        return steps

    def _reconcile(
        self, executions: Sequence[Mapping[str, Any]], steps: Mapping[int, StepEvidence]
    ) -> None:
        """Every plan step was executed exactly once, and nothing else was.

        Phase 12 reconciled ``plans.plan_json`` against ``plan_steps`` before
        dispatching. This is the same reconciliation repeated at verification
        time, against the records as they stand now, because the gap between
        "what was authorized" and "what is stored" is where a fabricated state
        would show up:

        * A plan step with no execution is refused. A run that skipped a step has
          produced no output for it, and a PASS over the steps that *did* run
          would be a success claim about a plan that was not carried out.
        * An execution naming a step that is not in the plan is refused. There is
          no row to attach a verdict to that corresponds to anything authorized.
        * Two executions for one step is refused for the same reason: at most one
          of them is the dispatch the plan asked for, and which one cannot be
          determined from the records.

        A refusal here happens before any verdict is recorded, so the task is left
        at ``executed`` with nothing written -- the state says "this evidence does
        not add up", and the rows are left for Phase 15 to classify rather than
        being summarised into a verdict about a step that may not have run.
        """

        by_step: dict[int, list[Mapping[str, Any]]] = {}
        for execution in executions:
            step_id = execution.get("plan_step_id")
            if not isinstance(step_id, int) or step_id not in steps:
                raise VerificationRefused(
                    f"execution {execution.get('id')} names plan step {step_id!r}, "
                    "which is not a step of the executed plan",
                    code=VerificationErrorCode.EXECUTION_NOT_RECONCILED,
                )
            by_step.setdefault(step_id, []).append(execution)

        missing = sorted(set(steps) - set(by_step))
        if missing:
            raise VerificationRefused(
                f"plan steps {missing} were never executed",
                code=VerificationErrorCode.EXECUTION_NOT_RECONCILED,
            )
        duplicated = sorted(sid for sid, rows in by_step.items() if len(rows) > 1)
        if duplicated:
            raise VerificationRefused(
                f"plan steps {duplicated} have more than one execution",
                code=VerificationErrorCode.EXECUTION_NOT_RECONCILED,
            )

    def _step_for(
        self, execution: Mapping[str, Any], steps: Mapping[int, StepEvidence]
    ) -> StepEvidence:
        """The plan step an execution belongs to, with its tool re-checked.

        The executor reconciled the tool before dispatch, so re-reading it here
        could in principle be redundant. It is not, because the interval between
        the two is exactly the interval in which a stored row can be edited, and
        the verifier's job is to certify the rows as they stand rather than as
        they stood once. A disagreement is a FAIL rather than a refusal: the
        execution exists, so a verdict can honestly be recorded against it.
        """

        step_id = execution.get("plan_step_id")
        if not isinstance(step_id, int) or step_id not in steps:
            # Unreachable: `_reconcile` refused every execution not in the plan
            # before any verdict was reached.
            raise VerificationRefused(
                f"execution {execution.get('id')} names no stored plan step",
                code=VerificationErrorCode.STEP_UNREADABLE,
            )
        step = steps[step_id]
        actual = "" if execution.get("tool_id") is None else str(execution["tool_id"])
        if actual != step.tool_id:
            return StepEvidence(
                step_id=step.step_id,
                step_key=step.step_key,
                tool_id=actual,
                plan_tool_id=step.plan_tool_id,
                arguments=step.arguments,
                tool_mismatch=step.plan_tool_id,
            )
        return step

    # -- one execution ---------------------------------------------------

    def _verify_execution(
        self,
        session_token: object,
        task_id: int,
        execution: Mapping[str, Any],
        steps: Mapping[int, StepEvidence],
    ) -> ExecutionVerdict:
        """Judge one execution. Always returns a verdict; never leaves it blank.

        A result that will not parse is still a verdict about that result, so it
        is recorded as a FAIL with ``result_unreadable`` rather than raised. The
        distinction that matters is *who* is being told what:

        * A stored result that is unreadable is the tool's or storage's output
          being wrong. The task is ``verifying``, the execution exists, and there
          is a row to attach the finding to -- so it is recorded.
        * An input that will not parse, or an execution that never completed, is
          the *plan* or the *run* not supporting a verdict at all. Nothing
          meaningful can be recorded against it, so those were refused before the
          task moved to ``verifying``.

        Both fail closed. The difference is only whether the refusal leaves a
        verdict behind for Phase 15 to classify.
        """

        step = self._step_for(execution, steps)
        step_id = int(execution["plan_step_id"])
        outcome = self._judge(execution, step)
        result = _as_object(execution.get("result_json"), max_bytes=MAX_RESULT_BYTES)

        # For a PASS and for a FAIL alike: the digests are what let a later reader
        # tell whether the bytes this verdict was reached from are still the bytes
        # in the database. A result that failed to parse has no comparable bytes,
        # so its digest is null rather than a digest of a placeholder.
        evidence: dict[str, Any] = {
            **outcome.evidence(),
            "task_id": task_id,
            "execution_id": int(execution["id"]),
            "plan_step_id": step_id,
            "tool_id": step.tool_id,
            "plan_step_tool_id": step.plan_tool_id,
            "step_key": step.step_key,
            "input_digest": _digest(step.arguments),
            # Null rather than a digest of a placeholder: there are no bytes here
            # to identify, and a digest of `{}` would read as "the output was an
            # empty object", which is a claim this verdict has not made.
            "result_digest": None if result is None else _digest(result),
            "execution_status": str(execution["status"]),
        }
        verification_id = self._auth.record_verification(
            session_token,
            execution_id=int(execution["id"]),
            result=RESULT_PASS if outcome.passed else RESULT_FAIL,
            verifier=VERIFIER_NAME,
            verifier_version=VERIFIER_VERSION,
            evidence=evidence,
            plan_step_id=step_id,
            detail={"code": outcome.code, "detail": outcome.detail[:MAX_DETAIL_CHARS]},
        )
        return ExecutionVerdict(
            execution_id=int(execution["id"]),
            verification_id=verification_id,
            plan_step_id=step_id,
            tool_id=step.tool_id,
            step_key=step.step_key,
            passed=outcome.passed,
            code=outcome.code,
            detail=outcome.detail,
            result=result,
        )

    def _judge(
        self, execution: Mapping[str, Any], step: StepEvidence
    ) -> RuleOutcome:
        """The comparison for one execution, in the order the refusals deserve."""

        if step.tool_mismatch is not None:
            # The execution claims a different tool than the step it names. Nothing
            # about the recorded output can be judged until that is resolved, and it
            # is not resolved by picking one of the two values.
            return RuleOutcome(
                verdict=FAIL,
                code=CODE_TOOL_MISMATCH,
                detail=(
                    f"execution ran {step.tool_id!r} but plan step {step.step_id} "
                    f"authorized {step.tool_mismatch!r}"
                ),
            )
        result = _as_object(execution.get("result_json"), max_bytes=MAX_RESULT_BYTES)
        if result is None:
            return RuleOutcome(
                verdict=FAIL,
                code=CODE_RESULT_UNREADABLE,
                detail="the recorded result is not a readable JSON object",
            )
        return self._rules.verify(step.tool_id, step.arguments, result)

    @staticmethod
    def _as_task_id(task_id: object) -> int:
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
            raise VerificationRefused(
                "task_id must be a positive integer row id",
                code=VerificationErrorCode.TASK_NOT_EXECUTED,
            )
        return task_id


def _parse_json_object(
    raw: object, *, what: str, code: str
) -> Mapping[str, Any]:
    """Parse stored JSON text into an object, or refuse.

    For *inputs*. Refuses rather than substituting a default: a step input that
    will not parse means the verifier cannot say what question it is answering,
    which is a refusal rather than a verdict. Results take the same treatment
    through :func:`_as_object` but land on a FAIL, because an unreadable result is
    a finding about a run rather than an absence of a question.
    """

    if raw is None:
        raise VerificationRefused(
            f"{what} is missing", code=VerificationErrorCode.RESULT_MISSING
        )
    parsed = _as_object(raw, max_bytes=MAX_RESULT_BYTES)
    if parsed is None:
        raise VerificationRefused(f"{what} is not a readable JSON object", code=code)
    return parsed


def _as_object(raw: object, *, max_bytes: int) -> Mapping[str, Any] | None:
    """Parse stored JSON text into an object, or return ``None``.

    Bounded on the encoded size before parsing rather than after, so a hostile row
    cannot make the verifier allocate a large object in order to reject it.
    Returns ``None`` instead of raising so the caller decides whether unreadable
    bytes are a verdict or a refusal.
    """

    if not isinstance(raw, str):
        return None
    if len(raw.encode("utf-8", errors="replace")) > max_bytes:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, Mapping):
        return None
    return dict(parsed)


def _is_true(value: object) -> bool:
    """Whether a stored flag means "yes".

    SQLite has no boolean, and every writer in this codebase stores ``1``. Checking
    for truthiness of the raw value instead would accept the string ``"0"``, which
    is truthy as a Python object and false as a fact.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return False


def _digest(value: object) -> str:
    """A content digest of verified inputs and results.

    An identifier, not tamper evidence: nothing here is signed, and Phase 14 is
    where the chained digest lives. Its job is to let a reader tell whether the
    bytes this verdict was reached from are still the bytes in the database.
    """

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
