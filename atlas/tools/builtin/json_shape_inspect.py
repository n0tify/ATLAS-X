"""Structural inspection of a JSON document supplied as text.

Reports the *shape* of a document — types, key paths, depth, node count — and
never the values it walks past. That is the point: a caller can learn that a
dataset has an unexpected nested field without this tool copying the field's
contents into a log, a provenance record, or a UI.

The document arrives as text rather than as a parsed object so that the
dispatcher's input validation applies to it before anything is parsed, and so
that the bound is a byte bound on text the platform already holds.

Deterministic: the same document and the same bounds always produce the same
shape, including the same truncation point.
"""

from __future__ import annotations

import json
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

TOOL_ID = "json_shape_inspect"
IMPLEMENTATION_ID = "atlas.tools.builtin.json_shape_inspect:compute"

MAX_DOCUMENT_CHARS = 1_000_000
MIN_DEPTH = 1
MAX_DEPTH = 16
MAX_KEYS = 500
MAX_KEY_PATH_CHARS = 200
MAX_TYPE_NAMES = 12

INPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(
            name="document",
            type="string",
            required=True,
            description="JSON text to inspect. Values are counted, never returned.",
            max_length=MAX_DOCUMENT_CHARS,
        ),
        SchemaField(
            name="max_depth",
            type="integer",
            required=False,
            description="How deep to walk before reporting truncation.",
            minimum=MIN_DEPTH,
            maximum=MAX_DEPTH,
        ),
        SchemaField(
            name="max_keys",
            type="integer",
            required=False,
            description="How many distinct key paths to report.",
            minimum=1,
            maximum=MAX_KEYS,
        ),
    )
)

OUTPUT_SCHEMA = ToolSchema(
    fields=(
        SchemaField(name="root_type", type="string", max_length=32),
        SchemaField(name="node_count", type="integer", minimum=0, maximum=10_000_000),
        SchemaField(name="depth_reached", type="integer", minimum=0, maximum=MAX_DEPTH),
        SchemaField(
            name="distinct_types",
            type="array",
            description="JSON type names seen, sorted.",
            item_type="string",
            max_items=MAX_TYPE_NAMES,
        ),
        SchemaField(
            name="key_paths",
            type="array",
            description="Dotted key paths seen, in document order, bounded.",
            item_type="string",
            max_items=MAX_KEYS,
        ),
        SchemaField(
            name="truncated",
            type="boolean",
            description="True when a bound stopped the walk early.",
        ),
    )
)


def compute(context: ToolContext, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    """Describe the shape of ``document``. ``context`` is unused: no state read."""

    text = arguments["document"]
    depth_limit = int(arguments.get("max_depth", MAX_DEPTH))
    key_limit = int(arguments.get("max_keys", MAX_KEYS))

    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError) as exc:
        # Malformed JSON is an input problem, not a tool malfunction. It is
        # reported as such so the caller learns nothing about the tool's
        # internals and can correct the document.
        raise ToolInputInvalid("document is not valid JSON") from exc

    walker = _ShapeWalk(depth_limit=depth_limit, key_limit=key_limit)
    walker.walk(parsed, path="", depth=1)
    return {
        "root_type": _type_name(parsed),
        "node_count": walker.node_count,
        "depth_reached": walker.depth_reached,
        "distinct_types": sorted(walker.types_seen)[:MAX_TYPE_NAMES],
        "key_paths": walker.key_paths,
        "truncated": walker.truncated,
    }


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


class _ShapeWalk:
    """Bounded iterative walk. No recursion, so a deep document cannot exhaust
    the interpreter stack."""

    __slots__ = (
        "_depth_limit",
        "_key_limit",
        "depth_reached",
        "key_paths",
        "node_count",
        "truncated",
        "types_seen",
    )

    def __init__(self, *, depth_limit: int, key_limit: int) -> None:
        self._depth_limit = depth_limit
        self._key_limit = key_limit
        self.node_count = 0
        self.depth_reached = 0
        self.key_paths: list[str] = []
        self.types_seen: set[str] = set()
        self.truncated = False

    def walk(self, root: object, *, path: str, depth: int) -> None:
        stack: list[tuple[object, str, int]] = [(root, path, depth)]
        while stack:
            node, node_path, node_depth = stack.pop()
            self.node_count += 1
            self.depth_reached = max(self.depth_reached, min(node_depth, self._depth_limit))
            self.types_seen.add(_type_name(node))

            if node_depth >= self._depth_limit:
                if isinstance(node, (dict, list)) and node:
                    self.truncated = True
                continue
            if isinstance(node, dict):
                for key, child in node.items():
                    child_path = f"{node_path}.{key}" if node_path else str(key)
                    if len(child_path) > MAX_KEY_PATH_CHARS:
                        child_path = child_path[:MAX_KEY_PATH_CHARS]
                    if len(self.key_paths) < self._key_limit:
                        self.key_paths.append(child_path)
                    elif child_path not in self.key_paths:
                        self.truncated = True
                    stack.append((child, child_path, node_depth + 1))
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    child_path = f"{node_path}[{index}]" if node_path else f"[{index}]"
                    stack.append((child, child_path, node_depth + 1))


def define() -> ToolDefinition:
    return ToolDefinition(
        tool_id=TOOL_ID,
        title="JSON shape inspection",
        description=(
            "Structural summary of a JSON document: types, key paths, depth, node "
            "count. Values are counted, never returned."
        ),
        version="1.0.0",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        limits=ToolLimits(
            max_input_bytes=MAX_DOCUMENT_CHARS * 4,
            max_output_bytes=64 * 1024,
            timeout_seconds=15,
        ),
        determinism=Determinism.DETERMINISTIC,
        provenance_fields=frozenset(ProvenanceField),
        implementation=compute,
        implementation_id=IMPLEMENTATION_ID,
    )
