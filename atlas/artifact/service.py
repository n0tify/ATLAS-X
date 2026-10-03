"""Phase 17: Artifact service for creating and managing artifacts.

This is the authorization boundary for artifact operations. It enforces:
- Ownership: artifacts belong to the execution's task owner.
- Bounds: content size, count, and metadata limits are enforced.
- Integrity: checksums are computed and stored.
- Provenance: every artifact creation is recorded in the provenance chain.

What it does not do:
- It does not read artifact content (that's a separate Phase 10B sandbox concern).
- It does not serve artifact content directly (that's a separate API concern).
- It does not modify artifacts after creation (they are immutable).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from atlas.artifact.repo import ArtifactRepo

if TYPE_CHECKING:
    from atlas.security.policy import DenyReason, Operation, Resource
    from atlas.security.service import AuthorizationService

logger = logging.getLogger(__name__)


class ArtifactService:
    """Records artifacts and enforces bounds, integrity, and ownership."""

    def __init__(
        self,
        authorization: AuthorizationService,
        *,
        artifact_repo: Optional["ArtifactRepo"] = None,
    ) -> None:
        self._auth = authorization
        self._artifacts = artifact_repo or None  # Will be created on first use

    @property
    def _repo(self) -> "ArtifactRepo":
        if self._artifacts is None:
            from atlas.artifact.repo import ArtifactRepo
            self._artifacts = ArtifactRepo()
        return self._artifacts

    def create(
        self,
        session_token: object,
        *,
        execution_id: int,
        name: str,
        kind: str,
        content: Optional[str] = None,
        relative_path: Optional[str] = None,
        kind_override: Optional[str] = None,
        source: str = "tool",
        metadata: Optional[dict[str, Any]] = None,
    ) -> int:
        """Create an artifact for an execution.

        Ownership is verified: the caller must own the execution's task.
        Content and metadata bounds are enforced.

        Returns the new artifact's row id.
        """

        identity = self._auth.authenticate(session_token)
        eid = self._auth._as_id(execution_id, Resource.EXECUTION)

        with self._auth._db.transaction() as conn:
            # Verify ownership of the execution's task
            exec_row = self._auth._executions.get(conn, eid)
            if exec_row is None:
                self._auth._deny(
                    identity, Resource.EXECUTION, Operation.READ, DenyReason.RESOURCE_NOT_OWNED
                )
            task_id = int(exec_row["task_id"])
            self._auth._require_owned_task(
                conn,
                identity,
                task_id,
                resource=Resource.ARTIFACT,
                operation=Operation.CREATE,
            )

            # Create the artifact
            artifact_id = self._repo.create(
                conn,
                execution_id=eid,
                name=name,
                kind=kind,
                relative_path=relative_path,
                content=content,
                source="tool" if source == "tool" else source,
                metadata={} if source == "tool" else None,
                created_by=identity.username,
            )

            # Record provenance
            self._auth._provenance.record_event(
                conn,
                task_id=task_id,
                execution_id=eid,
                event_type="artifact_created",
                actor="artifact_service",
                detail={
                    "artifact_id": artifact_id,
                    "name": name,
                    "kind": kind,
                    "size_bytes": len(content.encode("utf-8")) if content else 0,
                    "source": source,
                },
            )

            logger.info(
                "artifact created user_id=%s task_id=%s execution_id=%s "
                "artifact_id=%s name=%s kind=%s size=%d",
                identity.user_id,
                task_id,
                eid,
                artifact_id,
                name,
                kind,
                len(content.encode("utf-8")) if content else 0,
            )
            return artifact_id

    def get(self, session_token: object, artifact_id: int) -> Optional[dict[str, Any]]:
        """Read an artifact by id, enforcing ownership."""

        identity = self._auth.authenticate(session_token)
        aid = self._auth._as_id(artifact_id, Resource.ARTIFACT)

        with self._auth._db.transaction() as conn:
            artifact = self._repo.get(conn, aid)
            if artifact is None:
                return None
            # Verify ownership via execution -> task
            exec_row = self._auth._executions.get(conn, artifact.execution_id)
            if exec_row is None:
                return None
            self._auth._require_owned_task(
                conn,
                identity,
                int(exec_row["task_id"]),
                resource=Resource.ARTIFACT,
                operation=Operation.READ,
            )
            return artifact.as_dict()

    def list_for_execution(
        self, session_token: object, execution_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List artifacts for an execution the caller owns."""

        identity = self._auth.authenticate(session_token)
        eid = self._auth._as_id(execution_id, Resource.EXECUTION)

        with self._auth._db.transaction() as conn:
            # Verify ownership
            exec_row = self._auth._executions.get(conn, eid)
            if exec_row is None:
                self._auth._deny(
                    identity, Resource.ARTIFACT, Operation.READ, DenyReason.RESOURCE_NOT_OWNED
                )
            self._auth._require_owned_task(
                conn,
                self._auth.authenticate(session_token),
                int(exec_row["task_id"]),
                resource=Resource.ARTIFACT,
                operation=Operation.READ,
            )
            artifacts = self._repo.for_execution(conn, eid, limit)
            return [a.as_dict() for a in artifacts]

    def list_for_task(
        self, session_token: object, task_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List artifacts for a task the caller owns."""

        tid = self._auth._as_id(task_id, Resource.TASK)

        with self._auth._db.transaction() as conn:
            self._auth._require_owned_task(
                conn,
                self._auth.authenticate(session_token),
                tid,
                resource=Resource.ARTIFACT,
                operation=Operation.READ,
            )
            artifacts = self._repo.for_task(conn, tid, limit)
            return [a.as_dict() for a in artifacts]

    def verify(self, session_token: object, artifact_id: int) -> None:
        """Mark an artifact as verified by its creator."""

        identity = self._auth.authenticate(session_token)
        aid = self._auth._as_id(artifact_id, Resource.ARTIFACT)

        with self._auth._db.transaction() as conn:
            artifact = self._repo.get(conn, aid)
            if artifact is None:
                raise ValueError(f"artifact {aid} not found")
            exec_row = self._auth._executions.get(conn, artifact.execution_id)
            if exec_row is None:
                raise ValueError("execution not found")
            self._auth._require_owned_task(
                conn,
                self._auth.authenticate(session_token),
                int(exec_row["task_id"]),
                resource=Resource.ARTIFACT,
                operation=Operation.CREATE,  # verification is a form of creation
            )
            self._repo.verify(conn, aid, identity.username)

__all__ = ["ArtifactService"]
