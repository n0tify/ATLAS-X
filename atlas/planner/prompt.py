"""The planning prompt: the only place the model is told what it may ask for.

The prompt is built from the frozen registry, never from a hand-written list of
tool names. That is the point: a tool the planner advertises is a tool that is
registered, so the model cannot be told about a capability ATLAS-X does not have,
and a tool added to the registry cannot be forgotten here.

What the prompt does not do is constrain the model's freedom of *strategy*. It
states the output contract and the available tools; which of those tools to call,
in what order, and with what arguments is the model's decision, and the validator
-- not the prompt -- is what decides whether the answer is executable. A prompt
that quietly encoded a preferred plan would make the H1 ablation measure the
prompt rather than the planner.

The tool catalogue is rendered from :meth:`ToolDefinition.describe`, which is the
same serialization provenance records, so the model is shown the real declared
schemas and its bounds.

The template uses :class:`string.Template` rather than ``str.format`` for exactly
one reason: the contract it embeds is itself a JSON object, and ``format`` would
read every brace in that example as a substitution field.
"""

from __future__ import annotations

import json
from string import Template
from typing import Any, Mapping, Sequence

from atlas.planner.model import ModelMessage
from atlas.tools.registry import ToolRegistry

PLAN_CONTRACT_VERSION = "atlas-plan-1"

_SYSTEM_TEMPLATE = """\
You are the planner for ATLAS-X, a local research system. You turn a goal into a
plan of tool calls. You do not call tools yourself and you cannot run code.

Reply with one JSON object and nothing else. No prose, no markdown fence, no
commentary. The object has exactly this shape:

{
  "summary": "<one sentence, under 500 characters, describing the approach>",
  "steps": [
    {
      "step_key": "<lowercase_snake_case identifier, unique within the plan>",
      "tool_id": "<one of the tool ids listed below>",
      "input": { "<arguments for that tool, matching its input schema>" },
      "depends_on": ["<step_key of a step listed earlier in this array>"],
      "produces_artifact_kind": "<optional short kind, or omit the field>",
      "action": "<optional one-line description of what this step is for>"
    }
  ]
}

Rules you must satisfy or the plan will be rejected:

* Use between 1 and $max_steps steps, and at most $max_tool_calls tool calls.
* Only use tool ids from the list below. An unregistered tool id is rejected.
* "input" must satisfy that tool's input_schema, including its bounds. Every field
  it does not declare is rejected; do not add fields.
* "depends_on" may only name step_keys that appear in this same plan. Omit the
  field for a step that depends on nothing. Never depend on your own step_key.
* The dependency graph must be acyclic.
* Prefer fewer steps. Do not repeat a step that the goal already implies.
* You are proposing; ATLAS-X validates and verifies everything you write. A plan
  you are not confident about should be shorter, not more elaborate.

Available tools:

$catalogue
"""


def tool_catalogue(registry: ToolRegistry) -> tuple[dict[str, Any], ...]:
    """The registered tools, described by the same serializer provenance uses."""

    entries: list[dict[str, Any]] = []
    for definition in registry.list_definitions():
        described = definition.describe()
        entries.append(
            {
                "tool_id": described["tool_id"],
                "title": described["title"],
                "description": described["description"],
                "determinism": described["determinism"],
                "requires_sandbox": described["requires_sandbox"],
                "input_schema": described["input_schema"],
                "output_schema": described["output_schema"],
            }
        )
    return tuple(entries)


def build_messages(
    *,
    goal: str,
    registry: ToolRegistry,
    max_steps: int,
    max_tool_calls: int,
    tool_ids: Sequence[str] | None = None,
) -> tuple[ModelMessage, ...]:
    """Build the transcript: a contract, the catalogue, then the goal.

    ``tool_ids`` narrows the catalogue to the tools the caller's grants permit.
    It is a *prompt-side* narrowing only -- the registry stays the authority, and
    a plan naming a tool outside the narrowing is refused by validation rather
    than quietly tolerated. Passing ``None`` offers the whole registry, which is
    correct when grants already decide what may be dispatched.
    """

    catalogue = tool_catalogue(registry)
    if tool_ids is not None:
        allowed = set(tool_ids)
        catalogue = tuple(entry for entry in catalogue if entry["tool_id"] in allowed)
    if not catalogue:
        # An empty catalogue would invite the model to invent a tool id. Say so
        # instead, and let it decline, which is a truthful answer.
        catalogue_text = "(no tools are available for this task)"
    else:
        # Compact separators, not ``indent=2``. The catalogue is the bulk of the
        # prompt, and whitespace is the one thing here that costs context without
        # telling the model anything it cannot read.
        catalogue_text = json.dumps(
            catalogue, separators=(",", ":"), sort_keys=True, ensure_ascii=True
        )

    system = Template(_SYSTEM_TEMPLATE).substitute(
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
        catalogue=catalogue_text,
    )
    user = (
        "Goal:\n"
        f"{goal.strip()}\n\n"
        "Reply with the JSON plan object only."
    )
    return (ModelMessage(role="system", content=system), ModelMessage(role="user", content=user))


def parse_plan_text(text: str) -> Mapping[str, Any]:
    """Parse a model reply into a payload, tolerating only a bare JSON object.

    A fence is stripped because every local model wraps JSON in one often enough
    that refusing it would mean rejecting correct plans for a cosmetic reason.
    Nothing else is repaired: a truncated reply, prose around the object, or two
    objects are all refused. Guessing where a reply "must have" ended would be
    inventing a plan the model did not write.
    """

    stripped = text.strip()
    if not stripped:
        raise ValueError("model reply is empty")
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines[0].startswith("```json"):
            lines = lines[1:]
        elif lines[0].startswith("```"):
            lines = lines[1:]
        else:
            raise ValueError("model reply starts with an unterminated code fence")
        while lines and lines[-1].strip() != "```":
            lines.pop()
        if lines and lines[-1].strip() == "```":
            lines.pop()
        stripped = "\n".join(lines).strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model reply is not a JSON object: {exc.msg}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("model reply is a JSON value that is not an object")
    return payload
