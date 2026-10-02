"""The single authorization boundary for ATLAS-X.

Every storage-facing operation that touches user-owned data goes through this
service. It is the only place where an authenticated actor is paired with a
resource, and the only place that raises an authorization failure.

Boundaries by design:

* **Identity comes from a session token**, resolved by
  :class:`~atlas.security.identity.IdentityResolver`. No method accepts a
  ``user_id`` argument, so a caller cannot nominate the actor.
* **The policy decides**, the repository scopes rows, and the caller receives
  data. A denied lookup and a missing row produce the same outward result, so
  this is not a resource-existence oracle.
* **Checks and effects share one transaction**, so a decision cannot be made
  against state the subsequent statement does not see.
* **Failures are closed.** Every unexpected condition becomes
  :class:`~atlas.security.errors.AuthorizationError`. No path converts a
  failure into an allow.
* **No provenance is written for authorization decisions.** Recording one would
  require an actor value, and the actor vocabulary is an unresolved
  contradiction (C-06). Writing none keeps that decision open.

Authorization is not filesystem authorization. Owning a row does not authorize
access to any host path, and this service performs no path validation.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Mapping, NoReturn, Sequence

from atlas.auth.service import AuthService
from atlas.security.errors import (
    AuthorizationError,
    InvalidAuthorizationRequest,
    PermissionDenied,
    ResultUnpublishable,
)
from atlas.security.identity import Identity, IdentityResolver
from atlas.security.policy import (
    OWNERSHIP_UNDECIDED,
    Decision,
    DenyReason,
    Operation,
    Resource,
    ToolGrantSource,
    decide_operation,
    decide_tool_invocation,
    is_valid_resource_id,
)
from atlas.storage.db import Database
from atlas.storage.execution_repo import ExecutionRepo, ExecutionWriteInvalid
from atlas.storage.owned_resources import (
    OwnedResourceRepo,
    UnsupportedOwnedResource,
    owned_table_for,
)
from atlas.storage.plan_repo import PlanRepo, PlanWriteInvalid
from atlas.storage.repositories import ProvenanceRepo, TaskRepo
from atlas.storage.task_status import (
    StatusTransitionRefused,
    TaskStatus,
    check_task_transition,
)
from atlas.storage.verification_repo import VerificationRepo, VerificationWriteInvalid
from atlas.util import utcnow_iso

logger = logging.getLogger(__name__)

#: Default provenance actor for events written through this boundary. This phase
#: does not define an actor taxonomy; see C-06.
AUTHORIZATION_ACTOR = "user"

#: Denial reasons that describe a request the policy could not evaluate at all.
_MALFORMED_REASONS = frozenset(
    {
        DenyReason.MALFORMED_RESOURCE_ID,
        DenyReason.UNKNOWN_RESOURCE,
        DenyReason.UNKNOWN_OPERATION,
        DenyReason.UNSUPPORTED_FILTER,
    }
)

_IDENTITY_REASONS = frozenset({DenyReason.MISSING_IDENTITY, DenyReason.INVALID_IDENTITY})

#: Bound on the serialized task result. Generous enough for a Phase 18 report and
#: tight enough that a task row cannot be turned into a blob store. Refused rather
#: than truncated: a truncated report that still reads as a result is worse than a
#: visible refusal.
MAX_TASK_RESULT_CHARS = 1_000_000


def _encode_result(result: Mapping[str, Any]) -> str:
    """Serialize a task result under the size bound, or refuse."""

    encoded = json.dumps(dict(result), ensure_ascii=True, sort_keys=True, default=str)
    if len(encoded) > MAX_TASK_RESULT_CHARS:
        raise InvalidAuthorizationRequest(DenyReason.UNSUPPORTED_FILTER)
    return encoded


class AuthorizationService:
    """Owner-scoped, operation-scoped, deny-by-default access to user data."""

    def __init__(
        self,
        db: Database,
        auth: AuthService,
        *,
        identities: IdentityResolver | None = None,
        tasks: TaskRepo | None = None,
        plans: PlanRepo | None = None,
        executions: ExecutionRepo | None = None,
        verifications: VerificationRepo | None = None,
        provenance: ProvenanceRepo | None = None,
        owned: OwnedResourceRepo | None = None,
        tool_grants: ToolGrantSource | None = None,
    ) -> None:
        self._db = db
        self._auth = auth
        self._identities = identities or IdentityResolver(db, auth)
        self._tasks = tasks or TaskRepo()
        self._plans = plans or PlanRepo()
        self._executions = executions or ExecutionRepo()
        self._verifications = verifications or VerificationRepo()
        self._provenance = provenance or ProvenanceRepo()
        self._owned = owned or OwnedResourceRepo()
        self._tool_grants = tool_grants

    def authenticate(self, session_token: object) -> Identity:
        """Verify a session token. Absence, expiry, and revocation all deny."""

        return self._identities.from_session_token(session_token)

    def create_task(
        self, session_token: object, *, title: str, goal: str
    ) -> dict[str, Any]:
        identity = self.authenticate(session_token)
        self._permit(identity, Resource.TASK, Operation.CREATE)
        with self._db.transaction() as conn:
            task_id = self._tasks.create(
                conn, user_id=identity.user_id, title=title, goal=goal
            )
            row = self._tasks.get(conn, identity.user_id, task_id)
        if row is None:
            self._deny(identity, Resource.TASK, Operation.CREATE, DenyReason.RESOURCE_NOT_FOUND)
        return row

    def get_task(self, session_token: object, task_id: object) -> dict[str, Any]:
        identity = self.authenticate(session_token)
        rid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, Resource.TASK, Operation.READ)
        with self._db.transaction() as conn:
            row = self._tasks.get(conn, identity.user_id, rid)
        if row is None:
            self._deny(identity, Resource.TASK, Operation.READ, DenyReason.RESOURCE_NOT_OWNED)
        return row

    def list_tasks(self, session_token: object) -> list[dict[str, Any]]:
        identity = self.authenticate(session_token)
        self._permit(identity, Resource.TASK, Operation.READ)
        with self._db.transaction() as conn:
            return self._tasks.list_for_user(conn, identity.user_id)

    def delete_task(self, session_token: object, task_id: object) -> None:
        identity = self.authenticate(session_token)
        rid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, Resource.TASK, Operation.DELETE)
        with self._db.transaction() as conn:
            if self._tasks.get(conn, identity.user_id, rid) is None:
                self._deny(identity, Resource.TASK, Operation.DELETE, DenyReason.RESOURCE_NOT_OWNED)
            self._tasks.delete(conn, identity.user_id, rid)

    def create_plan(
        self,
        session_token: object,
        *,
        task_id: object,
        plan_json: str,
        digest: str,
        steps: Sequence[Mapping[str, Any]],
        model_id: str | None,
        source: str,
        validated: bool,
        validation_json: str | None,
        supersedes_plan_id: int | None = None,
    ) -> dict[str, Any]:
        """Persist one plan and its steps against a task the caller owns.

        This is the only path that writes a plan row, and it is here rather than
        in the planner so that the ownership check and the write share one
        transaction: a plan cannot be attached to a task whose owner was not
        confirmed in the same transaction that stored it.

        The parameters are primitives rather than planner types on purpose.
        ``atlas.security`` must not depend on ``atlas.planner``, and the
        structural checks that keep a written plan honest -- source and status
        vocabulary, digest shape, contiguous step positions -- live in
        :class:`~atlas.storage.plan_repo.PlanRepo`, which is called from inside
        this transaction.
        """

        identity = self.authenticate(session_token)
        tid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, Resource.PLAN, Operation.CREATE)
        self._permit(identity, Resource.PLAN_STEP, Operation.APPEND)
        superseded = (
            None if supersedes_plan_id is None else self._as_id(supersedes_plan_id, Resource.PLAN)
        )
        with self._db.transaction() as conn:
            if self._tasks.get(conn, identity.user_id, tid) is None:
                # Not owned and not existing produce the same outcome, so this
                # cannot be used to probe for another user's task.
                self._deny(identity, Resource.PLAN, Operation.CREATE, DenyReason.RESOURCE_NOT_OWNED)
            if superseded is not None and (
                self._owned.get_owned(
                    conn, resource=Resource.PLAN, user_id=identity.user_id, resource_id=superseded
                )
                is None
                or self._plans.task_id_for(conn, plan_id=superseded) != tid
            ):
                # A revision must belong to the task it revises. Without this a
                # caller could chain a plan of their own onto somebody else's plan
                # by naming its id, and the head of that chain would cross tasks.
                self._deny(
                    identity,
                    Resource.PLAN,
                    Operation.CREATE,
                    DenyReason.RESOURCE_NOT_OWNED,
                )
            try:
                return self._plans.create(
                    conn,
                    task_id=tid,
                    plan_json=plan_json,
                    digest=digest,
                    model_id=model_id,
                    source=source,
                    validated=validated,
                    validation_json=validation_json,
                    steps=steps,
                    supersedes_plan_id=superseded,
                )
            except (PlanWriteInvalid, ValueError) as exc:
                # A structurally impossible plan is a caller bug, not a denial and
                # not a leak. It is raised as an authorization-service refusal so
                # it cannot reach a client as a success with a partial row.
                logger.warning(
                    "plan write rejected user_id=%s task_id=%s detail=%s",
                    identity.user_id,
                    tid,
                    exc,
                )
                raise InvalidAuthorizationRequest(DenyReason.UNSUPPORTED_FILTER) from exc

    def plan_head(self, session_token: object, task_id: object) -> dict[str, Any]:
        """The plan that no other plan supersedes, for a task the caller owns."""

        identity = self.authenticate(session_token)
        tid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, Resource.PLAN, Operation.READ)
        with self._db.transaction() as conn:
            if self._tasks.get(conn, identity.user_id, tid) is None:
                self._deny(identity, Resource.PLAN, Operation.READ, DenyReason.RESOURCE_NOT_OWNED)
            row = self._plans.head_for_task(conn, tid)
        if row is None:
            self._deny(identity, Resource.PLAN, Operation.READ, DenyReason.RESOURCE_NOT_FOUND)
        return row

    def plan_steps(self, session_token: object, plan_id: object) -> list[dict[str, Any]]:
        """The steps of a plan the caller owns, in position order."""

        identity = self.authenticate(session_token)
        pid = self._as_id(plan_id, Resource.PLAN)
        self._permit(identity, Resource.PLAN_STEP, Operation.READ)
        with self._db.transaction() as conn:
            if (
                self._owned.get_owned(
                    conn, resource=Resource.PLAN, user_id=identity.user_id, resource_id=pid
                )
                is None
            ):
                self._deny(
                    identity, Resource.PLAN_STEP, Operation.READ, DenyReason.RESOURCE_NOT_OWNED
                )
            return self._plans.steps_for_plan(conn, pid)

    def set_task_status(
        self, session_token: object, task_id: object, *, status: str
    ) -> dict[str, Any]:
        """Move a task to ``status``, refusing a transition that does not exist.

        The transition table is checked here rather than in the caller, so a
        status that cannot be reached is refused at the boundary that owns writes
        and not merely avoided by whichever component happened to be correct.
        """

        identity = self.authenticate(session_token)
        tid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, Resource.TASK, Operation.UPDATE)
        with self._db.transaction() as conn:
            row = self._tasks.get(conn, identity.user_id, tid)
            if row is None:
                self._deny(identity, Resource.TASK, Operation.UPDATE, DenyReason.RESOURCE_NOT_OWNED)
            current = str(row["status"])
            # Not a denial and not swallowed: the caller owns the task, it asked
            # for a move the lifecycle does not have, and
            # StatusTransitionRefused carries both statuses for the caller to log
            # or surface. Wrapping it in an authorization error would claim the
            # policy refused a move that policy never had an opinion about.
            check_task_transition(current, status)
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (status, utcnow_iso(), tid, identity.user_id),
            )
            updated = self._tasks.get(conn, identity.user_id, tid)
        if updated is None:
            raise RuntimeError("task disappeared during a status update")
        return updated

    def record_verification(
        self,
        session_token: object,
        *,
        execution_id: object,
        result: str,
        verifier: str,
        verifier_version: str,
        detail: Mapping[str, Any] | None = None,
        evidence: Mapping[str, Any] | None = None,
        plan_step_id: int | None = None,
        artifact_id: int | None = None,
    ) -> int:
        """Record one verification verdict against an execution.

        Create-only by policy: ``atlas.security`` grants the verifier no
        ``update`` or ``delete`` on this resource, so a verdict written here
        cannot be revised through any path in this codebase.

        Ownership is the execution's task's, and it is checked inside the same
        transaction that inserts the row -- so a verdict cannot land against an
        execution belonging to somebody else's task, not even transiently.
        """

        identity = self.authenticate(session_token)
        eid = self._as_id(execution_id, Resource.EXECUTION)
        self._permit(identity, Resource.VERIFICATION, Operation.CREATE)
        with self._db.transaction() as conn:
            row = self._executions.get(conn, eid)
            if row is None:
                self._deny(
                    identity,
                    Resource.VERIFICATION,
                    Operation.CREATE,
                    DenyReason.RESOURCE_NOT_OWNED,
                )
            self._require_owned_task(
                conn,
                identity,
                int(row["task_id"]),
                resource=Resource.VERIFICATION,
                operation=Operation.CREATE,
            )
            try:
                return self._verifications.create(
                    conn,
                    execution_id=eid,
                    result=result,
                    verifier=verifier,
                    verifier_version=verifier_version,
                    detail=detail,
                    evidence=evidence,
                    plan_step_id=plan_step_id,
                    artifact_id=artifact_id,
                )
            except VerificationWriteInvalid as exc:
                # Not a denial: the caller owns the execution and the verdict was
                # structurally impossible. Surfaced as an invalid request so it
                # cannot reach a client as a silent success.
                logger.warning(
                    "verification write refused user_id=%s execution_id=%s detail=%s",
                    identity.user_id,
                    eid,
                    exc,
                )
                raise InvalidAuthorizationRequest(DenyReason.UNSUPPORTED_FILTER) from exc

    def verifications_for_task(
        self, session_token: object, task_id: object
    ) -> list[dict[str, Any]]:
        """Every verdict on a task the caller owns, oldest first.

        The read side of the create-only policy: a caller may see what was
        verified for their own task and may not alter any of it.
        """

        identity = self.authenticate(session_token)
        tid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, Resource.VERIFICATION, Operation.READ)
        with self._db.transaction() as conn:
            self._require_owned_task(
                conn,
                identity,
                tid,
                resource=Resource.VERIFICATION,
                operation=Operation.READ,
            )
            return self._verifications.for_task(conn, tid)

    def finish_verified_task(
        self, session_token: object, task_id: object, *, result: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Mark a ``verified`` task ``succeeded`` and write its result.

        The one place ``tasks.result_json`` and ``tasks.verified_at`` are written,
        and the one place a task may become successful.

        Two independent conditions must both hold, and the second is the one that
        carries the weight:

        1. The task is already ``verified``. Since Phase 13 removed the
           ``executed → verified`` edge, ``verified`` is reachable only from
           ``verifying``, so this is not a formality -- but it is the weaker of
           the two, because a status is a single free-text column.
        2. **Every execution of the task carries a recorded PASS.** Checked here
           rather than trusted from the caller, and counted against the total
           number of executions rather than merely being non-zero. A task whose
           executions all passed still has nothing verified if one of them was
           never looked at, and that is the exact shape of the bug this closes:
           a status column is a claim, the verdict rows are the evidence for it.

        Condition 2 is what makes this method safe to call directly. A caller that
        skipped the verifier and walked the task to ``verified`` by hand would
        satisfy (1) and fail (2).

        ``result`` is written in the same transaction as the status change.
        Writing them separately would leave a window where the task reads
        ``succeeded`` with no result, or carries a result while still ``verified``.
        """

        identity = self.authenticate(session_token)
        tid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, Resource.TASK, Operation.UPDATE)
        encoded = _encode_result(result)
        with self._db.transaction() as conn:
            row = self._tasks.get(conn, identity.user_id, tid)
            if row is None:
                self._deny(identity, Resource.TASK, Operation.UPDATE, DenyReason.RESOURCE_NOT_OWNED)
            if str(row["status"]) != TaskStatus.VERIFIED.value:
                raise StatusTransitionRefused(
                    current=str(row["status"]), requested=TaskStatus.SUCCEEDED.value
                )
            passed, total = self._verifications.pass_coverage_for_task(conn, tid)
            if total == 0 or passed != total:
                # No executions at all, or at least one without a PASS. Either way
                # there is no verified output behind the result being asked for.
                logger.warning(
                    "result withheld user_id=%s task_id=%s passed=%s total=%s",
                    identity.user_id,
                    tid,
                    passed,
                    total,
                )
                raise ResultUnpublishable()
            conn.execute(
                "UPDATE tasks SET status = ?, result_json = ?, verified_at = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (
                    TaskStatus.SUCCEEDED.value,
                    encoded,
                    utcnow_iso(),
                    utcnow_iso(),
                    tid,
                    identity.user_id,
                ),
            )
            updated = self._tasks.get(conn, identity.user_id, tid)
        if updated is None:
            raise RuntimeError("task disappeared while completing")
        return updated

    def begin_execution(
        self,
        session_token: object,
        *,
        task_id: object,
        plan_id: object,
        plan_step_id: int | None,
        tool_id: str | None,
        invocation_id: str | None,
        origin: str,
        max_concurrent: int,
        attempt: int = 1,
    ) -> int:
        """Open one dispatch row, refusing a task that is already running.

        The duplicate check and the insert share this transaction, so two
        concurrent callers cannot both observe "no execution in flight" and both
        proceed. ``max_concurrent`` is a count, not a boolean, and the query is
        capped by it rather than materializing every in-flight row.

        A refusal here is a genuine authorization outcome, not a tool failure: the
        caller owns the task but may not run it twice at once.
        """

        identity = self.authenticate(session_token)
        tid = self._as_id(task_id, Resource.TASK)
        pid = self._as_id(plan_id, Resource.PLAN)
        self._permit(identity, Resource.EXECUTION, Operation.APPEND)
        self._permit(identity, Resource.TASK, Operation.UPDATE)

        def deny_not_owned() -> NoReturn:
            self._deny(
                identity,
                Resource.EXECUTION,
                Operation.APPEND,
                DenyReason.RESOURCE_NOT_OWNED,
            )

        with self._db.transaction() as conn:
            if self._tasks.get(conn, identity.user_id, tid) is None:
                deny_not_owned()
            owned_plan = self._owned.get_owned(
                conn, resource=Resource.PLAN, user_id=identity.user_id, resource_id=pid
            )
            # A plan the caller does not own, and a plan that belongs to a
            # different task, are both refused the same way. Accepting the second
            # would let a caller execute one of its own plans against someone
            # else's task, which ownership alone does not prevent.
            if owned_plan is None or owned_plan["task_id"] != tid:
                deny_not_owned()
            if (
                isinstance(max_concurrent, bool)
                or not isinstance(max_concurrent, int)
                or max_concurrent < 1
            ):
                raise InvalidAuthorizationRequest(DenyReason.UNSUPPORTED_FILTER)
            in_flight = self._executions.in_flight_for_task(
                conn, task_id=tid, limit=max_concurrent
            )
            if len(in_flight) >= max_concurrent:
                # Counted from storage, inside the transaction that writes the row.
                # A process-local lock would not see a second ATLAS-X process on
                # the same database, which is the case the setting exists for.
                self._deny(
                    identity,
                    Resource.EXECUTION,
                    Operation.APPEND,
                    DenyReason.DUPLICATE_EXECUTION,
                )
            if invocation_id is not None:
                already = conn.execute(
                    "SELECT 1 FROM executions WHERE invocation_id = ?", (invocation_id,)
                ).fetchone()
                if already is not None:
                    # A denial rather than an error: the caller owns everything
                    # involved and still may not do this. The unique index would
                    # refuse the insert too, but reporting it here means the caller
                    # learns *why* rather than that a constraint fired, and it is
                    # why `invocation_id` is the correlation key recovery uses to
                    # avoid replaying a dispatch.
                    self._deny(
                        identity,
                        Resource.EXECUTION,
                        Operation.APPEND,
                        DenyReason.DUPLICATE_EXECUTION,
                    )
            try:
                execution_id = self._executions.create(
                    conn,
                    task_id=tid,
                    plan_id=pid,
                    plan_step_id=plan_step_id,
                    tool_id=tool_id,
                    invocation_id=invocation_id,
                    origin=origin,
                    attempt=attempt,
                )
            except ExecutionWriteInvalid as exc:
                logger.warning(
                    "execution write refused user_id=%s detail=%s", identity.user_id, exc
                )
                raise InvalidAuthorizationRequest(DenyReason.UNSUPPORTED_FILTER) from exc

            # Record execution started in the provenance chain, within the same
            # transaction that created the execution row.
            self._provenance.record_event(
                conn,
                task_id=tid,
                execution_id=execution_id,
                plan_id=pid,
                plan_step_id=plan_step_id,
                tool_id=tool_id,
                invocation_id=invocation_id,
                event_type="execution_started",
                actor="executor",
                detail={"origin": origin, "attempt": attempt},
            )
            return execution_id

    def end_execution(
        self,
        session_token: object,
        execution_id: object,
        *,
        result: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        error: str | None = None,
    ) -> None:
        """Close a dispatch row as succeeded or failed.

        Exactly one of ``result`` and ``error_code`` may be given. The
        alternatives are not interchangeable: an execution cannot succeed with no
        output, and it cannot fail without a stable code for Phase 15 to classify.
        The check is here because this is the only path that closes a row.
        """

        identity = self.authenticate(session_token)
        eid = self._as_id(execution_id, Resource.EXECUTION)
        self._permit(identity, Resource.EXECUTION, Operation.UPDATE)
        if (result is None) == (error_code is None):
            raise InvalidAuthorizationRequest(DenyReason.UNSUPPORTED_FILTER)
        with self._db.transaction() as conn:
            row = self._executions.get(conn, eid)
            if row is not None:
                # An execution has no user_id column; ownership is the task's, so
                # a caller closes only rows reached through a task they own.
                self._require_owned_task(
                    conn,
                    identity,
                    int(row["task_id"]),
                    resource=Resource.EXECUTION,
                    operation=Operation.UPDATE,
                )
            if row is None:
                self._deny(
                    identity,
                    Resource.EXECUTION,
                    Operation.UPDATE,
                    DenyReason.RESOURCE_NOT_OWNED,
                )
            try:
                if result is not None:
                    self._executions.complete(conn, execution_id=eid, result=result)
                    event_type = "execution_completed"
                    detail = {"status": "succeeded"}
                else:
                    assert error_code is not None
                    self._executions.fail(
                        conn, execution_id=eid, error_code=error_code, error=error
                    )
                    event_type = "execution_failed"
                    detail = {"status": "failed", "error_code": error_code}
            except ExecutionWriteInvalid as exc:
                logger.warning(
                    "execution close refused user_id=%s detail=%s", identity.user_id, exc
                )
                raise InvalidAuthorizationRequest(DenyReason.UNSUPPORTED_FILTER) from exc

            # Record execution completion in the provenance chain.
            self._provenance.record_event(
                conn,
                task_id=int(row["task_id"]),
                execution_id=eid,
                event_type=event_type,
                actor="executor",
                detail=detail,
            )

    def mark_plan_step(
        self, session_token: object, plan_step_id: object, *, status: str
    ) -> None:
        """Record a step's outcome on its plan step row."""

        identity = self.authenticate(session_token)
        sid = self._as_id(plan_step_id, Resource.PLAN_STEP)
        self._permit(identity, Resource.PLAN_STEP, Operation.UPDATE)
        with self._db.transaction() as conn:
            if (
                self._owned.get_owned(
                    conn,
                    resource=Resource.PLAN_STEP,
                    user_id=identity.user_id,
                    resource_id=sid,
                )
                is None
            ):
                self._deny(
                    identity,
                    Resource.PLAN_STEP,
                    Operation.UPDATE,
                    DenyReason.RESOURCE_NOT_OWNED,
                )
            try:
                self._executions.mark_plan_step(conn, plan_step_id=sid, status=status)
            except ExecutionWriteInvalid as exc:
                logger.warning(
                    "plan step write refused user_id=%s detail=%s", identity.user_id, exc
                )
                raise InvalidAuthorizationRequest(DenyReason.UNSUPPORTED_FILTER) from exc

    def executions_for_task(
        self, session_token: object, task_id: object
    ) -> list[dict[str, Any]]:
        """Every dispatch row for a task the caller owns, in insertion order."""

        identity = self.authenticate(session_token)
        tid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, Resource.EXECUTION, Operation.READ)
        with self._db.transaction() as conn:
            self._require_owned_task(
                conn,
                identity,
                tid,
                resource=Resource.EXECUTION,
                operation=Operation.READ,
            )
            return self._executions.for_task(conn, tid)

    def in_flight_executions(
        self, session_token: object, task_id: object
    ) -> list[dict[str, Any]]:
        """In-flight dispatches for a task the caller owns.

        A read, not a reservation. Deciding whether a run may start belongs to
        :meth:`begin_execution`, which re-checks inside the transaction that writes
        the row; this exists so a caller can *display* that a task is busy.
        """

        identity = self.authenticate(session_token)
        tid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, Resource.EXECUTION, Operation.READ)
        with self._db.transaction() as conn:
            self._require_owned_task(
                conn,
                identity,
                tid,
                resource=Resource.EXECUTION,
                operation=Operation.READ,
            )
            return self._executions.in_flight_for_task(conn, task_id=tid, limit=64)

    def get_owned_resource(
        self, session_token: object, *, resource: object, resource_id: object
    ) -> dict[str, Any]:
        kind = self._as_owned_resource(resource)
        identity = self.authenticate(session_token)
        rid = self._as_id(resource_id, kind)
        self._permit(identity, kind, Operation.READ)
        with self._db.transaction() as conn:
            row = self._owned.get_owned(
                conn, resource=kind, user_id=identity.user_id, resource_id=rid
            )
        if row is None:
            self._deny(identity, kind, Operation.READ, DenyReason.RESOURCE_NOT_OWNED)
        return row

    def list_owned_resources(
        self,
        session_token: object,
        *,
        resource: object,
        task_id: object,
        parent_id: object | None = None,
    ) -> list[dict[str, Any]]:
        kind = self._as_owned_resource(resource)
        identity = self.authenticate(session_token)
        tid = self._as_id(task_id, Resource.TASK)
        self._permit(identity, kind, Operation.READ)
        pid = None if parent_id is None else self._as_id(parent_id, kind)
        with self._db.transaction() as conn:
            if self._tasks.get(conn, identity.user_id, tid) is None:
                self._deny(identity, kind, Operation.READ, DenyReason.RESOURCE_NOT_OWNED)
            try:
                return self._owned.list_owned_for_task(
                    conn,
                    resource=kind,
                    user_id=identity.user_id,
                    task_id=tid,
                    parent_id=pid,
                )
            except UnsupportedOwnedResource:
                # Never let an internal storage error escape the boundary.
                self._deny(identity, kind, Operation.READ, DenyReason.UNSUPPORTED_FILTER)

    def append_provenance_event(
        self,
        session_token: object,
        *,
        resource: object,
        resource_id: object,
        event_type: str,
        actor: str = AUTHORIZATION_ACTOR,
        detail: dict[str, Any] | None = None,
    ) -> int:
        """Append a provenance event, deriving ownership context from the target.

        The caller names the resource it acted on and never a task id. The task
        link is resolved from storage, so an event cannot be filed against
        another user's task by supplying that task's id.
        """

        kind = self._as_resource(resource)
        identity = self.authenticate(session_token)
        rid = self._as_id(resource_id, kind)
        self._permit(identity, kind, Operation.APPEND)
        with self._db.transaction() as conn:
            if kind is Resource.TASK:
                owned = self._tasks.get(conn, identity.user_id, rid) is not None
                task_id: int | None = rid
                execution_id: int | None = None
            else:
                owned = (
                    self._owned.get_owned(
                        conn, resource=kind, user_id=identity.user_id, resource_id=rid
                    )
                    is not None
                )
                task_id = None
                execution_id = rid
            if not owned:
                self._deny(identity, kind, Operation.APPEND, DenyReason.RESOURCE_NOT_OWNED)
            return self._owned.record_provenance(
                conn,
                task_id=task_id,
                execution_id=execution_id,
                event_type=event_type,
                actor=actor,
                detail=detail,
            )

    def authorize_tool_invocation(
        self,
        session_token: object,
        *,
        tool_name: object,
        resource: object,
        resource_id: object,
    ) -> Decision:
        """Answer whether a tool may be invoked. Never dispatches anything.

        Both halves of the question are answered here: the actor must own the
        target resource, and the capability must be permitted and granted. A
        grant alone is not enough, which is what stops a cross-resource
        authorization attempt.
        """

        kind = self._as_resource(resource)
        identity = self.authenticate(session_token)
        rid = self._as_id(resource_id, kind)
        with self._db.transaction() as conn:
            if kind is Resource.TASK:
                owned = self._tasks.get(conn, identity.user_id, rid) is not None
            else:
                owned = (
                    self._owned.get_owned(
                        conn, resource=kind, user_id=identity.user_id, resource_id=rid
                    )
                    is not None
                )
        if not owned:
            self._deny(identity, kind, Operation.INVOKE, DenyReason.RESOURCE_NOT_OWNED)

        decision = decide_tool_invocation(
            identity_id=identity.user_id,
            tool_name=tool_name,
            resource=kind,
            resource_id=rid,
            grants=self._tool_grants,
        )
        if not decision.allowed:
            logger.warning(
                "authorization denied user_id=%s resource=%s operation=%s reason=%s",
                identity.user_id,
                kind.value,
                Operation.INVOKE.value,
                decision.reason.value,
            )
        return decision

    def require_tool_invocation(
        self,
        session_token: object,
        *,
        tool_name: object,
        resource: object,
        resource_id: object,
    ) -> None:
        """Raise unless an invocation is authorized. The gate Phase 09 must call."""

        decision = self.authorize_tool_invocation(
            session_token, tool_name=tool_name, resource=resource, resource_id=resource_id
        )
        if not decision.allowed:
            raise PermissionDenied(decision.reason)

    @staticmethod
    def _as_resource(resource: object) -> Resource:
        if not isinstance(resource, Resource):
            raise InvalidAuthorizationRequest(DenyReason.UNKNOWN_RESOURCE)
        return resource

    @staticmethod
    def _as_owned_resource(resource: object) -> Resource:
        kind = AuthorizationService._as_resource(resource)
        if kind in OWNERSHIP_UNDECIDED:
            # The schema gives this resource no owner, so there is nothing to
            # check a grant against. Denied by name rather than treated as
            # unknown, because the gap is a deferred decision, not a typo.
            raise PermissionDenied(DenyReason.RESOURCE_OWNERSHIP_UNDECIDED)
        try:
            owned_table_for(kind)
        except UnsupportedOwnedResource as exc:
            raise InvalidAuthorizationRequest(DenyReason.UNKNOWN_RESOURCE) from exc
        return kind

    @staticmethod
    def _as_id(value: object, kind: Resource) -> int:
        if not is_valid_resource_id(value):
            logger.debug("authorization rejected malformed id for resource=%s", kind.value)
            raise InvalidAuthorizationRequest(DenyReason.MALFORMED_RESOURCE_ID)
        return value

    def _permit(self, identity: Identity, resource: Resource, operation: Operation) -> None:
        decision = decide_operation(
            identity_id=identity.user_id, resource=resource, operation=operation
        )
        if not decision.allowed:
            self._deny(identity, resource, operation, decision.reason)

    def _require_owned_task(
        self,
        conn: sqlite3.Connection,
        identity: Identity,
        task_id: int,
        *,
        resource: Resource,
        operation: Operation,
    ) -> None:
        """Deny unless ``task_id`` is a task ``identity`` owns.

        Takes the caller's open connection rather than opening one, because the
        whole point is that this check and the write it guards commit or roll back
        together. Re-reading ownership in a second transaction would leave a window
        where a delete between the two leaves a write authorized against nothing.
        """

        if self._tasks.get(conn, identity.user_id, task_id) is None:
            self._deny(identity, resource, operation, DenyReason.RESOURCE_NOT_OWNED)

    def _deny(
        self,
        identity: Identity,
        resource: Resource,
        operation: Operation,
        reason: DenyReason,
    ) -> NoReturn:
        logger.warning(
            "authorization denied user_id=%s resource=%s operation=%s reason=%s",
            identity.user_id,
            resource.value,
            operation.value,
            reason.value,
        )
        if reason in _IDENTITY_REASONS:
            raise AuthorizationError(reason)
        if reason in _MALFORMED_REASONS:
            raise InvalidAuthorizationRequest(reason)
        raise PermissionDenied(reason)
