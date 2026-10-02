# ATLAS-X Tool Registry Review

Phase 09. This review records what the controlled tool registry and the dispatch
boundary now are, what they are tested to be, and what they are not. It is
written after the implementation and its tests; every IMPLEMENTED/TESTED label
below was established by reading code and by a named test in
`tests/test_tools.py`.

Nothing here claims ATLAS-X is sandboxed or safe against a malicious in-process
caller. It claims a specific set of properties and states the residual limits
next to them.

## Review scope

- **In scope:** what a tool is allowed to declare, how a tool becomes
  registered, how a grant is persisted and scoped, the ordering inside
  dispatch, input/output bounds, the per-task call budget, provenance, and the
  five built-in tools.
- **Out of scope and untouched:** the sandbox (Phase 10), planner, orchestrator,
  executor, verifier, recovery, evaluation, UI, and the model runtime. No file
  outside `atlas/tools/`, `atlas/storage/migrations.py`,
  `atlas/storage/tool_grants.py`, `atlas/storage/owned_resources.py`,
  `atlas/storage/__init__.py`, and `tests/` was changed, apart from
  documentation.
- **Authority:** `docs/SYSTEM_SPECIFICATION.md` (Tool, ToolPermission, section 8
  traceability), `docs/THREAT_MODEL.md` (A1, A3, A4, D1, non-guarantees),
  `docs/STORAGE_REVIEW.md` (section 12 version checks, section 13
  `relative_path`), `docs/CONFIGURATION_REVIEW.md` (unapplied tool limits),
  `docs/AUTHORIZATION_REVIEW.md` (the `ToolGrantSource` contract this phase
  implements), and `docs/DECISIONS.md` (SQLite-first, bounded resources,
  security-first).

## 1. What was implemented

| Component | Label | Evidence |
|---|---|---|
| `atlas/tools/definition.py` — `ToolDefinition`, `ToolLimits`, `ToolContext`, admissibility sets | IMPLEMENTED | `test_host_filesystem_access_requires_the_sandbox_and_is_refused`, `test_network_access_is_refused`, `test_non_determinism_is_refused` |
| `atlas/tools/schema.py` — `SchemaField`, `ToolSchema`, `validate_input`, `validate_output` | IMPLEMENTED | `test_numeric_field_without_bounds_is_not_constructible` and the eleven sibling bound tests |
| `atlas/tools/registry.py` — `ToolRegistry`, `default_registry`, `freeze` | IMPLEMENTED | `test_default_registry_is_frozen_and_holds_the_five_built_ins`, `test_frozen_registry_refuses_further_registration` |
| `atlas/tools/context.py` — `OwnedTaskView`, owner-scoped and read-only | IMPLEMENTED | `test_the_view_never_hands_back_a_connection`, `test_the_view_has_no_write_method`, `test_the_view_applies_the_owner_predicate` |
| `atlas/tools/dispatch.py` — `ToolDispatcher`, `DispatchLimits`, `ToolInvocation` | IMPLEMENTED | `test_dispatch_without_a_grant_never_runs_the_implementation` |
| `atlas/tools/errors.py` — nine distinct failure classes with stable codes | IMPLEMENTED | `test_every_error_carries_a_stable_code` |
| `atlas/storage/tool_grants.py` — `ToolGrantRepo` implementing the Phase 08 `ToolGrantSource` | IMPLEMENTED | `test_grant_is_persisted_and_readable_for_its_owner`, `test_grant_survives_a_new_repo_instance` |
| `atlas/storage/migrations.py` — `tool_permissions`, `SCHEMA_VERSION = 2`, `SchemaVersionError` | IMPLEMENTED | `test_a_v1_database_is_upgraded_to_the_current_version`, `test_a_newer_schema_is_refused_rather_than_written_to` |
| `atlas/tools/builtin/` — five tools | IMPLEMENTED, green | `test_text_statistics_counts_text` … `test_task_graph_summary_rejects_an_unknown_resource_kind` |
| `tests/test_tools.py` — 154 collected cases | IMPLEMENTED, green | this phase's pytest run |
| A `tools` table | NOT IMPLEMENTED, deliberately | see section 3 |
| Role, attribute, or ABAC evaluation | NOT IMPLEMENTED | `AZ-06` accepted in Phase 08; unchanged |
| Process isolation, interruption, memory or CPU limits | NOT IMPLEMENTED | Phase 10; see section 8 |

## 2. The dispatch order is the security property

`ToolDispatcher.dispatch` performs exactly these steps, in this order:

1. `AuthorizationService.authenticate` — the actor comes from a session token.
2. `ToolRegistry.find` — malformed and unknown ids both fail closed.
3. Task id validation.
4. **`AuthorizationService.require_tool_invocation`** — the capability decision.
5. Per-task call budget.
6. `tool.invoked` provenance.
7. Input schema validation and the input byte bound.
8. The implementation, through `ToolDefinition.invoke`.
9. Elapsed-budget check, output schema validation, output byte bound.
10. `tool.completed` provenance, and the result.

Step 4 is before step 7 deliberately. Validating input first would let a caller
without the grant learn the tool's field names, bounds, and error phrasing by
comparing failures — a free oracle for the shape of a capability they may not
use. `test_authorization_runs_before_input_validation` asserts that four
different payloads, valid and invalid alike, all produce the same authorization
denial and no tool error.

Step 5 is before step 6 deliberately. Counting the attempt is what enforces the
budget, and writing the record after the check means a caller who is out of
budget cannot grow the audit table by dispatching again.

**The mandatory test.** `test_dispatch_without_a_grant_never_runs_the_implementation`
registers a tool whose body increments a counter, dispatches it with no grant,
and asserts `counter.calls == 0`. Asserting only that a `PermissionDenied` was
raised would also pass if the implementation had run first and authorization had
failed afterwards. `test_a_revoked_grant_stops_the_implementation_on_the_next_call`
repeats the assertion across a revocation.

## 3. Two places this deviates from the specification, on purpose

**No `tools` table.** `docs/SYSTEM_SPECIFICATION.md` lists a `Tool` entity. The
registry here is code, not rows, so a table would be a second source of truth
that could disagree with the code at runtime. The table is not created;
`docs/STORAGE_REVIEW.md` should be amended to say so. A consequence worth naming:
`tool_permissions.tool_name` is a string with no foreign key, so a grant can name
a capability nothing implements. Such a grant is inert — the registry lookup at
step 2 fails first — but it is also invisible to a foreign key, which is a
weaker guarantee than a schema-level one.

**Provenance is written directly, not through `append_provenance_event`.** The
dispatcher inserts into `provenance_events` itself rather than calling the
Phase 08 service method. The dispatcher is inside the trusted boundary and has
already authorized the target, so the extra round trip buys nothing, and routing
through the service would re-authenticate mid-dispatch. The tradeoff is that the
dispatcher trusts its own `task_id` after step 4 rather than re-deriving it from
storage the way `append_provenance_event` does. This is acceptable only because
step 4 established ownership of that exact id, and the file link in section 5
records it as a place a later phase should re-examine.

## 4. What a tool may declare

`ToolDefinition.__post_init__` refuses a definition rather than degrading it:

| Declaration | Result | Reason |
|---|---|---|
| `filesystem_access` other than `NONE` | `ToolUnsupported` | needs Phase 10 confinement |
| `network_access = ALLOWED` | `ToolUnsupported` | no network tool exists in this design |
| `determinism = NON_DETERMINISTIC` | `ToolUnsupported` | Phases 13 and 21 consume the declaration |
| `requires_sandbox = True` | `ToolUnsupported` | no sandbox exists yet |
| a prohibited capability | `ToolUnsupported` | the policy would deny it anyway; refusing at registration keeps it out of listings and provenance |
| a non-`MAJOR.MINOR.PATCH` version | `ToolDefinitionInvalid` | a version is what makes a digest reproducible |
| unbounded numeric, string, or array bounds | `ValueError` at schema construction | nothing unbounded may reach an implementation |

Widening any of these is a reviewed change to `definition.py` made together with
the phase that supplies the missing control. It is not a matter of flipping a
setting.

## 5. Grants

`tool_permissions` holds one row per `(user, capability, scope)`. A grant names a
capability, a user, a scope, and an active flag. There is no role column, no
wildcard, and no "all tools" row; the absence of a row is the denial.

- **Owner-scoped reads.** `grants_for` filters on the user id the authorization
  boundary resolved, in SQL. `test_grant_is_persisted_and_readable_for_its_owner`
  asserts bob's grant list is empty.
- **Scope is a closed vocabulary.** `NULL` means the user's own resources;
  `task:<id>` narrows to one task. A stored scope outside that vocabulary is
  *dropped on read*, not repaired — guessing what a malformed scope was meant to
  authorize is the failure mode a security decision must not have.
- **No secrets.** No token, key, or password column exists, and
  `test_a_grant_row_holds_no_secret` asserts it.
- **Writes are the operator's.** `grant` and `revoke` take no session token and
  are reachable from no request path. There is no method that grants a capability
  to "whoever is asking".
- **Registry readiness is reported honestly.** `registry_ready` is a constructor
  argument, so a deployment with no tool set denies with `TOOL_NO_REGISTRY`
  rather than reading a grant as permission for something unimplemented.

## 6. Bounds, and what they do not do

| Bound | Source | Enforced |
|---|---|---|
| Field type, length, item count, numeric range | declared schema | before the implementation |
| Input bytes | `ToolLimits.max_input_bytes` | before the implementation |
| Output bytes | `ToolLimits.max_output_bytes`, `DispatchLimits.max_output_chars`, `HARD_OUTPUT_CEILING` | after the implementation |
| Tool calls per task | `DispatchLimits.max_tool_calls`, from `Settings` | before the implementation |
| Elapsed time | `ToolLimits.timeout_seconds` | **after** the call returns |
| Rows a tool may read | `MAX_VIEW_ROWS`, pushed into SQL | per query |
| Memory, CPU, filesystem, network | — | **not bounded** |

Two of these deserve emphasis rather than a table row.

**The elapsed budget detects; it does not interrupt.** An in-process function
that has already returned cannot be stopped. A tool that hangs holds the request
thread until it finishes, and the check then fails the invocation it could not
prevent. This is Phase 10's work, and the limit is recorded in
`docs/CONFIGURATION_REVIEW.md` as still not enforceable.

**The call budget is derived from the audit log, not from memory.** Counting
`tool.invoked` events means the budget survives a process restart and cannot be
reset by restarting — `test_the_budget_survives_a_new_dispatcher` asserts it.

## 7. The five built-in tools

| Tool | Reads | Determinism | Never does |
|---|---|---|---|
| `text_statistics` | caller-supplied text | deterministic | touch storage |
| `numeric_summary` | caller-supplied numbers | deterministic | touch storage |
| `json_shape_inspect` | caller-supplied JSON text | deterministic | return any value it walks past |
| `artifact_metadata` | the caller's own artifact rows | state-dependent | read a file, return `content` or `relative_path`, open a host path |
| `task_graph_summary` | the caller's own row counts | state-dependent | read any content |

`artifact_metadata` is the one that would be tempting to make a file reader. It
declines, and the reason is recorded in the module: `artifacts.relative_path` is
not validated (`docs/STORAGE_REVIEW.md` §13) and confinement belongs to Phase 10,
so a path reader in Phase 09 would claim a control the code does not have.

`json_shape_inspect` walks iteratively and never returns a value, so a dataset can
be profiled for unexpected nested fields without its contents reaching a log, a
provenance record, or a UI.

## 8. Non-guarantees

These are the honest limits. None is fixed by anything in this phase.

- **Not sandboxed.** No process isolation, no syscall restriction, no memory or
  CPU ceiling, no network namespace. A tool body runs in the application's
  process with the application's privileges.
- **Timeout is detection, not interruption.** See section 6.
- **An in-process caller holding a `ToolRegistry` can read
  `definition.implementation` and call it.** Python has no access control.
  `ToolDefinition.invoke` gives the dispatcher one greppable call site and
  excludes the callable from `repr` and equality, but it does not make the body
  unreachable. The real guarantee is that *every request* is authorized, not
  that in-process code cannot skip authorization. Closing this needs a process
  boundary, which is Phase 10.
- **Direct SQLite access is trusted.** `AuthorizationService` protects callers
  that go through it. Code holding the `Database` object can read any table. The
  same is true of the tool layer, which is why `atlas/tools/context.py` withholds
  the connection from implementations rather than trusting them with it.
- **Provenance is not tamper-evident.** Digests identify which input ran, so a
  stored number and a recomputed number compare. Nothing is signed or chained, so
  this is not proof that a record is unaltered. `AZ-02` (events with no owning
  task) is unchanged.
- **The registry is the whole tool set.** Five tools, all pure or
  owner-scoped-read. There is no tool that writes, and no planner to invoke one.
- **`SecretsRedactionFilter` remains unwired** (`AZ-05`), so complete runtime log
  redaction is still not established.
- **Scope is only two levels.** A grant is global-to-the-user or
  task-specific. There is no per-resource or per-artifact scope, and no role.

## 9. Traceability

| Requirement | Where |
|---|---|
| Explicit, persistent, scoped, revocable tool grants | §5, `atlas/storage/tool_grants.py` |
| Single dispatch path; authorization before execution | §2, `test_dispatch_without_a_grant_never_runs_the_implementation` |
| Validated, bounded, typed tool contracts | §4, §6 |
| Smallest safe built-in set | §7 |
| Owner-scoped, least-privilege data access | `atlas/tools/context.py`, `test_the_view_applies_the_owner_predicate` |
| Stable, schema-versioned persistence | `SCHEMA_VERSION = 2`, `SchemaVersionError` |
| Documented non-goals and refusals | §4, §8 |

## 10. Status of this document

Written after the implementation. Not to be edited by a later phase to remove a
limitation from §8; add to §8 and say which phase closed it.
