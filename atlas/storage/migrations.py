"""Deterministic, idempotent schema initialization.

All statements are created with IF NOT EXISTS so that initialization from an
empty directory and from an already-initialized directory produces the same
result. A single versioned row in ``schema_migrations`` records the applied
schema version.

Initialization fails closed when the database was written by a newer version of
the code. A newer schema may have added a table this build then writes to
incorrectly, or one whose meaning has changed, so running old code against it is
worse than refusing to start. ``docs/STORAGE_REVIEW.md`` §12.1 asks for version
checks and compatibility failure behavior; this is the narrow part of that
requirement that applies while the only version change is additive.

Version 3 is the first change that is **not** purely additive in shape. The v2
``plans`` table carried ``UNIQUE(task_id)``, which says a task has at most one
plan row forever. Phase 16 recovery needs the earlier plan kept while a revised
one is proposed, so the constraint has to go and ``supersedes_plan_id`` has to
arrive in its place. SQLite cannot drop a column constraint, so that one table
is rebuilt by copying it; everything else in v3 is ``ALTER TABLE ... ADD
COLUMN``, which is additive and idempotent.

:func:`upgrade_to_v3` performs that work and must run on a connection with
``foreign_keys`` OFF and no open transaction. Both requirements are load-bearing:

* With foreign keys ON, ``DROP TABLE plans`` fires ``ON DELETE CASCADE`` against
  ``plan_steps`` and **deletes every step of every plan**. The rebuild would then
  appear to succeed while quietly discarding the rows it was supposed to
  preserve. The pragma is a no-op inside a transaction, so the rebuild cannot
  happen part-way through :func:`init_db`.
* ``ALTER TABLE ... RENAME TO`` rewrites the foreign key clauses of other tables
  that reference the renamed table, so the copy and the rename have to be one
  unit of work rather than two separately retryable steps.

:func:`init_db` therefore records the version and creates anything missing, and
:meth:`atlas.storage.db.Database.initialize` calls :func:`upgrade_to_v3` first,
on its own connection. Both halves are idempotent, so initialization from an
empty directory, from a v2 database, and from an up-to-date database all
converge on the same schema.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 4


class SchemaVersionError(RuntimeError):
    """The database schema is not compatible with this build."""

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        failed_login_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        goal TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        result_json TEXT,
        verified_at TEXT,
        failure_category TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id)
    """,
    # One plan row per *proposal*, not per task: `supersedes_plan_id` chains a
    # revised plan to the one it replaces, so recovery keeps the earlier plan
    # instead of overwriting it. The v2 UNIQUE(task_id) is gone; the head of the
    # chain is the plan no other plan supersedes.
    """
    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        plan_json TEXT NOT NULL,
        validated INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'legacy',
        status TEXT NOT NULL DEFAULT 'proposed',
        model_id TEXT,
        digest TEXT,
        supersedes_plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
        validation_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plans_task_id ON plans(task_id, id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plans_supersedes ON plans(supersedes_plan_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS plan_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        action TEXT NOT NULL,
        tool_name TEXT,
        tool_id TEXT,
        step_key TEXT,
        depends_on_json TEXT,
        input_json TEXT,
        produces_artifact_kind TEXT,
        provenance_event_id INTEGER REFERENCES provenance_events(id) ON DELETE SET NULL,
        failure_category TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plan_steps_plan_id ON plan_steps(plan_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plan_steps_plan_position ON plan_steps(plan_id, position)
    """,
    """
    CREATE TABLE IF NOT EXISTS executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        attempt INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'pending',
        plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
        plan_step_id INTEGER REFERENCES plan_steps(id) ON DELETE SET NULL,
        tool_id TEXT,
        invocation_id TEXT,
        origin TEXT NOT NULL DEFAULT 'direct',
        started_at TEXT,
        finished_at TEXT,
        -- Nullable, unlike created_at on every other table. SQLite cannot add a
        -- NOT NULL column to a table that already holds rows without inventing a
        -- value for them, so a NOT NULL here would mean the upgraded database and
        -- a fresh one disagree. Legacy v2 executions genuinely have no creation
        -- timestamp distinct from started_at, so NULL is the honest value and the
        -- executor writes the column on every row it creates.
        created_at TEXT,
        result_json TEXT,
        error TEXT,
        error_code TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_executions_task_id ON executions(task_id)
    """,
    # Partial index rather than a column UNIQUE: executions that are not part of a
    # dispatched invocation must be able to share a NULL.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_executions_invocation
        ON executions(invocation_id) WHERE invocation_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_executions_plan_step ON executions(plan_step_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'file',
        relative_path TEXT,
        content TEXT,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        checksum TEXT,
        source TEXT NOT NULL DEFAULT 'tool',
        verified INTEGER NOT NULL DEFAULT 0,
        metadata_json TEXT,
        created_by TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_artifacts_execution_id ON artifacts(execution_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
        verifier TEXT NOT NULL,
        result TEXT NOT NULL,
        detail_json TEXT,
        artifact_id INTEGER REFERENCES artifacts(id) ON DELETE SET NULL,
        plan_step_id INTEGER REFERENCES plan_steps(id) ON DELETE SET NULL,
        verifier_version TEXT,
        evidence_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_verifications_execution_id ON verifications(execution_id)
    """,
    # The Phase 13 requirement is that a verification names the artifact it
    # checked. Without this column the only available answer is "the artifacts of
    # this execution", which cannot distinguish which one was verified.
    """
    CREATE INDEX IF NOT EXISTS idx_verifications_artifact ON verifications(artifact_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        diagnosis TEXT,
        detail_json TEXT,
        plan_step_id INTEGER REFERENCES plan_steps(id) ON DELETE SET NULL,
        invocation_id TEXT,
        error_code TEXT,
        retryable INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_failures_execution_id ON failures(execution_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS recovery_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
        attempt_no INTEGER NOT NULL,
        diagnosis TEXT,
        new_plan_json TEXT,
        outcome TEXT NOT NULL DEFAULT 'pending',
        failure_id INTEGER REFERENCES failures(id) ON DELETE SET NULL,
        limit_no INTEGER,
        detail_json TEXT,
        finished_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recovery_attempts_execution_id ON recovery_attempts(execution_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS provenance_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
        execution_id INTEGER REFERENCES executions(id) ON DELETE SET NULL,
        plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
        plan_step_id INTEGER REFERENCES plan_steps(id) ON DELETE SET NULL,
        tool_id TEXT,
        invocation_id TEXT,
        sequence_no INTEGER,
        chain_digest TEXT,
        event_type TEXT NOT NULL,
        actor TEXT NOT NULL,
        detail_json TEXT,
        created_at TEXT NOT NULL,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provenance_events_task ON provenance_events(task_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provenance_events_execution ON provenance_events(execution_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provenance_events_invocation ON provenance_events(invocation_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provenance_events_chain
        ON provenance_events(task_id, sequence_no)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provenance_events_user ON provenance_events(user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_name TEXT NOT NULL,
        config_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        results_json TEXT,
        started_at TEXT,
        finished_at TEXT,
        created_at TEXT NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluation_runs_name ON evaluation_runs(run_name)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_evaluation_runs_user ON evaluation_runs(user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        tool_name TEXT NOT NULL,
        scope TEXT,
        granted_by TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        revoked_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tool_permissions_user ON tool_permissions(user_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_permissions_unique
        ON tool_permissions(user_id, tool_name, IFNULL(scope, ''))
    """,
    """
    CREATE TABLE IF NOT EXISTS user_preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
        onboarding_completed INTEGER NOT NULL DEFAULT 0,
        reduced_motion INTEGER NOT NULL DEFAULT 0,
        high_contrast INTEGER NOT NULL DEFAULT 0,
        theme_mode TEXT NOT NULL DEFAULT 'system',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_preferences_user ON user_preferences(user_id)
    """,
)


def applied_version(conn: sqlite3.Connection) -> int | None:
    """The schema version recorded in the database, or None if uninitialized.

    ``MAX`` rather than a bare fetch: :func:`init_db` keeps exactly one row, but
    a database written before that invariant existed may hold several versions,
    and reporting an arbitrary one of them would make the compatibility check
    depend on row order.
    """

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if row is None:
        return None
    version = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    if version is None or version["version"] is None:
        return None
    return int(version["version"])


def check_schema_version(conn: sqlite3.Connection) -> None:
    """Refuse to run against a schema this build does not understand."""

    version = applied_version(conn)
    if version is not None and version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"database schema version {version} is newer than this build's "
            f"{SCHEMA_VERSION}; upgrade the application instead of downgrading the data"
        )


def init_db(conn: sqlite3.Connection) -> None:
    check_schema_version(conn)
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    # Replace the recorded version rather than appending one. A v1 database
    # already holding a row for version 1 would otherwise keep that row, and a
    # second row for version 3 would leave two competing claims about the
    # schema.
    conn.execute("DELETE FROM schema_migrations")
    conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (SCHEMA_VERSION,))


# --------------------------------------------------------------- v2 -> v3


#: The v3 shape of ``plans``. Held as one string because it is executed twice —
#: once by :func:`init_db` for an empty directory, once by :func:`rebuild_plans`
#: for an existing v2 table — and two copies of a table definition would be two
#: places for them to drift apart.
PLANS_V3_SQL = """
CREATE TABLE {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    plan_json TEXT NOT NULL,
    validated INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'legacy',
    status TEXT NOT NULL DEFAULT 'proposed',
    model_id TEXT,
    digest TEXT,
    supersedes_plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    validation_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

#: Columns added to existing v2 tables by version 3. ``ALTER TABLE ADD COLUMN``
#: is idempotent only when guarded, so each entry is checked before it runs.
_V3_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("tasks", "result_json TEXT"),
    ("tasks", "verified_at TEXT"),
    ("tasks", "failure_category TEXT"),
    ("plans", "source TEXT NOT NULL DEFAULT 'legacy'"),
    ("plans", "status TEXT NOT NULL DEFAULT 'proposed'"),
    ("plans", "model_id TEXT"),
    ("plans", "digest TEXT"),
    ("plans", "supersedes_plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL"),
    ("plans", "validation_json TEXT"),
    ("plan_steps", "tool_id TEXT"),
    ("plan_steps", "step_key TEXT"),
    ("plan_steps", "depends_on_json TEXT"),
    ("plan_steps", "produces_artifact_kind TEXT"),
    (
        "plan_steps",
        "provenance_event_id INTEGER REFERENCES provenance_events(id) ON DELETE SET NULL",
    ),
    ("plan_steps", "failure_category TEXT"),
    ("executions", "plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL"),
    ("executions", "plan_step_id INTEGER REFERENCES plan_steps(id) ON DELETE SET NULL"),
    ("executions", "tool_id TEXT"),
    ("executions", "invocation_id TEXT"),
    ("executions", "origin TEXT NOT NULL DEFAULT 'direct'"),
    ("executions", "error_code TEXT"),
    ("executions", "created_at TEXT"),
    ("artifacts", "source TEXT NOT NULL DEFAULT 'tool'"),
    ("artifacts", "verified INTEGER NOT NULL DEFAULT 0"),
    ("artifacts", "metadata_json TEXT"),
    ("artifacts", "created_by TEXT"),
    ("verifications", "artifact_id INTEGER REFERENCES artifacts(id) ON DELETE SET NULL"),
    ("verifications", "plan_step_id INTEGER REFERENCES plan_steps(id) ON DELETE SET NULL"),
    ("verifications", "verifier_version TEXT"),
    ("verifications", "evidence_json TEXT"),
    ("failures", "plan_step_id INTEGER REFERENCES plan_steps(id) ON DELETE SET NULL"),
    ("failures", "invocation_id TEXT"),
    ("failures", "error_code TEXT"),
    ("failures", "retryable INTEGER NOT NULL DEFAULT 0"),
    ("recovery_attempts", "failure_id INTEGER REFERENCES failures(id) ON DELETE SET NULL"),
    ("recovery_attempts", "limit_no INTEGER"),
    ("recovery_attempts", "detail_json TEXT"),
    ("recovery_attempts", "finished_at TEXT"),
    ("provenance_events", "plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL"),
    ("provenance_events", "plan_step_id INTEGER REFERENCES plan_steps(id) ON DELETE SET NULL"),
    ("provenance_events", "tool_id TEXT"),
    ("provenance_events", "invocation_id TEXT"),
    ("provenance_events", "sequence_no INTEGER"),
    ("provenance_events", "chain_digest TEXT"),
)


# V4 added columns: user_id ownership for evaluation_runs and provenance_events
# Note: SQLite ALTER TABLE doesn't support adding FK constraints, so they are
# declared in the CREATE TABLE statements for new databases only.
_V4_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("evaluation_runs", "user_id INTEGER NOT NULL"),
    ("provenance_events", "user_id INTEGER"),
)


class SchemaUpgradeError(RuntimeError):
    """A v2 database could not be brought forward to version 3."""


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    return frozenset(str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})"))


def _plans_needs_rebuild(conn: sqlite3.Connection) -> bool:
    """Whether ``plans`` still carries the v2 ``UNIQUE(task_id)``.

    A table with no ``source`` column is pre-v3. It is rebuilt whether or not it
    currently holds rows: the constraint has to go regardless, and refusing to
    migrate an empty table would leave a schema that differs by population.
    """

    if not _table_exists(conn, "plans"):
        return False
    columns = _columns(conn, "plans")
    if "source" in columns:
        return False
    return True


def rebuild_plans(conn: sqlite3.Connection) -> None:
    """Replace a v2 ``plans`` table with the v3 shape, keeping its rows.

    The caller is responsible for the conditions named in the module docstring:
    ``foreign_keys`` OFF and no open transaction. On a connection that does not
    meet them this function still returns, but ``plan_steps`` will have lost
    every row it pointed at, which is exactly the outcome this design refuses.
    """

    if not _table_exists(conn, "plans"):
        return
    temporary = "plans_v3_upgrade"
    if _table_exists(conn, temporary):
        raise SchemaUpgradeError(
            f"a leftover {temporary!r} table is present; the previous upgrade did "
            "not finish and cannot be resumed automatically"
        )
    conn.execute(PLANS_V3_SQL.format(name=temporary))
    conn.execute(
        f"INSERT INTO {temporary} "
        "(id, task_id, plan_json, validated, source, status, created_at, updated_at) "
        "SELECT id, task_id, plan_json, validated, 'legacy', "
        "CASE WHEN validated = 1 THEN 'validated' ELSE 'proposed' END, "
        "created_at, updated_at FROM plans"
    )
    conn.execute("DROP TABLE plans")
    conn.execute(f"ALTER TABLE {temporary} RENAME TO plans")


def upgrade_to_v3(conn: sqlite3.Connection) -> bool:
    """Bring a pre-v3 database forward. Returns whether anything changed.

    Idempotent, and a no-op on an empty directory: ``init_db`` creates the v3
    shape directly there, so there is nothing to upgrade.

    The whole upgrade is one transaction. :func:`rebuild_plans` and the ``ALTER
    TABLE`` loop both change schema, and a half-applied upgrade is worse than an
    unapplied one: ``plans`` would be rebuilt without the ``ADD COLUMN`` pass
    having run, and the recorded version would still claim v2. If the caller
    already opened a transaction, this joins it and the caller still owns the
    commit. If not, this opens and closes its own, so the guarantee does not
    depend on how the function was reached. ``atlas.storage.db.Database`` relies
    on exactly that: it drives the upgrade with foreign keys off, which is a
    no-op inside a transaction and therefore has to happen before one begins.
    """

    if conn.in_transaction:
        changed = _upgrade_to_v3(conn)
        changed = _upgrade_to_v4(conn) or changed
        return changed
    conn.execute("BEGIN")
    try:
        changed = _upgrade_to_v3(conn)
        changed = _upgrade_to_v4(conn) or changed
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return changed


def _upgrade_to_v3(conn: sqlite3.Connection) -> bool:
    """The body of :func:`upgrade_to_v3`, run inside a transaction."""

    if applied_version(conn) is None and not _table_exists(conn, "plans"):
        return False

    check_schema_version(conn)
    changed = False

    if _plans_needs_rebuild(conn):
        rebuild_plans(conn)
        changed = True

    for table, clause in _V3_ADDED_COLUMNS:
        if not _table_exists(conn, table):
            # A table the v3 statement set creates directly. Adding a column that
            # :func:`init_db` already declares would be refused by SQLite.
            continue
        column = clause.split()[0]
        if column in _columns(conn, table):
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {clause}")
        changed = True

    if changed:
        # The indexes for v3 live in SCHEMA_STATEMENTS, which :func:`init_db`
        # runs immediately after this. Creating them here too would only
        # duplicate the statements.
        #
        # The check runs before the commit, so a database that cannot be brought
        # forward consistently is rolled back whole rather than left upgraded.
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise SchemaUpgradeError(
                f"upgrade to version {SCHEMA_VERSION} left {len(violations)} foreign "
                f"key violations; the database was left at its original shape"
            )
    return changed


def _upgrade_to_v4(conn: sqlite3.Connection) -> bool:
    """The body of :func:`upgrade_to_v4`, run inside a transaction.

    Adds user_id ownership columns to evaluation_runs and provenance_events.
    """
    check_schema_version(conn)
    changed = False

    for table, clause in _V4_ADDED_COLUMNS:
        if not _table_exists(conn, table):
            continue
        column = clause.split()[0]
        if column in _columns(conn, table):
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {clause}")
        changed = True

    if changed:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise SchemaUpgradeError(
                f"upgrade to version {SCHEMA_VERSION} left {len(violations)} foreign "
                f"key violations; the database was left at its original shape"
            )
    return changed
