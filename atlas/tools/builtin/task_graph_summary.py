"""Row counts for the caller's own task graph.

Answers "what already exists under this task" without reading any content: how
many plans, steps, executions, artifacts, verifications, failures, recovery
attempts, and provenance events hang from the task. Every count is owner-scoped,
so a task belonging to another user reports nothing rather than their totals.

`state_dependent` rather than `deterministic`: identical input yields different
numbers once the task changes. The declaration is what lets a later verifier
know the difference instead of assuming a stable answer.
"""

from __future__ import annotations

from typing import Any, Mapping

from atlas.security.policy import Resource
from atlas.tools.definition import (
    Determinism,
    ProvenanceField,
    ToolContext,
    ToolDefinition,
    ToolLimits,
)
from atlas.tools.schema import SchemaField, ToolSchema

TOOL_ID = "task_graph_summary"
IMPLEMENTATION_ID = "atlas.tools.builtin.task_graph_summary:compute"

MAX_COUNT = 1_000_000

#: The resource kinds this tool reports, in a fixed order so the output is
#: comparable across runs.
REPORTED: tuple[tuple[str, Resource], ...] = (
    ("plan_count", Resource.PLAN),
    ("plan_step_count", Resource.PLAN_STEP),
    ("execution_count", Resource.EXECUTION),
    ("artifact_count", Resource.ARTIFACT),
    ("verification_count", Resource.VERIFICATION),
    ("failure_count", Resource.FAILURE),
    ("recovery_attempt_count", Resource.RECOVERY_ATTEMPT),
    ("provenance_event_count", Resource.PROVENANCE_EVENT),
)

_CHOICES = tuple(name.removesuffix("_count") for name, _ in REPORTED)

INPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(
            name="include",
            type="array",
            required=False,
            description="Resource kinds to count. Omit for all of them.",
            item_type="string",
            max_items=len(REPORTED),
            choices=_CHOICES,
        ),
    )
)

#: Only the kinds named in ``include`` appear, so no count is required. Marking
#: them required would make a filtered run fail output validation.
OUTPUT_SCHEMA = ToolSchema(
    fields=tuple(
        SchemaField(
            name=name, type="integer", required=False, minimum=0, maximum=MAX_COUNT
        )
        for name, _ in REPORTED
    )
)


def compute(context: ToolContext, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    """Count owned rows under the authorized task. ``context.view`` is the only
    data source and it is already scoped to the caller."""

    requested = arguments.get("include")
    wanted = set(requested) if requested else {resource.value for _, resource in REPORTED}
    result: dict[str, int] = {}
    for name, resource in REPORTED:
        if resource.value not in wanted:
            continue
        result[name] = min(
            context.view.count_rows(
                resource=resource, user_id=context.user_id, task_id=context.task_id
            ),
            MAX_COUNT,
        )
    return result


def define() -> ToolDefinition:
    return ToolDefinition(
        tool_id=TOOL_ID,
        title="Task graph summary",
        description=(
            "Owner-scoped row counts for the plans, steps, executions, artifacts, "
            "verifications, failures, recovery attempts, and provenance events "
            "under the authorized task."
        ),
        version="1.0.0",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        limits=ToolLimits(
            max_input_bytes=1024,
            max_output_bytes=1024,
            timeout_seconds=10,
        ),
        determinism=Determinism.STATE_DEPENDENT,
        provenance_fields=frozenset(ProvenanceField),
        implementation=compute,
        implementation_id=IMPLEMENTATION_ID,
    )
