"""Phase 08 authorization tests.

These tests establish security invariants, not coverage of happy paths. The
negative cases are the point: an authenticated user must not reach another
user's rows, an absent or unknown permission must deny, and no failure mode may
convert into an allow.

The suite exercises the boundary the way the future UI and CLI will: by holding
a real session token and calling the service. There is no UI, so nothing here
depends on one.
"""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path
from typing import Any, Sequence

import pytest

from atlas.auth.service import AuthService
from atlas.security.errors import (
    AuthorizationError,
    InvalidAuthorizationRequest,
    PermissionDenied,
    Unauthenticated,
)
from atlas.security.identity import Identity, IdentityResolver
from atlas.security.policy import (
    PERMITTED_OPERATIONS,
    PROHIBITED_TOOL_CAPABILITIES,
    Decision,
    DenyReason,
    NoToolGrants,
    Operation,
    Resource,
    ToolGrant,
    decide_operation,
    decide_tool_invocation,
)
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.owned_resources import (
    _OWNED_TABLES,
    OwnedResourceRepo,
    UnsupportedOwnedResource,
)
from atlas.storage.repositories import TaskRepo, UserRepo

PASSWORD = "correct-horse-battery"

DESCENDANTS = (
    Resource.PLAN,
    Resource.PLAN_STEP,
    Resource.EXECUTION,
    Resource.ARTIFACT,
    Resource.VERIFICATION,
    Resource.FAILURE,
    Resource.RECOVERY_ATTEMPT,
)

LISTABLE = DESCENDANTS + (Resource.PROVENANCE_EVENT,)


# Fixtures and helpers


@pytest.fixture
def authz(db: Database, auth: AuthService) -> AuthorizationService:
    return AuthorizationService(db, auth)


@pytest.fixture
def two_users(auth: AuthService) -> tuple[int, int]:
    alice = int(_register(auth, "alice")["id"])
    bob = int(_register(auth, "bob")["id"])
    return alice, bob


def _register(auth: AuthService, username: str) -> dict[str, Any]:
    return auth.register(username, PASSWORD)


def _token(auth: AuthService, username: str) -> str:
    return str(auth.login(username, PASSWORD)["token"])


def _last_id(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"])


def _count(db: Database, table: str) -> int:
    with db.transaction() as conn:
        return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


def _event_id(db: Database, event_type: str) -> int:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT id FROM provenance_events WHERE event_type = ?", (event_type,)
        ).fetchone()
    return int(row["id"])


def _seed_chain(db: Database, user_id: int) -> dict[str, int]:
    """Create one full task -> ... -> artifact chain directly through storage.

    Direct inserts stand in for the phases that will own these writes (11-16).
    They also let a test create rows that a future bug might leave unowned.
    """

    ids: dict[str, int] = {}
    with db.transaction() as conn:
        ids["task"] = TaskRepo().create(conn, user_id=user_id, title="t", goal="g")
        conn.execute(
            "INSERT INTO plans (task_id, plan_json, created_at, updated_at) VALUES (?,?,?,?)",
            (ids["task"], "{}", "t", "t"),
        )
        ids["plan"] = _last_id(conn)
        conn.execute(
            "INSERT INTO plan_steps (plan_id, position, action, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (ids["plan"], 1, "do a thing", "t", "t"),
        )
        ids["plan_step"] = _last_id(conn)
        conn.execute("INSERT INTO executions (task_id) VALUES (?)", (ids["task"],))
        execution_id = _last_id(conn)
        ids["execution"] = execution_id
        conn.execute(
            "INSERT INTO artifacts (execution_id, name, created_at) VALUES (?,?,?)",
            (execution_id, "out.txt", "t"),
        )
        ids["artifact"] = _last_id(conn)
        conn.execute(
            "INSERT INTO verifications (execution_id, verifier, result, created_at) "
            "VALUES (?,?,?,?)",
            (execution_id, "deterministic", "PASS", "t"),
        )
        ids["verification"] = _last_id(conn)
        conn.execute(
            "INSERT INTO failures (execution_id, category, created_at) VALUES (?,?,?)",
            (execution_id, "runtime", "t"),
        )
        ids["failure"] = _last_id(conn)
        conn.execute(
            "INSERT INTO recovery_attempts (execution_id, attempt_no, created_at) "
            "VALUES (?,?,?)",
            (execution_id, 1, "t"),
        )
        ids["recovery_attempt"] = _last_id(conn)
    return ids


class _FakeGrants:
    """A grant source that returns only the grants it was handed, per user."""

    def __init__(
        self, grants: dict[int, Sequence[ToolGrant]], *, ready: bool = True
    ) -> None:
        self._grants = grants
        self._ready = ready

    @property
    def registry_ready(self) -> bool:
        return self._ready

    def grants_for(self, user_id: int) -> Sequence[ToolGrant]:
        return self._grants.get(user_id, ())


# A. Identity


def test_valid_session_token_yields_identity(
    authz: AuthorizationService, auth: AuthService
) -> None:
    user = _register(auth, "alice")
    identity = authz.authenticate(_token(auth, "alice"))
    assert identity.user_id == user["id"]
    assert identity.username == "alice"
    assert identity.session_id > 0


@pytest.mark.parametrize("bad", [None, "", "   ", 12345, b"bytes", ["token"]])
def test_missing_or_malformed_identity_is_denied(
    authz: AuthorizationService, bad: object
) -> None:
    with pytest.raises(Unauthenticated) as caught:
        authz.authenticate(bad)
    assert caught.value.reason in {
        DenyReason.MISSING_IDENTITY,
        DenyReason.INVALID_IDENTITY,
    }
    assert str(caught.value) == "access denied"


def test_unknown_session_token_is_denied(authz: AuthorizationService) -> None:
    with pytest.raises(Unauthenticated):
        authz.authenticate("token-that-was-never-issued")


def test_expired_session_is_denied(
    authz: AuthorizationService, auth: AuthService, db: Database
) -> None:
    _register(auth, "alice")
    token = _token(auth, "alice")
    with db.transaction() as conn:
        conn.execute("UPDATE sessions SET expires_at = ?", ("2000-01-01T00:00:00+00:00",))
    with pytest.raises(Unauthenticated):
        authz.authenticate(token)


def test_revoked_session_is_denied(authz: AuthorizationService, auth: AuthService) -> None:
    _register(auth, "alice")
    token = _token(auth, "alice")
    assert auth.logout(token) is True
    with pytest.raises(Unauthenticated):
        authz.authenticate(token)


def test_unauthenticated_actor_cannot_read_a_protected_resource(
    authz: AuthorizationService, auth: AuthService
) -> None:
    _register(auth, "alice")
    task_id = authz.create_task(_token(auth, "alice"), title="a", goal="g")["id"]
    with pytest.raises(Unauthenticated):
        authz.get_task(None, task_id)
    with pytest.raises(Unauthenticated):
        authz.list_tasks("")
    with pytest.raises(Unauthenticated):
        authz.delete_task("forged-token", task_id)


def test_no_public_service_method_accepts_a_user_id(authz: AuthorizationService) -> None:
    """The actor must never be nominable by a request."""

    for name, member in inspect.getmembers(AuthorizationService, inspect.isfunction):
        if name.startswith("_"):
            continue
        parameters = inspect.signature(member).parameters
        assert "user_id" not in parameters, f"{name} accepts a caller-supplied user_id"
        assert "actor_id" not in parameters, f"{name} accepts a caller-supplied actor_id"


def test_identity_resolver_rejects_a_user_id_in_place_of_a_token(
    db: Database, auth: AuthService
) -> None:
    resolver = IdentityResolver(db, auth)
    user = _register(auth, "alice")
    with pytest.raises(Unauthenticated):
        resolver.from_session_token(user["id"])


# B. Ownership


def test_owner_can_read_own_task(authz: AuthorizationService, auth: AuthService) -> None:
    _register(auth, "alice")
    token = _token(auth, "alice")
    created = authz.create_task(token, title="mine", goal="do it")
    assert authz.get_task(token, created["id"])["id"] == created["id"]


def test_non_owner_cannot_read_a_task_by_id(
    authz: AuthorizationService, auth: AuthService
) -> None:
    _register(auth, "alice")
    _register(auth, "bob")
    task_id = authz.create_task(_token(auth, "alice"), title="a", goal="g")["id"]
    with pytest.raises(PermissionDenied):
        authz.get_task(_token(auth, "bob"), task_id)


def test_task_listing_never_leaks_another_users_tasks(
    authz: AuthorizationService, auth: AuthService
) -> None:
    _register(auth, "alice")
    _register(auth, "bob")
    authz.create_task(_token(auth, "alice"), title="a", goal="g")
    authz.create_task(_token(auth, "bob"), title="b", goal="g")
    assert [row["title"] for row in authz.list_tasks(_token(auth, "alice"))] == ["a"]
    assert [row["title"] for row in authz.list_tasks(_token(auth, "bob"))] == ["b"]


def test_non_owner_cannot_delete_a_task(
    authz: AuthorizationService, auth: AuthService, db: Database
) -> None:
    _register(auth, "alice")
    _register(auth, "bob")
    task_id = authz.create_task(_token(auth, "alice"), title="a", goal="g")["id"]
    with pytest.raises(PermissionDenied):
        authz.delete_task(_token(auth, "bob"), task_id)
    assert _count(db, "tasks") == 1
    authz.delete_task(_token(auth, "alice"), task_id)
    assert _count(db, "tasks") == 0


def test_denied_lookup_is_indistinguishable_from_a_missing_one(
    authz: AuthorizationService, auth: AuthService
) -> None:
    """No resource-existence oracle: same type, same message."""

    _register(auth, "alice")
    _register(auth, "bob")
    task_id = authz.create_task(_token(auth, "alice"), title="a", goal="g")["id"]
    bob = _token(auth, "bob")

    with pytest.raises(AuthorizationError) as not_owned:
        authz.get_task(bob, task_id)
    with pytest.raises(AuthorizationError) as missing:
        authz.get_task(bob, task_id + 9999)

    assert type(not_owned.value) is type(missing.value)
    assert str(not_owned.value) == str(missing.value) == "access denied"
    assert not_owned.value.external_message == missing.value.external_message


@pytest.mark.parametrize("kind", DESCENDANTS)
def test_non_owner_cannot_read_any_descendant_by_id(
    authz: AuthorizationService,
    auth: AuthService,
    db: Database,
    two_users: tuple[int, int],
    kind: Resource,
) -> None:
    ids = _seed_chain(db, two_users[0])
    with pytest.raises(PermissionDenied):
        authz.get_owned_resource(
            _token(auth, "bob"), resource=kind, resource_id=ids[kind.value]
        )
    assert authz.get_owned_resource(
        _token(auth, "alice"), resource=kind, resource_id=ids[kind.value]
    )


@pytest.mark.parametrize("kind", LISTABLE)
def test_non_owner_cannot_list_another_users_descendants(
    authz: AuthorizationService,
    auth: AuthService,
    db: Database,
    two_users: tuple[int, int],
    kind: Resource,
) -> None:
    ids = _seed_chain(db, two_users[0])
    authz.append_provenance_event(
        _token(auth, "alice"),
        resource=Resource.EXECUTION,
        resource_id=ids["execution"],
        event_type="execution.started",
    )
    with pytest.raises(PermissionDenied):
        authz.list_owned_resources(
            _token(auth, "bob"), resource=kind, task_id=ids["task"]
        )
    assert isinstance(
        authz.list_owned_resources(
            _token(auth, "alice"), resource=kind, task_id=ids["task"]
        ),
        list,
    )


def test_listing_narrows_to_the_requested_parent(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    ids = _seed_chain(db, two_users[0])
    token = _token(auth, "alice")
    assert len(
        authz.list_owned_resources(
            token, resource=Resource.ARTIFACT, task_id=ids["task"], parent_id=ids["execution"]
        )
    ) == 1
    assert (
        authz.list_owned_resources(
            token,
            resource=Resource.ARTIFACT,
            task_id=ids["task"],
            parent_id=ids["execution"] + 999,
        )
        == []
    )


def test_provenance_without_a_resolvable_owner_is_invisible_to_everyone(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    """A provenance event with no task and no execution has no resolvable owner."""

    ids = _seed_chain(db, two_users[0])
    with db.transaction() as conn:
        OwnedResourceRepo().record_provenance(
            conn, event_type="user.registered", actor="auth", detail={"user_id": 1}
        )
    orphan = _event_id(db, "user.registered")

    # Unreadable by id, for either user.
    for who in ("alice", "bob"):
        with pytest.raises(PermissionDenied):
            authz.get_owned_resource(
                _token(auth, who), resource=Resource.PROVENANCE_EVENT, resource_id=orphan
            )

    # Absent from the owner's task listing, because it belongs to no task.
    listed = authz.list_owned_resources(
        _token(auth, "alice"), resource=Resource.PROVENANCE_EVENT, task_id=ids["task"]
    )
    assert orphan not in [row["id"] for row in listed]

    # And the non-owner cannot list the task at all.
    with pytest.raises(PermissionDenied):
        authz.list_owned_resources(
            _token(auth, "bob"), resource=Resource.PROVENANCE_EVENT, task_id=ids["task"]
        )


def test_provenance_append_derives_ownership_instead_of_trusting_the_caller(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    ids = _seed_chain(db, two_users[0])
    event_id = authz.append_provenance_event(
        _token(auth, "alice"),
        resource=Resource.EXECUTION,
        resource_id=ids["execution"],
        event_type="execution.finished",
    )
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT task_id, execution_id FROM provenance_events WHERE id = ?", (event_id,)
        ).fetchone()
    assert row["execution_id"] == ids["execution"]
    assert row["task_id"] is None


def test_provenance_append_onto_another_users_execution_is_denied(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    ids = _seed_chain(db, two_users[0])
    before = _count(db, "provenance_events")
    with pytest.raises(PermissionDenied):
        authz.append_provenance_event(
            _token(auth, "bob"),
            resource=Resource.EXECUTION,
            resource_id=ids["execution"],
            event_type="execution.finished",
        )
    assert _count(db, "provenance_events") == before


def test_provenance_append_onto_own_task_is_allowed(
    authz: AuthorizationService, auth: AuthService, db: Database
) -> None:
    _register(auth, "alice")
    token = _token(auth, "alice")
    task_id = authz.create_task(token, title="a", goal="g")["id"]
    event_id = authz.append_provenance_event(
        token, resource=Resource.TASK, resource_id=task_id, event_type="task.created"
    )
    assert event_id > 0
    events = authz.list_owned_resources(
        token, resource=Resource.PROVENANCE_EVENT, task_id=task_id
    )
    assert [event["event_type"] for event in events] == ["task.created"]


def test_provenance_append_onto_a_provenance_event_is_denied(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    ids = _seed_chain(db, two_users[0])
    authz.append_provenance_event(
        _token(auth, "alice"),
        resource=Resource.TASK,
        resource_id=ids["task"],
        event_type="task.created",
    )
    event_id = _event_id(db, "task.created")
    with pytest.raises(PermissionDenied) as caught:
        authz.append_provenance_event(
            _token(auth, "alice"),
            resource=Resource.PROVENANCE_EVENT,
            resource_id=event_id,
            event_type="nested",
        )
    assert caught.value.reason is DenyReason.OPERATION_NOT_PERMITTED


def test_task_ownership_cannot_be_reassigned_by_any_repository() -> None:
    """A4 guard: no code path moves a task to another user."""

    for repo_class in (TaskRepo, UserRepo, OwnedResourceRepo):
        for name, member in inspect.getmembers(repo_class, inspect.isfunction):
            if name.startswith("_"):
                continue
            source = inspect.getsource(member).upper()
            assert "UPDATE TASKS SET USER_ID" not in source, (
                f"{repo_class.__name__}.{name} can reassign task ownership"
            )
    assert not hasattr(TaskRepo, "update_owner")
    assert not hasattr(TaskRepo, "transfer")


# C. Operations


def test_authentication_does_not_imply_update_permission(
    authz: AuthorizationService, auth: AuthService
) -> None:
    """Authentication decides who you are, not what you may change.

    Rewritten in Phase 12. The claim is no longer "there is no update anywhere" --
    ``TASK.UPDATE`` and ``PLAN_STEP.UPDATE`` were added deliberately, each with an
    enforcement point in
    :class:`~atlas.security.service.AuthorizationService`. What has to keep holding
    is that an update is permitted only where one of those enforcement points
    exists, and that the decision comes from the operation table rather than from
    the caller having a session.
    """

    _register(auth, "alice")
    token = _token(auth, "alice")
    task = authz.create_task(token, title="a", goal="g")
    assert authz.get_task(token, task["id"])
    for resource in (
        Resource.PLAN,
        Resource.ARTIFACT,
        Resource.VERIFICATION,
        Resource.FAILURE,
    ):
        decision = decide_operation(
            identity_id=1, resource=resource, operation=Operation.UPDATE
        )
        assert not decision.allowed
        assert decision.reason is DenyReason.OPERATION_NOT_PERMITTED


def test_only_the_phase_12_updates_are_permitted() -> None:
    """The whole set of update permissions, enumerated.

    Written as an equality against the complete set rather than as three passing
    assertions, so adding an ``UPDATE`` anywhere else has to be a deliberate edit
    here instead of something a reviewer has to notice.

    Three resources are updatable, and each one is updatable for a reason that is
    not "it seemed reasonable":

    * ``TASK`` -- the executor moves a task through the lifecycle.
    * ``PLAN_STEP`` -- the executor records a step's outcome.
    * ``EXECUTION`` -- the executor closes a dispatch row it opened.
    """

    permitted_updates = {
        resource
        for resource, operations in PERMITTED_OPERATIONS.items()
        if Operation.UPDATE in operations
    }
    assert permitted_updates == frozenset(
        {Resource.TASK, Resource.PLAN_STEP, Resource.EXECUTION}
    )


@pytest.mark.parametrize(
    ("resource", "operation"),
    [
        # TASK.UPDATE and PLAN_STEP.UPDATE moved out of this list in Phase 12;
        # they are pinned by test_only_the_phase_12_updates_are_permitted. Every
        # other denial below is unchanged and must keep failing closed.
        (Resource.ARTIFACT, Operation.CREATE),
        (Resource.ARTIFACT, Operation.DELETE),
        (Resource.PLAN, Operation.DELETE),
        (Resource.PLAN, Operation.UPDATE),
        (Resource.PROVENANCE_EVENT, Operation.APPEND),
        (Resource.VERIFICATION, Operation.DELETE),
        (Resource.FAILURE, Operation.UPDATE),
        (Resource.RECOVERY_ATTEMPT, Operation.DELETE),
    ],
)
def test_ungranted_operations_are_denied(resource: Resource, operation: Operation) -> None:
    decision = decide_operation(identity_id=1, resource=resource, operation=operation)
    assert not decision.allowed
    assert decision.reason in {
        DenyReason.OPERATION_NOT_PERMITTED,
        DenyReason.UNKNOWN_OPERATION,
    }


@pytest.mark.parametrize("bad_operation", ["read", "READ", None, 7, object()])
def test_malformed_operation_is_denied(bad_operation: object) -> None:
    decision = decide_operation(
        identity_id=1, resource=Resource.TASK, operation=bad_operation
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.UNKNOWN_OPERATION


@pytest.mark.parametrize("bad_resource", ["task", "TASK", None, 7, object()])
def test_malformed_resource_kind_is_denied(bad_resource: object) -> None:
    decision = decide_operation(
        identity_id=1, resource=bad_resource, operation=Operation.READ
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.UNKNOWN_RESOURCE


@pytest.mark.parametrize("bad_identity", [None, 0, -1, True, "1", 1.5, object()])
def test_malformed_identity_is_denied(bad_identity: object) -> None:
    decision = decide_operation(
        identity_id=bad_identity, resource=Resource.TASK, operation=Operation.READ
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.MISSING_IDENTITY


@pytest.mark.parametrize(
    "bad_id", ["1", "abc", 0, -5, None, True, False, 1.5, 2**63, [], object()]
)
def test_malformed_resource_identifier_is_rejected_by_the_boundary(
    authz: AuthorizationService, auth: AuthService, bad_id: object
) -> None:
    _register(auth, "alice")
    token = _token(auth, "alice")
    with pytest.raises(InvalidAuthorizationRequest) as caught:
        authz.get_task(token, bad_id)
    assert caught.value.reason is DenyReason.MALFORMED_RESOURCE_ID
    assert str(caught.value) == "access denied"


def test_evaluation_runs_are_denied_by_name(
    authz: AuthorizationService, auth: AuthService, db: Database
) -> None:
    _register(auth, "alice")
    token = _token(auth, "alice")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO evaluation_runs (run_name, config_json, created_at) VALUES (?,?,?)",
            ("baseline", "{}", "t"),
        )
        run_id = _last_id(conn)

    decision = decide_operation(
        identity_id=1, resource=Resource.EVALUATION_RUN, operation=Operation.READ
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.RESOURCE_OWNERSHIP_UNDECIDED

    with pytest.raises(PermissionDenied) as caught:
        authz.get_owned_resource(
            token, resource=Resource.EVALUATION_RUN, resource_id=run_id
        )
    assert caught.value.reason is DenyReason.RESOURCE_OWNERSHIP_UNDECIDED
    assert "evaluation_runs" not in OwnedResourceRepo().owned_table_names()


def test_unsupported_filter_does_not_leak_an_internal_error(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    """A provenance event has no single direct parent, so the filter is refused."""

    ids = _seed_chain(db, two_users[0])
    with pytest.raises(InvalidAuthorizationRequest) as caught:
        authz.list_owned_resources(
            _token(auth, "alice"),
            resource=Resource.PROVENANCE_EVENT,
            task_id=ids["task"],
            parent_id=ids["execution"],
        )
    assert caught.value.reason is DenyReason.UNSUPPORTED_FILTER
    assert str(caught.value) == "access denied"


def test_task_resource_is_not_served_by_the_descendant_repository(
    authz: AuthorizationService, auth: AuthService
) -> None:
    _register(auth, "alice")
    token = _token(auth, "alice")
    task_id = authz.create_task(token, title="a", goal="g")["id"]
    with pytest.raises(InvalidAuthorizationRequest):
        authz.get_owned_resource(token, resource=Resource.TASK, resource_id=task_id)


# D. Tool permissions


def test_tool_authorization_is_a_decision_not_an_execution(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    ids = _seed_chain(db, two_users[0])
    before = _count(db, "executions")
    decision = authz.authorize_tool_invocation(
        _token(auth, "alice"),
        tool_name="read_file",
        resource=Resource.EXECUTION,
        resource_id=ids["execution"],
    )
    assert isinstance(decision, Decision)
    assert not decision.allowed
    assert decision.reason is DenyReason.TOOL_NO_REGISTRY
    assert _count(db, "executions") == before


@pytest.mark.parametrize("bad_name", [None, "", "   ", 5, [], object()])
def test_unknown_tool_name_is_denied(bad_name: object) -> None:
    decision = decide_tool_invocation(
        identity_id=1, tool_name=bad_name, resource=Resource.EXECUTION
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.TOOL_UNKNOWN


@pytest.mark.parametrize("name", sorted(PROHIBITED_TOOL_CAPABILITIES))
def test_prohibited_capability_classes_can_never_be_granted(name: str) -> None:
    """No grant source, however complete, may authorize these."""

    source = _FakeGrants({1: (ToolGrant(tool_name=name),)})
    decision = decide_tool_invocation(
        identity_id=1, tool_name=name, resource=Resource.EXECUTION, grants=source
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.TOOL_CAPABILITY_PROHIBITED


@pytest.mark.parametrize(
    "variant", ["SHELL", " shell ", "Sub-Process", "PYTHON", "file_system", "Network"]
)
def test_prohibited_names_are_matched_after_normalization(variant: str) -> None:
    decision = decide_tool_invocation(
        identity_id=1, tool_name=variant, resource=Resource.EXECUTION
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.TOOL_CAPABILITY_PROHIBITED


def test_missing_registry_denies_even_for_a_plausible_tool() -> None:
    decision = decide_tool_invocation(
        identity_id=1, tool_name="summarize", resource=Resource.EXECUTION
    )
    assert decision.reason is DenyReason.TOOL_NO_REGISTRY
    assert NoToolGrants().grants_for(1) == ()
    assert NoToolGrants().registry_ready is False


def test_tool_without_a_grant_is_denied() -> None:
    source = _FakeGrants({1: (ToolGrant(tool_name="other_tool"),)})
    decision = decide_tool_invocation(
        identity_id=1, tool_name="summarize", resource=Resource.EXECUTION, grants=source
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.TOOL_NO_GRANT


def test_tool_grant_is_scoped_to_the_user_holding_it(
    db: Database, auth: AuthService, two_users: tuple[int, int]
) -> None:
    """A grant held by another user authorizes nothing for this actor."""

    ids = _seed_chain(db, two_users[0])
    service = AuthorizationService(
        db, auth, tool_grants=_FakeGrants({two_users[1]: (ToolGrant("summarize"),)})
    )
    decision = service.authorize_tool_invocation(
        _token(auth, "alice"),
        tool_name="summarize",
        resource=Resource.EXECUTION,
        resource_id=ids["execution"],
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.TOOL_NO_GRANT


def test_explicit_grant_allows_the_decision() -> None:
    source = _FakeGrants({1: (ToolGrant(tool_name="summarize"),)})
    decision = decide_tool_invocation(
        identity_id=1, tool_name="summarize", resource=Resource.EXECUTION, grants=source
    )
    assert decision.allowed
    assert decision.reason is DenyReason.ALLOWED


def test_tool_authorization_respects_the_operation_policy() -> None:
    """A grant cannot widen the operation policy: no resource permits invoke."""

    source = _FakeGrants({1: (ToolGrant(tool_name="summarize"),)})
    for resource in Resource:
        permitted = PERMITTED_OPERATIONS[resource]
        assert Operation.INVOKE not in permitted, (
            f"{resource.value} permits invoke without a tool policy"
        )
    decision = decide_tool_invocation(
        identity_id=1,
        tool_name="summarize",
        resource=Resource.EVALUATION_RUN,
        grants=source,
    )
    assert not decision.allowed
    assert decision.reason is DenyReason.RESOURCE_OWNERSHIP_UNDECIDED


def test_task_scoped_grant_does_not_authorize_another_task(
    db: Database, auth: AuthService, two_users: tuple[int, int]
) -> None:
    ids = _seed_chain(db, two_users[0])
    service = AuthorizationService(
        db, auth, tool_grants=_FakeGrants({two_users[0]: (ToolGrant("summarize", "task:1"),)})
    )
    with pytest.raises(PermissionDenied):
        service.authorize_tool_invocation(
            _token(auth, "alice"),
            tool_name="summarize",
            resource=Resource.TASK,
            resource_id=ids["task"] + 500,
        )
    decision = service.authorize_tool_invocation(
        _token(auth, "alice"),
        tool_name="summarize",
        resource=Resource.TASK,
        resource_id=ids["task"],
    )
    assert decision.allowed


def test_tool_invocation_on_another_users_resource_is_denied(
    db: Database, auth: AuthService, two_users: tuple[int, int]
) -> None:
    """Cross-resource tool authorization attempt, with a valid grant in hand."""

    ids = _seed_chain(db, two_users[0])
    service = AuthorizationService(
        db, auth, tool_grants=_FakeGrants({two_users[1]: (ToolGrant("summarize"),)})
    )
    with pytest.raises(PermissionDenied):
        service.authorize_tool_invocation(
            _token(auth, "bob"),
            tool_name="summarize",
            resource=Resource.EXECUTION,
            resource_id=ids["execution"],
        )


def test_require_tool_invocation_raises_for_every_denial(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    ids = _seed_chain(db, two_users[0])
    token = _token(auth, "alice")
    with pytest.raises(PermissionDenied):
        authz.require_tool_invocation(
            token,
            tool_name="read_file",
            resource=Resource.EXECUTION,
            resource_id=ids["execution"],
        )
    with pytest.raises(PermissionDenied):
        authz.require_tool_invocation(
            token,
            tool_name="shell",
            resource=Resource.EXECUTION,
            resource_id=ids["execution"],
        )
    with pytest.raises(InvalidAuthorizationRequest):
        authz.require_tool_invocation(
            token,
            tool_name="read_file",
            resource=Resource.EXECUTION,
            resource_id="not-an-id",
        )
    with pytest.raises(Unauthenticated):
        authz.require_tool_invocation(
            "forged",
            tool_name="read_file",
            resource=Resource.EXECUTION,
            resource_id=ids["execution"],
        )


# E. Bypass attempts


def test_owned_repository_exposes_no_unscoped_read() -> None:
    """Structural: every descendant row read demands an owner."""

    row_reads = ("get_owned", "list_owned_for_task")
    for name in row_reads:
        member = getattr(OwnedResourceRepo, name)
        assert "user_id" in inspect.signature(member).parameters, (
            f"{name} has no owner predicate"
        )
    assert not hasattr(OwnedResourceRepo, "get")
    assert not hasattr(OwnedResourceRepo, "get_by_id")
    assert not hasattr(OwnedResourceRepo, "list_all")


def test_direct_repository_use_cannot_read_another_users_row(
    db: Database, two_users: tuple[int, int]
) -> None:
    """The repository scopes rows but is not the boundary; the service is.

    This records why the boundary cannot be pushed down into storage: the
    repository trusts the ``user_id`` it is handed, so only the service, which
    derives that id from a session token, is authoritative.
    """

    ids = _seed_chain(db, two_users[0])
    repo = OwnedResourceRepo()
    with db.transaction() as conn:
        assert (
            repo.get_owned(
                conn,
                resource=Resource.ARTIFACT,
                user_id=two_users[0],
                resource_id=ids["artifact"],
            )
            is not None
        )
        assert (
            repo.get_owned(
                conn,
                resource=Resource.ARTIFACT,
                user_id=two_users[1],
                resource_id=ids["artifact"],
            )
            is None
        )


def test_rows_written_by_a_future_phase_remain_owner_scoped(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    """A row inserted straight into storage is still unreachable cross-user."""

    ids = _seed_chain(db, two_users[1])
    with pytest.raises(PermissionDenied):
        authz.get_owned_resource(
            _token(auth, "alice"), resource=Resource.ARTIFACT, resource_id=ids["artifact"]
        )


def test_repeated_denials_never_escalate(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    ids = _seed_chain(db, two_users[0])
    bob = _token(auth, "bob")
    for _ in range(10):
        with pytest.raises(PermissionDenied):
            authz.get_owned_resource(
                bob, resource=Resource.ARTIFACT, resource_id=ids["artifact"]
            )
        with pytest.raises(PermissionDenied):
            authz.get_task(bob, ids["task"])
    assert authz.get_owned_resource(
        _token(auth, "alice"), resource=Resource.ARTIFACT, resource_id=ids["artifact"]
    )


def test_authorization_modules_import_nothing_that_executes() -> None:
    root = Path(__file__).resolve().parents[1] / "atlas"
    files = sorted((root / "security").glob("*.py")) + [
        root / "storage" / "owned_resources.py"
    ]
    forbidden = (
        "import subprocess",
        "from subprocess",
        "import socket",
        "import urllib",
        "import requests",
        "os.system",
        "os.popen",
        "eval(",
        "exec(",
        "pickle",
    )
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{path.name} references {token}"


def test_policy_layer_performs_no_io() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "atlas" / "security" / "policy.py"
    ).read_text(encoding="utf-8")
    for token in ("sqlite3", "Database", "import os", "open("):
        assert token not in source, f"policy.py references {token}"


def test_policy_tables_are_immutable() -> None:
    with pytest.raises(TypeError):
        PERMITTED_OPERATIONS[Resource.TASK] = frozenset()  # type: ignore[index]
    with pytest.raises(TypeError):
        _OWNED_TABLES["task"] = None  # type: ignore[index]


def test_storage_and_policy_resource_vocabularies_agree() -> None:
    assert {member.value for member in Resource} == set(_OWNED_TABLES) | {
        "task",
        "evaluation_run",
    }


def test_unsupported_owned_resource_is_refused_at_the_storage_layer() -> None:
    with pytest.raises(UnsupportedOwnedResource):
        OwnedResourceRepo().get_owned(
            sqlite3.connect(":memory:"),
            resource=Resource.TASK,
            user_id=1,
            resource_id=1,
        )


# F. Failure modes


def test_identity_dependency_failure_is_not_converted_into_an_allow(
    authz: AuthorizationService, auth: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(auth, "alice")
    token = _token(auth, "alice")

    class _Broken:
        @staticmethod
        def from_session_token(_token_value: object) -> Identity:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(authz, "_identities", _Broken())
    with pytest.raises(sqlite3.OperationalError):
        authz.get_task(token, 1)


def test_repository_lookup_failure_is_not_converted_into_an_allow(
    authz: AuthorizationService, auth: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(auth, "alice")
    token = _token(auth, "alice")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("no such table: tasks")

    monkeypatch.setattr(authz._tasks, "get", boom)
    with pytest.raises(sqlite3.OperationalError):
        authz.get_task(token, 1)


def test_malformed_persisted_owner_data_denies(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    """A provenance row whose task link is null is not attributable and is hidden."""

    ids = _seed_chain(db, two_users[0])
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO provenance_events (task_id, execution_id, event_type, actor, created_at) "
            "VALUES (NULL, NULL, 'task.orphaned', 'executor', 't')"
        )
    orphan = _event_id(db, "task.orphaned")
    with pytest.raises(PermissionDenied):
        authz.get_owned_resource(
            _token(auth, "alice"), resource=Resource.PROVENANCE_EVENT, resource_id=orphan
        )
    rows = authz.list_owned_resources(
        _token(auth, "alice"), resource=Resource.PROVENANCE_EVENT, task_id=ids["task"]
    )
    assert "task.orphaned" not in [row["event_type"] for row in rows]


def test_authorization_writes_no_provenance_for_its_own_decisions(
    authz: AuthorizationService, auth: AuthService, db: Database, two_users: tuple[int, int]
) -> None:
    """Keeps the actor vocabulary (C-06) open by recording no actor value here."""

    ids = _seed_chain(db, two_users[0])
    before = _count(db, "provenance_events")
    with pytest.raises(PermissionDenied):
        authz.get_owned_resource(
            _token(auth, "bob"), resource=Resource.ARTIFACT, resource_id=ids["artifact"]
        )
    assert _count(db, "provenance_events") == before


def test_denial_log_carries_a_reason_and_no_secret_material(
    authz: AuthorizationService,
    auth: AuthService,
    db: Database,
    two_users: tuple[int, int],
    caplog: pytest.LogCaptureFixture,
) -> None:
    ids = _seed_chain(db, two_users[0])
    token = _token(auth, "bob")
    with caplog.at_level("WARNING", logger="atlas.security.service"):
        with pytest.raises(PermissionDenied):
            authz.get_task(token, ids["task"])
    assert caplog.records, "a denial must remain diagnosable"
    assert "resource_not_owned" in caplog.text
    assert token not in caplog.text
    assert PASSWORD not in caplog.text
