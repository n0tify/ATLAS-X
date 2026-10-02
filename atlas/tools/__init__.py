"""Controlled tool registry, grant-backed authorization, and dispatch.

This package holds the Phase 09 capability layer: what a tool *is*
(:mod:`atlas.tools.definition`), the authoritative list of approved tools
(:mod:`atlas.tools.registry`), what a caller *is allowed* to invoke
(:mod:`atlas.storage.tool_grants`, read through the Phase 08 policy), and the one
path that runs a tool (:mod:`atlas.tools.dispatch`).

Three separations are the point of the layout, and each has its own module so it
cannot be quietly collapsed:

* **Registry describes, authorization grants, dispatch executes.** Looking a
  tool up says nothing about whether this caller may run it.
* **A failure is classified, not swallowed.** :mod:`atlas.tools.errors` keeps
  unknown-tool, invalid-input, resource-limit, execution-failure, and
  invalid-output distinct, and keeps all of them distinct from an authorization
  denial. As of Phase 10B it also owns the sandbox failures, so that a denied
  escape and a malformed tool ID are distinguishable in the audit record
  without a second taxonomy.
* **A tool body is bounded by construction.** Schemas refuse an unbounded field
  and :mod:`atlas.tools.context` hands implementations an owner-scoped view
  instead of a database connection.

Phase 10B changed the last of these. A tool body no longer runs in this process:
:mod:`atlas.tools.dispatch` hands the work to a guest through
:mod:`atlas.sandbox.supervisor`, so the view it passes is a snapshot rather than
a connection and the declared timeout is enforced during the call instead of
after it.

Re-exports here are **eager**, and that is load-bearing rather than incidental.
Phase 10B introduced an import cycle: the sandbox error types subclass
:class:`ToolError` to stay in this taxonomy, so importing a sandbox module runs
this package's initializer, which re-exports :mod:`atlas.tools.dispatch`. The
first answer to that was to re-export lazily through ``importlib``, and it was
the wrong one: ``test_no_tool_layer_module_can_reach_a_shell_or_an_import``
forbids dynamic import anywhere in the tool layer precisely because a dynamic
import is a code-execution vector, so a lazy re-export quietly switched off a
Phase 09 control to work around an import order.

The cycle is now broken at its only remaining edge. :mod:`atlas.tools.dispatch`
resolves :mod:`atlas.sandbox.supervisor` when it builds a supervisor and when it
classifies an outcome, rather than when it is imported, which leaves the rest of
the dependency graph acyclic. Eager imports here are therefore possible, the tool
layer is free of ``importlib``, and an import cycle in this package is a real
error again instead of something the module system papers over at runtime.
"""

from __future__ import annotations

from atlas.tools.context import MAX_VIEW_ROWS, OwnedTaskView
from atlas.tools.definition import (
    Determinism,
    FilesystemAccess,
    NetworkAccess,
    ProvenanceField,
    ToolContext,
    ToolDefinition,
    ToolLimits,
)
from atlas.tools.dispatch import DispatchLimits, ToolDispatcher, ToolInvocation
from atlas.tools.errors import (
    MalformedToolId,
    SandboxUnavailable,
    SandboxViolation,
    ToolDefinitionInvalid,
    ToolError,
    ToolErrorCode,
    ToolExecutionFailed,
    ToolInputInvalid,
    ToolInputTooLarge,
    ToolLimitExceeded,
    ToolOutputInvalid,
    ToolOutputTooLarge,
    ToolUnsupported,
    UnknownTool,
)
from atlas.tools.registry import ToolRegistry, default_registry
from atlas.tools.schema import (
    SchemaField,
    ToolSchema,
    validate_input,
    validate_output,
)

__all__ = [
    "MAX_VIEW_ROWS",
    "Determinism",
    "DispatchLimits",
    "FilesystemAccess",
    "MalformedToolId",
    "NetworkAccess",
    "OwnedTaskView",
    "ProvenanceField",
    "SandboxUnavailable",
    "SandboxViolation",
    "SchemaField",
    "ToolContext",
    "ToolDefinition",
    "ToolDefinitionInvalid",
    "ToolDispatcher",
    "ToolError",
    "ToolErrorCode",
    "ToolExecutionFailed",
    "ToolInputInvalid",
    "ToolInputTooLarge",
    "ToolInvocation",
    "ToolLimits",
    "ToolLimitExceeded",
    "ToolOutputInvalid",
    "ToolOutputTooLarge",
    "ToolRegistry",
    "ToolSchema",
    "ToolUnsupported",
    "UnknownTool",
    "default_registry",
    "validate_input",
    "validate_output",
]
