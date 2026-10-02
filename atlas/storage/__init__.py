"""Persistence: SQLite connection handling, deterministic migrations, and repositories."""

from atlas.storage.db import Database
from atlas.storage.owned_resources import (
    OwnedResourceRepo,
    OwnedTable,
    UnsupportedOwnedResource,
    owned_table_for,
)
from atlas.storage.repositories import (
    ProvenanceEvent,
    ProvenanceRepo,
    ProvenanceVerificationCode,
    ProvenanceVerificationError,
    SessionRepo,
    TaskRepo,
    UserRepo,
)

#: ``atlas.storage.tool_grants`` is deliberately NOT re-exported here. It
#: imports ``atlas.security.policy`` for the ``ToolGrant`` contract, and
#: ``atlas.security`` imports ``atlas.storage``; re-exporting it would make
#: ``import atlas.storage`` depend on the security package's import order and
#: fail as a circular import depending on which module is loaded first.
#: Import it by full path instead: ``from atlas.storage.tool_grants import ...``.

__all__ = [
    "Database",
    "UserRepo",
    "SessionRepo",
    "TaskRepo",
    "ProvenanceEvent",
    "ProvenanceRepo",
    "ProvenanceVerificationCode",
    "ProvenanceVerificationError",
    "OwnedResourceRepo",
    "OwnedTable",
    "UnsupportedOwnedResource",
    "owned_table_for",
]
