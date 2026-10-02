"""Plan validation: the gate between a model's proposal and something executable.

A plan document says which tools to call with what. Validation is what turns
that into something ATLAS-X is willing to run, and it is deliberately split from
parsing: :mod:`atlas.planner.plan` answers "is this well formed", and this module
answers "is this allowed and coherent".

Three things are checked here, and the split matters because they fail for
different reasons:

* **Every named tool is registered.** Not merely well formed -- present in the
  frozen registry. A plan that names an unregistered tool is refused outright;
  there is no "closest match" behaviour, because a plan is model output and the
  nearest registered tool is still not the tool that was asked for.
* **Every step's input satisfies that tool's declared schema.** The same
  :func:`~atlas.tools.schema.validate_input` the dispatcher uses before it runs
  anything, so a plan cannot pass here and fail later at dispatch, and cannot
  carry an argument the tool never declared.
* **The dependency graph is resolvable and acyclic.** Unknown keys, self-
  dependencies, and cycles are findings. The report also carries the execution
  order, so the executor does not re-derive a topological sort that could
  disagree with the one that was validated.

Findings are **reported, not raised**. A refusal is worth persisting, and a
report is what gets persisted: the plan row records ``validated = 0``, a
``rejected`` status, and the findings, so "what did the model propose, and what
was wrong with it" is answerable after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from atlas.planner.plan import PlanDocument, PlanStep
from atlas.tools.errors import MalformedToolId, ToolInputInvalid, UnknownTool
from atlas.tools.registry import ToolRegistry
from atlas.tools.schema import validate_input


class FindingCode:
    """Stable codes for plan validation findings."""

    UNKNOWN_TOOL = "unknown_tool"
    INVALID_TOOL_INPUT = "invalid_tool_input"
    UNKNOWN_DEPENDENCY = "unknown_dependency"
    DEPENDENCY_CYCLE = "dependency_cycle"
    TOO_MANY_STEPS = "too_many_steps"


@dataclass(frozen=True)
class Finding:
    """One reason a plan is not executable."""

    code: str
    message: str
    step_key: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "step_key": self.step_key}


@dataclass(frozen=True)
class ValidationReport:
    """The verdict on one plan, plus the order to run it in when valid."""

    findings: tuple[Finding, ...] = ()
    order: tuple[str, ...] = ()
    tool_calls: int = 0

    @property
    def valid(self) -> bool:
        return not self.findings

    def to_json(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "tool_calls": self.tool_calls,
            "order": list(self.order),
            "findings": [finding.to_json() for finding in self.findings],
        }


class PlanValidator:
    """Registry-aware validation for one plan document."""

    def __init__(self, registry: ToolRegistry, *, max_steps: int, max_tool_calls: int) -> None:
        if max_steps <= 0 or max_tool_calls <= 0:
            raise ValueError("plan bounds must be positive")
        self._registry = registry
        self._max_steps = max_steps
        self._max_tool_calls = max_tool_calls

    def validate(self, plan: PlanDocument) -> ValidationReport:
        findings: list[Finding] = []
        if len(plan.steps) > self._max_steps:
            findings.append(
                Finding(
                    FindingCode.TOO_MANY_STEPS,
                    f"plan has {len(plan.steps)} steps, at most {self._max_steps} allowed",
                )
            )
        if len(plan.steps) > self._max_tool_calls:
            findings.append(
                Finding(
                    FindingCode.TOO_MANY_STEPS,
                    f"plan needs {len(plan.steps)} tool calls, "
                    f"at most {self._max_tool_calls} allowed",
                )
            )

        for step in plan.steps:
            findings.extend(self._validate_tool(step))

        known = {step.step_key for step in plan.steps}
        for step in plan.steps:
            for dependency in step.depends_on:
                if dependency not in known:
                    findings.append(
                        Finding(
                            FindingCode.UNKNOWN_DEPENDENCY,
                            f"depends on {dependency!r}, which is not a step in this plan",
                            step.step_key,
                        )
                    )

        # A cycle is only meaningful once every reference resolves, so this runs
        # last: a plan with an unknown dependency would otherwise also report a
        # spurious cycle from the node that referenced it.
        if not findings:
            cycle = _find_cycle(plan)
            if cycle is not None:
                findings.append(
                    Finding(
                        FindingCode.DEPENDENCY_CYCLE,
                        "dependency cycle: " + " -> ".join(cycle),
                    )
                )
        if findings:
            # An invalid plan gets no order. Publishing one anyway would let a
            # caller run the parts that happened to be fine.
            return ValidationReport(findings=tuple(findings), tool_calls=len(plan.steps))
        return ValidationReport(
            order=tuple(_topological_order(plan)),
            tool_calls=len(plan.steps),
        )

    def _validate_tool(self, step: PlanStep) -> list[Finding]:
        try:
            definition = self._registry.find(step.tool_id)
        except UnknownTool:
            return [
                Finding(
                    FindingCode.UNKNOWN_TOOL,
                    f"no registered tool {step.tool_id!r}",
                    step.step_key,
                )
            ]
        except MalformedToolId:
            return [
                Finding(
                    FindingCode.UNKNOWN_TOOL,
                    f"tool_id {step.tool_id!r} is not a usable tool name",
                    step.step_key,
                )
            ]
        try:
            validate_input(definition.input_schema, step.input)
        except ToolInputInvalid as exc:
            return [
                Finding(
                    FindingCode.INVALID_TOOL_INPUT,
                    f"input does not satisfy {definition.tool_id}: {exc}",
                    step.step_key,
                )
            ]
        return []


def _adjacency(plan: PlanDocument) -> dict[str, list[str]]:
    return {step.step_key: list(step.depends_on) for step in plan.steps}


def _find_cycle(plan: PlanDocument) -> list[str] | None:
    """Return a cycle as a path, or None. Iterative, to survive a deep plan."""

    adjacency = _adjacency(plan)
    state: dict[str, int] = {}
    for start in adjacency:
        if state.get(start):
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = [start]
        state[start] = 1
        while stack:
            node, index = stack[-1]
            neighbours = adjacency.get(node, ())
            if index >= len(neighbours):
                state[node] = 2
                stack.pop()
                path.pop()
                continue
            stack[-1] = (node, index + 1)
            neighbour = neighbours[index]
            if state.get(neighbour) == 1:
                return path[path.index(neighbour) :] + [neighbour]
            if not state.get(neighbour):
                state[neighbour] = 1
                stack.append((neighbour, 0))
                path.append(neighbour)
    return None


def _topological_order(plan: PlanDocument) -> list[str]:
    """Dependency order, stable with respect to the model's own step order.

    Ties are broken by ``position`` so that two documents differing only in a
    sibling step's order produce the same execution order for the part that
    matters, and so the order is reproducible rather than dependent on dict
    iteration.
    """

    adjacency = _adjacency(plan)
    remaining = {key: set(value) & set(adjacency) for key, value in adjacency.items()}
    position = {step.step_key: step.position for step in plan.steps}
    order: list[str] = []
    while remaining:
        ready = sorted(
            (key for key, deps in remaining.items() if not deps), key=lambda k: position[k]
        )
        if not ready:
            # Only reachable when a cycle survived, which validate() has already
            # turned into a finding. Raising here would be a latent crash path, so
            # the remaining nodes are appended rather than deadlocking.
            order.extend(sorted(remaining, key=lambda k: position[k]))
            break
        for key in ready:
            order.append(key)
            del remaining[key]
        for deps in remaining.values():
            deps.difference_update(ready)
    return order
