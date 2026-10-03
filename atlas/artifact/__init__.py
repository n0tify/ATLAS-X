"""Phase 17: Artifact management for durable tool outputs.

Artifacts are the durable outputs of tool executions. They are stored with
bounded metadata and optional content, linked to executions and provenance.

Key guarantees:
- Ownership: artifacts belong to the execution's task owner.
- Bounds: content size, count, and metadata limits are enforced.
- Integrity: SHA-256 checksums are computed and stored.
- Provenance: every artifact creation is recorded in the provenance chain.
- Immutability: artifacts are created once and never modified (only verified).
"""

from __future__ import annotations

from atlas.artifact.repo import ArtifactRecord, ArtifactRepo, ArtifactWriteInvalid
from atlas.artifact.service import ArtifactService
from atlas.artifact.types import (
    DIGEST_ALGORITHM,
    MAX_ARTIFACTS_PER_EXECUTION,
    MAX_CONTENT_BYTES,
    MAX_KIND_CHARS,
    MAX_METADATA_JSON_CHARS,
    MAX_NAME_CHARS,
    MAX_TOTAL_EXECUTION_BYTES,
    ArtifactKind,
    ArtifactSource,
)

__all__ = [
    "ArtifactKind",
    "ArtifactSource",
    "DIGEST_ALGORITHM",
    "MAX_ARTIFACTS_PER_EXECUTION",
    "MAX_CONTENT_BYTES",
    "MAX_KIND_CHARS",
    "MAX_METADATA_JSON_CHARS",
    "MAX_NAME_CHARS",
    "MAX_TOTAL_EXECUTION_BYTES",
    "ArtifactRecord",
    "ArtifactRepo",
    "ArtifactWriteInvalid",
    "ArtifactService",
    "ArtifactKind",
    "ArtifactSource",
]
