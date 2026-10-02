"""Persistence layer tests (Phase 6)."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from atlas.storage.db import Database
from atlas.storage.migrations import SCHEMA_VERSION
from atlas.storage.repositories import ProvenanceRepo, TaskRepo, UserRepo
from atlas.util import utcnow_iso

EXPECTED_TABLES = {
    "schema_migrations",
    "users",
    "sessions",
    "tasks",
    "plans",
    "plan_steps",
    "executions",
    "artifacts",
    "verifications",
    "failures",
    "recovery_attempts",
    "provenance_events",
    "evaluation_runs",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row["name"] for row in rows}


def test_initialize_from_empty_directory_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "nested" / "data" / "atlas.db")
    db.initialize()
    db.initialize()

    with db.transaction() as conn:
        tables = _table_names(conn)
        assert EXPECTED_TABLES <= tables
        version = conn.execute("SELECT version FROM schema_migrations").fetchone()
        assert version["version"] == SCHEMA_VERSION
        count = conn.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()["c"]
        assert count == 1


def test_foreign_key_enforced_on_tasks_user(tmp_path) -> None:
    db = Database(tmp_path / "atlas.db")
    db.initialize()
    users = UserRepo()
    tasks = TaskRepo()

    with db.transaction() as conn:
        user_id = users.create(conn, username="owner", password_hash="x")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            tasks.create(conn, user_id=user_id + 999, title="t", goal="g")


def test_foreign_key_enforced_on_sessions_user(tmp_path) -> None:
    db = Database(tmp_path / "atlas.db")
    db.initialize()
    sessions = _sessions_repo()

    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            sessions.create(
                conn, user_id=999, token_hash="abc", expires_at=utcnow_iso()
            )


def _sessions_repo():
    from atlas.storage.repositories import SessionRepo

    return SessionRepo()


def test_ownership_relationships_are_enforced(tmp_path) -> None:
    db = Database(tmp_path / "atlas.db")
    db.initialize()
    users = UserRepo()
    tasks = TaskRepo()

    with db.transaction() as conn:
        alice = users.create(conn, username="alice", password_hash="x")
        bob = users.create(conn, username="bob", password_hash="x")
        task_id = tasks.create(conn, user_id=alice, title="t", goal="g")

    with db.transaction() as conn:
        assert tasks.get(conn, alice, task_id) is not None
        assert tasks.get(conn, bob, task_id) is None
        assert tasks.get(conn, alice, task_id + 999) is None
        assert tasks.delete(conn, bob, task_id) == 0
        assert tasks.list_for_user(conn, bob) == []

    with db.transaction() as conn:
        assert tasks.delete(conn, alice, task_id) == 1
    with db.transaction() as conn:
        assert tasks.get(conn, alice, task_id) is None


def test_delete_user_cascades_owned_tasks(tmp_path) -> None:
    db = Database(tmp_path / "atlas.db")
    db.initialize()
    users = UserRepo()
    tasks = TaskRepo()

    with db.transaction() as conn:
        user_id = users.create(conn, username="cascade-me", password_hash="x")
        task_id = tasks.create(conn, user_id=user_id, title="t", goal="g")
        users.delete(conn, user_id)

    with db.transaction() as conn:
        assert tasks.get(conn, user_id, task_id) is None


def test_provenance_records_and_survives_task_delete(tmp_path) -> None:
    db = Database(tmp_path / "atlas.db")
    db.initialize()
    users = UserRepo()
    tasks = TaskRepo()
    provenance = ProvenanceRepo()

    with db.transaction() as conn:
        user_id = users.create(conn, username="p-user", password_hash="x")
        task_id = tasks.create(conn, user_id=user_id, title="t", goal="g")
        provenance.record(
            conn, task_id=task_id, event_type="task.created", actor="test", detail={"k": 1}
        )
        tasks.delete(conn, user_id, task_id)

    with db.transaction() as conn:
        row = conn.execute(
            "SELECT task_id FROM provenance_events WHERE event_type='task.created'"
        ).fetchone()
        assert row is not None
        assert row["task_id"] is None


def test_transaction_rollback_leaves_no_partial_rows(tmp_path) -> None:
    db = Database(tmp_path / "atlas.db")
    db.initialize()
    users = UserRepo()

    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            users.create(conn, username="partial", password_hash="x")
            raise RuntimeError("boom")

    with db.transaction() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        assert count == 0


def test_concurrent_basic_operations(tmp_path) -> None:
    db = Database(tmp_path / "atlas.db")
    db.initialize()
    users = UserRepo()
    usernames = [f"thread-user-{i}" for i in range(6)]

    def add(username: str) -> None:
        with db.transaction() as conn:
            users.create(conn, username=username, password_hash="ignore")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(add, usernames))

    with db.transaction() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        assert count == 6
