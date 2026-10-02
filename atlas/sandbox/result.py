"""What a sandboxed invocation produced, in the platform's terms.

The supervisor's job is to run something and decide what it means. This module
holds the decision's output: a :class:`SandboxOutcome` that says either "here is
the validated tool output" or "here is the specific control that was crossed",
together with the evidence an operator would need to believe it.

Two design points are worth stating because they are what keeps the report
honest.

First, :attr:`SandboxOutcome.memory` is reported, not assumed. Every run carries
the cgroup's observed ``memory.peak`` and ``memory.events``, so a claim about
memory behaviour is backed by the kernel's own accounting for that run rather
than by the configured limit. A run that hit the cap repeatedly and was never
OOM-killed looks different from one that was, and the report has to show that
difference instead of collapsing both into "memory was limited".

Second, a violation is carried as a value, never as an exception that unwinds
through the dispatcher. The dispatcher needs to record *which* control was
crossed in the audit record, and an exception carrying only a message would lose
exactly the field the incident review needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from atlas.sandbox.protocol import Diagnostics, Envelope, Status, ViolationKind

__all__ = ["SandboxOutcome", "memory_report"]


@dataclass(frozen=True)
class MemoryReport:
    """Observed memory behaviour for one invocation."""

    limit_bytes: int
    peak_bytes: int | None
    #: ``memory.events`` counters. ``max`` counts times reclaim hit the cap;
    #: ``oom_kill`` counts times the kernel actually killed the cgroup. A run with
    #: ``max > 0`` and ``oom_kill == 0`` is the documented signature of a cap that
    #: throttled without terminating anything.
    events: Mapping[str, int]

    @property
    def cap_was_hit(self) -> bool:
        return self.events.get("max", 0) > 0

    @property
    def oom_killed(self) -> bool:
        return self.events.get("oom_kill", 0) > 0

    def as_json(self) -> dict[str, Any]:
        return {
            "limit_bytes": self.limit_bytes,
            "peak_bytes": self.peak_bytes,
            "events": dict(self.events),
            "cap_was_hit": self.cap_was_hit,
            "oom_killed": self.oom_killed,
        }


def memory_report(limit_bytes: int, diagnostics: Diagnostics) -> MemoryReport:
    return MemoryReport(
        limit_bytes=limit_bytes,
        peak_bytes=diagnostics.cgroup_peak_bytes,
        events=dict(diagnostics.cgroup_events),
    )


@dataclass(frozen=True)
class SandboxOutcome:
    """The result of one sandboxed invocation."""

    #: Validated tool output. Present only when :attr:`ok` is true.
    output: Mapping[str, Any] | None
    status: Status
    violation: ViolationKind | None
    message: str | None
    elapsed_ms: int
    memory: MemoryReport
    diagnostics: Diagnostics
    #: The platform error code the confined side reported, if any. Carried so the
    #: classification survives the boundary intact; see :attr:`Envelope.error_code`.
    error_code: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is Status.OK

    @property
    def crossed_control(self) -> bool:
        """Whether a declared access control was violated, as opposed to a bound."""

        return self.status is Status.POLICY_DENIED

    def require_output(self) -> Mapping[str, Any]:
        """The output, or a refusal.

        Callers that have already checked :attr:`ok` still get a checked read, so
        a future caller cannot forget the check and silently pass ``None`` onward
        as if it were a result.
        """

        if not self.ok or self.output is None:
            raise SandboxOutcomeError(
                f"sandboxed invocation did not succeed: {self.status.value}"
                + (f" ({self.violation.value})" if self.violation else "")
            )
        return self.output

    @classmethod
    def from_envelope(
        cls, envelope: Envelope, *, memory_limit_bytes: int
    ) -> SandboxOutcome:
        return cls(
            output=envelope.output,
            status=Status(envelope.status),
            violation=(
                None if envelope.violation is None else ViolationKind(envelope.violation)
            ),
            message=envelope.error_message,
            elapsed_ms=envelope.elapsed_ms,
            memory=memory_report(memory_limit_bytes, envelope.diagnostics),
            diagnostics=envelope.diagnostics,
            error_code=envelope.error_code,
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "violation": None if self.violation is None else self.violation.value,
            "elapsed_ms": self.elapsed_ms,
            "memory": self.memory.as_json(),
            "observations": dict(self.diagnostics.observations),
            "message": self.message,
            "error_code": self.error_code,
        }


class SandboxOutcomeError(RuntimeError):
    """A caller asked an unsuccessful outcome for its output."""
