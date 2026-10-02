"""Structured plan generation and validation against the frozen tool registry.

The Phase 11 planner. It asks a local model for a plan, refuses anything the
model returns that ATLAS-X will not run, and persists the result -- including the
refusals, because "the model proposed this and we rejected it" is an answer the
provenance record has to be able to give.

The layout keeps four things apart that are easy to collapse:

* **Asking** (:mod:`atlas.planner.model`, :mod:`atlas.planner.prompt`) is a
  bounded conversation with a local daemon over loopback. It has no authority:
  it returns a string.
* **Believing** (:mod:`atlas.planner.plan`) is parsing that string under the same
  bounds any other untrusted payload gets. A document it returns is well formed,
  not correct.
* **Approving** (:mod:`atlas.planner.validator`) is the registry check. It is the
  only thing that can say a plan may run, and "may be proposed" is still not
  permission to execute.
* **Acting** is Phase 12, and it goes through authorization and the dispatcher.
  Nothing in this package can dispatch a tool.

Re-exports are eager, for the reason
:mod:`atlas.tools` documents: a lazy ``__getattr__`` re-export needs
``importlib``, and dynamic import is exactly the code-execution vector the tool
layer's controls are built to keep out. The dependency graph here is acyclic, so
there is no cycle to work around.
"""

from __future__ import annotations

from atlas.planner.errors import (
    ModelTimeout,
    ModelUnavailable,
    PlanError,
    PlanErrorCode,
    PlanOutputInvalid,
    PlanRejected,
)
from atlas.planner.model import LocalModelClient, ModelMessage, ModelResponse
from atlas.planner.plan import PlanDocument, PlanStep
from atlas.planner.prompt import build_messages, parse_plan_text, tool_catalogue
from atlas.planner.service import PlannerService, PlanningOutcome
from atlas.planner.validator import Finding, FindingCode, PlanValidator, ValidationReport

__all__ = [
    "Finding",
    "FindingCode",
    "LocalModelClient",
    "ModelMessage",
    "ModelResponse",
    "ModelTimeout",
    "ModelUnavailable",
    "PlanDocument",
    "PlanError",
    "PlanErrorCode",
    "PlanOutputInvalid",
    "PlanRejected",
    "PlanStep",
    "PlanValidator",
    "PlannerService",
    "PlanningOutcome",
    "ValidationReport",
    "build_messages",
    "parse_plan_text",
    "tool_catalogue",
]
