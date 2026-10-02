"""The approved tool set.

Every tool ATLAS-X can invoke is named here. There is no discovery mechanism,
no plugin loader, and no way for a request to add to this list: a new
capability is a source change to this package, reviewed like any other.

Each tool is deliberately boring — bounded input, deterministic or explicitly
state-dependent output, no host filesystem, no network, no subprocess, no
arbitrary Python. The registry's value is that this list is short enough to
audit by reading.
"""

from __future__ import annotations

from atlas.tools.builtin import (
    artifact_metadata,
    json_shape_inspect,
    numeric_summary,
    task_graph_summary,
    text_statistics,
)
from atlas.tools.definition import ToolDefinition

_MODULES = (
    text_statistics,
    numeric_summary,
    json_shape_inspect,
    artifact_metadata,
    task_graph_summary,
)


def build_definitions() -> tuple[ToolDefinition, ...]:
    """Every approved definition, in a stable order."""

    definitions = tuple(module.define() for module in _MODULES)
    return tuple(sorted(definitions, key=lambda definition: definition.tool_id))
