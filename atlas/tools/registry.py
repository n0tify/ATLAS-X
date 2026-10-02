"""The tool registry: the one authoritative list of what can be invoked.

A registry resolves a tool id to a :class:`~atlas.tools.definition.ToolDefinition`
and nothing else. It holds no authorization state, so it cannot allow anything
on its own — the registry describes capability, authorization grants authority,
and :mod:`atlas.tools.dispatch` refuses to run an implementation the policy did
not approve. Keeping those separate is what stops "the registry already knows
the tool is fine" from becoming a bypass.

Registration happens in code, at application start, through
:func:`default_registry`. Nothing in this module can be reached from a request:
there is no unregister, no replace, no reload, and no path from a caller-supplied
string to an implementation. After :meth:`ToolRegistry.freeze` the contents are
immutable, so a grant that was decided against one tool set cannot be spent
against another.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Iterable, Iterator, Mapping

from atlas.tools.definition import (
    MAX_TOOL_ID_LENGTH,
    MIN_TOOL_ID_LENGTH,
    TOOL_ID_PATTERN,
    ToolDefinition,
)
from atlas.tools.errors import MalformedToolId, ToolDefinitionInvalid, UnknownTool


class ToolRegistry:
    """Immutable-after-freeze mapping of tool id to definition."""

    __slots__ = ("_definitions", "_frozen")

    def __init__(self, definitions: Iterable[ToolDefinition] = ()) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._frozen = False
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ToolDefinition) -> ToolDefinition:
        """Add one approved tool. Duplicate or malformed ids are refused."""

        if not isinstance(definition, ToolDefinition):
            raise ToolDefinitionInvalid("only a ToolDefinition can be registered")
        if self._frozen:
            raise ToolDefinitionInvalid(
                "registry is frozen; tool registration is an application concern"
            )
        existing = self._definitions.get(definition.tool_id)
        if existing is not None:
            if existing.implementation_id == definition.implementation_id:
                raise ToolDefinitionInvalid(
                    f"tool {definition.tool_id!r} is already registered"
                )
            raise ToolDefinitionInvalid(
                f"tool id {definition.tool_id!r} is already bound to "
                f"{existing.implementation_id!r}; change the id or bump the version"
            )
        self._definitions[definition.tool_id] = definition
        return definition

    def freeze(self) -> None:
        """Make the registry immutable. Idempotent."""

        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def __contains__(self, tool_id: object) -> bool:
        return isinstance(tool_id, str) and tool_id in self._definitions

    def __iter__(self) -> Iterator[ToolDefinition]:
        return iter(self.snapshot().values())

    def __len__(self) -> int:
        return len(self._definitions)

    def snapshot(self) -> Mapping[str, ToolDefinition]:
        """A read-only view of the current contents."""

        return MappingProxyType(dict(self._definitions))

    def capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def list_definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def find(self, tool_id: object) -> ToolDefinition:
        """Resolve an id to its definition, or refuse.

        A malformed id and an unknown id fail closed, and they fail differently
        on purpose: being told your own request was malformed is information
        about your request, not about anybody's data.

        The two cases are separated by the same pattern that
        :mod:`atlas.tools.definition` uses to admit a tool id, not by a second,
        looser vocabulary. Two patterns would mean an id could be accepted by
        :meth:`register` under one definition of "well formed" and rejected by
        :meth:`find` under another.
        """

        if (
            not isinstance(tool_id, str)
            or not TOOL_ID_PATTERN.fullmatch(tool_id)
            or not MIN_TOOL_ID_LENGTH <= len(tool_id) <= MAX_TOOL_ID_LENGTH
        ):
            raise MalformedToolId(f"tool id is not a usable name: {tool_id!r}")
        definition = self._definitions.get(tool_id)
        if definition is None:
            raise UnknownTool(f"no tool registered for id {tool_id!r}")
        return definition

    def describe_all(self) -> tuple[dict[str, object], ...]:
        return tuple(definition.describe() for definition in self.list_definitions())


def default_registry() -> ToolRegistry:
    """Build the registry of approved tools, frozen.

    This is the only place the tool set is defined. It is code, not data, so
    adding a capability is a reviewed source change rather than a database row
    or a request.
    """

    from atlas.tools.builtin import build_definitions

    registry = ToolRegistry(build_definitions())
    registry.freeze()
    return registry
