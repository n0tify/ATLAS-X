"""SQLite connection management and transactional access.

Every call to :meth:`Database.transaction` produces a fresh connection with a
strict set of pragmas (foreign keys ON, WAL, busy timeout, normal sync), gives
the caller a commit-on-success / rollback-on-exception scope, then closes it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from atlas.storage.migrations import init_db, upgrade_to_v3


class Database:
    def __init__(self, path: str | Path, timeout_seconds: float = 5.0) -> None:
        self._path = Path(path)
        self._timeout = timeout_seconds
        if str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _configure(conn: sqlite3.Connection) -> None:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 10000")

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=10.0)
        self._configure(conn)
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Bring the database to this build's schema version, idempotently.

        The version upgrade runs first and on its own connection because the one
        statement in it that is not additive -- the ``plans`` rebuild -- has to
        run with foreign keys off and outside a transaction. See
        :mod:`atlas.storage.migrations` for why both conditions are required.

        ``isolation_level = None`` puts the connection in autocommit so that
        ``PRAGMA foreign_keys`` and ``BEGIN`` are both statements we issue rather
        than something the driver decides. The pragma has to be set before the
        transaction exists, because SQLite ignores it inside one.
        """

        conn = self.connect()
        try:
            conn.isolation_level = None
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("PRAGMA journal_mode = WAL")
            upgrade_to_v3(conn)
        finally:
            conn.close()

        with self.transaction() as conn:
            init_db(conn)
