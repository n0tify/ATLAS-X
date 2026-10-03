"""Phase 17: Artifact type definitions and constants.

Artifacts are the durable outputs of tool executions. They are stored with
bounded metadata and optional content, linked to executions and provenance.
"""

from __future__ import annotations

from enum import Enum


class ArtifactKind(str, Enum):
    """Standard artifact kinds. Extensible but closed for this phase."""

    FILE = "file"
    LOG = "log"
    REPORT = "report"
    DATA = "data"
    IMAGE = "image"
    MODEL = "model"
    OTHER = "other"


class ArtifactSource(str, Enum):
    """Origin of the artifact."""

    TOOL = "tool"
    RECOVERY = "recovery"
    USER = "user"
    SYSTEM = "system"


#: Maximum length of artifact name.
MAX_NAME_CHARS = 256

#: Maximum length of artifact kind.
MAX_KIND_CHARS = 32

#: Maximum artifact content size (10 MB).
MAX_CONTENT_BYTES = 10 * 1024 * 1024

#: Maximum artifact metadata JSON size.
MAX_METADATA_JSON_CHARS = 64_000

#: Maximum total size of all artifacts per execution (50 MB).
MAX_TOTAL_EXECUTION_BYTES = 50 * 1024 * 1024

#: Maximum number of artifacts per execution.
MAX_ARTIFACTS_PER_EXECUTION = 100

#: Digest algorithm for artifact checksums.
DIGEST_ALGORITHM = "sha256"


__all__ = [
    "ArtifactKind",
    "ArtifactSource",
    "MAX_NAME_CHARS",
    "MAX_KIND_CHARS",
    "MAX_CONTENT_BYTES",
    "MAX_METADATA_JSON_CHARS",
    "MAX_TOTAL_EXECUTION_BYTES",
    "MAX_ARTIFACTS_PER_EXECUTION",
    "DIGEST_ALGORITHM",
]
