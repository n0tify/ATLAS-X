"""Deterministic statistics over caller-supplied text.

Pure function of its input: no clock, no randomness, no filesystem, no
database. Two invocations with the same ``text`` produce the same numbers,
which is what lets a later verifier compare them.
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
from atlas.tools.schema import SchemaField, ToolSchema

TOOL_ID = "text_statistics"
IMPLEMENTATION_ID = "atlas.tools.builtin.text_statistics:compute"

MAX_TEXT_CHARS = 200_000
MAX_WORDS = 50_000

INPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(
            name="text",
            type="string",
            required=True,
            description="Text to measure. Bounded by max_length.",
            max_length=MAX_TEXT_CHARS,
        ),
        SchemaField(
            name="count_words",
            type="boolean",
            required=False,
            description="Split on whitespace to produce word statistics.",
        ),
    )
)

OUTPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(name="char_count", type="integer", minimum=0, maximum=MAX_TEXT_CHARS),
        SchemaField(name="line_count", type="integer", minimum=0, maximum=MAX_TEXT_CHARS),
        SchemaField(
            name="longest_line_length", type="integer", minimum=0, maximum=MAX_TEXT_CHARS
        ),
        SchemaField(name="word_count", type="integer", minimum=0, maximum=MAX_WORDS),
        SchemaField(name="unique_word_count", type="integer", minimum=0, maximum=MAX_WORDS),
        SchemaField(name="min_word_length", type="integer", minimum=0, maximum=MAX_TEXT_CHARS),
        SchemaField(name="max_word_length", type="integer", minimum=0, maximum=MAX_TEXT_CHARS),
    )
)


def compute(context: ToolContext, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    """Measure ``text``. ``context`` is unused: this tool touches no state."""

    text = arguments["text"]
    lines = text.splitlines()
    words = text.split() if arguments.get("count_words", True) else []
    lengths = [len(word) for word in words]
    return {
        "char_count": len(text),
        "line_count": len(lines),
        "longest_line_length": max((len(line) for line in lines), default=0),
        "word_count": len(words),
        "unique_word_count": len(set(words)),
        "min_word_length": min(lengths, default=0),
        "max_word_length": max(lengths, default=0),
    }


def define() -> ToolDefinition:
    return ToolDefinition(
        tool_id=TOOL_ID,
        title="Text statistics",
        description=(
            "Deterministic character, line, and word counts for a bounded string."
        ),
        version="1.0.0",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        limits=ToolLimits(
            max_input_bytes=MAX_TEXT_CHARS * 4,
            max_output_bytes=512,
            timeout_seconds=5,
        ),
        determinism=Determinism.DETERMINISTIC,
        provenance_fields=frozenset(ProvenanceField),
        implementation=compute,
        implementation_id=IMPLEMENTATION_ID,
        # Declared because it is true, not because it is optional: from Phase 10B
        # the dispatcher sends every tool through the sandbox regardless, and a
        # declaration that says otherwise would be a claim the registry cannot
        # distinguish from a trusted bypass.
        requires_sandbox=True,
    )
