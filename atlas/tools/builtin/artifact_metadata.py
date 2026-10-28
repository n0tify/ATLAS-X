"""Artifact metadata for one of the caller's executions.

This is the "inspect a produced file" capability, implemented as metadata
inspection rather than file reading. It reports what the platform recorded when
the artifact was produced — name, kind, size, whether a checksum exists — and
returns no content and no host path.

Declining to read the file is the security decision, not a limitation to work
around. Reading an artifact means opening a path from a database column, and
`docs/STORAGE_REVIEW.md` §13 is explicit that `artifacts.relative_path` is not
validated and that filesystem confinement belongs to the sandbox phase. A
registry that handed a tool a validated-looking path reader in Phase 09 would be
claiming a control the code does not have. Phase 10 supplies confinement; this
tool needs none of it.
"""

from __future__ import annotations

from typing import Any, Mapping

from atlas.security.policy import MAX_RESOURCE_ID, Resource
from atlas.tools.definition import (
    Determinism,
    ProvenanceField,
    ToolContext,
    ToolDefinition,
    ToolLimits,
)
from atlas.tools.errors import ToolExecutionFailed
from atlas.tools.schema import SchemaField, ToolSchema

TOOL_ID = "artifact_metadata"
IMPLEMENTATION_ID = "atlas.tools.builtin.artifact_metadata:compute"

MAX_NAMES = 100
MAX_NAME_CHARS = 200
MAX_KINDS = 20
MAX_TOTAL_BYTES = 2**53 - 1

INPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(
            name="execution_id",
            type="integer",
            required=True,
            description="Execution whose artifacts should be described.",
            minimum=1,
            maximum=MAX_RESOURCE_ID,
        ),
    )
)

OUTPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(name="execution_id", type="integer", minimum=1, maximum=MAX_RESOURCE_ID),
        SchemaField(name="artifact_count", type="integer", minimum=0, maximum=MAX_NAMES),
        SchemaField(name="total_size_bytes", type="integer", minimum=0, maximum=MAX_TOTAL_BYTES),
        SchemaField(
            name="names",
            type="array",
            description="Artifact names, bounded.",
            item_type="string",
            max_items=MAX_NAMES,
        ),
        SchemaField(
            name="kinds",
            type="array",
            description="Distinct artifact kinds, sorted.",
            item_type="string",
            max_items=MAX_KINDS,
        ),
        SchemaField(
            name="all_checksums_present",
            type="boolean",
            description="True only when every artifact carries a checksum.",
        ),
    )
)


def compute(context: ToolContext, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    """Describe artifacts of the authorized execution.

    The rows come through the owner-scoped view, so an execution belonging to
    another user is simply not found. Reading happens in two steps on purpose:
    the execution must be confirmed to be the caller's before its artifacts are
    read at all.
    """

    execution_id = int(arguments["execution_id"])
    view = context.view

    execution = view.get_row(
        resource=Resource.EXECUTION, user_id=context.user_id, resource_id=execution_id
    )
    if execution is None:
        raise ToolExecutionFailed(
            "no execution with that id exists for the authorized task"
        )

    # The execution's own task owns its artifacts; use that rather than the
    # caller's currently-selected task so an artifact lookup is not falsely
    # refused when the playground's selected task differs from the execution's.
    execution_task_id = execution.get("task_id")
    artifact_task_id = int(execution_task_id) if execution_task_id is not None else context.task_id

    # Narrowed to the execution in SQL, not by filtering afterwards, so the
    # row cap cannot hide artifacts belonging to the requested execution.
    selected = view.list_rows(
        resource=Resource.ARTIFACT,
        user_id=context.user_id,
        task_id=artifact_task_id,
        parent_id=execution_id,
        limit=MAX_NAMES,
    )

    names = [str(row.get("name") or "")[:MAX_NAME_CHARS] for row in selected]
    kinds = sorted({str(row.get("kind") or "")[:MAX_NAME_CHARS] for row in selected})
    total = sum(
        int(row["size_bytes"]) for row in selected if isinstance(row.get("size_bytes"), int)
    )
    return {
        "execution_id": execution_id,
        "artifact_count": len(selected),
        "total_size_bytes": min(total, MAX_TOTAL_BYTES),
        "names": names,
        "kinds": kinds[:MAX_KINDS],
        "all_checksums_present": bool(selected)
        and all(bool(row.get("checksum")) for row in selected),
    }


def define() -> ToolDefinition:
    return ToolDefinition(
        tool_id=TOOL_ID,
        title="Artifact metadata",
        description=(
            "Names, kinds, sizes, and checksum presence for the artifacts of one "
            "of the caller's executions. Returns no content and no host path."
        ),
        version="1.0.0",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        limits=ToolLimits(
            max_input_bytes=1024,
            max_output_bytes=32 * 1024,
            timeout_seconds=10,
        ),
        determinism=Determinism.STATE_DEPENDENT,
        provenance_fields=frozenset(ProvenanceField),
        implementation=compute,
        implementation_id=IMPLEMENTATION_ID,
    )
