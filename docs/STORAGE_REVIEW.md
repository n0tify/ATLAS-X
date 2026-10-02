# ATLAS-X Storage Review

Status: **Phase 06 review gate.** Review only. This document records the current
SQLite implementation, its guarantees, its gaps, and the work required before
authorization or execution features are introduced. No application code, schema,
authorization, sandbox, planner, verifier, recovery, or tool-execution behavior
was changed by this phase.

Review date: 2026-09-25

## Review scope

The following storage sources were inspected:

- `atlas/storage/db.py`
- `atlas/storage/repositories.py`
- `atlas/storage/migrations.py`
- `tests/test_storage.py`

Related configuration, authentication, security, specification, threat-model,
and architecture documents were consulted where they describe storage
boundaries. `docs/STORAGE_REVIEW.md` did not exist before this review. The other
requested documents (`DECISIONS.md`, `environment-reconnaissance.md`,
`TECHNOLOGY_STACK.md`, `SYSTEM_SPECIFICATION.md`, `THREAT_MODEL.md`,
`ARCHITECTURE_RECONCILIATION.md`, and `CONFIGURATION_REVIEW.md`) are present.

## 1. Current SQLite architecture

ATLAS-X uses Python's standard-library `sqlite3` module. There is no database
server, ORM, migration framework, or external persistence service.

`Database` owns the database path and opens a new connection for each call to
`connect()` or `transaction()`:

- The parent directory is created when the path is not `:memory:`
  (`atlas/storage/db.py:18-23`).
- Every connection enables `PRAGMA foreign_keys = ON`, requests WAL journal
  mode, uses `synchronous = NORMAL`, and sets a 5,000 ms busy timeout
  (`atlas/storage/db.py:25-35`).
- `transaction()` commits after the context body succeeds, rolls back on any
  `BaseException`, and closes the connection in all cases
  (`atlas/storage/db.py:38-48`).
- `initialize()` runs the deterministic schema initializer inside one
  transaction (`atlas/storage/db.py:50-52`).
- The configured `timeout_seconds` is passed to `sqlite3.connect`, but the
  subsequent `busy_timeout` pragma fixes the effective busy timeout at 5,000 ms
  (`atlas/storage/db.py:19-21`, `atlas/storage/db.py:31`).

The current architecture is appropriate for a single-host, local-first
application and gives each operation a short-lived connection. It is not a
connection pool, a multi-process coordination layer, or an authorization
boundary. WAL and the busy timeout reduce some reader/writer contention but do
not guarantee that concurrent writers will never receive
`database is locked`.

The database file is a host filesystem object. Its protection ultimately depends
on the operating-system account and filesystem permissions. No application-level
filesystem confinement is implemented in the storage layer.

## 2. Current schema

> **Phase 09 update.** `atlas/storage/migrations.py` now defines schema version
> `2` and 14 tables: `tool_permissions` was added, `SchemaVersionError` and
> `check_schema_version()` now refuse a database written by a newer build, and
> `init_db()` replaces the version marker rather than appending one, so a
> migrated database cannot hold two competing version claims. The
> `Tool` entity planned in `docs/SYSTEM_SPECIFICATION.md` is deliberately **not**
> implemented as a table; the registry is code, so a table would be a second
> source of truth. `tool_permissions.tool_name` therefore carries no foreign
> key, and a grant naming an unimplemented capability is inert rather than
> impossible. See `docs/TOOL_REGISTRY_REVIEW.md` §3 and §5.

`atlas/storage/migrations.py` defines schema version `1` and 13 tables. All
creation statements use `IF NOT EXISTS`; `init_db()` then inserts the version
with `INSERT OR IGNORE` (`atlas/storage/migrations.py:13-15`,
`atlas/storage/migrations.py:201-207`).

| Table | Purpose | Important constraints and relationships |
|---|---|---|
| `schema_migrations` | Records the applied version | `version` is the primary key; one row is expected. **Phase 09:** a compatibility check now runs, and the marker is replaced rather than appended |
| `users` | Account identity and password-derived material | Unique `username`; stores `password_hash`, lockout state, and timestamps |
| `sessions` | Hashed session identifiers | `user_id` references `users` with `ON DELETE CASCADE`; `token_hash` is unique; expiry/revocation timestamps are stored |
| `tasks` | User-owned research tasks | `user_id` references `users` with `ON DELETE CASCADE`; indexed by user |
| `plans` | One structured plan per task | `task_id` is unique and cascades on task deletion |
| `plan_steps` | Ordered plan actions | Cascades from plans; no database uniqueness or range constraint on `position` |
| `executions` | Execution attempts | Cascades from tasks; no uniqueness or range constraint on `attempt` |
| `artifacts` | Execution outputs and metadata | Cascades from executions; `relative_path` and `content` have no storage-level path or size validation |
| `verifications` | Verification records | Cascades from executions; `result` has no `CHECK` constraint |
| `failures` | Failure and diagnosis records | Cascades from executions |
| `recovery_attempts` | Recovery records | Cascades from executions; `attempt_no` has no uniqueness or range constraint |
| `provenance_events` | Audit events | Task and execution references use `ON DELETE SET NULL`; event rows have no owner column |
| `evaluation_runs` | Run-level benchmark configuration/results | Unique `run_name`; no user or authorization relationship |

Indexes exist for usernames, session lookup/ownership/expiry, task ownership,
child-record foreign keys, and evaluation-run names. Foreign-key enforcement is
enabled per connection, and the tests confirm the task and session foreign-key
relationships.

The schema does not yet include the planned `Tool`, `ToolPermission`, or
benchmark-task structures. Their absence is consistent with the phase plan;
this review does not add them.

### Schema limitations

The current constraints enforce referential shape, but not the full domain
model. There are no database `CHECK` constraints for statuses, validated flags,
attempt numbers, positions, result values, nonnegative sizes, timestamp format,
or JSON validity. Repository callers and future domain services must enforce
those rules. The existing `user_id` foreign key establishes ownership
relationships, but it does not itself authorize access.

## 3. Data integrity

### Existing strengths

- Foreign keys are enabled on every newly opened connection.
- Unique indexes protect usernames, session-token digests, and evaluation-run
  names; `plans.task_id` is unique.
- Cascades connect sessions/tasks to users and child records to tasks or
  executions.
- The transaction context rolls back failed units of work and closes
  connections.
- `TaskRepo` includes `user_id` in its read and delete predicates
  (`atlas/storage/repositories.py:156-179`).
- SQL values are bound through parameters in the repository methods.
- The idempotent initializer is safe to call repeatedly on the same initialized
  database, as covered by `test_initialize_from_empty_directory_is_idempotent`.

### Integrity gaps

1. **Version recording is not migration validation.** `init_db()` creates
   missing objects and ignores an already-present version, but it does not
   compare the stored version with `SCHEMA_VERSION`, reject an unknown version,
   or apply upgrades. Re-running initialization against an incompatible older
   or hand-edited schema can therefore succeed without proving compatibility.
2. **Domain invariants are mostly application-side or absent.** A caller can
   write a negative `size_bytes`, arbitrary status text, duplicate plan-step
   positions, duplicate execution attempts, or a non-`0/1` `validated` value if
   it bypasses future validation. JSON columns are text columns and are not
   checked with SQLite JSON constraints.
3. **Session expiry is not part of the repository contract.**
   `SessionRepo.get_valid()` filters revocation but not `expires_at`
   (`atlas/storage/repositories.py:111-119`). `AuthService.validate_session()`
   checks expiry after calling it, which protects the current service path, but
   a future caller could misuse the repository method.
4. **Provenance relationships are not constrained for consistency.** A caller
   can record an event with unrelated valid `task_id` and `execution_id` values,
   or with both null. There is no owner column or composite relationship tying
   the event to the task's user.
5. **Some mutation methods do not verify affected-row counts.** Password,
   lockout, and user mutation helpers return no row count, so a missing or
   mismatched identifier can result in a silent no-op.
6. **Timestamps are text and comparison semantics are implicit.** Application
   timestamps are UTC ISO strings, while the migration default for
   `schema_migrations` uses a different UTC suffix. The expiry cleanup query
   compares text lexicographically and the service parses strings without a
   storage-level format constraint.

## 4. User and data isolation

The current repository layer provides **partial application-level ownership
scoping**, not authorization.

- `TaskRepo.get()`, `list_for_user()`, and `delete()` filter by the supplied
  `user_id`.
- Tasks own plans, executions, and their descendants through foreign keys.
- User deletion cascades sessions and tasks.
- `UserRepo` and `SessionRepo` identify the account or session involved in an
  operation, but do not implement roles, permissions, or action policies.

The following limitations are material:

- There is no authorization layer, role model, permission table, or central
  authorization check.
- There are no repositories for plans, executions, artifacts, verifications,
  failures, or recovery attempts, so their future queries have not yet been
  reviewed for owner predicates.
- `ProvenanceRepo.record()` accepts task and execution IDs but no user/owner
  predicate. A direct connection or future unscoped query can read or write
  events without a user boundary.
- `evaluation_runs` is global and has no owner relationship.
- SQLite has no row-level security policy in this implementation. A caller that
  has a connection can execute arbitrary SQL outside the repository helpers.
- The task ownership tests prove only the behavior of the specific helper
  methods tested; they do not prove isolation for every future entity or query.

Therefore this review does **not** claim that user/data authorization exists or
that all data is isolated. It records only the ownership predicates that are
present in the current code.

## 5. SQL injection safety

The inspected storage code uses parameter placeholders for all data values in
repository queries. User names, task IDs, token hashes, timestamps, and JSON
payloads are passed as bound parameters. Table and column names, `ORDER BY`
targets, and schema statements are fixed literals; no user-controlled SQL
identifier or SQL string concatenation was found in the inspected files
(`atlas/storage/repositories.py:28-205`, `atlas/storage/migrations.py:15-207`).

This is a good SQL-injection baseline. It does not:

- authorize the requested row,
- validate a path,
- validate a JSON payload,
- constrain a status or size, or
- protect a caller that bypasses the repositories and writes SQL directly.

The test suite does not yet include adversarial input values such as quotes,
SQL comments, or malformed Unicode in repository methods. Those tests are
recommended before new storage query surfaces are added.

## 6. Filesystem and database-path safety

The current database path handling is not project-confined:

- `Database.__init__()` accepts any `str | Path` and creates its parent
  directory recursively (`atlas/storage/db.py:18-23`).
- `Settings.database_path` is a path value without a project-root constraint
  (`atlas/config/settings.py:21-25`).
- Absolute paths, `..` components, and paths outside the workspace are not
  rejected. Existing junctions/symlinks are not resolved or checked before the
  parent is created.
- No explicit file ACL, mode, ownership, or restrictive-permission setup is
  performed by the storage layer.
- WAL mode can create `atlas.db-wal` and `atlas.db-shm` sidecars beside the
  selected database. Those sidecars are not separately inventoried or cleaned
  up here.
- No backup, checkpoint, integrity-check, corruption-recovery, or file-retention
  policy is implemented.

The `artifacts.relative_path` column is only a data column. No current artifact
writer, path resolver, or repository enforces that it is relative, normalized,
and contained beneath a sandbox root. The storage review therefore does not
claim filesystem isolation or sandbox enforcement.

The existing local-first design makes the OS permission model the current outer
boundary, but that is not equivalent to an application-enforced project-root
boundary.

## 7. Transactions and concurrency behavior

The transaction context provides a straightforward commit-on-success and
rollback-on-exception unit of work. It also rolls back if commit itself raises.
Foreign keys, WAL, and the busy timeout provide useful baseline behavior for a
single laptop.

Current limitations are:

- SQLite has one writer at a time. WAL improves reader/writer coexistence but
  does not eliminate writer serialization.
- The effective busy timeout is hard-coded to 5,000 ms after the constructor's
  `timeout_seconds` is applied; the constructor option does not fully control
  lock waiting.
- There is no retry/backoff policy for `OperationalError: database is locked`.
- There is no migration lock, initialization lock, or schema-compatibility
  transaction protocol beyond SQLite's normal locking.
- Nested transaction scopes are not implemented, and there are no savepoints.
- `Database.connect()` is public, so callers can manage commits and transactions
  outside the `transaction()` policy.
- The concurrency test only performs six independent inserts from six threads.
  It does not test simultaneous updates to one row, read/write contention,
  multi-process access, lock timeout behavior, initialization races, or
  cancellation/close paths.

The auth service performs a user read in one transaction and a later failure or
success update in another. Concurrent login attempts can therefore race on the
read-modify-write login-failure counter; this is an auth/concurrency concern that
must be addressed by the authentication phase, not silently treated as a
storage guarantee.

## 8. Sensitive data handling

Current positive controls are:

- Passwords are hashed by the authentication layer before `UserRepo.create()`;
  the storage layer does not receive plaintext passwords in the normal path.
- Raw session tokens are not written by the current auth path; only token
  digests are stored.
- Public user queries select only `id`, `username`, and `created_at`.
- The redaction filter exists, although its runtime wiring is a separate
  configuration-review finding.

Storage risks and limitations are:

- `UserRepo.get_by_username()` and `get_by_id()` use `SELECT *` and return the
  full row, including `password_hash` and lockout fields, to any internal caller
  that uses those methods. They are not safe defaults for response or logging
  boundaries.
- Task goals, artifact content, verification details, and failure details are
  stored as plaintext SQLite text. SQLite provides no at-rest encryption here.
- `ProvenanceRepo.record()` serializes arbitrary `detail` dictionaries with
  `json.dumps()` but does not redact secrets, enforce a size bound, or apply a
  field allowlist. A future producer could persist credentials or full prompts
  in `detail_json`.
- Database backups, WAL contents, and filesystem copies can retain data after a
  logical delete. The application does not currently implement secure erasure.
- The OS account and filesystem permissions are the current protection for the
  database and any sidecar files.

## 9. Deletion and retention

Deletion is primarily relational and immediate:

- Deleting a user cascades sessions and tasks.
- Deleting a task cascades plans, plan steps, executions, artifacts,
  verifications, failures, and recovery attempts.
- Deleting an execution cascades artifacts, verifications, failures, and
  recovery attempts.
- Provenance task/execution references are set to null, preserving the event row
  but removing its direct relationship to the deleted object.

There is no soft-delete marker, deletion audit record, retention period,
per-user purge workflow, or recovery policy. Evaluation runs are not tied to a
user and have no deletion path in the inspected layer. Expired or revoked
sessions are removed lazily by `AuthService.validate_session()` through
`SessionRepo.delete_expired()`; there is no scheduler or independent retention
job.

Logical deletion is not secure erasure. The database, WAL, backups, and any
copied artifacts can retain plaintext or recoverable data. A future retention
policy must state whether research provenance is retained, anonymized, or
purged after user deletion.

## 10. Existing storage-test coverage

`tests/test_storage.py` contains eight storage tests:

| Test | Coverage |
|---|---|
| `test_initialize_from_empty_directory_is_idempotent` | Parent creation, repeated initialization, expected table presence, one migration row |
| `test_foreign_key_enforced_on_tasks_user` | Task-to-user foreign key rejection |
| `test_foreign_key_enforced_on_sessions_user` | Session-to-user foreign key rejection |
| `test_ownership_relationships_are_enforced` | Task read/delete/list behavior for owner and non-owner |
| `test_delete_user_cascades_owned_tasks` | User-to-task cascade |
| `test_provenance_records_and_survives_task_delete` | Event creation and `ON DELETE SET NULL` behavior |
| `test_transaction_rollback_leaves_no_partial_rows` | Rollback after an exception |
| `test_concurrent_basic_operations` | Six independent threaded inserts |

The tests are useful baseline coverage and use temporary directories. They do
not cover:

- schema version mismatch or a real migration upgrade,
- malformed or incompatible existing tables/indexes,
- all child foreign keys and cascades,
- status, boolean, range, timestamp, JSON, or uniqueness domain constraints,
- direct `SessionRepo` expiry semantics and cleanup scheduling,
- SQL-injection-shaped repository inputs,
- database path confinement, absolute paths, traversal, or junction/symlink
  cases,
- lock contention, busy timeout configuration, multi-process use, or
  initialization races,
- commit failure, nested transactions, or connection lifecycle edge cases,
- redaction, plaintext-at-rest posture, secret-bearing provenance details,
  retention, or secure deletion,
- authorization/ownership for provenance and every future child entity.

No tests were added in this review phase.

## 11. Findings

Severity reflects the current reviewed state and the impact of relying on it for
future authorization or execution features. It is not a claim that an
unimplemented future component is already exploitable.

### CRITICAL

- **None identified in the inspected storage code.** No remote entry point,
  sandboxed execution path, or direct unparameterized SQL was found. This is not
  a security clearance; the absence of an execution path is not a control.

### HIGH

- **H-1 — Authorization is not implemented.** `TaskRepo` ownership predicates
  are useful, but there is no role/permission layer and no owner-scoped storage
  API for the other planned entities or provenance. Before any caller can read
  or mutate domain data, every operation needs an explicit authorization gate
  and negative cross-user tests. ATLAS-X currently does not have that gate.
- **H-2 — Schema evolution is not implemented safely enough for future
  persistence changes.** Version `1` is recorded but not validated or upgraded.
  An incompatible database can be initialized without an explicit failure. A
  versioned migration/validation protocol must precede schema changes that
  authorization or execution depends on.

### MEDIUM

- **M-1 — Database paths are unrestricted.** `Database` and `Settings` accept
  paths outside the project and create parent directories. This contradicts a
  strict project-scoped filesystem rule. The current risk is configuration-
  controlled; it becomes higher if a UI or untrusted caller can influence the
  path.
- **M-2 — Session validity is split between service and repository.**
  `SessionRepo.get_valid()` does not enforce `expires_at`; current auth service
  code compensates, but the storage contract is easy to misuse when new callers
  are added.
- **M-3 — Domain constraints are incomplete.** Statuses, attempts, positions,
  sizes, booleans, timestamps, and JSON fields are not database-validated.
  Future services must reject invalid values before writing them, and important
  invariants should have database constraints where practical.
- **M-4 — Provenance ownership and consistency are not enforced.** Events have
  no owner column, can contain unrelated task/execution IDs, and can be queried
  without a user predicate. This is a gap for future authorization and audit
  queries.
- **M-5 — Sensitive content is plaintext and provenance details are not
  redacted or size-bounded.** OS permissions are the only current at-rest
  boundary; future logging, provenance, and artifact producers need explicit
  data-minimization rules.
- **M-6 — Retention and secure deletion are unspecified.** Cascades are logical
  deletes only; no policy covers sessions, provenance, evaluation runs,
  backups, WAL files, or recovery of deleted plaintext.
- **M-7 — Concurrency behavior is only partially characterized.** The fixed
  busy timeout, lack of retry policy, and untested writer contention can turn
  simultaneous operations into lock errors or lost read-modify-write updates.
- **M-8 — Full user rows are available through internal `SELECT *` helpers.**
  This is not a current response leak because the auth service uses a public
  projection, but it is a future secret-handling hazard.

### LOW

- **L-1 — `connect()` exposes connection management outside the transaction
  policy.** Callers can bypass the standard commit/rollback/close scope.
- **L-2 — Timestamp handling mixes text representations.** Lexicographic
  cleanup comparisons and parser exceptions are possible for externally altered
  or malformed values.
- **L-3 — Initialization is tested for repeatability, not migration safety or
  concurrent initialization.**

### INFORMATIONAL

- **I-1 — SQLite is the intended local-first relational store.** WAL, foreign
  keys, and a short-lived connection model are reasonable for one laptop.
- **I-2 — No current storage code executes tools, generated code, or models.**
  Resource limits, sandbox boundaries, planner behavior, verifier behavior, and
  recovery limits are therefore not enforced by this layer.
- **I-3 — Database integrity, filesystem security, and authorization are
  separate properties.** Passing the current tests establishes baseline
  relational behavior only; it does not establish filesystem isolation or
  authorization.
- **I-4 — The current implementation is a foundation for later phases, not a
  completed production security boundary.**

## 12. Required changes before authorization or execution features

The following are prerequisites, not changes made by this review.

### Before authorization

1. Define the authorization policy and ensure every storage-facing operation
   receives the authenticated user identity; do not infer authorization from a
   caller-supplied `user_id` alone.
2. Add owner-scoped repository/query contracts for tasks, plans, executions,
   artifacts, verifications, failures, recovery records, and provenance, with
   cross-user negative tests at every surface.
3. Define whether evaluation runs are global research data or user-owned, and
   enforce that decision before exposing them to a multi-user UI.
4. Make session expiry/revocation validation an explicit invariant at the
   boundary used by all future callers; do not rely solely on a method name
   that does not check expiry.
5. Define role, permission, grant, revocation, and audit requirements before
   adding tool permissions or privileged operations.
6. Keep filesystem authorization and database authorization separate: a valid
   row owner does not by itself authorize access to an arbitrary host path.

### Before execution, tools, sandbox, planner, or verifier features

1. Add a real schema migration/validation protocol with version checks,
   transactional upgrades, and compatibility failure behavior.
2. Constrain the database path to the approved project/data root, reject
   traversal and unsafe path forms, account for junctions/symlinks, and define
   restrictive file permissions and sidecar handling.
3. Add the required database constraints and domain validation for status
   transitions, attempts, plan-step ordering, sizes, timestamps, JSON payloads,
   and provenance linkage.
4. Define transaction boundaries for multi-record execution state changes and
   add contention, retry, and multi-process tests appropriate to the supported
   local deployment.
5. Establish data classification, redaction, provenance-detail allowlists, size
   caps, backup policy, retention policy, and secure-deletion expectations
   before storing prompts, tool inputs, generated code, or artifacts.
6. Enforce configured task, plan, tool, recovery, output, artifact, log,
   timeout, and concurrency limits at their owning runtime call sites. A
   setting in `Settings` is not enforcement.
7. Keep sandbox filesystem confinement, checksum verification, path rejection,
   and resource controls in the future sandbox phase; the current artifact
   columns provide no enforcement.
8. Require authorization before every tool dispatch and every read/write of an
   execution-owned resource. Missing authorization must fail closed.

## 13. Explicit boundary distinction

### Database integrity

The current code provides foreign-key enforcement, uniqueness where declared,
transactional commit/rollback, and limited cascade behavior. It does not yet
provide schema migration safety, complete domain constraints, durable
provenance integrity, or guarantees for every repository operation. Integrity
means the database maintains its declared relationships and transactions; it
does not mean a caller is allowed to access a row.

### Filesystem security

The storage code does not enforce a project-root boundary, artifact-root
boundary, path confinement, or filesystem permissions. It can create the parent
of any configured database path, and SQLite may create WAL/SHM sidecars. A path
stored in `artifacts.relative_path` is not validated. Filesystem security must
be implemented and tested by the future storage/sandbox boundary; it is not
provided by foreign keys or transaction handling.

### Authorization

Authorization does not exist yet. `TaskRepo`'s `WHERE user_id = ?` predicates
are ownership filtering for a few helper methods, not a complete authorization
system. There are no roles, permissions, policy checks, or enforcement before
future tool/execution actions. No claim of authorization, filesystem isolation,
or enforced future execution limits is made by this review.

## Current Phase 06 conclusion

The existing SQLite foundation is suitable to carry forward to the next gate,
provided the gaps above remain explicit blockers. The current storage tests
cover basic initialization, foreign keys, task ownership, cascades, rollback,
provenance survival, and independent threaded writes. They do not constitute a
complete storage security or authorization test suite.

This phase changes documentation only. It does not claim that authorization,
filesystem isolation, sandboxing, or future resource-limit enforcement exists.
Phase 07 must not be started from this review.

## Verification

The required final pytest, Ruff, and mypy results are recorded in the Phase 06
handoff after this document is created. No verification result is inferred here.

Files modified by this review: `docs/STORAGE_REVIEW.md` (created only).
