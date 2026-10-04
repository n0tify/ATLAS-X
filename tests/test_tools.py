"""Phase 09: the controlled tool registry and the single dispatch boundary.

The tests are grouped by the property they defend rather than by the module they
exercise, because the properties are what has to survive future edits:

* what a tool is allowed to declare, and what registration refuses outright;
* what the schema layer refuses to let reach an implementation;
* that authorization is decided *before* an implementation can run, with the
  invocation count asserted rather than the exception alone;
* that a grant is a real persisted row, owner-scoped, scoped, and revocable;
* that every run is bounded and recorded, and that a failure is recorded too;
* that the built-in tools do what their names say and read nothing they should
  not.

Every test builds its own database through the ``db`` fixture, so no state is
shared between them.
"""

from __future__ import annotations

import inspect
import io
import json
import tokenize
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pytest

from atlas.auth.service import AuthService
from atlas.sandbox.errors import exception_for
from atlas.sandbox.protocol import Status
from atlas.security.errors import AuthorizationError, PermissionDenied
from atlas.security.policy import PROHIBITED_TOOL_CAPABILITIES, Resource
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.migrations import (
    SCHEMA_VERSION,
    SchemaVersionError,
    applied_version,
    init_db,
)
from atlas.storage.owned_resources import UnsupportedOwnedResource
from atlas.storage.repositories import TaskRepo
from atlas.storage.tool_grants import ToolGrantRepo, parse_scope, task_scope
from atlas.tools.context import MAX_VIEW_ROWS, OwnedTaskView
from atlas.tools.definition import (
    TOOL_ID_PATTERN,
    Determinism,
    FilesystemAccess,
    NetworkAccess,
    ProvenanceField,
    ToolContext,
    ToolDefinition,
    ToolLimits,
)
from atlas.tools.dispatch import (
    TOOL_COMPLETED_EVENT,
    TOOL_INVOKED_EVENT,
    DispatchLimits,
    ToolDispatcher,
    ToolInvocation,
)
from atlas.tools.errors import (
    MalformedToolId,
    ToolDefinitionInvalid,
    ToolError,
    ToolErrorCode,
    ToolExecutionFailed,
    ToolInputInvalid,
    ToolInputTooLarge,
    ToolLimitExceeded,
    ToolOutputInvalid,
    ToolOutputTooLarge,
    ToolUnsupported,
    UnknownTool,
)
from atlas.tools.registry import ToolRegistry, default_registry
from atlas.tools.schema import SchemaField, ToolSchema, validate_input, validate_output

PASSWORD = "correct-horse-battery-staple"

#: The approved tool set, spelled out rather than derived from
#: ``build_definitions()``. Deriving it would make these tests pass whatever the
#: registry happens to contain, which is exactly the drift they exist to catch:
#: adding a tool is a capability change and should have to edit this list.
BUILTIN_TOOL_IDS = (
    "artifact_metadata",
    "csv_statistics",
    "json_shape_inspect",
    "numeric_summary",
    "task_graph_summary",
    "text_statistics",
)


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def authz(db: Database, auth: AuthService) -> AuthorizationService:
    """Authorization with no tool grants at all: every capability denies."""

    return AuthorizationService(db, auth)


@pytest.fixture
def authz_with_grants(
    db: Database, auth: AuthService, alice_token: str
) -> tuple[AuthorizationService, ToolGrantRepo]:
    """Authorization with a real, empty grant table: registry ready, no grants.

    Depends on ``alice_token`` so that ``alice`` exists. The grants are still
    empty; registering a user is not the same as granting it a capability.
    """

    assert alice_token
    source = ToolGrantRepo(db, registry_ready=True)
    return AuthorizationService(db, auth, tool_grants=source), source


@pytest.fixture
def grants(db: Database) -> ToolGrantRepo:
    return ToolGrantRepo(db, registry_ready=True)


@pytest.fixture
def granted(
    db: Database, auth: AuthService, grants: ToolGrantRepo, alice_token: str
) -> tuple[AuthorizationService, ToolDispatcher]:
    """A dispatcher where ``alice`` holds every built-in capability globally."""

    authz = AuthorizationService(db, auth, tool_grants=grants)
    dispatcher = ToolDispatcher(db, authz, default_registry())
    for tool_id in BUILTIN_TOOL_IDS:
        grants.grant(user_id=_user_id(db, "alice"), tool_name=tool_id, granted_by="operator")
    return authz, dispatcher


@pytest.fixture
def alice_token(auth: AuthService) -> str:
    auth.register("alice", PASSWORD)
    return str(auth.login("alice", PASSWORD)["token"])


def _user_id(db: Database, username: str) -> int:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
    assert row is not None
    return int(row["id"])


def _token(auth: AuthService, username: str) -> str:
    return str(auth.login(username, PASSWORD)["token"])


def _new_task(db: Database, user_id: int) -> int:
    with db.transaction() as conn:
        return TaskRepo().create(conn, user_id=user_id, title="t", goal="g")


def _events(db: Database, task_id: int, event_type: str) -> list[dict[str, Any]]:
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT event_type, actor, detail_json FROM provenance_events "
            "WHERE task_id = ? AND event_type = ? ORDER BY id ASC",
            (task_id, event_type),
        ).fetchall()
    return [dict(row) for row in rows]


def _detail(event: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(str(event["detail_json"]))


# ------------------------------------------------- what a tool may declare


class _Counting:
    """A tool body that records every call, so tests can assert on the count.

    Used for the ordering tests: the claim being tested is not "an exception was
    raised" but "the implementation never ran", and only a count can show that.
    """

    def __init__(self, result: Mapping[str, Any] | None = None) -> None:
        self.calls = 0
        self.seen: list[Mapping[str, Any]] = []
        self._result = dict(result or {"ok": True})

    def __call__(
        self, context: ToolContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.calls += 1
        self.seen.append(dict(arguments))
        return dict(self._result)


def _definition(
    implementation: Callable[..., Mapping[str, Any]] | None = None,
    **overrides: Any,
) -> ToolDefinition:
    """A minimal valid definition, overridable per test."""

    fields: dict[str, Any] = {
        "tool_id": "probe_tool",
        "title": "Probe",
        "description": "Counts its own invocations.",
        "version": "1.0.0",
        "input_schema": ToolSchema(
            fields=(
                SchemaField(
                    name="value", type="integer", minimum=0, maximum=1000, required=False
                ),
            )
        ),
        "output_schema": ToolSchema(
            fields=(SchemaField(name="ok", type="boolean"),)
        ),
        "limits": ToolLimits(max_input_bytes=1024, max_output_bytes=1024, timeout_seconds=5),
        "determinism": Determinism.DETERMINISTIC,
        "provenance_fields": frozenset(
            {ProvenanceField.TOOL_ID, ProvenanceField.TOOL_VERSION}
        ),
        "implementation": implementation or _Counting(),
        "implementation_id": "tests.test_tools:probe",
    }
    fields.update(overrides)
    return ToolDefinition(**fields)


@pytest.mark.parametrize(
    "tool_id",
    [
        "Tool_Name",
        "tool name",
        "tool.name",
        "tool/name",
        "../tool",
        "tool:name",
        "-tool",
        "1tool",
        "tool__name",
        "a",
        "t" * 65,
    ],
)
def test_tool_id_must_be_lowercase_snake_case(tool_id: str) -> None:
    with pytest.raises(ToolDefinitionInvalid):
        _definition(tool_id=tool_id)


@pytest.mark.parametrize("tool_id", ["text_statistics", "json_shape_inspect", "abc"])
def test_well_formed_tool_id_is_accepted(tool_id: str) -> None:
    assert _definition(tool_id=tool_id).tool_id == tool_id


def test_capability_defaults_to_the_tool_id() -> None:
    assert _definition().capability == "probe_tool"


def test_capability_that_does_not_match_the_tool_id_is_refused() -> None:
    with pytest.raises(ToolDefinitionInvalid):
        _definition(capability="other_tool")


def test_prohibited_capability_is_never_registrable() -> None:
    for capability in sorted(PROHIBITED_TOOL_CAPABILITIES):
        with pytest.raises(ToolUnsupported):
            _definition(tool_id=capability, capability=capability)


def test_host_filesystem_access_requires_the_sandbox_and_is_refused() -> None:
    for access in (FilesystemAccess.HOST_READ, FilesystemAccess.HOST_WRITE):
        with pytest.raises(ToolUnsupported):
            _definition(filesystem_access=access)


def test_network_access_is_refused() -> None:
    with pytest.raises(ToolUnsupported):
        _definition(network_access=NetworkAccess.ALLOWED)


def test_non_determinism_is_refused() -> None:
    with pytest.raises(ToolUnsupported):
        _definition(determinism=Determinism.NON_DETERMINISTIC)


def test_requiring_a_sandbox_is_registrable_now_that_one_exists() -> None:
    # Phase 10B removed the refusal. The declaration became meaningful rather
    # than forbidden, and the registry no longer treats a sandbox-requiring tool
    # as unrepresentable.
    definition = _definition(requires_sandbox=True)
    assert definition.requires_sandbox is True


def test_requires_sandbox_must_still_be_a_bool() -> None:
    for value in ("yes", 1, None, object()):
        with pytest.raises(ToolDefinitionInvalid):
            _definition(requires_sandbox=value)


def test_version_must_be_explicit_semver() -> None:
    for version in ("1", "1.0", "v1.0.0", "1.0.0-beta", ""):
        with pytest.raises(ToolDefinitionInvalid):
            _definition(version=version)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_input_bytes": 0, "max_output_bytes": 1024, "timeout_seconds": 5},
        {"max_input_bytes": 1024, "max_output_bytes": -1, "timeout_seconds": 5},
        {"max_input_bytes": 1024, "max_output_bytes": 1024, "timeout_seconds": 0},
        {"max_input_bytes": True, "max_output_bytes": 1024, "timeout_seconds": 5},
        {"max_input_bytes": 64 * 1024 * 1024, "max_output_bytes": 1024, "timeout_seconds": 5},
        {"max_input_bytes": 1024, "max_output_bytes": 1024, "timeout_seconds": 10_000},
    ],
)
def test_limits_must_be_bounded_positive_integers(limits: Mapping[str, Any]) -> None:
    with pytest.raises(ToolDefinitionInvalid):
        _definition(limits=ToolLimits(**dict(limits)))


def test_a_tool_must_require_provenance() -> None:
    with pytest.raises(ToolDefinitionInvalid):
        _definition(provenance_fields=frozenset())
    with pytest.raises(ToolDefinitionInvalid):
        _definition(provenance_fields=frozenset({ProvenanceField.TOOL_ID}))


def test_definition_describes_itself_without_exposing_the_implementation() -> None:
    described = _definition().describe()
    assert described["tool_id"] == "probe_tool"
    assert described["capability"] == "probe_tool"
    assert described["input_schema"]["type"] == "object"
    assert "implementation" not in described
    assert not any("callable" in str(value) for value in described.values())


# ------------------------------------------------------------ the registry


def test_default_registry_is_frozen_and_holds_every_built_in() -> None:
    registry = default_registry()
    assert registry.frozen
    assert registry.capabilities() == BUILTIN_TOOL_IDS


def test_default_registry_has_no_prohibited_capability() -> None:
    for tool_id in default_registry().capabilities():
        assert tool_id not in PROHIBITED_TOOL_CAPABILITIES


def test_no_registered_tool_declares_filesystem_network_or_sandbox_access() -> None:
    """No tool asks for more capability, and every one of them asks for the sandbox.

    The first two assertions are unchanged from Phase 09 and mean the same thing:
    no registered tool declares filesystem or network reach, so the sandbox never
    has to decide whether to grant either.

    The third was ``requires_sandbox is False``, which asserted the Phase 09 world
    where a body ran in the ATLAS-X process and needed no confinement. Phase 10B
    inverted it, and inverting it is the point: there is no longer a shape of tool
    that opts out of the sandbox, so the flag is asserted ``True`` for every
    definition rather than dropped. A future tool that declared
    ``requires_sandbox = False`` would restore exactly the bypass this phase
    removed, and this is the assertion that catches it.
    """

    for definition in default_registry().list_definitions():
        assert definition.filesystem_access is FilesystemAccess.NONE
        assert definition.network_access is NetworkAccess.NONE
        assert definition.requires_sandbox is True


def test_no_registered_tool_is_non_deterministic() -> None:
    for definition in default_registry().list_definitions():
        assert definition.determinism in {
            Determinism.DETERMINISTIC,
            Determinism.STATE_DEPENDENT,
        }


def test_frozen_registry_refuses_further_registration() -> None:
    registry = default_registry()
    with pytest.raises(ToolDefinitionInvalid):
        registry.register(_definition())


def test_registry_refuses_a_duplicate_tool_id() -> None:
    registry = ToolRegistry([_definition()])
    with pytest.raises(ToolDefinitionInvalid):
        registry.register(_definition())
    assert registry.capabilities() == ("probe_tool",)


def test_registry_refuses_a_non_definition() -> None:
    with pytest.raises(ToolDefinitionInvalid):
        ToolRegistry().register(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "tool_id",
    [
        "has spaces",
        "../../etc/passwd",
        "os.system",
        "text_statistics;drop",
        "TEXT_STATISTICS",
        "text-statistics",
        "",
        "x" * 200,
        None,
        7,
        ["text_statistics"],
    ],
)
def test_a_malformed_id_is_refused(tool_id: Any) -> None:
    with pytest.raises(MalformedToolId):
        default_registry().find(tool_id)


def test_a_well_formed_but_unregistered_id_is_unknown() -> None:
    with pytest.raises(UnknownTool):
        default_registry().find("no_such_tool")


def test_registry_lookup_uses_the_same_pattern_as_registration() -> None:
    """One vocabulary for "well formed", or an id can be valid on one path only."""

    definition = _definition()
    assert TOOL_ID_PATTERN.fullmatch(definition.tool_id) is not None
    assert TOOL_ID_PATTERN.fullmatch("has spaces") is None
    registry = ToolRegistry([definition])
    assert registry.find(definition.tool_id) is definition


def test_lookup_is_case_sensitive_so_a_name_cannot_be_guessed() -> None:
    """Case folding would let ``Text_Statistics`` and ``text_statistics`` both
    resolve, so a grant stored under one spelling would be spent under the other."""

    with pytest.raises(MalformedToolId):
        default_registry().find("Text_Statistics")
    # A kebab-case near miss is malformed, not unknown: the request could never
    # have named a registered tool, whatever the registry contained.
    with pytest.raises(MalformedToolId):
        default_registry().find("text-statistics")


def test_describe_all_is_stable_and_carries_no_user_data() -> None:
    described = default_registry().describe_all()
    assert [item["tool_id"] for item in described] == list(BUILTIN_TOOL_IDS)
    for item in described:
        assert "user_id" not in item
        assert "task_id" not in item


# --------------------------------------------------------------- schemas


def test_numeric_field_without_bounds_is_not_constructible() -> None:
    with pytest.raises(ValueError):
        SchemaField(name="n", type="integer")


def test_string_field_without_max_length_is_not_constructible() -> None:
    with pytest.raises(ValueError):
        SchemaField(name="s", type="string")


def test_array_field_without_max_items_is_not_constructible() -> None:
    with pytest.raises(ValueError):
        SchemaField(name="xs", type="array", item_type="integer")


def test_numeric_array_without_item_bounds_is_not_constructible() -> None:
    with pytest.raises(ValueError):
        SchemaField(name="xs", type="array", item_type="number", max_items=10)


def test_free_form_nested_objects_are_not_supported() -> None:
    with pytest.raises(ValueError):
        SchemaField(name="obj", type="object")


def test_a_bound_that_does_not_apply_to_the_type_is_refused() -> None:
    with pytest.raises(ValueError):
        SchemaField(name="s", type="string", max_length=10, minimum=1)
    with pytest.raises(ValueError):
        SchemaField(name="xs", type="array", item_type="integer", max_items=5, max_length=10)


def test_bounds_above_each_other_are_refused() -> None:
    with pytest.raises(ValueError):
        SchemaField(name="n", type="integer", minimum=10, maximum=1)
    with pytest.raises(ValueError):
        SchemaField(name="s", type="string", max_length=1, min_length=5)


def test_choices_must_match_the_declared_type() -> None:
    with pytest.raises(ValueError):
        SchemaField(
            name="s", type="string", max_length=10, choices=("a", 2)
        )


def test_array_choices_constrain_the_items() -> None:
    field = SchemaField(
        name="xs",
        type="array",
        item_type="string",
        max_items=3,
        choices=("a", "b"),
    )
    assert validate_input(ToolSchema(fields=(field,)), {"xs": ["a", "b"]}) == {
        "xs": ["a", "b"]
    }
    with pytest.raises(ToolInputInvalid):
        validate_input(ToolSchema(fields=(field,)), {"xs": ["a", "c"]})


def test_duplicate_field_names_are_refused() -> None:
    field = SchemaField(name="n", type="integer", minimum=0, maximum=1)
    with pytest.raises(ValueError):
        ToolSchema(fields=(field, field))


def test_non_mapping_payload_is_rejected_rather_than_crashing() -> None:
    schema = ToolSchema(fields=(SchemaField(name="n", type="integer", minimum=0, maximum=1),))
    for payload in ([], "text", 7, None, {1, 2}):
        with pytest.raises(ToolInputInvalid):
            validate_input(schema, payload)


def test_unexpected_field_is_rejected() -> None:
    schema = ToolSchema(fields=(SchemaField(name="n", type="integer", minimum=0, maximum=1),))
    with pytest.raises(ToolInputInvalid):
        validate_input(schema, {"n": 1, "extra": 2})


def test_missing_required_field_is_rejected_and_optional_one_is_allowed() -> None:
    schema = ToolSchema(
        fields=(
            SchemaField(name="n", type="integer", minimum=0, maximum=1),
            SchemaField(name="m", type="integer", required=False, minimum=0, maximum=1),
        )
    )
    assert validate_input(schema, {"n": 0}) == {"n": 0}


def test_bounds_are_enforced_on_every_scalar() -> None:
    schema = ToolSchema(
        fields=(SchemaField(name="n", type="number", minimum=-1.5, maximum=1.5),)
    )
    assert validate_input(schema, {"n": 1.5}) == {"n": 1.5}
    for bad in (1.6, -1.6, 1e308, float("nan"), float("inf")):
        with pytest.raises(ToolInputInvalid):
            validate_input(schema, {"n": bad})


def test_a_boolean_is_not_accepted_as_an_integer() -> None:
    schema = ToolSchema(fields=(SchemaField(name="n", type="integer", minimum=0, maximum=5),))
    with pytest.raises(ToolInputInvalid):
        validate_input(schema, {"n": True})


def test_string_length_bounds_are_enforced() -> None:
    schema = ToolSchema(fields=(SchemaField(name="s", type="string", max_length=4),))
    assert validate_input(schema, {"s": "abcd"}) == {"s": "abcd"}
    with pytest.raises(ToolInputInvalid):
        validate_input(schema, {"s": "abcde"})


def test_array_length_bounds_are_enforced() -> None:
    schema = ToolSchema(
        fields=(
            SchemaField(
                name="xs",
                type="array",
                item_type="integer",
                max_items=2,
                item_minimum=0,
                item_maximum=9,
            ),
        )
    )
    assert validate_input(schema, {"xs": [1, 2]}) == {"xs": [1, 2]}
    with pytest.raises(ToolInputInvalid):
        validate_input(schema, {"xs": [1, 2, 3]})
    with pytest.raises(ToolInputInvalid):
        validate_input(schema, {"xs": [1, 99]})


def test_array_items_are_bounded_in_length_too() -> None:
    schema = ToolSchema(
        fields=(
            SchemaField(
                name="xs",
                type="array",
                item_type="string",
                max_items=2,
                item_max_length=3,
            ),
        )
    )
    assert validate_input(schema, {"xs": ["ab"]}) == {"xs": ["ab"]}
    with pytest.raises(ToolInputInvalid):
        validate_input(schema, {"xs": ["abcd"]})


def test_output_validation_reports_a_different_error_than_input() -> None:
    schema = ToolSchema(
        fields=(SchemaField(name="ok", type="boolean"),)
    )
    with pytest.raises(ToolOutputInvalid):
        validate_output(schema, {"ok": "not a boolean"})
    with pytest.raises(ToolInputInvalid):
        validate_input(schema, {"ok": "not a boolean"})


def test_every_error_carries_a_stable_code() -> None:
    schema = ToolSchema(fields=(SchemaField(name="n", type="integer", minimum=0, maximum=1),))
    with pytest.raises(ToolError) as caught:
        validate_input(schema, {"n": 9})
    assert caught.value.code == ToolErrorCode.INVALID_INPUT


# ------------------------------------------------------- the grant source


def test_scope_parsing_distinguishes_global_from_malformed() -> None:
    assert parse_scope(None) is None
    assert parse_scope("task:7") == "task:7"
    for bad in ("", "task:", "task:abc", "task:0", "task:-1", "global", 7, True, "task:1 "):
        assert parse_scope(bad) is False


def test_task_scope_refuses_an_unusable_id() -> None:
    assert task_scope(7) == "task:7"
    for bad in (0, -1, True, "7", None):
        with pytest.raises((TypeError, ValueError)):
            task_scope(bad)


def test_no_grants_means_every_capability_denies(
    db: Database, authz: AuthorizationService, alice_token: str
) -> None:
    task = _new_task(db, _user_id(db, "alice"))
    with pytest.raises(PermissionDenied):
        authz.require_tool_invocation(
            alice_token, tool_name="text_statistics", resource=Resource.TASK, resource_id=task
        )


def test_registry_readiness_is_reported_honestly(db: Database) -> None:
    assert ToolGrantRepo(db, registry_ready=True).registry_ready is True
    assert ToolGrantRepo(db, registry_ready=False).registry_ready is False


def test_grant_is_persisted_and_readable_for_its_owner(
    db: Database, auth: AuthService, grants: ToolGrantRepo
) -> None:
    auth.register("alice", PASSWORD)
    auth.register("bobby", PASSWORD)
    alice = _user_id(db, "alice")
    bob = _user_id(db, "bobby")

    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")

    assert [g.tool_name for g in grants.grants_for(alice)] == ["text_statistics"]
    assert grants.grants_for(bob) == ()
    assert grants.capabilities_for(alice) == frozenset({"textstatistics"})
    assert grants.capabilities_for(bob) == frozenset()


def test_grant_survives_a_new_repo_instance(db: Database, grants: ToolGrantRepo) -> None:
    alice = _register_id(db, "alice")
    grants.grant(user_id=alice, tool_name="numeric_summary", granted_by="operator")
    assert [g.tool_name for g in ToolGrantRepo(db, registry_ready=True).grants_for(alice)] == [
        "numeric_summary"
    ]


def _register_id(db: Database, username: str) -> int:
    with db.transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at) "
            "VALUES (?, 'x', 't', 't')",
            (username,),
        )
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)


def test_revoke_removes_the_capability_immediately(
    db: Database, grants: ToolGrantRepo
) -> None:
    alice = _register_id(db, "alice")
    grant_id = grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    assert grants.grants_for(alice)
    assert grants.revoke(user_id=alice, grant_id=grant_id) is True
    assert grants.grants_for(alice) == ()
    assert grants.revoke(user_id=alice, grant_id=grant_id) is False


def test_revoke_cannot_reach_another_users_grant(db: Database, grants: ToolGrantRepo) -> None:
    alice = _register_id(db, "alice")
    bob = _register_id(db, "bobby")
    grant_id = grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    assert grants.revoke(user_id=bob, grant_id=grant_id) is False
    assert grants.grants_for(alice)


def test_regranting_replaces_rather_than_duplicating(
    db: Database, grants: ToolGrantRepo
) -> None:
    alice = _register_id(db, "alice")
    first = grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    second = grants.grant(user_id=alice, tool_name="text_statistics", granted_by="admin")
    assert first == second
    rows = grants.list_for_user(alice)
    assert len(rows) == 1
    assert rows[0]["granted_by"] == "admin"


def test_a_task_scoped_grant_does_not_apply_to_another_task(
    db: Database,
    auth: AuthService,
    alice_token: str,
    authz_with_grants: tuple[AuthorizationService, ToolGrantRepo],
) -> None:
    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    one = _new_task(db, alice)
    two = _new_task(db, alice)
    grants.grant(
        user_id=alice,
        tool_name="text_statistics",
        granted_by="operator",
        scope=task_scope(one),
    )
    authz.require_tool_invocation(
        alice_token, tool_name="text_statistics", resource=Resource.TASK, resource_id=one
    )
    with pytest.raises(PermissionDenied):
        authz.require_tool_invocation(
            alice_token, tool_name="text_statistics", resource=Resource.TASK, resource_id=two
        )


def test_a_task_scoped_grant_does_not_leak_into_another_user(
    db: Database,
    auth: AuthService,
    alice_token: str,
    authz_with_grants: tuple[AuthorizationService, ToolGrantRepo],
) -> None:
    authz, grants = authz_with_grants
    auth.register("bobby", PASSWORD)
    alice = _user_id(db, "alice")
    bob = _user_id(db, "bobby")
    alice_task = _new_task(db, alice)
    bob_task = _new_task(db, bob)
    grants.grant(
        user_id=alice,
        tool_name="text_statistics",
        granted_by="operator",
        scope=task_scope(alice_task),
    )
    with pytest.raises(PermissionDenied):
        authz.require_tool_invocation(
            _token(auth, "bobby"),
            tool_name="text_statistics",
            resource=Resource.TASK,
            resource_id=bob_task,
        )
    assert alice_token


def test_a_malformed_stored_scope_drops_the_grant_rather_than_widening_it(
    db: Database, grants: ToolGrantRepo
) -> None:
    alice = _register_id(db, "alice")
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    with db.transaction() as conn:
        conn.execute("UPDATE tool_permissions SET scope = 'everything'")
    assert grants.grants_for(alice) == ()


def test_grant_refuses_a_capability_for_a_user_that_does_not_exist(
    db: Database, grants: ToolGrantRepo
) -> None:
    with pytest.raises(ValueError):
        grants.grant(user_id=999, tool_name="text_statistics", granted_by="operator")


@pytest.mark.parametrize("tool_name", ["", "   ", None, 7, "!"])
def test_grant_refuses_an_unusable_capability_name(
    db: Database, grants: ToolGrantRepo, tool_name: Any
) -> None:
    alice = _register_id(db, "alice")
    with pytest.raises(ValueError):
        grants.grant(user_id=alice, tool_name=tool_name, granted_by="operator")


def test_grant_refuses_a_malformed_scope(db: Database, grants: ToolGrantRepo) -> None:
    alice = _register_id(db, "alice")
    with pytest.raises(ValueError):
        grants.grant(
            user_id=alice, tool_name="text_statistics", granted_by="operator", scope="all"
        )


def test_grant_requires_naming_who_made_it(db: Database, grants: ToolGrantRepo) -> None:
    alice = _register_id(db, "alice")
    with pytest.raises(ValueError):
        grants.grant(user_id=alice, tool_name="text_statistics", granted_by="  ")


def test_grants_for_an_unusable_id_is_empty_not_an_error(
    db: Database, grants: ToolGrantRepo
) -> None:
    for bad in (0, -1, True, "1", None):
        assert grants.grants_for(bad) == ()  # type: ignore[arg-type]


def test_a_grant_row_holds_no_secret(db: Database, grants: ToolGrantRepo) -> None:
    alice = _register_id(db, "alice")
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    with db.transaction() as conn:
        columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(tool_permissions)")
        }
    assert not columns & {"token", "secret", "key", "password", "credential"}


# ------------------------------------------------- authorization ordering


def _spy_registry(counter: _Counting) -> ToolRegistry:
    """A frozen one-tool registry whose body is the supplied counter."""

    registry = ToolRegistry([_definition(tool_id="text_statistics", implementation=counter)])
    registry.freeze()
    return registry


def _real_definition(tool_id: str, **overrides: Any) -> ToolDefinition:
    """A host-side definition for a real built-in tool, with fields overridden.

    Phase 10B moved the tool body out of this process, so a definition built by
    :func:`_definition` — whose ``implementation`` is a host callable and whose
    ``implementation_id`` is ``tests.test_tools:probe`` — is refused at the
    boundary. That refusal is the design working, not a gap to route around: the
    guest resolves the tool from its own frozen copy and rejects any
    ``implementation_id`` that does not match it, so there is no way to make a
    test-only body execute as a real tool.

    Tests that need to vary something the *host* enforces — a declared limit, an
    output schema — around a body that really runs therefore start from the real
    definition and replace only those fields. The body still executes the guest's
    own implementation, which is what makes these tests worth having: they
    exercise the real subprocess rather than a stub.

    ``implementation`` is deliberately left alone. It is never called on this
    side; it is dead weight on the host definition and replacing it would only
    create the impression that a host body can run.
    """

    real = default_registry().find(tool_id)
    assert real is not None, f"{tool_id} is not a registered tool"
    return replace(real, **overrides)


def test_dispatch_without_a_grant_never_runs_the_implementation(
    db: Database, alice_token: str, authz_with_grants: tuple[AuthorizationService, ToolGrantRepo]
) -> None:
    """The mandatory Phase 09 ordering test, asserted on the invocation count.

    Checking that a ``PermissionDenied`` was raised would also pass if the
    implementation had run first and authorization had failed afterwards. Only
    the count distinguishes the two.
    """

    authz, _ = authz_with_grants
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    counter = _Counting()
    dispatcher = ToolDispatcher(db, authz, _spy_registry(counter))

    with pytest.raises(AuthorizationError):
        dispatcher.dispatch(
            alice_token, tool_id="text_statistics", task_id=task, arguments={"value": 1}
        )

    assert counter.calls == 0, "an implementation ran without an explicit grant"
    assert counter.seen == []
    assert _events(db, task, TOOL_INVOKED_EVENT) == []


def test_a_revoked_grant_stops_the_implementation_on_the_next_call(
    db: Database,
    auth: AuthService,
    alice_token: str,
    authz_with_grants: tuple[AuthorizationService, ToolGrantRepo],
) -> None:
    """A revocation takes effect before the next body runs.

    Phase 09 counted invocations of a host-side callable. That counter no longer
    exists, and deliberately so: the body runs in the guest, so there is no host
    call for this process to count. The audit trail is the honest observable —
    an invocation that reaches the tool records ``tool_completed``, so if the
    second call ran the tool we would see a second record.

    Counting audit records rather than host calls is also the stronger assertion:
    it holds even if the body were re-hosted, and it cannot be satisfied by an
    exception raised after the fact.
    """

    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    registry = ToolRegistry([_real_definition("text_statistics")])
    registry.freeze()
    dispatcher = ToolDispatcher(db, authz, registry)
    grant_id = grants.grant(
        user_id=alice, tool_name="text_statistics", granted_by="operator"
    )

    dispatcher.dispatch(
        alice_token, tool_id="text_statistics", task_id=task, arguments={"text": "a b"}
    )
    completed = _events(db, task, TOOL_COMPLETED_EVENT)
    assert [_detail(event)["status"] for event in completed] == ["ok"]

    assert grants.revoke(user_id=alice, grant_id=grant_id) is True
    with pytest.raises(AuthorizationError):
        dispatcher.dispatch(
            alice_token,
            tool_id="text_statistics",
            task_id=task,
            arguments={"text": "a b"},
        )
    assert _events(db, task, TOOL_COMPLETED_EVENT) == completed, (
        "the implementation ran after its grant was revoked"
    )


def test_an_unauthenticated_caller_reaches_nothing(
    db: Database, authz_with_grants: tuple[AuthorizationService, ToolGrantRepo]
) -> None:
    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    dispatcher = ToolDispatcher(db, authz, default_registry())

    for bad_token in (None, "", "not-a-token", 7, ["t"]):
        with pytest.raises(AuthorizationError):
            dispatcher.dispatch(
                bad_token, tool_id="text_statistics", task_id=task, arguments={"text": "x"}
            )
    assert _events(db, task, TOOL_INVOKED_EVENT) == []


def test_authorization_runs_before_input_validation(
    db: Database,
    auth: AuthService,
    alice_token: str,
    authz: AuthorizationService,
) -> None:
    """A denied caller must not learn the tool's schema from its error.

    If validation ran first, a malformed payload would produce a schema error and
    a well-formed one would produce a permission error, which is a free oracle for
    the shape of a capability the caller may not use. Both payloads below are
    refused identically, and neither produces a tool error.
    """

    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    dispatcher = ToolDispatcher(db, authz, default_registry())

    payloads: list[object] = [
        {"values": "nonsense"},
        {"values": [1.0, 2.0]},
        {},
        {"unknown_field": True},
    ]
    for payload in payloads:
        with pytest.raises(AuthorizationError) as denied:
            dispatcher.dispatch(
                alice_token, tool_id="numeric_summary", task_id=task, arguments=payload
            )
        assert not isinstance(denied.value, ToolError)
    assert _events(db, task, TOOL_INVOKED_EVENT) == []


def test_a_known_tool_cannot_be_dispatched_on_another_users_task(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    authz, dispatcher = granted
    auth.register("bobby", PASSWORD)
    bob = _user_id(db, "bobby")
    bob_task = _new_task(db, bob)

    with pytest.raises(AuthorizationError):
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="text_statistics",
            task_id=bob_task,
            arguments={"text": "hello"},
        )
    assert _events(db, bob_task, TOOL_INVOKED_EVENT) == []


def test_dispatch_takes_no_user_id_argument(
    granted: tuple[AuthorizationService, ToolDispatcher]
) -> None:
    inspect
    _, dispatcher = granted
    parameters = set(inspect.signature(ToolDispatcher.dispatch).parameters)
    assert "user_id" not in parameters
    assert "user_id" not in inspect.signature(dispatcher.dispatch).parameters


def test_no_public_authorization_method_accepts_a_user_id(authz: AuthorizationService) -> None:
    inspect
    for name in dir(authz):
        if name.startswith("_"):
            continue
        member = getattr(authz, name)
        if not callable(member):
            continue
        assert "user_id" not in inspect.signature(member).parameters, name


# -------------------------------------------------- dispatch and provenance


def test_a_granted_dispatch_returns_a_validated_result(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)

    invocation = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="text_statistics",
        task_id=task,
        arguments={"text": "one two three"},
    )

    assert isinstance(invocation, ToolInvocation)
    assert invocation.result["word_count"] == 3
    assert invocation.task_id == task
    assert invocation.provenance_event_id > 0


def test_a_completed_invocation_is_recorded_with_digests_and_no_raw_input(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    secret = "hunter2-do-not-log"

    invocation = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="text_statistics",
        task_id=task,
        arguments={"text": secret},
    )

    completed = _events(db, task, TOOL_COMPLETED_EVENT)
    assert len(completed) == 1
    detail = _detail(completed[0])
    assert detail["status"] == "ok"
    assert detail["tool_id"] == "text_statistics"
    assert detail["user_id"] == alice
    assert detail["task_id"] == task
    assert len(detail["input_digest"]) == 64
    assert len(detail["output_digest"]) == 64
    assert secret not in completed[0]["detail_json"]
    assert secret not in json.dumps(invocation.to_record())


def test_the_same_input_produces_the_same_digest(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    one = _new_task(db, alice)
    two = _new_task(db, alice)
    token = _token(auth, "alice")

    first = dispatcher.dispatch(
        token, tool_id="text_statistics", task_id=one, arguments={"text": "same"}
    )
    second = dispatcher.dispatch(
        token, tool_id="text_statistics", task_id=two, arguments={"text": "same"}
    )
    assert first.record["input_digest"] == second.record["input_digest"]
    assert first.record["output_digest"] == second.record["output_digest"]


def test_a_deterministic_tool_gives_the_same_answer_twice(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    one = _new_task(db, alice)
    two = _new_task(db, alice)
    token = _token(auth, "alice")

    payload = {"values": [3.0, 1.0, 2.0]}
    first = dispatcher.dispatch(
        token, tool_id="numeric_summary", task_id=one, arguments=payload
    )
    second = dispatcher.dispatch(
        token, tool_id="numeric_summary", task_id=two, arguments=payload
    )
    assert dict(first.result) == dict(second.result)


def test_the_provenance_actor_is_the_authenticated_principal(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="text_statistics",
        task_id=task,
        arguments={"text": "hi"},
    )
    for event_type in (TOOL_INVOKED_EVENT, TOOL_COMPLETED_EVENT):
        assert [event["actor"] for event in _events(db, task, event_type)] == ["user"]


def test_invalid_input_is_refused_and_recorded_as_a_failure(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)

    with pytest.raises(ToolInputInvalid):
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="numeric_summary",
            task_id=task,
            arguments={"values": ["not a number"]},
        )

    detail = _detail(_events(db, task, TOOL_COMPLETED_EVENT)[0])
    assert detail["status"] == "failed"
    assert detail["error_code"] == ToolErrorCode.INVALID_INPUT
    assert "output_digest" not in detail


def test_an_oversized_input_is_refused_before_the_implementation_runs(
    db: Database, auth: AuthService, authz_with_grants: tuple[AuthorizationService, ToolGrantRepo]
) -> None:
    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    counter = _Counting({"ok": True})
    registry = ToolRegistry(
        [
            _definition(
                tool_id="text_statistics",
                implementation=counter,
                # The character bound is deliberately looser than the byte bound,
                # so the dispatcher's byte limit is what refuses this. A schema
                # bound that fired first would not exercise the dispatcher at all.
                input_schema=ToolSchema(
                    fields=(SchemaField(name="text", type="string", max_length=1000),)
                ),
                output_schema=ToolSchema(fields=(SchemaField(name="ok", type="boolean"),)),
                limits=ToolLimits(
                    max_input_bytes=64, max_output_bytes=1024, timeout_seconds=5
                ),
            )
        ]
    )
    registry.freeze()
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    dispatcher = ToolDispatcher(db, authz, registry)

    with pytest.raises(ToolInputTooLarge):
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="text_statistics",
            task_id=task,
            arguments={"text": "x" * 200},
        )
    assert counter.calls == 0


def test_the_schema_bound_and_the_byte_bound_are_different_refusals(
    db: Database,
    auth: AuthService,
    authz_with_grants: tuple[AuthorizationService, ToolGrantRepo],
) -> None:
    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    registry = ToolRegistry(
        [
            _definition(
                tool_id="text_statistics",
                input_schema=ToolSchema(
                    fields=(SchemaField(name="text", type="string", max_length=10),)
                ),
            )
        ]
    )
    registry.freeze()
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    dispatcher = ToolDispatcher(db, authz, registry)

    with pytest.raises(ToolInputInvalid) as caught:
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="text_statistics",
            task_id=task,
            arguments={"text": "x" * 50},
        )
    assert caught.value.code == ToolErrorCode.INVALID_INPUT


def test_oversized_output_fails_rather_than_being_truncated(
    db: Database, auth: AuthService, authz_with_grants: tuple[AuthorizationService, ToolGrantRepo]
) -> None:
    """An oversized result is a failure, and the audit code survives the boundary.

    The bound here is tighter than the real ``text_statistics`` output, so the
    overflow is detected in the guest while the tool body is still confined. The
    interesting part is that the recorded code is ``output_too_large`` and not a
    generic resource failure: the guest sends ``OUTPUT_TOO_LARGE`` and the host
    honours the specific code over the coarse ``RESOURCE_EXCEEDED`` status. If
    that mapping regresses, this fails — which is the point of asserting the code
    rather than just the exception type.
    """

    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    registry = ToolRegistry(
        [
            _real_definition(
                "text_statistics",
                limits=ToolLimits(
                    max_input_bytes=4096, max_output_bytes=64, timeout_seconds=5
                ),
            )
        ]
    )
    registry.freeze()
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    dispatcher = ToolDispatcher(db, authz, registry)

    with pytest.raises(ToolOutputTooLarge):
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="text_statistics",
            task_id=task,
            arguments={"text": "a b c"},
        )
    detail = _detail(_events(db, task, TOOL_COMPLETED_EVENT)[0])
    assert detail["status"] == "failed"
    assert detail["error_code"] == ToolErrorCode.OUTPUT_TOO_LARGE


def test_output_that_breaks_its_own_schema_is_a_failure_not_a_result(
    db: Database, auth: AuthService, authz_with_grants: tuple[AuthorizationService, ToolGrantRepo]
) -> None:
    """The host re-validates what the guest returns; it does not take it on trust.

    The host declares ``char_count`` as a string while the real tool produces an
    integer. The guest never sees the tampered schema — it validates against its
    own frozen copy, which passes — so the result crosses the boundary intact and
    is then rejected here at :func:`validate_output`. That is exactly the property
    under test: moving the body into a subprocess did not move validation onto the
    far side of it, where a compromised guest could satisfy it.
    """

    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    registry = ToolRegistry(
        [
            _real_definition(
                "text_statistics",
                output_schema=ToolSchema(
                    fields=(
                        SchemaField(name="char_count", type="string", max_length=8),
                    )
                ),
            )
        ]
    )
    registry.freeze()
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    dispatcher = ToolDispatcher(db, authz, registry)

    with pytest.raises(ToolOutputInvalid):
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="text_statistics",
            task_id=task,
            arguments={"text": "abc"},
        )


def test_an_implementation_that_raises_is_a_failure_not_a_result() -> None:
    """A failure the guest cannot classify still becomes a failed record.

    This test used to inject a body that raised, which is no longer possible: the
    body runs in the guest and the guest will not run a test-supplied callable.
    What the original test actually protected is still worth protecting, so it is
    asserted at the boundary instead — an unclassified ``tool_error`` maps to
    ``ToolExecutionFailed``, and the caller learns nothing beyond the guest's own
    generic message.

    Sanitising the exception text is deliberately the guest's job and is covered by
    ``guest/selftest.py``; what the host owes is not to re-interpret a code it does
    not recognise as anything more specific, and not to invent detail of its own.
    """

    failure = exception_for(
        status=Status.TOOL_ERROR,
        violation=None,
        message="tool raised inside the sandbox",
    )
    assert isinstance(failure, ToolExecutionFailed)
    assert str(failure) == (
        "tool raised inside the sandbox: tool raised inside the sandbox"
    )

    unknown = exception_for(
        status=Status.TOOL_ERROR,
        violation=None,
        message="tool raised inside the sandbox",
        error_code="not_a_real_error_code",
    )
    assert type(unknown) is type(failure), (
        "an unrecognised code must not select a more specific exception type"
    )


def test_an_unusable_task_id_is_refused(
    granted: tuple[AuthorizationService, ToolDispatcher], auth: AuthService
) -> None:
    _, dispatcher = granted
    token = _token(auth, "alice")
    for bad in (0, -1, True, "1", None, 1.5):
        with pytest.raises(ToolError):
            dispatcher.dispatch(
                token, tool_id="text_statistics", task_id=bad, arguments={"text": "x"}
            )


def test_a_malformed_tool_id_is_refused(
    granted: tuple[AuthorizationService, ToolDispatcher], auth: AuthService
) -> None:
    _, dispatcher = granted
    token = _token(auth, "alice")
    with pytest.raises(MalformedToolId):
        dispatcher.dispatch(token, tool_id="not a name", task_id=1, arguments={})
    with pytest.raises(UnknownTool):
        dispatcher.dispatch(token, tool_id="no_such_tool", task_id=1, arguments={})


def test_a_dispatcher_refuses_an_unfrozen_registry(
    db: Database, auth: AuthService, authz: AuthorizationService
) -> None:
    with pytest.raises(ToolExecutionFailed):
        ToolDispatcher(db, authz, ToolRegistry([_definition()]))


# ---------------------------------------------------------------- budget


def test_the_per_task_call_budget_is_enforced(
    db: Database, auth: AuthService, authz_with_grants: tuple[AuthorizationService, ToolGrantRepo]
) -> None:
    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    dispatcher = ToolDispatcher(
        db, authz, default_registry(), limits=DispatchLimits(max_tool_calls=2)
    )
    token = _token(auth, "alice")

    dispatcher.dispatch(
        token, tool_id="text_statistics", task_id=task, arguments={"text": "a"}
    )
    dispatcher.dispatch(
        token, tool_id="text_statistics", task_id=task, arguments={"text": "b"}
    )
    with pytest.raises(ToolLimitExceeded):
        dispatcher.dispatch(
            token, tool_id="text_statistics", task_id=task, arguments={"text": "c"}
        )
    assert len(_events(db, task, TOOL_INVOKED_EVENT)) == 2


def test_the_budget_is_per_task_not_per_user(
    db: Database, auth: AuthService, authz_with_grants: tuple[AuthorizationService, ToolGrantRepo]
) -> None:
    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    first = _new_task(db, alice)
    second = _new_task(db, alice)
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    dispatcher = ToolDispatcher(
        db, authz, default_registry(), limits=DispatchLimits(max_tool_calls=1)
    )
    token = _token(auth, "alice")

    dispatcher.dispatch(
        token, tool_id="text_statistics", task_id=first, arguments={"text": "a"}
    )
    dispatcher.dispatch(
        token, tool_id="text_statistics", task_id=second, arguments={"text": "b"}
    )


def test_the_budget_survives_a_new_dispatcher(
    db: Database, auth: AuthService, authz_with_grants: tuple[AuthorizationService, ToolGrantRepo]
) -> None:
    authz, grants = authz_with_grants
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    grants.grant(user_id=alice, tool_name="text_statistics", granted_by="operator")
    limits = DispatchLimits(max_tool_calls=1)
    token = _token(auth, "alice")

    ToolDispatcher(db, authz, default_registry(), limits=limits).dispatch(
        token, tool_id="text_statistics", task_id=task, arguments={"text": "a"}
    )
    with pytest.raises(ToolLimitExceeded):
        ToolDispatcher(db, authz, default_registry(), limits=limits).dispatch(
            token, tool_id="text_statistics", task_id=task, arguments={"text": "b"}
        )


def test_dispatch_limits_reject_a_nonsense_configuration() -> None:
    for kwargs in ({"max_tool_calls": 0}, {"max_output_chars": -1}, {"max_tool_calls": True}):
        with pytest.raises(ValueError):
            DispatchLimits(**kwargs)


def test_dispatch_limits_come_from_settings(db: Database, authz: AuthorizationService) -> None:
    from atlas.config.settings import Settings

    limits = DispatchLimits.from_settings(
        Settings(max_tool_calls=7, max_output_chars=1234)
    )
    assert limits.max_tool_calls == 7
    assert limits.max_output_chars == 1234
    assert DispatchLimits.from_settings(Settings()).max_tool_calls == 12


# ----------------------------------------------------- introspection


def test_describe_needs_no_identity_and_returns_metadata_only(
    granted: tuple[AuthorizationService, ToolDispatcher]
) -> None:
    _, dispatcher = granted
    described = dispatcher.describe("text_statistics")
    assert described["tool_id"] == "text_statistics"
    assert "implementation" not in described


def test_list_tools_needs_no_identity(granted: tuple[AuthorizationService, ToolDispatcher]) -> None:
    _, dispatcher = granted
    assert [item["tool_id"] for item in dispatcher.list_tools()] == list(BUILTIN_TOOL_IDS)


# ------------------------------------------------------ built-in behaviour


def test_text_statistics_counts_text(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="text_statistics",
        task_id=task,
        arguments={"text": "one two\nthree"},
    ).result
    assert result["char_count"] == len("one two\nthree")
    assert result["line_count"] == 2
    assert result["word_count"] == 3
    assert result["unique_word_count"] == 3
    assert result["max_word_length"] == 5


def test_text_statistics_can_skip_word_work(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="text_statistics",
        task_id=task,
        arguments={"text": "one two", "count_words": False},
    ).result
    assert result["char_count"] == 7
    assert result["word_count"] == 0


def test_numeric_summary_reports_expected_statistics(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="numeric_summary",
        task_id=task,
        arguments={"values": [1.0, 2.0, 3.0, 4.0]},
    ).result
    assert result["count"] == 4
    assert result["minimum"] == 1.0
    assert result["maximum"] == 4.0
    assert result["sum"] == 10.0
    assert result["mean"] == 2.5
    assert result["median"] == 2.5
    assert result["population_variance"] == pytest.approx(1.25)


def test_numeric_summary_can_omit_the_costly_statistics(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="numeric_summary",
        task_id=task,
        arguments={"values": [1.0, 2.0], "compute_variance": False},
    ).result
    assert "count" in result
    assert "population_variance" not in result


def test_numeric_summary_rejects_an_empty_list_rather_than_inventing_a_number(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    with pytest.raises(ToolInputInvalid):
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="numeric_summary",
            task_id=task,
            arguments={"values": []},
        )


def test_json_shape_inspect_reports_shape_and_never_values(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    secret = "s3cret-value"
    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="json_shape_inspect",
        task_id=task,
        arguments={"document": json.dumps({"user": {"email": secret}, "rows": [1, 2]})},
    ).result

    assert result["root_type"] == "object"
    assert "user.email" in result["key_paths"]
    assert "rows" in result["key_paths"]
    assert secret not in json.dumps(dict(result))
    assert result["truncated"] is False


def test_json_shape_inspect_reports_malformed_json_as_an_input_problem(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    with pytest.raises(ToolInputInvalid):
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="json_shape_inspect",
            task_id=task,
            arguments={"document": "{not json"},
        )


def test_json_shape_inspect_stops_at_its_depth_bound(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="json_shape_inspect",
        task_id=task,
        arguments={"document": json.dumps({"a": {"b": {"c": {"d": 1}}}}), "max_depth": 2},
    ).result
    assert result["depth_reached"] == 2
    assert result["truncated"] is True


def test_json_shape_inspect_survives_a_very_deep_document(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    document: dict[str, Any] = {"leaf": 1}
    for _ in range(200):
        document = {"n": document}
    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="json_shape_inspect",
        task_id=task,
        arguments={"document": json.dumps(document), "max_depth": 4},
    ).result
    assert result["depth_reached"] == 4
    assert result["truncated"] is True


def _seed_execution(db: Database, user_id: int, artifacts: Sequence[tuple[str, str, int]]) -> int:
    """Create one execution and its artifacts directly through storage."""

    with db.transaction() as conn:
        task_id = TaskRepo().create(conn, user_id=user_id, title="t", goal="g")
        cursor = conn.execute(
            "INSERT INTO executions (task_id) VALUES (?)", (task_id,)
        )
        execution_id = int(cursor.lastrowid)
        for name, kind, size in artifacts:
            conn.execute(
                "INSERT INTO artifacts (execution_id, name, kind, size_bytes, created_at) "
                "VALUES (?, ?, ?, ?, 't')",
                (execution_id, name, kind, size),
            )
    return task_id


def test_artifact_metadata_reports_metadata_and_no_content(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _seed_execution(db, alice, [("out.txt", "file", 120), ("plot.png", "image", 4096)])
    with db.transaction() as conn:
        execution_id = int(
            conn.execute("SELECT id FROM executions WHERE task_id = ?", (task,)).fetchone()["id"]
        )

    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="artifact_metadata",
        task_id=task,
        arguments={"execution_id": execution_id},
    ).result

    assert result["artifact_count"] == 2
    assert sorted(result["names"]) == ["out.txt", "plot.png"]
    assert sorted(result["kinds"]) == ["file", "image"]
    assert result["total_size_bytes"] == 4216
    assert result["all_checksums_present"] is False
    assert "content" not in result
    assert "relative_path" not in result


def test_artifact_metadata_cannot_reach_another_users_execution(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    auth.register("bobby", PASSWORD)
    bob = _user_id(db, "bobby")
    bob_task = _seed_execution(db, bob, [("bob.txt", "file", 1)])
    alice = _user_id(db, "alice")
    alice_task = _new_task(db, alice)
    with db.transaction() as conn:
        bob_execution = int(
            conn.execute(
                "SELECT id FROM executions WHERE task_id = ?", (bob_task,)
            ).fetchone()["id"]
        )
    grants_for_dispatcher = dispatcher
    assert grants_for_dispatcher is dispatcher

    with pytest.raises(ToolExecutionFailed):
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="artifact_metadata",
            task_id=alice_task,
            arguments={"execution_id": bob_execution},
        )


def test_task_graph_summary_counts_only_the_callers_rows(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    auth.register("bobby", PASSWORD)
    bob = _user_id(db, "bobby")
    alice = _user_id(db, "alice")
    # bob holds the same capability; the difference under test is task scoping,
    # not grant presence.
    ToolGrantRepo(db, registry_ready=True).grant(
        user_id=bob, tool_name="task_graph_summary", granted_by="operator"
    )
    alice_task = _seed_execution(db, alice, [("a.txt", "file", 1), ("b.txt", "file", 1)])
    bob_task = _seed_execution(db, bob, [("bob.txt", "file", 1)])

    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="task_graph_summary",
        task_id=alice_task,
        arguments={},
    ).result
    assert result["artifact_count"] == 2
    assert result["execution_count"] == 1
    assert result["plan_count"] == 0

    # The same tool on bob's task reports only bob's rows, so the counts are a
    # property of the task rather than of the tool.
    bob_result = dispatcher.dispatch(
        _token(auth, "bobby"),
        tool_id="task_graph_summary",
        task_id=bob_task,
        arguments={},
    ).result
    assert bob_result["artifact_count"] == 1


def test_task_graph_summary_honours_its_include_filter(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    result = dispatcher.dispatch(
        _token(auth, "alice"),
        tool_id="task_graph_summary",
        task_id=task,
        arguments={"include": ["plan", "artifact"]},
    ).result
    assert set(result) == {"plan_count", "artifact_count"}


def test_task_graph_summary_rejects_an_unknown_resource_kind(
    granted: tuple[AuthorizationService, ToolDispatcher], db: Database, auth: AuthService
) -> None:
    _, dispatcher = granted
    alice = _user_id(db, "alice")
    task = _new_task(db, alice)
    with pytest.raises(ToolInputInvalid):
        dispatcher.dispatch(
            _token(auth, "alice"),
            tool_id="task_graph_summary",
            task_id=task,
            arguments={"include": ["evaluation_run"]},
        )


# ------------------------------------------------------- the task view


def test_the_view_never_hands_back_a_connection(db: Database) -> None:
    view = OwnedTaskView(db)
    for name in dir(view):
        if name.startswith("_"):
            continue
        member = getattr(view, name)
        if callable(member):
            inspect

            annotations = inspect.signature(member).parameters
            assert "conn" not in annotations
            assert "connection" not in annotations


def test_the_view_has_no_write_method(db: Database) -> None:
    view = OwnedTaskView(db)
    for name in dir(view):
        assert not name.startswith(("create", "insert", "update", "delete", "write"))


def test_the_view_applies_the_owner_predicate(db: Database) -> None:
    view = OwnedTaskView(db)
    alice = _register_id(db, "alice")
    bob = _register_id(db, "bobby")
    alice_task = _seed_execution(db, alice, [("a.txt", "file", 1)])
    bob_task = _seed_execution(db, bob, [("b.txt", "file", 1)])

    assert len(view.list_rows(resource="execution", user_id=alice, task_id=alice_task)) == 1
    assert view.list_rows(resource="execution", user_id=alice, task_id=bob_task) == []
    assert (
        view.list_rows(resource="artifact", user_id=bob, task_id=alice_task) == []
    ), "another user's rows were readable through the view"


def test_the_view_returns_none_for_a_row_the_caller_does_not_own(db: Database) -> None:
    view = OwnedTaskView(db)
    alice = _register_id(db, "alice")
    bob = _register_id(db, "bobby")
    alice_task = _seed_execution(db, alice, [("a.txt", "file", 1)])
    with db.transaction() as conn:
        execution_id = int(
            conn.execute(
                "SELECT id FROM executions WHERE task_id = ?", (alice_task,)
            ).fetchone()["id"]
        )
    assert view.get_row(resource="execution", user_id=alice, resource_id=execution_id)
    assert view.get_row(resource="execution", user_id=bob, resource_id=execution_id) is None


def test_the_view_limit_is_pushed_into_the_query(db: Database) -> None:
    view = OwnedTaskView(db)
    alice = _register_id(db, "alice")
    task = _seed_execution(db, alice, [("a.txt", "file", 1)])
    assert len(view.list_rows(resource="artifact", user_id=alice, task_id=task, limit=1)) == 1
    for bad in (0, -1, True, "5", MAX_VIEW_ROWS + 1):
        with pytest.raises(ValueError):
            view.list_rows(
                resource="artifact", user_id=alice, task_id=task, limit=bad
            )


def test_the_view_refuses_a_resource_it_does_not_own_safely(db: Database) -> None:
    view = OwnedTaskView(db)
    alice = _register_id(db, "alice")
    task = _seed_execution(db, alice, [])
    assert view.supports("artifact") is True
    # ``task`` is served by TaskRepo and ``evaluation_run`` has no owner column,
    # so neither may be reached through the owner-scoped view.
    assert view.supports("task") is False
    assert view.supports("evaluation_run") is False
    for unsupported in ("task", "evaluation_run", "user", None, 7):
        with pytest.raises(UnsupportedOwnedResource):
            view.list_rows(resource=unsupported, user_id=alice, task_id=task)


def test_counting_does_not_require_reading_every_row(db: Database) -> None:
    view = OwnedTaskView(db)
    alice = _register_id(db, "alice")
    bob = _register_id(db, "bobby")
    alice_task = _seed_execution(db, alice, [("a.txt", "file", 1), ("b.txt", "file", 1)])
    bob_task = _seed_execution(db, bob, [("bob.txt", "file", 1)])
    assert view.count_rows(resource="artifact", user_id=alice, task_id=alice_task) == 2
    assert view.count_rows(resource="artifact", user_id=alice, task_id=bob_task) == 0


def test_counting_is_distinct_from_paging(db: Database) -> None:
    """A count must cover every row even when a read is capped at the ceiling."""

    view = OwnedTaskView(db)
    alice = _register_id(db, "alice")
    task = _seed_execution(db, alice, [])
    with db.transaction() as conn:
        execution_id = int(
            conn.execute(
                "SELECT id FROM executions WHERE task_id = ?", (task,)
            ).fetchone()["id"]
        )
        for index in range(MAX_VIEW_ROWS + 25):
            conn.execute(
                "INSERT INTO artifacts (execution_id, name, created_at) VALUES (?, ?, 't')",
                (execution_id, f"a{index}.txt"),
            )
    assert view.count_rows(resource="artifact", user_id=alice, task_id=task) == (
        MAX_VIEW_ROWS + 25
    )
    assert (
        len(
            view.list_rows(
                resource="artifact", user_id=alice, task_id=task, limit=MAX_VIEW_ROWS
            )
        )
        == MAX_VIEW_ROWS
    )


# ------------------------------------------------------------- migrations


def test_schema_version_is_recorded_once(db: Database) -> None:
    with db.transaction() as conn:
        assert applied_version(conn) == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()["n"] == 1


def test_reinitializing_is_idempotent(db: Database) -> None:
    with db.transaction() as conn:
        init_db(conn)
        init_db(conn)
        assert applied_version(conn) == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()["n"] == 1


def test_a_v1_database_is_upgraded_to_the_current_version(tmp_path) -> None:
    """A database carrying only a version 1 marker must end up fully at v2.

    The interesting part is the marker: appending a second row would leave two
    competing claims about the schema, so the old row has to be replaced.
    """

    path = tmp_path / "old.db"
    legacy = Database(path)
    legacy.initialize()
    with legacy.transaction() as conn:
        conn.execute("DELETE FROM schema_migrations")
        conn.execute("INSERT INTO schema_migrations (version) VALUES (1)")
        conn.execute("DROP TABLE tool_permissions")

    upgraded = Database(path)
    upgraded.initialize()
    with upgraded.transaction() as conn:
        assert applied_version(conn) == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()["n"] == 1
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tool_permissions'"
        ).fetchone()
        assert exists is not None

    # Re-initializing the upgraded database must not drift or duplicate again.
    upgraded.initialize()
    with upgraded.transaction() as conn:
        assert applied_version(conn) == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()["n"] == 1


def test_upgrading_preserves_existing_data(tmp_path) -> None:
    path = tmp_path / "old.db"
    legacy = Database(path)
    legacy.initialize()
    with legacy.transaction() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at) "
            "VALUES ('carol', 'h', 't', 't')"
        )
        conn.execute("DELETE FROM schema_migrations")
        conn.execute("INSERT INTO schema_migrations (version) VALUES (1)")

    Database(path).initialize()
    with Database(path).transaction() as conn:
        assert conn.execute("SELECT username FROM users").fetchone()["username"] == "carol"


def test_a_newer_schema_is_refused_rather_than_written_to(db: Database) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM schema_migrations")
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)", (SCHEMA_VERSION + 1,)
        )
    with pytest.raises(SchemaVersionError):
        db.initialize()


def test_tool_permissions_has_no_secret_column(db: Database) -> None:
    with db.transaction() as conn:
        columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(tool_permissions)")
        }
    assert {"user_id", "tool_name", "scope", "granted_by", "active"} <= columns
    assert not columns & {"token", "secret", "password", "key"}


# -------------------------------------------------------------- Phase 10


def test_no_tool_layer_module_can_reach_a_shell_or_an_import(db: Database) -> None:
    """No module in the tool layer may import a process or module loader.

    Checked as source text across the whole package rather than on one file,
    because the dangerous import would land in whichever module somebody next
    edits.
    """

    import atlas.tools as tools_package

    forbidden = (
        "subprocess",
        "os.system",
        "os.popen",
        "os.exec",
        "eval(",
        "exec(",
        "importlib",
        "__import__",
        "pty.",
        "shutil.rmtree",
        "urllib",
        "requests",
        "socket",
    )
    package_dir = Path(tools_package.__file__).parent
    for path in sorted(package_dir.rglob("*.py")):
        # Docstrings are prose and legitimately say "no subprocess". Tokenizing
        # and dropping string and comment tokens is what makes this a check on
        # code rather than on wording — an AST walk would not help, because
        # unparsing the module node re-emits its docstring.
        code = _code_without_strings(path)
        for needle in forbidden:
            assert needle not in code, f"{path.name} contains {needle!r}"


def _code_without_strings(path: Path) -> str:
    kept: list[str] = []
    source = io.StringIO(path.read_text(encoding="utf-8"))
    for token in tokenize.generate_tokens(source.readline):
        if token.type in {
            tokenize.STRING,
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
        }:
            continue
        kept.append(token.string)
    return " ".join(kept)


def test_the_implementation_is_excluded_from_repr_and_equality() -> None:
    """A definition's identity is its contract, not its callable."""

    first = _definition()
    second = _definition()
    assert first == second, "two identical definitions should compare equal"
    rendered = repr(first)
    # ``implementation_id`` is audit metadata and legitimately appears; the
    # callable itself must not, or every log line and error message that reprs a
    # definition would carry a memory address.
    assert "implementation=" not in rendered
    assert "object at 0x" not in rendered
    assert "function" not in rendered


def test_there_is_one_call_site_for_a_tool_body() -> None:
    """Exactly one place in the codebase may invoke a registered body.

    Phase 09 asserted one call site, in the host dispatcher, and that was the
    whole of the bypass surface. Phase 10B moves the call into the guest, so the
    count in the host is now *zero* — a stronger claim than before, because a
    single in-process call site was still a call site that ran with the
    platform's privileges — and the one remaining call site is the confined
    worker.

    Both halves are asserted. Checking only the host would pass just as happily
    if the guest acquired a second one, and checking only the guest would leave
    the host free to call a body directly again. A tool body is untrusted code,
    so "wherever it is called from" is the property; where it happens to be today
    is not.
    """

    import atlas.sandbox.guest.worker as worker_module
    import atlas.tools.dispatch as dispatch_module

    call = "definition.invoke("

    host = Path(dispatch_module.__file__).read_text(encoding="utf-8")
    assert host.count(call) == 0, "the host dispatcher must not invoke a body directly"
    assert "definition.implementation(" not in host

    guest = Path(worker_module.__file__).read_text(encoding="utf-8")
    assert guest.count(call) == 1, "the confined worker is the one call site"

    # No other module in either package may call a body, so adding a third call
    # site anywhere is a test failure rather than a review comment.
    import atlas.sandbox as sandbox_package
    import atlas.tools as tools_package

    for package in (tools_package, sandbox_package):
        package_dir = Path(package.__file__).parent
        for path in sorted(package_dir.rglob("*.py")):
            if path in (Path(dispatch_module.__file__), Path(worker_module.__file__)):
                continue
            count = path.read_text(encoding="utf-8").count(call)
            assert count == 0, f"{path} invokes a tool body at a third call site"


def test_no_builtin_tool_reads_the_host_filesystem(
    granted: tuple[AuthorizationService, ToolDispatcher]
) -> None:
    _, dispatcher = granted
    for definition in default_registry().list_definitions():
        assert definition.filesystem_access is FilesystemAccess.NONE
    # The artifact tool is the one that would be tempted, and it reports only
    # database metadata: no content and no relative_path key reaches a result.
    assert "relative_path" not in dispatcher.describe("artifact_metadata")["output_schema"][
        "properties"
    ]
