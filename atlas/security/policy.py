"""Pure authorization policy: identity, operation, ownership, and tool decisions.

This module contains no I/O, no database access, and no authentication logic.
It answers one question deterministically — "is this actor permitted to perform
this operation on this resource?" — and it answers DENY whenever anything is
missing, unknown, or unresolvable.

Design rules enforced here:

* Deny by default. An operation absent from :data:`PERMITTED_OPERATIONS` is
  denied even when the operation name is a well-formed known enum member.
* No roles and no elevation path. Ownership is the only grant; there is no
  attribute an actor can change to widen their own access.
* The policy never invents ownership. A resource whose ownership is not
  established by the schema is denied by name (:data:`Resource.EVALUATION_RUN`).
* Tool authorization is a decision only. It never dispatches, imports, or
  executes anything.

Actor vocabulary (``user``/``planner``/``executor``/``verifier``/``recovery``)
is deliberately not modelled here; see the unresolved contradiction C-06 in
``docs/UI_ARCHITECTURE.md``. This layer records no provenance events for that
reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Protocol, Sequence, TypeGuard


class Resource(str, Enum):
    """Resource kinds that authorization understands."""

    TASK = "task"
    PLAN = "plan"
    PLAN_STEP = "plan_step"
    EXECUTION = "execution"
    ARTIFACT = "artifact"
    VERIFICATION = "verification"
    FAILURE = "failure"
    RECOVERY_ATTEMPT = "recovery_attempt"
    PROVENANCE_EVENT = "provenance_event"
    EVALUATION_RUN = "evaluation_run"


class Operation(str, Enum):
    """Operation kinds that authorization understands."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    APPEND = "append"
    INVOKE = "invoke"


class DenyReason(str, Enum):
    """Stable internal classification for every authorization outcome."""

    ALLOWED = "allowed"
    MISSING_IDENTITY = "missing_identity"
    INVALID_IDENTITY = "invalid_identity"
    MALFORMED_RESOURCE_ID = "malformed_resource_id"
    UNKNOWN_RESOURCE = "unknown_resource"
    UNKNOWN_OPERATION = "unknown_operation"
    UNSUPPORTED_FILTER = "unsupported_filter"
    OPERATION_NOT_PERMITTED = "operation_not_permitted"
    RESOURCE_NOT_FOUND = "resource_not_found"
    RESOURCE_NOT_OWNED = "resource_not_owned"
    RESOURCE_OWNERSHIP_UNDECIDED = "resource_ownership_undecided"
    DUPLICATE_EXECUTION = "duplicate_execution"
    TOOL_NO_REGISTRY = "tool_no_registry"
    TOOL_UNKNOWN = "tool_unknown"
    TOOL_NO_GRANT = "tool_no_grant"
    TOOL_CAPABILITY_PROHIBITED = "tool_capability_prohibited"


#: Operations permitted to an authenticated owner. Anything not listed is denied.
#: The list grows only when an enforcement point for the operation exists in this
#: codebase, and each addition names the phase that added it:
#:
#: * Phase 11 added ``PLAN.CREATE`` and ``PLAN_STEP.APPEND`` for
#:   :meth:`~atlas.security.service.AuthorizationService.create_plan`, which
#:   persists a validated or rejected plan and its steps in the transaction that
#:   checked ownership of the task.
#: * Phase 12 added ``TASK.UPDATE`` for the task status the executor writes, and
#:   ``EXECUTION.UPDATE`` for closing a dispatch row the executor already opened.
#:   ``EXECUTION.APPEND`` and ``PLAN_STEP.UPDATE`` were already permitted, but
#:   nothing wrote them before; the enforcement points now exist.
#:
#: ``UPDATE`` remains absent for every resource Phase 12 does not own. A caller
#: still cannot edit a plan, an artifact, a verification, or a failure, and
#: ``create_plan`` is the only path that writes a plan row.
PERMITTED_OPERATIONS: MappingProxyType[Resource, frozenset[Operation]] = MappingProxyType(
    {
        Resource.TASK: frozenset(
            {
                Operation.CREATE,
                Operation.READ,
                Operation.DELETE,
                Operation.APPEND,
                Operation.UPDATE,
            }
        ),
        Resource.PLAN: frozenset({Operation.READ, Operation.CREATE}),
        Resource.PLAN_STEP: frozenset({Operation.READ, Operation.APPEND, Operation.UPDATE}),
        Resource.EXECUTION: frozenset(
            {Operation.READ, Operation.APPEND, Operation.UPDATE}
        ),
        Resource.ARTIFACT: frozenset({Operation.READ}),
        Resource.VERIFICATION: frozenset({Operation.READ}),
        Resource.FAILURE: frozenset({Operation.READ}),
        Resource.RECOVERY_ATTEMPT: frozenset({Operation.READ}),
        Resource.PROVENANCE_EVENT: frozenset({Operation.READ}),
        Resource.EVALUATION_RUN: frozenset(),
    }
)

#: Resource kinds whose ownership the current schema cannot establish.
#: ``evaluation_runs`` has no owner column and no relationship to a user, so
#: there is nothing to check against. The decision "global research data or
#: user-owned" is explicitly deferred by ``docs/STORAGE_REVIEW.md`` section 12.
#: Until that decision is made the only safe answer is denial.
OWNERSHIP_UNDECIDED: frozenset[Resource] = frozenset({Resource.EVALUATION_RUN})

#: Capability names that can never be granted to any actor, at any time, by any
#: grant source. Enforced before grant lookup so no future Phase 09 registry can
#: widen them by accident. Spellings are already normalized for
#: :func:`normalize_tool_name` — no separators, lowercase.
PROHIBITED_TOOL_CAPABILITIES: frozenset[str] = frozenset(
    {
        "arbitrarycode",
        "eval",
        "exec",
        "filesystem",
        "http",
        "network",
        "process",
        "python",
        "pythoneval",
        "shell",
        "ssh",
        "subprocess",
    }
)

MAX_RESOURCE_ID = 2**63 - 1


@dataclass(frozen=True)
class Decision:
    """An authorization outcome. ``allowed`` is False for every non-allow reason."""

    allowed: bool
    reason: DenyReason

    @classmethod
    def allow(cls) -> Decision:
        return cls(allowed=True, reason=DenyReason.ALLOWED)

    @classmethod
    def deny(cls, reason: DenyReason) -> Decision:
        return cls(allowed=False, reason=reason)


@dataclass(frozen=True)
class ToolGrant:
    """An explicit grant of one named capability.

    ``scope`` is either ``None`` (applies to the actor's own resources) or
    ``"task:<id>"``. Grants are read-only inputs; this phase creates none.
    """

    tool_name: str
    scope: str | None = None


class ToolGrantSource(Protocol):
    """Read-only view of the grants a user holds. Implemented in Phase 09."""

    @property
    def registry_ready(self) -> bool:
        """False while no tool registry exists, so denial can say why."""

    def grants_for(self, user_id: int) -> Sequence[ToolGrant]:
        """Grants held by ``user_id``. Must never return grants for another user."""


class NoToolGrants:
    """The only grant source that exists in Phase 08: no registry, no grants."""

    @property
    def registry_ready(self) -> bool:
        return False

    def grants_for(self, user_id: int) -> Sequence[ToolGrant]:
        return ()


def is_valid_resource_id(value: object) -> TypeGuard[int]:
    """True only for a concrete positive SQLite row id.

    ``bool`` is rejected explicitly: ``True`` is an ``int`` in Python and would
    otherwise resolve to row 1.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return 0 < value <= MAX_RESOURCE_ID


def is_valid_identity_id(value: object) -> TypeGuard[int]:
    """True only for a concrete positive user id."""

    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return 0 < value <= MAX_RESOURCE_ID


def _as_identity_id(value: object) -> int:
    """Narrow a value already accepted by :func:`is_valid_identity_id`."""

    if not is_valid_identity_id(value):
        raise TypeError("identity id is not a valid row id")
    return int(value)


def decide_operation(
    *,
    identity_id: object,
    resource: object,
    operation: object,
) -> Decision:
    """Decide a non-tool operation without touching storage.

    Ownership is *not* decided here — it needs a lookup. Callers must treat
    :data:`DenyReason.ALLOWED` from this function as "operation is defined and
    the actor is authenticated", never as "access is granted".
    """

    if not is_valid_identity_id(identity_id):
        return Decision.deny(DenyReason.MISSING_IDENTITY)
    if not isinstance(resource, Resource):
        return Decision.deny(DenyReason.UNKNOWN_RESOURCE)
    if resource in OWNERSHIP_UNDECIDED:
        return Decision.deny(DenyReason.RESOURCE_OWNERSHIP_UNDECIDED)
    if not isinstance(operation, Operation):
        return Decision.deny(DenyReason.UNKNOWN_OPERATION)
    if operation not in PERMITTED_OPERATIONS[resource]:
        return Decision.deny(DenyReason.OPERATION_NOT_PERMITTED)
    return Decision.allow()


def normalize_tool_name(value: object) -> str | None:
    """Return a comparable tool name, or None when the input is not a name.

    Case, surrounding space, and separators are removed so that ``"Sub-Process"``
    and ``"sub_process"`` cannot be used to slip past
    :data:`PROHIBITED_TOOL_CAPABILITIES`.
    """

    if not isinstance(value, str):
        return None
    collapsed = "".join(character for character in value.lower() if character.isalnum())
    return collapsed or None


def decide_tool_invocation(
    *,
    identity_id: object,
    tool_name: object,
    resource: object,
    resource_id: object | None = None,
    grants: ToolGrantSource | None = None,
) -> Decision:
    """Decide whether an actor may invoke a capability. Never executes anything.

    Ownership of ``resource_id`` is *not* decided here; that needs a lookup and
    belongs to :class:`~atlas.security.service.AuthorizationService`. This
    function is the capability half of the question: is this a known, permitted,
    granted capability for a resource kind that has an established owner?

    The answer is ``TOOL_NO_REGISTRY`` in Phase 08 because no registry and no
    grant can exist yet. The full ordering is implemented now so that Phase 09
    only has to supply a real grant source.
    """

    if not is_valid_identity_id(identity_id):
        return Decision.deny(DenyReason.MISSING_IDENTITY)

    normalized = normalize_tool_name(tool_name)
    if normalized is None:
        return Decision.deny(DenyReason.TOOL_UNKNOWN)
    if normalized in PROHIBITED_TOOL_CAPABILITIES:
        return Decision.deny(DenyReason.TOOL_CAPABILITY_PROHIBITED)
    if not isinstance(resource, Resource):
        return Decision.deny(DenyReason.UNKNOWN_RESOURCE)
    if resource in OWNERSHIP_UNDECIDED:
        return Decision.deny(DenyReason.RESOURCE_OWNERSHIP_UNDECIDED)

    source = grants if grants is not None else NoToolGrants()
    if not source.registry_ready:
        return Decision.deny(DenyReason.TOOL_NO_REGISTRY)

    user_id = _as_identity_id(identity_id)
    for grant in source.grants_for(user_id):
        if normalize_tool_name(grant.tool_name) != normalized:
            continue
        if grant.scope is None:
            return Decision.allow()
        if grant.scope == f"task:{resource_id}":
            return Decision.allow()
    return Decision.deny(DenyReason.TOOL_NO_GRANT)
