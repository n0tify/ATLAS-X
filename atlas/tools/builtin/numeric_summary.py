"""Deterministic descriptive statistics over a bounded list of numbers.

Pure function of its input. Results are rounded to a fixed number of decimal
places so that a stored number and a recomputed number compare equal as text,
which is what a reproducibility check in a later phase will rely on.

The population variance is used, not the sample variance: the list is the whole
input, not a sample drawn from a larger population.
"""

from __future__ import annotations

from typing import Any, Mapping

from atlas.tools.definition import (
    Determinism,
    ProvenanceField,
    ToolContext,
    ToolDefinition,
    ToolLimits,
)
from atlas.tools.errors import ToolInputInvalid
from atlas.tools.schema import SchemaField, ToolSchema

TOOL_ID = "numeric_summary"
IMPLEMENTATION_ID = "atlas.tools.builtin.numeric_summary:compute"

MAX_VALUES = 10_000
VALUE_ABS_MAX = 1e12
SUM_ABS_MAX = MAX_VALUES * VALUE_ABS_MAX
VARIANCE_MAX = 4 * (VALUE_ABS_MAX**2)
ROUND_DIGITS = 6

INPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(
            name="values",
            type="array",
            required=True,
            description="Numbers to summarize. Length and magnitude are both bounded.",
            item_type="number",
            max_items=MAX_VALUES,
            item_minimum=-VALUE_ABS_MAX,
            item_maximum=VALUE_ABS_MAX,
        ),
        SchemaField(
            name="compute_variance",
            type="boolean",
            required=False,
            description="Include mean, median, and population variance.",
        ),
    )
)

OUTPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(name="count", type="integer", minimum=0, maximum=MAX_VALUES),
        SchemaField(name="minimum", type="number", minimum=-VALUE_ABS_MAX, maximum=VALUE_ABS_MAX),
        SchemaField(name="maximum", type="number", minimum=-VALUE_ABS_MAX, maximum=VALUE_ABS_MAX),
        SchemaField(name="sum", type="number", minimum=-SUM_ABS_MAX, maximum=SUM_ABS_MAX),
        # The three statistics below are present only when the caller asked for
        # them, so they are optional in the contract as well as in the result.
        # Declaring them required would make a legal run fail output validation.
        SchemaField(
            name="mean",
            type="number",
            required=False,
            minimum=-VALUE_ABS_MAX,
            maximum=VALUE_ABS_MAX,
        ),
        SchemaField(
            name="median",
            type="number",
            required=False,
            minimum=-VALUE_ABS_MAX,
            maximum=VALUE_ABS_MAX,
        ),
        SchemaField(
            name="population_variance",
            type="number",
            required=False,
            minimum=0,
            maximum=VARIANCE_MAX,
        ),
    )
)


def compute(context: ToolContext, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    """Summarize ``values``. ``context`` is unused: this tool touches no state."""

    values: list[float] = list(arguments["values"])
    if not values:
        # An empty list has no minimum. Failing is the honest answer; returning a
        # sentinel would put a number in the record that means nothing.
        raise ToolInputInvalid("values must contain at least one number")

    total = sum(values)
    count = len(values)
    ordered = sorted(values)
    middle = count // 2
    median = (
        ordered[middle]
        if count % 2 == 1
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    mean = total / count
    variance = sum((value - mean) ** 2 for value in values) / count

    result: dict[str, Any] = {
        "count": count,
        "minimum": ordered[0],
        "maximum": ordered[-1],
        "sum": total,
    }
    if arguments.get("compute_variance", True):
        result["mean"] = mean
        result["median"] = median
        result["population_variance"] = variance
    return {key: _rounded(value) for key, value in result.items()}


def _rounded(value: float | int) -> float | int:
    """Round floats so a stored number and a recomputed number compare as text.

    The declared output bounds already cover every value a bounded input can
    produce, so nothing is clamped here. Clamping would publish a number the
    tool did not actually compute.
    """

    if isinstance(value, int):
        return value
    return round(float(value), ROUND_DIGITS)


def define() -> ToolDefinition:
    return ToolDefinition(
        tool_id=TOOL_ID,
        title="Numeric summary",
        description=(
            "Count, extremes, sum, and optionally mean/median/population variance "
            "for a bounded list of numbers."
        ),
        version="1.0.0",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        limits=ToolLimits(
            max_input_bytes=MAX_VALUES * 32,
            max_output_bytes=512,
            timeout_seconds=10,
        ),
        determinism=Determinism.DETERMINISTIC,
        provenance_fields=frozenset(ProvenanceField),
        implementation=compute,
        implementation_id=IMPLEMENTATION_ID,
    )
