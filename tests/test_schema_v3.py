"""Phase 11 to 17 groundwork: the version 3 schema migration.

The properties these tests defend are not "the new columns exist". They are:

* a v2 database survives the upgrade with its ``plan_steps`` **rows** intact --
  the rebuild drops and recreates ``plans``, and with foreign keys enabled that
  drop cascades the child table away;
* the upgrade is idempotent, because ``Database.initialize`` runs on every start;
* ``plans`` can now hold a revised plan beside the one it supersedes, which is
  the storage precondition Phase 16 recovery needs and ``UNIQUE(task_id)``
  forbade;
* the columns the later phases depend on are present on both a fresh database
  and an upgraded one, so no phase has to branch on which schema it is talking to;
* a leftover table from a half-finished upgrade is refused rather than guessed at.

The v2 tables below are written out literally rather than derived from the
current statements. A fixture that rebuilt "the old schema" out of the new one
would stop being a v2 database the moment the new schema changed, and would then
pass against a migration that never ran.
"""

from __future__ import annotations

import sqlite3

import pytest

from atlas.storage.db import Database
from atlas.storage.migrations import (
    SCHEMA_VERSION,
    SchemaUpgradeError,
    SchemaVersionError,
    applied_version,
    check_schema_version,
    init_db,
    upgrade_to_v3,
)

#: The schema as it stood at version 2, for the tables the upgrade touches.
V2_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE users (
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
    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        goal TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
        plan_json TEXT NOT NULL,
        validated INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE plan_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        action TEXT NOT NULL,
        tool_name TEXT,
        input_json TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        attempt INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'pending',
        started_at TEXT,
        finished_at TEXT,
        result_json TEXT,
        error TEXT
    )
    """,
    """
    CREATE TABLE artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'file',
        relative_path TEXT,
        content TEXT,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        checksum TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
        verifier TEXT NOT NULL,
        result TEXT NOT NULL,
        detail_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        diagnosis TEXT,
        detail_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE recovery_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
        attempt_no INTEGER NOT NULL,
        diagnosis TEXT,
        new_plan_json TEXT,
        outcome TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE provenance_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
        execution_id INTEGER REFERENCES executions(id) ON DELETE SET NULL,
        event_type TEXT NOT NULL,
        actor TEXT NOT NULL,
        detail_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
)

#: Columns each later phase reads. Listed once so a missing column names itself.
EXPECTED_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tasks", ("result_json", "verified_at", "failure_category")),
    ("plans", ("source", "status", "model_id", "digest", "supersedes_plan_id", "validation_json")),
    (
        "plan_steps",
        (
            "tool_id",
            "step_key",
            "depends_on_json",
            "produces_artifact_kind",
            "provenance_event_id",
            "failure_category",
        ),
    ),
    (
        "executions",
        (
            "plan_id",
            "plan_step_id",
            "tool_id",
            "invocation_id",
            "origin",
            "error_code",
            "created_at",
        ),
    ),
    ("artifacts", ("source", "verified", "metadata_json", "created_by")),
    ("verifications", ("artifact_id", "plan_step_id", "verifier_version", "evidence_json")),
    ("failures", ("plan_step_id", "invocation_id", "error_code", "retryable")),
    ("recovery_attempts", ("failure_id", "limit_no", "detail_json", "finished_at")),
    (
        "provenance_events",
        ("plan_id", "plan_step_id", "tool_id", "invocation_id", "sequence_no", "chain_digest"),
    ),
)


def _legacy_database(tmp_path) -> Database:
    """A populated version 2 database at ``tmp_path/legacy.db``."""

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for statement in V2_STATEMENTS:
        conn.execute(statement)
    conn.execute(
        "INSERT INTO users (username, password_hash, created_at, updated_at) "
        "VALUES ('ada', 'hash', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO tasks (user_id, title, goal, created_at, updated_at) "
        "VALUES (1, 't', 'g', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO plans (task_id, plan_json, validated, created_at, updated_at) "
        "VALUES (1, '{\"steps\": []}', 1, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO plan_steps (plan_id, position, action, tool_name, input_json, "
        "created_at, updated_at) VALUES (1, 0, 'invoke', 'numeric_summary', '{}', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO executions (task_id, status, started_at) VALUES (1, 'succeeded', 'now')"
    )
    conn.execute(
        "INSERT INTO artifacts (execution_id, name, content, size_bytes, checksum, created_at) "
        "VALUES (1, 'result.json', '{}', 2, 'abc', 'now')"
    )
    conn.execute(
        "INSERT INTO verifications (execution_id, verifier, result, created_at) "
        "VALUES (1, 'checksum', 'pass', 'now')"
    )
    conn.execute(
        "INSERT INTO failures (execution_id, category, diagnosis, created_at) "
        "VALUES (1, 'tool_error', 'boom', 'now')"
    )
    conn.execute(
        "INSERT INTO recovery_attempts (execution_id, attempt_no, outcome, created_at) "
        "VALUES (1, 1, 'exhausted', 'now')"
    )
    conn.execute(
        "INSERT INTO provenance_events (task_id, event_type, actor, created_at) "
        "VALUES (1, 'task.created', 'user', 'now')"
    )
    conn.execute("INSERT INTO schema_migrations (version) VALUES (2)")
    conn.commit()
    conn.close()
    return Database(path)


def _columns(database: Database, table: str) -> frozenset[str]:
    with database.transaction() as conn:
        return frozenset(
            str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")
        )


# ---------------------------------------------------------- the fresh path


def test_a_fresh_database_is_created_at_the_current_version(tmp_path) -> None:
    database = Database(tmp_path / "fresh.db")
    database.initialize()

    with database.transaction() as conn:
        assert applied_version(conn) == SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_fresh_database_carries_every_column_the_later_phases_read(tmp_path) -> None:
    database = Database(tmp_path / "fresh.db")
    database.initialize()

    for table, columns in EXPECTED_COLUMNS:
        present = _columns(database, table)
        missing = sorted(set(columns) - present)
        assert not missing, f"{table} is missing {missing}"


# --------------------------------------------------------- the upgrade path


def test_the_upgrade_brings_a_v2_database_to_the_current_version(tmp_path) -> None:
    database = _legacy_database(tmp_path)
    database.initialize()

    with database.transaction() as conn:
        assert applied_version(conn) == SCHEMA_VERSION


def test_the_upgrade_keeps_the_plan_steps_rows_the_rebuild_would_cascade_away(
    tmp_path,
) -> None:
    database = _legacy_database(tmp_path)
    database.initialize()

    with database.transaction() as conn:
        steps = [dict(row) for row in conn.execute("SELECT * FROM plan_steps")]
        assert len(steps) == 1
        assert steps[0]["plan_id"] == 1
        assert steps[0]["position"] == 0
        assert steps[0]["tool_name"] == "numeric_summary"
        # The v3 columns arrive empty rather than invented.
        assert steps[0]["tool_id"] is None
        assert steps[0]["step_key"] is None


def test_the_upgrade_keeps_every_other_table_intact(tmp_path) -> None:
    database = _legacy_database(tmp_path)
    database.initialize()

    with database.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM artifacts").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM verifications").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM failures").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM recovery_attempts").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM provenance_events").fetchone()["n"] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_the_upgrade_labels_a_carried_over_plan_as_legacy_and_validated(tmp_path) -> None:
    database = _legacy_database(tmp_path)
    database.initialize()

    with database.transaction() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id = 1").fetchone()
    assert row["source"] == "legacy"
    assert row["status"] == "validated"
    assert row["validated"] == 1
    assert row["supersedes_plan_id"] is None


def test_the_upgrade_labels_an_unvalidated_plan_as_proposed(tmp_path) -> None:
    database = _legacy_database(tmp_path)
    with database.transaction() as conn:
        conn.execute("UPDATE plans SET validated = 0 WHERE id = 1")
    database.initialize()

    with database.transaction() as conn:
        assert conn.execute("SELECT status FROM plans WHERE id = 1").fetchone()["status"] == (
            "proposed"
        )


def test_an_upgraded_database_carries_every_column_the_later_phases_read(tmp_path) -> None:
    database = _legacy_database(tmp_path)
    database.initialize()

    for table, columns in EXPECTED_COLUMNS:
        present = _columns(database, table)
        missing = sorted(set(columns) - present)
        assert not missing, f"{table} is missing {missing}"


def test_a_task_can_hold_a_revised_plan_beside_the_one_it_supersedes(tmp_path) -> None:
    database = _legacy_database(tmp_path)
    database.initialize()

    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO plans (task_id, plan_json, validated, source, status, "
            "supersedes_plan_id, created_at, updated_at) "
            "VALUES (1, '{\"steps\": [1]}', 1, 'model', 'validated', 1, 'now', 'now')"
        )
        rows = conn.execute("SELECT id, supersedes_plan_id FROM plans ORDER BY id").fetchall()

    assert len(rows) == 2
    assert rows[1]["supersedes_plan_id"] == rows[0]["id"]


def test_a_second_plan_for_one_task_is_refused_by_a_v2_schema(tmp_path) -> None:
    """The constraint the rebuild exists to remove really was there."""

    database = _legacy_database(tmp_path)
    with database.transaction() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO plans (task_id, plan_json, created_at, updated_at) "
                "VALUES (1, '{}', 'now', 'now')"
            )


def test_deleting_a_task_still_cascades_to_plans_and_their_steps(tmp_path) -> None:
    database = _legacy_database(tmp_path)
    database.initialize()

    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO plans (task_id, plan_json, supersedes_plan_id, created_at, updated_at) "
            "VALUES (1, '{}', 1, 'now', 'now')"
        )
        conn.execute("DELETE FROM tasks WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) AS n FROM plans").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM plan_steps").fetchone()["n"] == 0


def test_an_invocation_id_can_identify_only_one_execution(tmp_path) -> None:
    """The correlation id is unique, and the database refuses the duplicate.

    Phase 14 threads one ``invocation_id`` through the provenance event, the
    execution, the failure and the recovery attempt. If two executions could
    share it, every one of those joins becomes ambiguous and "which run produced
    this artifact" stops having an answer. A partial unique index is the
    smallest thing that makes the identifier trustworthy: executions that are
    not part of a dispatched invocation share NULL, and SQLite's UNIQUE would
    otherwise reject those too.
    """

    database = Database(tmp_path / "fresh.db")
    database.initialize()

    with database.transaction() as conn:
        # The owner has to exist. This test is about the index, not about
        # ownership, so it builds a real owner rather than relaxing the foreign
        # key -- a row that could only be inserted by breaking referential
        # integrity would not be evidence of anything.
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at) "
            "VALUES ('ada', 'hash', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO tasks (user_id, title, goal, created_at, updated_at) "
            "VALUES (1, 't', 'g', 'now', 'now')"
        )

        insert = (
            "INSERT INTO executions (task_id, status, invocation_id, origin, created_at) "
            "VALUES (1, 'pending', ?, 'plan_step', 'now')"
        )
        conn.execute(insert, ("inv-1",))

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("inv-1",))

        # Two rows that share nothing are fine: the index is partial, so a NULL
        # invocation does not collide with itself.
        conn.execute(insert, (None,))
        conn.execute(insert, (None,))

        count = conn.execute(
            "SELECT COUNT(*) AS n FROM executions WHERE invocation_id = 'inv-1'"
        ).fetchone()["n"]
        assert count == 1
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM executions WHERE invocation_id IS NULL"
        ).fetchone()["n"] == 2


# ------------------------------------------------------------ idempotence


def test_initializing_an_upgraded_database_twice_changes_nothing(tmp_path) -> None:
    database = _legacy_database(tmp_path)
    database.initialize()
    database.initialize()

    with database.transaction() as conn:
        assert applied_version(conn) == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) AS n FROM plans").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM plan_steps").fetchone()["n"] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_initializing_a_fresh_database_twice_changes_nothing(tmp_path) -> None:
    database = Database(tmp_path / "fresh.db")
    database.initialize()
    database.initialize()

    with database.transaction() as conn:
        assert applied_version(conn) == SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_the_upgrade_is_a_no_op_on_a_current_database(tmp_path) -> None:
    database = Database(tmp_path / "fresh.db")
    database.initialize()

    with database.transaction() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        assert upgrade_to_v3(conn) is False


def test_the_upgrade_leaves_an_empty_directory_for_init_db_to_create(tmp_path) -> None:
    database = Database(tmp_path / "empty.db")
    with database.transaction() as conn:
        assert upgrade_to_v3(conn) is False


# -------------------------------------------------------------- refusals


def test_a_newer_schema_is_still_refused(tmp_path) -> None:
    database = Database(tmp_path / "future.db")
    database.initialize()
    with database.transaction() as conn:
        conn.execute("DELETE FROM schema_migrations")
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (SCHEMA_VERSION + 5,))

    with database.transaction() as conn:
        with pytest.raises(SchemaVersionError):
            check_schema_version(conn)
        with pytest.raises(SchemaVersionError):
            init_db(conn)


def test_a_leftover_upgrade_table_is_refused_rather_than_guessed_at(tmp_path) -> None:
    database = _legacy_database(tmp_path)
    with database.transaction() as conn:
        conn.execute(
            "CREATE TABLE plans_v3_upgrade (id INTEGER PRIMARY KEY, task_id INTEGER)"
        )

    with pytest.raises(SchemaUpgradeError):
        database.initialize()


# ------------------------------------------- referential integrity of the new columns


def _populated_v3(tmp_path) -> Database:
    """A v3 database with one owner, task, plan, step, and execution."""

    database = Database(tmp_path / "populated.db")
    database.initialize()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at) "
            "VALUES ('ada', 'hash', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO tasks (user_id, title, goal, created_at, updated_at) "
            "VALUES (1, 't', 'g', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO plans (task_id, plan_json, created_at, updated_at) "
            "VALUES (1, '{}', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO plan_steps (plan_id, position, action, created_at, updated_at) "
            "VALUES (1, 0, 'invoke', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO executions (task_id, status, plan_id, plan_step_id, created_at) "
            "VALUES (1, 'pending', 1, 1, 'now')"
        )
    return database


@pytest.mark.parametrize(
    ("table", "statement"),
    (
        (
            "executions",
            "INSERT INTO executions (task_id, status, plan_id, created_at) "
            "VALUES (1, 'pending', 999, 'now')",
        ),
        (
            "executions",
            "INSERT INTO executions (task_id, status, plan_step_id, created_at) "
            "VALUES (1, 'pending', 999, 'now')",
        ),
        (
            "verifications",
            "INSERT INTO verifications (execution_id, verifier, result, artifact_id, created_at) "
            "VALUES (1, 'v', 'PASS', 999, 'now')",
        ),
        (
            "verifications",
            "INSERT INTO verifications (execution_id, verifier, result, plan_step_id, created_at) "
            "VALUES (1, 'v', 'PASS', 999, 'now')",
        ),
        (
            "failures",
            "INSERT INTO failures (execution_id, category, plan_step_id, created_at) "
            "VALUES (1, 'TOOL_ERROR', 999, 'now')",
        ),
        (
            "recovery_attempts",
            "INSERT INTO recovery_attempts (execution_id, attempt_no, failure_id, created_at) "
            "VALUES (1, 1, 999, 'now')",
        ),
        (
            "provenance_events",
            "INSERT INTO provenance_events (event_type, actor, plan_id, created_at) "
            "VALUES ('e', 'user', 999, 'now')",
        ),
        (
            "provenance_events",
            "INSERT INTO provenance_events (event_type, actor, plan_step_id, created_at) "
            "VALUES ('e', 'user', 999, 'now')",
        ),
    ),
)
def test_a_v3_lineage_column_refuses_a_dangling_reference(tmp_path, table, statement) -> None:
    """Every lineage column added by v3 is a real foreign key, not a loose integer.

    These columns are what let a later phase answer "which plan step produced
    this artifact". If the reference is not enforced, a wrong answer is
    storable and the join that would have caught it simply returns nothing,
    which reads the same as "no such relationship".
    """

    database = _populated_v3(tmp_path)

    with database.transaction() as conn:
        before = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

    with database.transaction() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(statement)

    # The refused insert left nothing behind.
    with database.transaction() as conn:
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == before


def test_deleting_a_plan_leaves_the_execution_that_used_it(tmp_path) -> None:
    """``plans.plan_id`` is ON DELETE SET NULL, not CASCADE.

    An execution is evidence. Losing it because a plan was tidied away would
    break provenance for a run that actually happened.
    """

    database = _populated_v3(tmp_path)

    with database.transaction() as conn:
        conn.execute("DELETE FROM plans WHERE id = 1")

    with database.transaction() as conn:
        row = conn.execute(
            "SELECT task_id, plan_id, plan_step_id FROM executions WHERE id = 1"
        ).fetchone()
        assert row["task_id"] == 1
        assert row["plan_id"] is None
        assert row["plan_step_id"] is None


def test_the_fresh_and_the_upgraded_schema_are_the_same_shape(tmp_path) -> None:
    """A fresh database and an upgraded one must be semantically identical.

    This is the invariant that lets every later phase write one query instead of
    branching on how the file got there.

    The comparison is structural rather than textual. ``ALTER TABLE ... ADD
    COLUMN`` appends, so an upgraded table carries its v3 columns at the end
    while a fresh one declares them in place -- ``failures.created_at`` is the
    obvious case. Column order has no meaning in SQLite for any query that names
    its columns, and this codebase never issues ``SELECT *``, so the difference
    is cosmetic. What must match is the set of columns with their types,
    nullability, defaults and primary-key flags, plus every foreign key and
    index, because those are what can change behaviour.
    """

    fresh = Database(tmp_path / "fresh.db")
    fresh.initialize()
    upgraded = _legacy_database(tmp_path)
    upgraded.initialize()

    assert _shape(fresh) == _shape(upgraded)


def _shape(database: Database) -> dict[str, object]:
    """A semantic fingerprint of every table, foreign key and index."""

    with database.transaction() as conn:
        names = [
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        shape: dict[str, object] = {}
        for name in names:
            columns = {
                str(row["name"]): (
                    str(row["type"]),
                    int(row["notnull"]),
                    row["dflt_value"],
                    int(row["pk"]),
                )
                for row in conn.execute(f"PRAGMA table_info({name})")
            }
            foreign_keys = sorted(
                (str(r["table"]), str(r["from"]), str(r["to"]), str(r["on_delete"]))
                for r in conn.execute(f"PRAGMA foreign_key_list({name})")
            )
            indexes = sorted(
                (str(r["name"]), int(r["unique"]))
                for r in conn.execute(f"PRAGMA index_list({name})")
                if not str(r["name"]).startswith("sqlite_autoindex")
            )
            shape[name] = (columns, foreign_keys, indexes)
    return shape


# ------------------------------------------------------------- atomicity


def test_an_upgrade_that_cannot_finish_leaves_the_database_untouched(tmp_path) -> None:
    """A refused upgrade must not leave half the schema applied.

    The plans rebuild and the ADD COLUMN pass are one unit. If the second fails,
    the first must be rolled back too, otherwise the file records version 2 while
    its plans table is already v3 and the next start refuses to continue.
    """

    database = _legacy_database(tmp_path)

    with database.transaction() as conn:
        # Pre-existing damage the post-upgrade foreign_key_check will find: a
        # step pointing at a plan that does not exist. Written with foreign keys
        # off because that is the only way to construct the broken state, and
        # constructing it is the point.
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO plan_steps (plan_id, position, action, created_at, updated_at) "
            "VALUES (999, 0, 'x', 'now', 'now')"
        )
        conn.execute("DELETE FROM schema_migrations")
        conn.execute("INSERT INTO schema_migrations (version) VALUES (2)")

    with pytest.raises(SchemaUpgradeError):
        with database.transaction() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            upgrade_to_v3(conn)

    with database.transaction() as conn:
        # Still v2, and neither the rebuilt plans table nor the added columns
        # survived the rollback.
        assert applied_version(conn) == 2

        def columns(table: str) -> frozenset[str]:
            rows = conn.execute(f"PRAGMA table_info({table})")
            return frozenset(str(row["name"]) for row in rows)

        assert "source" not in columns("plans")
        assert "source" not in columns("plan_steps")
        assert "tool_id" not in columns("plan_steps")
