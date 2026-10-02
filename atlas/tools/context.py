"""The narrow, owner-scoped data view a tool implementation is given.

Tool bodies need to read the caller's own rows — that is what makes a tool
useful at all — but they must not be handed a database connection. A
connection would let a tool implementation run arbitrary SQL and quietly become
a second, unaudited data-access layer that no owner predicate constrains.

:class:`OwnedTaskView` is that narrowing. Every method takes the ``user_id``
that authorization already established, applies the same owner predicate the
authorization layer relies on, and returns plain rows. There is no method for
writing, no method that accepts a caller-chosen owner, and no method that
returns a connection.
"""

from __future__ import annotations

from typing import Any

from atlas.security.policy import MAX_RESOURCE_ID
from atlas.storage.db import Database
from atlas.storage.owned_resources import (
    OwnedResourceRepo,
    UnsupportedOwnedResource,
    owned_table_for,
)

#: Hard ceiling on rows a single tool invocation may read. A tool that needs
#: more must page, which keeps one invocation's memory bounded.
MAX_VIEW_ROWS = 500


def _positive_id(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer row id")
    if not 0 < value <= MAX_RESOURCE_ID:
        raise ValueError(f"{name} must be a positive row id")
    return value


class OwnedTaskView:
    """Read-only, owner-scoped access to one user's rows."""

    __slots__ = ("_db", "_owned")

    def __init__(self, db: Database, owned: OwnedResourceRepo | None = None) -> None:
        self._db = db
        self._owned = owned or OwnedResourceRepo()

    def list_rows(
        self,
        *,
        resource: object,
        user_id: int,
        task_id: int,
        parent_id: int | None = None,
        limit: int = MAX_VIEW_ROWS,
    ) -> list[dict[str, Any]]:
        """Rows of ``resource`` under ``task_id`` that ``user_id`` owns.

        ``parent_id`` narrows in SQL to the direct parent (the execution for an
        artifact). Filtering after the read instead would silently cap results
        at ``limit`` and report a short list as if it were the whole answer.
        """

        owner = _positive_id(user_id, "user_id")
        task = _positive_id(task_id, "task_id")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 0 < limit <= MAX_VIEW_ROWS
        ):
            raise ValueError(f"limit must be 1..{MAX_VIEW_ROWS}")
        parent = None if parent_id is None else _positive_id(parent_id, "parent_id")
        owned_table_for(resource)
        with self._db.transaction() as conn:
            return self._owned.list_owned_for_task(
                conn,
                resource=resource,
                user_id=owner,
                task_id=task,
                parent_id=parent,
                limit=limit,
            )

    def count_rows(self, *, resource: object, user_id: int, task_id: int) -> int:
        """How many rows of ``resource`` under ``task_id`` that ``user_id`` owns."""

        owner = _positive_id(user_id, "user_id")
        task = _positive_id(task_id, "task_id")
        owned_table_for(resource)
        with self._db.transaction() as conn:
            return self._owned.count_owned_for_task(
                conn, resource=resource, user_id=owner, task_id=task
            )

    def get_row(
        self, *, resource: object, user_id: int, resource_id: int
    ) -> dict[str, Any] | None:
        """One row, or ``None`` when ``user_id`` does not own it.

        ``None`` is returned for both "not yours" and "does not exist", which
        keeps this view from being an existence oracle.
        """

        owner = _positive_id(user_id, "user_id")
        row_id = _positive_id(resource_id, "resource_id")
        owned_table_for(resource)
        with self._db.transaction() as conn:
            row = self._owned.get_owned(
                conn, resource=resource, user_id=owner, resource_id=row_id
            )
        return dict(row) if row is not None else None

    def supports(self, resource: object) -> bool:
        """Whether ``resource`` has an owner-scoped table at all."""

        try:
            owned_table_for(resource)
        except UnsupportedOwnedResource:
            return False
        return True
