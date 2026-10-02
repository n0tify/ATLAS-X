"""The plan document: a bounded, canonical, untrusted-to-trusted boundary type.

A plan is a list of steps, each naming one registered tool and carrying that
tool's declared input, plus the dependencies between steps. This module owns the
document's shape, the bounds on it, and the canonical form used for the stored
digest. It does not know whether a plan is *any good*: that is
:mod:`atlas.planner.validator`, which needs the registry.

Everything arriving from the model lands here first. The reply is parsed under
exactly the same bounds as any other untrusted payload, so a model cannot
introduce a field, a step count, a key length, or an input size that nothing
declared. Parsing raises :class:`~atlas.planner.errors.PlanOutputInvalid` and
never returns a half-built document.

The same canonical form has to be readable by the same parser, because
``plans.plan_json`` stores exactly these bytes: anything canonical emits that
:meth:`from_payload` would reject would make a stored plan unreadable. That
round-trip is what keeps a stored plan, its digest, and a later re-parse in
agreement.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from atlas.planner.errors import PlanOutputInvalid

MAX_SUMMARY_CHARS = 1_000
MAX_STEP_KEY_CHARS = 64
MAX_ACTION_CHARS = 200
MAX_ARTIFACT_KIND_CHARS = 64
MAX_STEPS_PER_PLAN = 50
MAX_DEPENDENCIES_PER_STEP = 32
#: A step's serialized input is bounded here as well as by the tool's own schema.
#: The tool schema check is the real contract; this stops a model from making the
#: planner hold a megabyte of JSON in order to be told the field name is wrong.
MAX_STEP_INPUT_CHARS = 16_000
MAX_INPUT_DEPTH = 8

#: Same shape as the tool id rule in :mod:`atlas.tools.definition`, and deliberately
#: so: a ``step_key`` is referenced by ``depends_on``, so it has to be a name that
#: cannot be confused with anything else in the document.
STEP_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

_PLAN_KEYS = frozenset({"summary", "steps"})
_STEP_KEYS = frozenset(
    {"step_key", "tool_id", "input", "depends_on", "produces_artifact_kind", "action"}
)


@dataclass(frozen=True)
class PlanStep:
    """One step: a tool, its already-bounded input, and its place in the graph.

    ``position`` is assigned by the order the model listed the steps, never by the
    model itself, so a step cannot choose its own row id or reorder itself ahead
    of a dependency.
    """

    position: int
    step_key: str
    tool_id: str
    input: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()
    produces_artifact_kind: str | None = None
    #: Short human-readable purpose for the step. Descriptive only: nothing
    #: dispatches on it, and ``plan_steps.action`` records it so the NOT NULL
    #: column holds what the model actually said rather than a copy of the tool id.
    action: str | None = None

    def canonical(self) -> dict[str, Any]:
        # ``position`` is deliberately absent. It is derived from the step's
        # index in ``steps``, so the array order already encodes it: swapping two
        # independent steps reorders the array and therefore changes this
        # document and its digest. Emitting the number as well would only make the
        # canonical form a payload the parser rejects -- ``position`` is not a
        # field the model may set, and a canonical document has to be readable by
        # the same parser that accepted the model's.
        return {
            "step_key": self.step_key,
            "tool_id": self.tool_id,
            "input": _canonicalize(self.input),
            "depends_on": list(self.depends_on),
            "produces_artifact_kind": self.produces_artifact_kind,
            "action": self.action,
        }


@dataclass(frozen=True)
class PlanDocument:
    """A complete plan. Constructed only by :meth:`from_payload`."""

    summary: str
    steps: tuple[PlanStep, ...]

    @classmethod
    def from_payload(cls, payload: object, *, max_steps: int) -> PlanDocument:
        """Build a document from an untrusted payload, or refuse.

        Every refusal is a :class:`PlanOutputInvalid`, and no partially built
        document escapes: the whole document is assembled first and returned
        only once every step has passed the structural bounds.
        """

        if not isinstance(payload, Mapping):
            raise PlanOutputInvalid("plan must be a JSON object")
        _reject_unknown(payload, _PLAN_KEYS, "plan")

        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise PlanOutputInvalid("plan 'summary' must be a non-empty string")
        if len(summary) > MAX_SUMMARY_CHARS:
            raise PlanOutputInvalid(
                f"plan 'summary' is longer than {MAX_SUMMARY_CHARS} characters"
            )

        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes)):
            raise PlanOutputInvalid("plan 'steps' must be an array")
        if not raw_steps:
            raise PlanOutputInvalid("plan must contain at least one step")
        ceiling = min(max_steps, MAX_STEPS_PER_PLAN)
        if len(raw_steps) > ceiling:
            raise PlanOutputInvalid(
                f"plan has {len(raw_steps)} steps, at most {ceiling} allowed"
            )

        steps = tuple(
            cls._step_from_payload(raw, position)
            for position, raw in enumerate(raw_steps)
        )
        _reject_duplicate_step_keys(steps)
        return cls(summary=summary, steps=steps)

    @staticmethod
    def _step_from_payload(payload: object, position: int) -> PlanStep:
        where = f"step {position}"
        if not isinstance(payload, Mapping):
            raise PlanOutputInvalid(f"{where} must be a JSON object")
        _reject_unknown(payload, _STEP_KEYS, where)

        step_key = payload.get("step_key")
        if not isinstance(step_key, str) or not STEP_KEY_PATTERN.fullmatch(step_key):
            raise PlanOutputInvalid(
                f"{where} has step_key {step_key!r}, which is not lowercase snake_case"
            )
        if len(step_key) > MAX_STEP_KEY_CHARS:
            raise PlanOutputInvalid(f"{where} step_key is longer than {MAX_STEP_KEY_CHARS}")

        tool_id = payload.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id:
            raise PlanOutputInvalid(f"{where} must name a tool in 'tool_id'")

        raw_input = payload.get("input", {})
        if not isinstance(raw_input, Mapping):
            raise PlanOutputInvalid(f"{where} 'input' must be a JSON object")
        _check_input_bounds(raw_input, where)
        step_input = _canonicalize(raw_input)

        depends_on = _read_dependencies(payload.get("depends_on", []), where)
        if step_key in depends_on:
            raise PlanOutputInvalid(f"{where} depends on itself")

        kind = payload.get("produces_artifact_kind")
        if kind is not None:
            if not isinstance(kind, str) or not kind.strip():
                raise PlanOutputInvalid(
                    f"{where} 'produces_artifact_kind' must be a non-empty string or absent"
                )
            if len(kind) > MAX_ARTIFACT_KIND_CHARS:
                raise PlanOutputInvalid(
                    f"{where} 'produces_artifact_kind' is longer than {MAX_ARTIFACT_KIND_CHARS}"
                )

        return PlanStep(
            position=position,
            step_key=step_key,
            tool_id=tool_id,
            input=step_input,
            depends_on=depends_on,
            produces_artifact_kind=kind,
            action=_read_optional_text(payload.get("action"), where, "action", MAX_ACTION_CHARS),
        )

    def step_by_key(self, step_key: str) -> PlanStep | None:
        for step in self.steps:
            if step.step_key == step_key:
                return step
        return None

    def canonical_json(self) -> str:
        """The exact bytes that :meth:`digest` is taken over."""

        return json.dumps(
            {
                "summary": self.summary,
                "steps": [step.canonical() for step in self.steps],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def digest(self) -> str:
        """Content address of the plan, independent of key order and spacing.

        Two runs whose plans differ only in JSON formatting hash the same, and two
        that differ in any step's tool, input, or dependency do not. The stored
        digest is what ``plans.digest`` records and what H1 compares across
        ablations, so it must be reproducible across processes and runs.
        """

        return "sha256:" + hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _reject_unknown(payload: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        # Refused rather than dropped. An extra field is either a model inventing
        # structure or a plan format this build does not implement, and both mean
        # the reply does not describe a plan we can execute.
        raise PlanOutputInvalid(f"{where} carries unknown fields {unknown!r}")


def _read_dependencies(payload: object, where: str) -> tuple[str, ...]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise PlanOutputInvalid(f"{where} 'depends_on' must be an array of step keys")
    if len(payload) > MAX_DEPENDENCIES_PER_STEP:
        raise PlanOutputInvalid(
            f"{where} declares more than {MAX_DEPENDENCIES_PER_STEP} dependencies"
        )
    seen: list[str] = []
    for item in payload:
        if not isinstance(item, str) or not STEP_KEY_PATTERN.fullmatch(item):
            raise PlanOutputInvalid(f"{where} 'depends_on' holds a non-step-key: {item!r}")
        if item not in seen:
            seen.append(item)
    return tuple(seen)


def _read_optional_text(
    value: object, where: str, name: str, ceiling: int
) -> str | None:
    """Read a bounded, non-empty descriptive string, or None when absent."""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PlanOutputInvalid(f"{where} {name!r} must be a non-empty string when present")
    if len(value) > ceiling:
        raise PlanOutputInvalid(f"{where} {name!r} is longer than {ceiling} characters")
    return value


def _check_input_bounds(payload: Mapping[str, Any], where: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=True, default=_refuse_non_json)
    if len(serialized) > MAX_STEP_INPUT_CHARS:
        raise PlanOutputInvalid(
            f"{where} 'input' is larger than {MAX_STEP_INPUT_CHARS} characters"
        )
    if _depth(payload) > MAX_INPUT_DEPTH:
        raise PlanOutputInvalid(f"{where} 'input' nests deeper than {MAX_INPUT_DEPTH}")


def _depth(value: object) -> int:
    if isinstance(value, Mapping):
        return 1 + max((_depth(item) for item in value.values()), default=0)
    if isinstance(value, (list, tuple)):
        return 1 + max((_depth(item) for item in value), default=0)
    return 0


def _refuse_non_json(value: object) -> Any:
    raise PlanOutputInvalid(f"step input holds a value that is not JSON: {type(value).__name__}")


def _canonicalize(value: object) -> Any:
    """Normalize a JSON value so equal plans serialize identically.

    Only conversions the JSON types imply: mappings keep their keys, sequences
    become lists, and tuples become lists. Nothing is reordered here -- the
    ``sort_keys`` in :meth:`PlanDocument.canonical_json` handles mapping keys, and
    a list's order is meaning.
    """

    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def _reject_duplicate_step_keys(steps: Sequence[PlanStep]) -> None:
    seen: set[str] = set()
    for step in steps:
        if step.step_key in seen:
            raise PlanOutputInvalid(f"duplicate step_key {step.step_key!r}")
        seen.add(step.step_key)
