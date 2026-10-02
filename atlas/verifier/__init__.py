"""Phase 13: deterministic verification.

The verifier is the only component that can decide a task's output is correct,
and it is the only path from ``executed`` to ``succeeded``. It reaches that
verdict from persisted records alone: it re-derives each step's expected output
from the recorded input and compares it against the recorded result.

Three parts, kept apart on purpose:

* :mod:`atlas.verifier.rules` -- what "correct" means for one registered tool, as
  a pure re-derivation. No rule imports the tool it checks, so a bug in the tool
  is not reproduced by the verifier and reported as agreement.
* :mod:`atlas.verifier.service` -- the orchestration: load the records, check the
  preconditions, record a verdict per execution, move the task only as far as the
  verdicts allow.
* :mod:`atlas.storage.verification_repo` -- one immutable evidence row per
  execution.

What it is not, and why the boundary matters:

* It does not trust the planner, the model, the UI, or the task's own status.
  ``executed`` is a precondition, not evidence.
* It does not ask a model whether a deterministic result is right. A model call
  here would make correctness unfalsifiable and non-reproducible.
* It does not write a successful result, and does not repair or re-run anything.
  Phase 15 classifies a failure and Phase 16 recovers from one; the verifier only
  records what it found.
* It does not reach a tool body. It reads stored JSON, which is why it can be
  trusted to disagree with the tool.

A PASS is the only route to a successful result, and it is not a route anything can
walk alone. Two independent conditions hold: the task reached ``verified``, which
the lifecycle permits only from ``verifying``, and every execution of the task
carries a recorded PASS. Either alone would be a claim; both together are the
evidence for one.

Re-exports are eager, for the reason :mod:`atlas.tools` documents: a lazy
``__getattr__`` re-export needs ``importlib``, and dynamic import is exactly the
code-execution vector the tool layer's controls are built to keep out.
"""

from __future__ import annotations

from atlas.verifier.errors import VerificationErrorCode, VerificationRefused
from atlas.verifier.rules import (
    CODE_FIELD_MISMATCH,
    CODE_MALFORMED_INPUT,
    CODE_MALFORMED_RESULT,
    CODE_MATCHED,
    CODE_MISSING_FIELD,
    CODE_NO_RULE,
    CODE_RESULT_UNREADABLE,
    CODE_TOOL_MISMATCH,
    CODE_UNEXPECTED_FIELD,
    FAIL,
    PASS,
    VERIFIER_NAME,
    CsvStatisticsRule,
    FieldCheck,
    NumericSummaryRule,
    RuleOutcome,
    RuleRegistry,
    TextStatisticsRule,
    VerificationRule,
)
from atlas.verifier.service import (
    VERIFIER_VERSION,
    ExecutionVerdict,
    StepEvidence,
    TaskVerificationReport,
    VerifierService,
)

#: Every verdict code, so Phase 15 can classify over the whole vocabulary without
#: importing the individual rule modules and hoping it caught them all.
RESULT_CODES = (
    CODE_MATCHED,
    CODE_FIELD_MISMATCH,
    CODE_MISSING_FIELD,
    CODE_UNEXPECTED_FIELD,
    CODE_MALFORMED_RESULT,
    CODE_MALFORMED_INPUT,
    CODE_NO_RULE,
    CODE_RESULT_UNREADABLE,
    CODE_TOOL_MISMATCH,
)

__all__ = [
    "CODE_FIELD_MISMATCH",
    "CODE_MALFORMED_INPUT",
    "CODE_MALFORMED_RESULT",
    "CODE_MATCHED",
    "CODE_MISSING_FIELD",
    "CODE_NO_RULE",
    "CODE_RESULT_UNREADABLE",
    "CODE_TOOL_MISMATCH",
    "CODE_UNEXPECTED_FIELD",
    "FAIL",
    "PASS",
    "RESULT_CODES",
    "VERIFIER_NAME",
    "VERIFIER_VERSION",
    "CsvStatisticsRule",
    "ExecutionVerdict",
    "FieldCheck",
    "NumericSummaryRule",
    "RuleOutcome",
    "RuleRegistry",
    "StepEvidence",
    "TaskVerificationReport",
    "TextStatisticsRule",
    "VerificationErrorCode",
    "VerificationRefused",
    "VerificationRule",
    "VerifierService",
]
