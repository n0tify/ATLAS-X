# ATLAS-X Authorization Review

Phase 08. This review records what the authorization layer now is, what it is
tested to be, and what it is not. It is written after the implementation and its
tests, and every IMPLEMENTED/TESTED label below was established by reading code
and by a named test in `tests/test_authorization.py`.

Nothing here claims ATLAS-X is secure. It claims a specific, narrow set of
properties, and states the residual limits next to them.

## Review scope

- **In scope:** identity binding, resource ownership, operation permissions, the
  tool-authorization interface, fail-closed failure behavior, and the tests that
  establish each.
- **Out of scope and untouched:** the tool registry and any tool execution
  (Phase 09), the sandbox (Phase 10), planner, orchestrator, verifier, recovery,
  UI, and the model runtime. No file outside `atlas/security/`,
  `atlas/storage/`, and `tests/` was changed, apart from documentation.
- **Authority:** `docs/SYSTEM_SPECIFICATION.md` (entities, security principles,
  section 8 traceability), `docs/THREAT_MODEL.md` (A3, A4, D1, non-guarantees),
  `docs/STORAGE_REVIEW.md` (section 4 isolation, section 12 prerequisites),
  `docs/AUTHENTICATION_REVIEW.md` (section 11 required changes), and
  `docs/DECISIONS.md` (local-first, SQLite-first, security-first).

## 1. What was implemented

| Component | Label | Evidence |
|---|---|---|
| `atlas/security/policy.py` — `Resource`, `Operation`, `DenyReason`, `Decision`, `PERMITTED_OPERATIONS`, `decide_operation`, `decide_tool_invocation` | IMPLEMENTED | pure functions, no I/O; asserted by `test_policy_layer_performs_no_io` |
| `atlas/security/errors.py` — `AuthorizationError` + `Unauthenticated`, `InvalidAuthorizationRequest`, `PermissionDenied`; one external message | IMPLEMENTED | `test_denied_lookup_is_indistinguishable_from_a_missing_one` |
| `atlas/security/identity.py` — `Identity`, `IdentityResolver` (session token → actor) | IMPLEMENTED | `tests/test_authorization.py` section A |
| `atlas/security/service.py` — `AuthorizationService`, the single enforcement boundary | IMPLEMENTED | sections B–F |
| `atlas/storage/owned_resources.py` — `OwnedResourceRepo`, `OwnedTable`, `owned_table_for` | IMPLEMENTED | `test_direct_repository_use_cannot_read_another_users_row` |
| `atlas/storage/__init__.py`, `atlas/security/__init__.py` — exports | IMPLEMENTED | import check |
| `tests/test_authorization.py` — 128 test cases across the six required areas | IMPLEMENTED, green | this phase's pytest run |
| `tools` / `tool_permissions` tables and a grant store | NOT IMPLEMENTED | Phase 09; `decide_tool_invocation` returns `TOOL_NO_REGISTRY` |
| Role or attribute-based access control | NOT IMPLEMENTED, deliberately | see section 3 |
| Filesystem, network, or host-path authorization | NOT IMPLEMENTED | sandbox phase; see section 7 |

`SCHEMA_VERSION` remains `1`. **No migration was required** — see section 5.

## 2. The authorization boundary

> `AuthorizationService` is the only public entry point for reading or writing
> user-owned data. Repositories scope rows; the service decides. Nothing above
> it may substitute a repository call for a service call, and nothing in it
> accepts a caller-supplied actor.

The split is deliberate:

- **Policy** (`policy.py`) answers "is this operation defined for this resource
  kind for an authenticated actor". It is pure, immutable, and has no I/O.
- **Storage** (`owned_resources.py`) answers "which rows belong to this user".
  Every descendant read joins to `tasks.user_id` and carries that predicate.
  There is no `get`, `get_by_id`, or `list_all` on `OwnedResourceRepo`
  (`test_owned_repository_exposes_no_unscoped_read`).
- **The service** joins the two, in one transaction, and raises.

`TaskRepo` remains the owner-scoped accessor for `tasks`, because `tasks` carries
its own `user_id`. Its methods were not modified.

### The actor cannot be nominated

No public method of `AuthorizationService` accepts `user_id` or `actor_id`;
`test_no_public_service_method_accepts_a_user_id` enforces this by signature
inspection, so a future edit that adds such a parameter fails the suite.
Identity is always derived from a session token through
`IdentityResolver.from_session_token`, which delegates the expiry and
revocation decision to `AuthService.validate_session` and re-confirms the
session row is still present. Authentication was not redesigned or weakened.

## 3. The model, and why it is this small

Four things are distinguished, and nothing else exists:

1. **Identity** — the `Identity` produced from a session token.
2. **Ownership** — the actor owns the row, resolved through `tasks.user_id`.
3. **Operation permission** — the operation is in `PERMITTED_OPERATIONS` for
   that resource kind.
4. **Tool permission** — the capability is not prohibited, a registry exists, and
   the actor holds a grant.

`PERMITTED_OPERATIONS` is the complete policy table:

| Resource | Permitted operations |
|---|---|
| `task` | `create`, `read`, `delete`, `append` |
| `plan`, `plan_step`, `execution`, `artifact`, `verification`, `failure`, `recovery_attempt` | `read` |
| `execution` | additionally `append` |
| `provenance_event` | `read` |
| `evaluation_run` | none |

There are **no roles, no permission strings in the database, and no elevation
path.** Ownership is the only grant. `update` is defined in the `Operation` enum
and permitted nowhere, which is what lets a test distinguish "unknown operation"
from "known but ungranted" (`test_ungranted_operations_are_denied`). The table
is exposed as a `MappingProxyType` of `frozenset`, so it cannot be widened at
runtime (`test_policy_tables_are_immutable`).

A4 (privilege escalation) is answered structurally rather than by a control that
could be bypassed: no repository can reassign `tasks.user_id`, asserted by
`test_task_ownership_cannot_be_reassigned_by_any_repository`, which inspects
every public method of `TaskRepo`, `UserRepo`, and `OwnedResourceRepo` for an
ownership update and asserts the setters do not exist.

## 4. Tool authorization (interface only)

`decide_tool_invocation(identity_id, tool_name, resource, resource_id, grants)`
and `AuthorizationService.require_tool_invocation(...)` answer the Phase 09
question and stop there. The evaluation order is fixed and deny-by-default:

1. invalid identity → `MISSING_IDENTITY`
2. name is not a string / normalizes to nothing → `TOOL_UNKNOWN`
3. name normalizes to a prohibited capability → `TOOL_CAPABILITY_PROHIBITED`
4. resource kind unknown → `UNKNOWN_RESOURCE`; ownership undecided →
   `RESOURCE_OWNERSHIP_UNDECIDED`
5. the actor does not own `resource_id` → `RESOURCE_NOT_OWNED` (service layer)
6. no registry → `TOOL_NO_REGISTRY`
7. no matching grant for **this** user → `TOOL_NO_GRANT`
8. otherwise allow

`PROHIBITED_TOOL_CAPABILITIES` is checked before the grant lookup, so no grant
source can authorize arbitrary shell, subprocess, Python eval, filesystem, or
network capability even if it claims to (`test_prohibited_capability_classes_can_never_be_granted`).
Names are compared after removing case and separators, so `Sub-Process`,
`sub_process`, and `SUBPROCESS` are the same name
(`test_prohibited_names_are_matched_after_normalization`).

Grants are per user and optionally scoped to `"task:<id>"`; a task-scoped grant
does not authorize another task
(`test_task_scoped_grant_does_not_authorize_another_task`). Because no registry
and no grant store exist, **every** tool decision in Phase 08 is a denial, and
the tests assert that. No test asserts an allow is possible in production, only
that the policy would allow a genuine grant — `test_explicit_grant_allows_the_decision`
uses a fake in-test grant source.

## 5. Ownership propagation, and the two places it breaks

Every task-descendant resource reaches an owner through `tasks.user_id`:

| Resource | Path to an owner | Hops |
|---|---|---|
| `plan` | `plans.task_id → tasks.user_id` | 1 |
| `plan_step` | `plan_steps.plan_id → plans.task_id → tasks.user_id` | 2 |
| `execution` | `executions.task_id → tasks.user_id` | 1 |
| `artifact`, `verification`, `failure`, `recovery_attempt` | `*.execution_id → executions.task_id → tasks.user_id` | 2 |
| `provenance_event` | `task_id → tasks`, else `execution_id → executions.task_id → tasks` | 1–2 |

Two resources do not resolve, and neither was repaired:

1. **`provenance_events` with both `task_id` and `execution_id` null.** This is
   a deliberate consequence of the durability design: the columns are nullable
   with `ON DELETE SET NULL` so audit events survive task deletion
   (`docs/THREAT_MODEL.md` D4), and account-level events such as
   `user.registered` have no task. Such a row has **no resolvable owner**, so it
   is denied to every user, including the account it concerns
   (`test_provenance_without_a_resolvable_owner_is_invisible_to_everyone`).
   This is a real limitation, not a bug: account-level provenance is currently
   unreadable through the authorization boundary. Closing it needs a decision
   about whether a `user_id` column belongs on `provenance_events`, which is
   not a Phase 08 decision.
2. **`evaluation_runs` has no owner column and no relationship to a user.**
   Whether benchmark runs are global research data or user-owned is explicitly
   deferred by `docs/STORAGE_REVIEW.md` section 12, item 3. Rather than invent
   an ownership model, the resource is denied **by name** with
   `RESOURCE_OWNERSHIP_UNDECIDED` (`test_evaluation_runs_are_denied_by_name`),
   and no owner-scoped SQL definition exists for it. This is why no migration
   was needed: the gap is answered with a denial, not with a schema change.

Provenance appends derive their task link from storage instead of trusting the
caller: `append_provenance_event` takes the resource it acted on, verifies
ownership, and writes `task_id` or `execution_id` itself. A caller cannot file an
event against another user's task by supplying that task's id
(`test_provenance_append_derives_ownership_instead_of_trusting_the_caller`,
`test_provenance_append_onto_another_users_execution_is_denied`).

## 6. Failure behavior

- **Fail closed.** Every unexpected condition becomes an `AuthorizationError`
  subclass. No path converts a failure into an allow.
- **No existence oracle.** A row the actor does not own and a row that does not
  exist produce the same exception type and the same message, `"access denied"`
  (`test_denied_lookup_is_indistinguishable_from_a_missing_one`). Internal
  classification is available on `.reason` for diagnostics and is never part of
  the message.
- **Dependencies fail loudly, not permissively.** An error from the identity
  resolver or from a repository propagates rather than being converted into a
  decision (`test_identity_dependency_failure_is_not_converted_into_an_allow`,
  `test_repository_lookup_failure_is_not_converted_into_an_allow`).
- **Malformed input is refused before any query.** Resource ids must be positive
  SQLite row ids; `True`, `0`, `-1`, `"1"`, `1.5`, and `2**63` are all rejected
  (`test_malformed_resource_identifier_is_rejected_by_the_boundary`). `bool` is
  rejected explicitly because `True` would otherwise address row 1.
- **Nothing internal escapes.** An unsupported list filter is converted into
  `InvalidAuthorizationRequest(UNSUPPORTED_FILTER)` rather than leaking a
  storage `LookupError` (`test_unsupported_filter_does_not_leak_an_internal_error`).
- **SQL.** Statement text is assembled only from the frozen `OwnedTable`
  registry; every caller value is a bound parameter. No caller-supplied value
  reaches the SQL string.
- **Logging.** Denials are logged at WARNING with actor id, resource kind,
  operation, and reason code, and nothing else. No token, password, or hash is
  logged (`test_denial_log_carries_a_reason_and_no_secret_material`).
  **Limitation:** `SecretsRedactionFilter` still is not attached to any runtime
  handler (finding H-02 in `docs/AUTHENTICATION_REVIEW.md`, unchanged). Log
  redaction completeness is not claimed.

## 7. Transaction and concurrency behavior

Every service method performs its authorization check and its effect inside a
single `Database.transaction()`, so a decision is never made against state the
following statement cannot see. SQLite's write lock serializes the delete path,
and task ownership is immutable in the current implementation, so no
check-then-act window can change an authorization outcome today.

Residual, stated rather than engineered away: `Database.transaction()` opens a
deferred transaction, so two concurrent readers can both pass a check before
either writes. This is acceptable only because ownership cannot change. If a
future phase adds ownership reassignment or shared task membership, this method
needs a stronger guarantee first.

## 8. Threat coverage

| Threat | Status after Phase 08 | Basis |
|---|---|---|
| A3 Broken object-level authorization | **Reduced for every existing user-owned resource.** All task descendants are owner-scoped in SQL, and cross-user access is denied for reads, lists, deletes, and provenance appends. | `tests/test_authorization.py` sections B, C, E |
| A4 Privilege escalation | **Materially reduced.** No roles, no permission storage, no elevation path, no ownership reassignment. | section 3 above |
| D1 Cross-user data access | **Reduced for storage-facing operations.** Every descendant read carries the owner predicate. | `test_direct_repository_use_cannot_read_another_users_row` |
| A1, A2, A5, A6, A7 | Unchanged; still owned by Phase 07 authentication. | `docs/AUTHENTICATION_REVIEW.md` |

Residual risk that remains after this phase:

- Any component that holds a `sqlite3.Connection` can still write arbitrary SQL
  and bypass every predicate. This is unchanged, is a property of Python, and is
  the outer trust boundary of the process.
- There is no browser, HTTP, or UI boundary, so no authorization path is exposed
  to a remote caller yet. The boundary is exercised only in-process.
- Authorization is not filesystem authorization. Owning a row authorizes no host
  path, and nothing in this phase validates a path.

## 9. Findings

| ID | Severity | Finding | Status |
|---|---|---|---|
| AZ-01 | High | `evaluation_runs` has no owner, so no ownership check is possible | **Open by design.** Denied by name; ownership decision deferred by `docs/STORAGE_REVIEW.md` §12.3 |
| AZ-02 | Medium | Provenance events with no task and no execution have no resolvable owner and are unreadable, including account-level events | **Open by design.** Denied; closing it needs a schema/ownership decision |
| AZ-03 | Medium | `AuthService.change_password(user_id, ...)` is not bound to a session principal (finding M-05 in `docs/AUTHENTICATION_REVIEW.md`) | **Open, deliberately not changed here.** It re-verifies the current password, so a caller-selected `user_id` is not by itself an escalation, and no surface exposes password management. It must be bound to the session principal before any such surface exists |
| AZ-04 | Low | `SessionRepo.get_valid()` still does not check `expires_at` (finding M-04) | **Partially mitigated.** The authorization boundary delegates to `AuthService.validate_session`, which does check it, and re-confirms it. The repository-level contract is still misleading |
| AZ-05 | Low | `SecretsRedactionFilter` is not attached to runtime handlers (finding H-02) | **Open.** Unchanged from Phase 07; not claimed as complete |
| AZ-06 | Informational | No role model exists | **Accepted.** Ownership-only is the smallest sufficient model; revisit only if a real requirement appears |

## 10. Required before the next protected surface

1. Supply a real grant source and registry in Phase 09, and make every tool
   dispatch call `require_tool_invocation` first.
2. Decide `evaluation_runs` ownership (AZ-01) before any multi-user UI or
   benchmark surface reads it.
3. Decide whether `provenance_events` needs a `user_id` (AZ-02) before account
   level audit history is displayed.
4. Bind password change to the session principal (AZ-03) before exposing it.
5. Re-run this cross-user matrix for every new query surface (D1's standing
   requirement) — `docs/STORAGE_REVIEW.md` §12.2.

## Verification

Newly run in this phase, in the project environment (`.venv`, Python 3.11):

- `pytest` → **164 passed** (36 pre-existing from Phases 06–07, 128 new in
  `tests/test_authorization.py`).
- `ruff check .` → **All checks passed!**
- `mypy atlas` → **Success: no issues found in 28 source files** (23 before this
  phase; 5 new modules).

No test was skipped, deselected, or suppressed. No result in this document is
carried forward from an earlier phase.

A post-implementation quality audit removed decorative `# ----` banner comments
from `atlas/security/service.py` and `tests/test_authorization.py` and reduced
the `atlas/security/__init__.py` docstring to a one-line package summary. No
behavior, signature, export, or test changed; no pre-existing project file used
that banner style. Post-audit results are identical to the figures above.

Files created: `atlas/security/policy.py`, `atlas/security/errors.py`,
`atlas/security/identity.py`, `atlas/security/service.py`,
`atlas/storage/owned_resources.py`, `tests/test_authorization.py`, and this
document. Files modified: `atlas/security/__init__.py`,
`atlas/storage/__init__.py`, and documentation. No dependency, environment, or
schema change. Phase 09 is not started.

### Documents updated by this phase

`SECURITY.md` (authorization design, two new standing rules, four explicit
non-guarantees), `docs/THREAT_MODEL.md` (A1, A3, A4, D1 mitigation, residual,
and test lines; two new non-guarantees; threat→control map),
`docs/ARCHITECTURE_RECONCILIATION.md` (§10 addendum superseding specific Phase 4
rows — the snapshot itself is unedited), `docs/AUTHENTICATION_REVIEW.md` (§13
prerequisite cross-reference; no finding changed), and this document. No other
document was modified, and no decision recorded in C-01…C-09 or D-01…D-12 was
altered, closed, or silently resolved.

