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

import logging
from typing import Any, NoReturn

from atlas.auth.service import AuthService
from atlas.security.errors import (
    AuthorizationError,
    InvalidAuthorizationRequest,
    PermissionDenied,
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
from atlas.storage.owned_resources import (
    OwnedResourceRepo,
    UnsupportedOwnedResource,
    owned_table_for,
)
from atlas.storage.repositories import TaskRepo

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


class AuthorizationService:
    """Owner-scoped, operation-scoped, deny-by-default access to user data."""

    def __init__(
        self,
        db: Database,
        auth: AuthService,
        *,
        identities: IdentityResolver | None = None,
        tasks: TaskRepo | None = None,
        owned: OwnedResourceRepo | None = None,
        tool_grants: ToolGrantSource | None = None,
    ) -> None:
        self._db = db
        self._auth = auth
        self._identities = identities or IdentityResolver(db, auth)
        self._tasks = tasks or TaskRepo()
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
