"""Deterministic row and column statistics over a bounded inline CSV string.

Exists for the Phase 18 end-to-end path: a user pastes a small CSV, a plan
measures it, and the result is verified. Boring on purpose — a pure function of
``text``, ``column``, and ``delimiter``, with no filesystem and no network, so the
CSV arrives as task input rather than as a file this process reads on the model's
say-so.

The parser is the strict one: split on ``"\\n"``, split each line on the delimiter,
reject quotes, carriage returns, ragged rows, and duplicate header names. That is
narrower than RFC 4180 on purpose. A permissive parser is a parser whose output
depends on which library implements it, and this project's whole verification story
rests on two implementations of the same contract being able to disagree loudly
rather than both quietly agreeing on something odd. Anything with quoting in it is
not data this tool measures.

Aggregates are computed only over a column whose every non-blank cell parses as a
finite number. A column with a blank or a word is counted but not summed: a mean
over the values that happened to parse is a statistic of a subset wearing the label
of the whole.
"""

from __future__ import annotations

import math
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

TOOL_ID = "csv_statistics"
IMPLEMENTATION_ID = "atlas.tools.builtin.csv_statistics:compute"

MAX_TEXT_CHARS = 100_000
MAX_ROWS = 500
MAX_COLUMNS = 50
MAX_COLUMN_NAME_CHARS = 128

#: Aggregate magnitude bound, matching the numeric tool's per-value bound so a
#: Phase 18 report reads consistently.
VALUE_ABS_MAX = 1e12
SUM_ABS_MAX = MAX_ROWS * VALUE_ABS_MAX

ROUND_DIGITS = 6

INPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(
            name="text",
            type="string",
            required=True,
            description=(
                "Inline CSV text. The first line is the header row. Quotes and "
                "carriage returns are not accepted."
            ),
            max_length=MAX_TEXT_CHARS,
        ),
        SchemaField(
            name="column",
            type="string",
            required=True,
            description="Header name of the column to aggregate.",
            max_length=MAX_COLUMN_NAME_CHARS,
        ),
        SchemaField(
            name="delimiter",
            type="string",
            required=False,
            description="Single-character field delimiter. Defaults to a comma.",
            max_length=1,
        ),
    )
)

OUTPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(name="row_count", type="integer", minimum=0, maximum=MAX_ROWS),
        SchemaField(
            name="column_count", type="integer", minimum=1, maximum=MAX_COLUMNS
        ),
        SchemaField(
            name="columns",
            type="array",
            required=False,
            description="Header names, sorted, so column order in the text is not a fact.",
            item_type="string",
            max_items=MAX_COLUMNS,
        ),
        SchemaField(
            name="numeric_count",
            type="integer",
            minimum=0,
            maximum=MAX_ROWS,
            description=(
                "Cells in the chosen column that parsed as numbers. Equal to the "
                "cell count when aggregates are present."
            ),
        ),
        SchemaField(
            name="minimum",
            type="number",
            required=False,
            minimum=-VALUE_ABS_MAX,
            maximum=VALUE_ABS_MAX,
        ),
        SchemaField(
            name="maximum",
            type="number",
            required=False,
            minimum=-VALUE_ABS_MAX,
            maximum=VALUE_ABS_MAX,
        ),
        SchemaField(
            name="sum",
            type="number",
            required=False,
            minimum=-SUM_ABS_MAX,
            maximum=SUM_ABS_MAX,
        ),
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
    )
)


def compute(context: ToolContext, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    """Measure ``text``. ``context`` is unused: this tool touches no state."""

    text = arguments["text"]
    column = arguments["column"]
    delimiter = arguments.get("delimiter", ",")

    rows = _parse(text, str(delimiter))
    header = rows[0]
    if column not in header:
        raise ToolInputInvalid(f"column {column!r} is not in the header row")
    width = header.index(column)
    body = rows[1:]

    cells = [row[width] for row in body]
    numbers: list[float] = []
    fully_numeric = bool(cells)
    for cell in cells:
        if not cell.strip():
            fully_numeric = False
            continue
        value = _to_number(cell)
        if value is None:
            fully_numeric = False
            continue
        numbers.append(value)

    result: dict[str, Any] = {
        "row_count": len(body),
        "column_count": len(header),
        "columns": sorted(header),
        "numeric_count": len(numbers),
    }
    if fully_numeric and numbers:
        total = sum(numbers)
        ordered = sorted(numbers)
        middle = len(ordered) // 2
        mean = total / len(ordered)
        result.update(
            {
                "minimum": ordered[0],
                "maximum": ordered[-1],
                "sum": total,
                "mean": mean,
                "median": (
                    ordered[middle]
                    if len(ordered) % 2 == 1
                    else (ordered[middle - 1] + ordered[middle]) / 2.0
                ),
            }
        )
    return {
        key: _rounded(value) if isinstance(value, float) else value
        for key, value in result.items()
    }


def _parse(text: str, delimiter: str) -> list[list[str]]:
    """Split ``text`` into rows, or refuse. Never guesses."""

    if not text:
        raise ToolInputInvalid("text must not be empty")
    if not delimiter or len(delimiter) != 1:
        raise ToolInputInvalid("delimiter must be a single character")
    if '"' in text:
        raise ToolInputInvalid("text must not contain double quotes")
    if "\r" in text:
        raise ToolInputInvalid("text must use newlines, not carriage returns")

    rows = [line.split(delimiter) for line in text.split("\n")]
    # A trailing newline is a terminator, not a record. Popping while the last row
    # is entirely empty rather than merely a list of one empty string, which is what
    # a single trailing newline produces.
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        raise ToolInputInvalid("text must have a header row")

    header = rows[0]
    if not all(cell.strip() for cell in header):
        raise ToolInputInvalid("header row has an empty column name")
    if len(set(header)) != len(header):
        raise ToolInputInvalid("header row has duplicate column names")
    if len(header) > MAX_COLUMNS:
        raise ToolInputInvalid(f"text has more than {MAX_COLUMNS} columns")
    for index, cell in enumerate(header):
        if len(cell) > MAX_COLUMN_NAME_CHARS:
            raise ToolInputInvalid(f"column name at position {index} is too long")
    if len(rows) - 1 > MAX_ROWS:
        raise ToolInputInvalid(f"text has more than {MAX_ROWS} data rows")
    for index, row in enumerate(rows[1:], start=2):
        if len(row) != len(header):
            raise ToolInputInvalid(
                f"line {index} has {len(row)} fields, header has {len(header)}"
            )
    return rows


def _to_number(cell: str) -> float | None:
    """A finite float, or ``None`` for anything else. Never raises."""

    try:
        value = float(cell)
    except ValueError:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _rounded(value: float) -> float:
    """Round floats so a stored number and a recomputed number compare as text.

    No clamping: a value the input bounds already exclude would mean the input
    bounds are wrong, and silently clamping would publish a number this tool did not
    compute.
    """

    return round(float(value), ROUND_DIGITS)


def define() -> ToolDefinition:
    return ToolDefinition(
        tool_id=TOOL_ID,
        title="CSV statistics",
        description=(
            "Row and column counts plus numeric aggregates for one column of a "
            "bounded inline CSV string."
        ),
        version="1.0.0",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        limits=ToolLimits(
            max_input_bytes=MAX_TEXT_CHARS * 4,
            max_output_bytes=2048,
            timeout_seconds=30,
        ),
        determinism=Determinism.DETERMINISTIC,
        provenance_fields=frozenset(ProvenanceField),
        implementation=compute,
        implementation_id=IMPLEMENTATION_ID,
        requires_sandbox=True,
    )
