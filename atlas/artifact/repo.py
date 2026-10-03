"""Storage for artifacts: one row per durable output.

An ``artifacts`` row represents a durable output produced by a tool execution
or recovery. It stores metadata and optional content, with integrity checking
via checksums.

Three properties this module enforces structurally rather than leaving to callers:

* **An artifact belongs to an execution.** ``execution_id`` is NOT NULL and
  references a valid execution. The execution's ownership implies the
  artifact's ownership.
* **Content is bounded.** ``content`` is capped at :data:`MAX_CONTENT_BYTES`,
  and total per-execution size is bounded by :data:`MAX_TOTAL_EXECUTION_BYTES`.
* **Integrity is verifiable.** ``checksum`` is a SHA-256 digest of the content,
  enabling tamper detection.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from atlas.artifact.types import (
    MAX_ARTIFACTS_PER_EXECUTION,
    MAX_CONTENT_BYTES,
    MAX_METADATA_JSON_CHARS,
    MAX_TOTAL_EXECUTION_BYTES,
)
from atlas.util import utcnow_iso

#: Bound on artifact name length.
MAX_NAME_CHARS = 256

#: Bound on artifact kind length.
MAX_KIND_CHARS = 32


class ArtifactWriteInvalid(ValueError):
    """A caller tried to write an artifact the schema could not honestly hold."""


@dataclass(frozen=True)
class ArtifactRecord:
    """One artifact, as stored."""

    id: int
    execution_id: int
    name: str
    kind: str
    relative_path: Optional[str]
    content: Optional[str]
    size_bytes: int
    checksum: Optional[str]
    source: str
    verified: int
    metadata_json: Optional[str]
    created_by: Optional[str]
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "name": self.name,
            "kind": self.kind,
            "relative_path": self.relative_path,
            "content": self.content,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "source": self.source,
            "verified": self.verified,
            "metadata_json": self.metadata_json,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


class ArtifactRepo:
    """Writes and reads for ``artifacts``."""

    def create(
        self,
        conn: sqlite3.Connection,
        *,
        execution_id: int,
        name: str,
        kind: str,
        relative_path: Optional[str] = None,
        content: Optional[str] = None,
        source: str = "tool",
        metadata: Optional[Mapping[str, Any]] = None,
        created_by: Optional[str] = None,
    ) -> int:
        """Record one artifact. Immutable once written."""

        if not isinstance(name, str) or not name.strip():
            raise ArtifactWriteInvalid("name must be a non-empty string")
        if len(name) > 256:
            raise ArtifactWriteInvalid("name exceeds 256 characters")

        if not isinstance(kind, str) or not kind.strip():
            raise ArtifactWriteInvalid("kind must be a non-empty string")
        if len(kind) > 32:
            raise ArtifactWriteInvalid("kind exceeds 32 characters")

        if relative_path is not None:
            if not isinstance(relative_path, str):
                raise ArtifactWriteInvalid("relative_path must be a string")
            if len(relative_path) > 512:
                raise ArtifactWriteInvalid("relative_path exceeds 512 characters")

        if content is not None:
            if not isinstance(content, str):
                raise ArtifactWriteInvalid("content must be a string")
            content_bytes = content.encode("utf-8")
            if len(content_bytes) > MAX_CONTENT_BYTES:
                raise ArtifactWriteInvalid(
                    f"content exceeds {MAX_CONTENT_BYTES} bytes"
                )
            checksum = hashlib.sha256(content_bytes).hexdigest()
        else:
            checksum = None

        if relative_path is not None and content is None:
            raise ArtifactWriteInvalid("relative_path requires content")

        # Check total execution size limit
        total_bytes = self._get_execution_total_bytes(conn, execution_id)
        content_size = len(content.encode("utf-8")) if content else 0
        if total_bytes + content_size > MAX_TOTAL_EXECUTION_BYTES:
            raise ArtifactWriteInvalid(
                f"execution artifacts would exceed {MAX_TOTAL_EXECUTION_BYTES} bytes"
            )

        # Check artifact count limit
        count = self._get_execution_artifact_count(conn, execution_id)
        if count >= MAX_ARTIFACTS_PER_EXECUTION:
            raise ArtifactWriteInvalid(
                f"execution would exceed {MAX_ARTIFACTS_PER_EXECUTION} artifacts"
            )

        cursor = conn.execute(
            "INSERT INTO artifacts "
            "(execution_id, name, kind, relative_path, content, size_bytes, "
            "checksum, source, verified, metadata_json, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                execution_id,
                name,
                kind,
                relative_path,
                content,
                content_size,
                checksum,
                source,
                _encode_json(metadata, "metadata"),
                created_by,
                utcnow_iso(),
            ),
        )
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("artifact insert returned no row id")
        return int(row_id)

    def get(self, conn: sqlite3.Connection, artifact_id: int) -> Optional[ArtifactRecord]:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def for_execution(
        self, conn: sqlite3.Connection, execution_id: int, limit: int = 100
    ) -> list[ArtifactRecord]:
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE execution_id = ? ORDER BY id ASC LIMIT ?",
            (execution_id, limit),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def for_task(
        self, conn: sqlite3.Connection, task_id: int, limit: int = 100
    ) -> list[ArtifactRecord]:
        rows = conn.execute(
            """
            SELECT a.* FROM artifacts a
            JOIN executions e ON e.id = a.execution_id
            WHERE e.task_id = ? ORDER BY a.id ASC LIMIT ?
            """,
            (task_id, limit),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def verify(
        self, conn: sqlite3.Connection, artifact_id: int, created_by: str
    ) -> None:
        """Mark an artifact as verified by its creator."""
        cursor = conn.execute(
            "UPDATE artifacts SET verified = 1, created_by = ? WHERE id = ? AND created_by = ?",
            (created_by, artifact_id, created_by),
        )
        if cursor.rowcount == 0:
            raise ArtifactWriteInvalid("artifact not found or not owned by caller")

    def _row_to_record(self, row: sqlite3.Row) -> ArtifactRecord:
        return ArtifactRecord(
            id=row["id"],
            execution_id=row["execution_id"],
            name=row["name"],
            kind=row["kind"],
            relative_path=row["relative_path"],
            content=row["content"],
            size_bytes=row["size_bytes"],
            checksum=row["checksum"],
            source=row["source"],
            verified=row["verified"],
            metadata_json=row["metadata_json"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )

    def _get_execution_total_bytes(
        self, conn: sqlite3.Connection, execution_id: int
    ) -> int:
        row = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM artifacts WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def _get_execution_artifact_count(
        self, conn: sqlite3.Connection, execution_id: int
    ) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        return int(row[0]) if row else 0


def _encode_json(value: Optional[Mapping[str, Any]], name: str) -> Optional[str]:
    if value is None:
        return None
    encoded = json.dumps(dict(value), ensure_ascii=True, sort_keys=True, default=str)
    if len(encoded) > MAX_METADATA_JSON_CHARS:
        raise ArtifactWriteInvalid(f"artifact {name} exceeds {MAX_METADATA_JSON_CHARS} characters")
    return encoded


__all__ = [
    "ArtifactRecord",
    "ArtifactRepo",
    "ArtifactWriteInvalid",
    "MAX_NAME_CHARS",
    "MAX_KIND_CHARS",
    "MAX_CONTENT_BYTES",
    "MAX_METADATA_JSON_CHARS",
    "MAX_TOTAL_EXECUTION_BYTES",
    "MAX_ARTIFACTS_PER_EXECUTION",
]
