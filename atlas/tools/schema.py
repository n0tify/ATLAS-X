"""Declarative input/output schemas for registered tools.

A tool's contract is data, not code: a frozen list of :class:`SchemaField`
values that is both the validator and the serializable description. One source
of truth means the schema reported to a caller, the schema enforced before
dispatch, and the schema recorded in provenance cannot drift apart.

The type set is deliberately small — ``string``, ``integer``, ``number``,
``boolean``, and ``array`` of a scalar. Free-form nested objects are not
supported. A free-form object would smuggle an unbounded, unvalidated value
past the dispatcher, which is the exact failure this layer exists to prevent.

Two invariants are enforced structurally rather than by convention:

* Every numeric field declares ``minimum`` and ``maximum``. An unbounded number
  is not registrable, so no tool can accept a value of arbitrary magnitude.
* Every string field declares ``max_length``, and every array declares
  ``max_items``. Nothing unbounded reaches an implementation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from atlas.tools.errors import ToolInputInvalid, ToolOutputInvalid

MAX_FIELD_NAME_LENGTH = 64
MAX_CHOICES = 32
MAX_FIELDS = 24

#: Applied to string items inside an array whose parent field declared no
#: ``max_length``. Array length is already bounded by ``max_items``, so this
#: only prevents a single pathological element.
MAX_ITEMS_STRING = 4096

SCALAR_TYPES = frozenset({"string", "integer", "number", "boolean"})

_JSON_TYPES: MappingProxyType[str, str] = MappingProxyType(
    {
        "string": "string",
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "array": "array",
    }
)


@dataclass(frozen=True)
class SchemaField:
    """One declared field of a tool input or output.

    ``minimum``/``maximum`` apply to numeric fields, ``max_length`` to strings,
    ``max_items``/``item_type`` to arrays. Fields that do not apply to the
    declared type must be left at their defaults, so a stray bound can never
    sit in a schema pretending to constrain something it does not.
    """

    name: str
    type: str
    required: bool = True
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None
    max_length: int | None = None
    min_length: int | None = None
    choices: tuple[Any, ...] | None = None
    item_type: str | None = None
    max_items: int | None = None
    item_minimum: float | None = None
    item_maximum: float | None = None
    item_max_length: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("schema field name must be a non-empty string")
        if len(self.name) > MAX_FIELD_NAME_LENGTH:
            raise ValueError(f"schema field name too long: {self.name!r}")
        if not self.name.replace("_", "").isalnum():
            raise ValueError(f"schema field name must be alphanumeric: {self.name!r}")
        if self.type not in _JSON_TYPES:
            raise ValueError(f"unsupported schema field type: {self.type!r}")
        if self.required is not True and self.required is not False:
            raise TypeError("required must be a bool")
        if self.type in {"integer", "number"}:
            self._require_numeric_bounds()
        elif self.type == "string":
            self._require_string_bounds()
        elif self.type == "array":
            self._require_array_bounds()
        if self.item_type is not None and self.type != "array":
            raise ValueError("item_type is only meaningful for array fields")
        if self.choices is not None:
            self._validate_choices()

    def _require_numeric_bounds(self) -> None:
        if self.minimum is None or self.maximum is None:
            raise ValueError(
                f"numeric field {self.name!r} must declare minimum and maximum"
            )
        if self.minimum > self.maximum:
            raise ValueError(f"field {self.name!r} has minimum above maximum")
        for bound in (self.minimum, self.maximum):
            if not math.isfinite(bound):
                raise ValueError(f"field {self.name!r} has a non-finite bound")

    def _require_string_bounds(self) -> None:
        if self.max_length is None or self.max_length <= 0:
            raise ValueError(f"string field {self.name!r} must declare max_length")
        if self.min_length is not None and (
            self.min_length < 0 or self.min_length > self.max_length
        ):
            raise ValueError(f"field {self.name!r} has min_length above max_length")
        _reject_stray_bounds(self, {"minimum", "maximum", "max_items", "item_type"})

    def _require_array_bounds(self) -> None:
        if self.item_type is None or self.item_type not in SCALAR_TYPES:
            raise ValueError(
                f"array field {self.name!r} must declare a scalar item_type"
            )
        if self.max_items is None or self.max_items <= 0:
            raise ValueError(f"array field {self.name!r} must declare max_items")
        _reject_stray_bounds(self, {"minimum", "maximum", "max_length", "min_length"})
        if self.item_type in {"integer", "number"}:
            if self.item_minimum is None or self.item_maximum is None:
                raise ValueError(
                    f"numeric array {self.name!r} must declare item bounds"
                )
            if self.item_minimum > self.item_maximum:
                raise ValueError(f"array {self.name!r} has item_minimum above item_maximum")
            if self.item_max_length is not None:
                raise ValueError("item_max_length is only meaningful for string items")
        elif self.item_max_length is not None and self.item_max_length <= 0:
            raise ValueError(f"array {self.name!r} has a non-positive item_max_length")

    def _validate_choices(self) -> None:
        assert self.choices is not None
        if not self.choices or len(self.choices) > MAX_CHOICES:
            raise ValueError(f"field {self.name!r} must declare 1..{MAX_CHOICES} choices")
        # For an array the choices constrain the items, not the array itself.
        choice_type = self.item_type if self.type == "array" else self.type
        for choice in self.choices:
            if not _matches_type(choice, str(choice_type)):
                raise ValueError(
                    f"choice {choice!r} does not match declared type {choice_type!r}"
                )

    def to_json_schema(self) -> dict[str, Any]:
        """Serializable description used for introspection and provenance."""

        node: dict[str, Any] = {"type": _JSON_TYPES[self.type]}
        if self.description:
            node["description"] = self.description
        if self.type in {"integer", "number"}:
            node["minimum"] = self.minimum
            node["maximum"] = self.maximum
        elif self.type == "string":
            node["maxLength"] = self.max_length
            if self.min_length is not None:
                node["minLength"] = self.min_length
        elif self.type == "array":
            item: dict[str, Any] = {"type": _JSON_TYPES[self.item_type or "string"]}
            if self.item_type in {"integer", "number"}:
                item["minimum"] = self.item_minimum
                item["maximum"] = self.item_maximum
            if self.item_type == "string":
                item["maxLength"] = self.item_max_length or MAX_ITEMS_STRING
            node["items"] = item
            node["maxItems"] = self.max_items
        if self.choices is not None:
            node["enum"] = list(self.choices)
        return node


def _reject_stray_bounds(field: SchemaField, names: set[str]) -> None:
    for name in names:
        if getattr(field, name) is not None:
            raise ValueError(f"field {field.name!r} must not declare {name}")


@dataclass(frozen=True)
class ToolSchema:
    """An ordered, validated set of fields describing one side of a contract."""

    fields: tuple[SchemaField, ...]
    allow_extra: bool = False

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValueError("a tool schema must declare at least one field")
        if len(self.fields) > MAX_FIELDS:
            raise ValueError(f"a tool schema may declare at most {MAX_FIELDS} fields")
        if not isinstance(self.allow_extra, bool):
            raise TypeError("allow_extra must be a bool")
        seen: set[str] = set()
        for field in self.fields:
            if field.name in seen:
                raise ValueError(f"duplicate schema field: {field.name!r}")
            seen.add(field.name)

    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def to_json_schema(self) -> dict[str, Any]:
        properties = {field.name: field.to_json_schema() for field in self.fields}
        required = [field.name for field in self.fields if field.required]
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": self.allow_extra,
        }


def _matches_type(value: object, field_type: str) -> bool:
    if field_type == "string":
        return isinstance(value, str)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "array":
        return isinstance(value, (list, tuple))
    return False


def _validate_value(field: SchemaField, value: object, *, for_output: bool) -> Any:
    if not _matches_type(value, field.type):
        raise _schema_error(field, f"expected type {field.type!r}", for_output)

    if field.type == "boolean":
        assert isinstance(value, bool)
        return value
    if field.type == "integer":
        assert isinstance(value, int) and not isinstance(value, bool)
        return _validate_number(field, value, for_output)
    if field.type == "number":
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        as_float = float(value)
        if not math.isfinite(as_float):
            raise _schema_error(field, "must be a finite number", for_output)
        return _validate_number(field, as_float, for_output)
    if field.type == "string":
        assert isinstance(value, str)
        if field.max_length is not None and len(value) > field.max_length:
            raise _schema_error(field, f"longer than max_length {field.max_length}", for_output)
        if field.min_length is not None and len(value) < field.min_length:
            raise _schema_error(field, f"shorter than min_length {field.min_length}", for_output)
        return _check_choices(field, value, for_output)

    assert isinstance(value, (list, tuple))
    items = list(value)
    assert field.max_items is not None
    if len(items) > field.max_items:
        raise _schema_error(field, f"more than max_items {field.max_items}", for_output)
    validated: list[Any] = []
    for index, item in enumerate(items):
        try:
            validated.append(_validate_item(field, index, item, for_output=for_output))
        except (ToolInputInvalid, ToolOutputInvalid) as exc:
            raise _schema_error(field, f"item {index} is invalid: {exc}", for_output) from exc
    return validated


def _validate_item(field: SchemaField, index: int, value: object, *, for_output: bool) -> Any:
    """Validate one array element against the bounds its parent declared.

    Written as a check on the parent rather than by synthesizing a child
    :class:`SchemaField`: a declared field is a contract with a name and its own
    bounds, and an array position is neither. Reusing the declared-field type here
    would mean either inventing a name like ``"xs[0]"`` that no schema declared
    or loosening the name rules that keep declared fields checkable.
    """

    item_type = field.item_type or "string"
    label = f"item {index} of {field.name!r}"
    if not _matches_type(value, item_type):
        raise _root_error(
            f"{label} has type {type(value).__name__}, expected {item_type}", for_output
        )
    if item_type == "boolean":
        assert isinstance(value, bool)
        return value
    if item_type in {"integer", "number"}:
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        as_float = float(value)
        low = field.item_minimum
        high = field.item_maximum
        assert low is not None and high is not None
        if not math.isfinite(as_float) or as_float < low or as_float > high:
            raise _root_error(
                f"{label} is outside the declared range [{low}, {high}]", for_output
            )
        return as_float if item_type == "number" else int(as_float)
    assert isinstance(value, str)
    ceiling = field.item_max_length or MAX_ITEMS_STRING
    if len(value) > ceiling:
        raise _root_error(f"{label} is longer than {ceiling} characters", for_output)
    if field.choices is not None and value not in field.choices:
        raise _root_error(
            f"{label} is not one of {list(field.choices)!r}", for_output
        )
    return value


def _validate_number(field: SchemaField, value: float, for_output: bool) -> Any:
    assert field.minimum is not None and field.maximum is not None
    if value < field.minimum or value > field.maximum:
        raise _schema_error(
            field, f"outside declared range [{field.minimum}, {field.maximum}]", for_output
        )
    return value


def _check_choices(field: SchemaField, value: Any, for_output: bool) -> Any:
    if field.choices is not None and value not in field.choices:
        raise _schema_error(field, f"not one of {list(field.choices)!r}", for_output)
    return value


def _schema_error(field: SchemaField, detail: str, for_output: bool) -> Exception:
    message = f"field {field.name!r} {detail}"
    if for_output:
        return ToolOutputInvalid(message)
    return ToolInputInvalid(message)


def _root_error(detail: str, for_output: bool) -> Exception:
    """Error for a whole payload rather than one declared field.

    A payload-level failure has no field to name, and building a synthetic
    :class:`SchemaField` for it would mean inventing a field that was never
    declared — and would itself raise, because the bounds it would lack are
    exactly the bounds every declared field must carry.
    """

    message = f"payload {detail}"
    if for_output:
        return ToolOutputInvalid(message)
    return ToolInputInvalid(message)


def validate_against(
    schema: ToolSchema, payload: object, *, for_output: bool = False
) -> dict[str, Any]:
    """Validate ``payload`` and return a normalized copy.

    Normalization is limited to the conversions the declared types imply
    (``integer`` to ``int``, ``number`` to ``float``, ``array`` to ``list``).
    Nothing is dropped, reordered into meaning, or reinterpreted: a caller
    cannot smuggle an unvalidated value through by relying on leniency.
    """

    if not isinstance(payload, Mapping):
        raise _root_error("must be a mapping", for_output)

    known = set(schema.field_names())
    unexpected = sorted(str(key) for key in payload if key not in known)
    if unexpected and not schema.allow_extra:
        raise _root_error(f"carries unexpected fields {unexpected!r}", for_output)

    result: dict[str, Any] = {}
    for field in schema.fields:
        if field.name not in payload:
            if field.required:
                raise _schema_error(field, "is required but missing", for_output)
            continue
        result[field.name] = _validate_value(field, payload[field.name], for_output=for_output)
    return result


def validate_input(schema: ToolSchema, payload: object) -> dict[str, Any]:
    return validate_against(schema, payload, for_output=False)


def validate_output(schema: ToolSchema, payload: object) -> dict[str, Any]:
    return validate_against(schema, payload, for_output=True)


def describe(schema: ToolSchema) -> dict[str, Any]:
    return schema.to_json_schema()
