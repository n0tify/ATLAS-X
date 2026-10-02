"""Deterministic verification rules: what "correct" means for one tool.

Each rule takes the *recorded input* and the *recorded output* of one execution
and re-derives the expected output from the input, comparing field by field. The
comparison is the evidence, and it is stored with the verdict.

Why the rules are re-implementations rather than calls into the tool
-------------------------------------------------------------------

A rule here deliberately does **not** import or call the tool body it checks. If
``TextStatisticsRule`` called ``atlas.tools.builtin.text_statistics.compute``, then
a bug in ``compute`` would be reproduced faithfully by the verifier and reported
as a PASS -- the verification would confirm that the tool did what the tool does.
Re-deriving the expected value from the recorded input, in a separate module with
no import of the tool, makes a disagreement mean something: one of the two
implementations of the contract is wrong, which is the finding worth having.

What this does and does not prove, stated plainly:

* It **does** prove the recorded output is exactly what the declared deterministic
  contract produces from the recorded input. A tampered ``result_json``, a
  truncated one, or one from a different run is caught.
* It **does not** prove the contract is the *right* contract for the user's goal.
  The rules encode "what these tools claim to do", not "what the user wanted". A
  model can propose a plan whose steps each verify and whose answer is useless;
  that is a Phase 18 evaluation question, not something a deterministic re-derivation
  can settle, and pretending otherwise would be the more dangerous claim.

Every rule is a pure function of its arguments: no clock, no randomness, no I/O,
no network, no model. A rule that could not be reproduced exactly would make
"repeated verification is deterministic" untrue.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from atlas.storage.verification_repo import MAX_CHECKS

#: Rules are versioned with the tool. A change to a tool's contract without a
#: change here would silently verify old evidence against a new expectation, so
#: the pair is recorded on every verdict and is part of the evidence.
VERIFIER_NAME = "atlas.verifier.rules"

#: Result vocabulary. Lower case to match the stored column.
PASS = "pass"
FAIL = "fail"

#: Why a verdict came out the way it did. Stable strings, because Phase 15
#: classifies from them and Phase 16 decides recoverability from them.
CODE_MATCHED = "matched"
CODE_FIELD_MISMATCH = "field_mismatch"
CODE_MISSING_FIELD = "missing_field"
CODE_UNEXPECTED_FIELD = "unexpected_field"
CODE_MALFORMED_RESULT = "malformed_result"
CODE_MALFORMED_INPUT = "malformed_input"
CODE_NO_RULE = "no_rule"

#: The two codes the *service* can reach that a rule cannot: they describe the
#: stored records rather than a comparison, so no rule can produce them. They live
#: here with the rest of the vocabulary because Phase 15 classifies over the whole
#: set and a code in two modules is a code that will eventually disagree with
#: itself.
CODE_RESULT_UNREADABLE = "result_unreadable"
CODE_TOOL_MISMATCH = "tool_mismatch"


@dataclass(frozen=True)
class FieldCheck:
    """One expected-versus-actual comparison, as stored evidence."""

    field: str
    expected: Any
    actual: Any
    ok: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class RuleOutcome:
    """What a rule concluded, before anything is persisted."""

    verdict: str
    code: str
    checks: tuple[FieldCheck, ...] = ()
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    def evidence(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "checks": [check.as_dict() for check in self.checks],
        }


class VerificationRule:
    """Base class. Subclasses declare a tool id and re-derive its output."""

    #: The registered ``tool_id`` this rule judges.
    tool_id: str = ""

    def expected(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """The output the contract requires for ``arguments``.

        Raises :class:`ValueError` when the input is not something this rule can
        judge -- which is a FAIL with ``malformed_input``, not an exception that
        escapes the verifier and leaves the task stranded in ``verifying``.
        """

        raise NotImplementedError

    def compare(
        self, arguments: Mapping[str, Any], result: Mapping[str, Any]
    ) -> RuleOutcome:
        """Re-derive and compare. Never trusts either side's provenance."""

        try:
            wanted = dict(self.expected(arguments))
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            return RuleOutcome(
                verdict=FAIL,
                code=CODE_MALFORMED_INPUT,
                detail=f"input does not satisfy the {self.tool_id} contract: {exc}",
            )
        if not wanted:
            return RuleOutcome(
                verdict=FAIL,
                code=CODE_MALFORMED_RESULT,
                detail=f"the {self.tool_id} rule produced no expected fields",
            )

        extra = sorted(set(result) - set(wanted))
        if extra:
            # An extra field is a real disagreement, not noise: it means the output
            # claims something the contract does not define. Silently ignoring it
            # would let a tampered result pass with one field rewritten.
            return RuleOutcome(
                verdict=FAIL,
                code=CODE_UNEXPECTED_FIELD,
                checks=(),
                detail=f"result carries fields the contract does not define: {extra}",
            )

        checks: list[FieldCheck] = []
        for field in sorted(wanted):
            if field not in result:
                checks.append(FieldCheck(field, wanted[field], None, False))
                continue
            checks.append(
                FieldCheck(
                    field,
                    wanted[field],
                    result[field],
                    _equal(wanted[field], result[field]),
                )
            )
        if len(checks) > MAX_CHECKS:
            return RuleOutcome(
                verdict=FAIL,
                code=CODE_MALFORMED_RESULT,
                detail=f"rule produced {len(checks)} comparisons, over the {MAX_CHECKS} bound",
            )
        failed = [check.field for check in checks if not check.ok]
        if failed:
            return RuleOutcome(
                verdict=FAIL,
                code=CODE_FIELD_MISMATCH,
                checks=tuple(checks),
                detail=f"fields disagree: {failed}",
            )
        return RuleOutcome(verdict=PASS, code=CODE_MATCHED, checks=tuple(checks))


def _equal(expected: Any, actual: Any) -> bool:
    """Compare a re-derived value with a recorded one.

    Numbers are compared by value rather than by repr, because the dispatcher
    round-trips results through JSON and ``round(1.0, 6)`` comes back as ``1.0``
    while an int stays an int. Anything that is not a number must match exactly,
    including its type: ``True`` and ``1`` are different answers, and treating them
    as equal would let a boolean result satisfy an integer field.
    """

    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if math.isnan(float(expected)) or math.isnan(float(actual)):
            return math.isnan(float(expected)) and math.isnan(float(actual))
        return float(expected) == float(actual)
    return expected == actual and type(expected) is type(actual)


class TextStatisticsRule(VerificationRule):
    """Character, line, and word counts over a bounded string.

    Re-derived from ``text`` and ``count_words`` exactly as the contract declares
    them, independently of :mod:`atlas.tools.builtin.text_statistics`.
    """

    tool_id = "text_statistics"

    def expected(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        text = arguments.get("text")
        if not isinstance(text, str):
            raise ValueError("'text' must be a string")
        count_words = arguments.get("count_words", True)
        if not isinstance(count_words, bool):
            raise ValueError("'count_words' must be a boolean")

        lines = text.splitlines()
        words = text.split() if count_words else []
        lengths = [len(word) for word in words]
        return {
            "char_count": len(text),
            "line_count": len(lines),
            "longest_line_length": max((len(line) for line in lines), default=0),
            "word_count": len(words),
            "unique_word_count": len(set(words)),
            "min_word_length": min(lengths, default=0),
            "max_word_length": max(lengths, default=0),
        }


class NumericSummaryRule(VerificationRule):
    """Descriptive statistics over a bounded list of numbers.

    The population variance is used, matching the contract: the list is the whole
    input, not a sample. Results are rounded to the same six decimal places the
    contract specifies, so a recomputed number and a stored number compare equal.
    """

    tool_id = "numeric_summary"

    ROUND_DIGITS = 6

    def expected(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        values = arguments.get("values")
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError("'values' must be a non-empty list of numbers")
        numbers: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("'values' must contain only numbers")
            if math.isnan(float(value)) or math.isinf(float(value)):
                raise ValueError("'values' must contain only finite numbers")
            numbers.append(float(value))

        compute_variance = arguments.get("compute_variance", True)
        if not isinstance(compute_variance, bool):
            raise ValueError("'compute_variance' must be a boolean")

        total = sum(numbers)
        count = len(numbers)
        ordered = sorted(numbers)
        middle = count // 2
        median = (
            ordered[middle]
            if count % 2 == 1
            else (ordered[middle - 1] + ordered[middle]) / 2.0
        )
        mean = total / count
        expected: dict[str, Any] = {
            "count": count,
            "minimum": ordered[0],
            "maximum": ordered[-1],
            "sum": total,
        }
        if compute_variance:
            expected["mean"] = mean
            expected["median"] = median
            expected["population_variance"] = sum(
                (value - mean) ** 2 for value in numbers
            ) / count
        return {key: self._rounded(value) for key, value in expected.items()}

    def _rounded(self, value: float | int) -> float | int:
        """Round exactly as the contract does, and refuse rather than clamp.

        Clamping would publish a number the contract does not produce, which is the
        one thing a verification must not do.
        """

        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return round(float(value), self.ROUND_DIGITS)


class CsvStatisticsRule(VerificationRule):
    """Row and column counts plus selected numeric column aggregates.

    Re-derived from the CSV text and the column name rather than from anything
    :mod:`atlas.tools.builtin.csv_statistics` computed, for the same reason the
    other rules re-derive rather than call.

    The aggregate statistics are optional in both the tool's contract and this
    rule, because they depend on the column's content: a text column has no mean.
    Expecting them unconditionally would fail every run over a string column.
    """

    tool_id = "csv_statistics"

    ROUND_DIGITS = 6

    #: Bound on how many cells this rule will compare, mirroring
    #: :data:`~atlas.storage.verification_repo.MAX_CHECKS`. A CSV of a few thousand
    #: cells would otherwise produce a verdict larger than the evidence bound and be
    #: refused at write time, after the verdict had been reached.
    MAX_CELLS = 64

    def expected(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        text = arguments.get("text")
        if not isinstance(text, str):
            raise ValueError("'text' must be a string")
        column = arguments.get("column")
        if not isinstance(column, str):
            raise ValueError("'column' must be a string")
        # Optional in the contract, so it is optional here too: an absent delimiter
        # means the documented default, exactly as it does for the tool. Requiring
        # it would fail every run that legitimately omitted it.
        delimiter = arguments.get("delimiter", ",")
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            raise ValueError("'delimiter' must be a single character")

        rows = _parse_csv(text, delimiter)
        header = rows[0]
        if column not in header:
            raise ValueError(f"'column' must name a header column, not {column!r}")
        if len(set(header)) != len(header):
            raise ValueError("'text' has duplicate header names")
        width = header.index(column)
        body = rows[1:]

        cells = [row[width] for row in body]
        expected: dict[str, Any] = {
            "row_count": len(body),
            "column_count": len(header),
            "columns": sorted(header),
        }
        if len(cells) + len(expected) > self.MAX_CELLS:
            raise ValueError(
                f"a CSV of {len(body)} rows produces more than {self.MAX_CELLS} checks"
            )

        numbers: list[float] = []
        fully_numeric = bool(cells)
        for cell in cells:
            if not cell.strip():
                fully_numeric = False
                continue
            parsed = _to_number(cell)
            if parsed is None:
                fully_numeric = False
                continue
            numbers.append(parsed)
        if fully_numeric and numbers:
            total = sum(numbers)
            ordered = sorted(numbers)
            middle = len(ordered) // 2
            mean = total / len(ordered)
            expected.update(
                {
                    "numeric_count": len(numbers),
                    "minimum": ordered[0],
                    "maximum": ordered[-1],
                    "sum": total,
                    "mean": mean,
                    "median": (
                        ordered[middle]
                        if len(ordered) % 2 == 1
                        else (ordered[middle - 1] + ordered[middle]) / 2.0
                    ),
                }
            )
        else:
            # A column with blanks or non-numeric cells is counted but not
            # aggregated. Reporting a mean over the values that happened to parse
            # would be a statistic of a subset, labelled as one of the whole.
            expected["numeric_count"] = len(numbers)
        return {
            key: self._rounded(value) if isinstance(value, float) else value
            for key, value in expected.items()
        }

    def _rounded(self, value: float) -> float:
        return round(float(value), self.ROUND_DIGITS)


def _to_number(cell: str) -> float | None:
    """A finite float, or ``None`` for anything else. Never raises.

    ``float()`` accepts ``"nan"`` and ``"inf"``, so a cell that parses to a
    non-finite value counts as not-a-number here. A statistic containing NaN
    propagates to every other statistic, and a record full of NaN is not evidence
    of anything.
    """

    try:
        value = float(cell)
    except ValueError:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _parse_csv(text: str, delimiter: str) -> list[list[str]]:
    """Split CSV text into rows of fields, or refuse. Never guesses.

    A small reader rather than :mod:`csv`, deliberately. The stdlib reader accepts
    embedded newlines inside quoted fields and returns rows of differing widths
    without complaint, and this rule must reject rather than guess. Anything the
    tool's own contract rejects is a malformed input here too; anything the tool
    accepts but this reader does not would be a disagreement between two
    implementations of the same contract, which is the finding worth having.
    """

    if not text:
        raise ValueError("'text' must not be empty")
    if '"' in text:
        raise ValueError("'text' must not contain double quotes")
    if "\r" in text:
        raise ValueError("'text' must use newlines, not carriage returns")
    rows = [line.split(delimiter) for line in text.split("\n")]
    # A trailing newline is a terminator, not a record. Matching the tool here
    # matters: disagreeing about it would fail every legal run.
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        raise ValueError("'text' must have a header row")
    if not all(cell.strip() for cell in rows[0]):
        raise ValueError("'text' has an empty column name in the header row")
    for index, row in enumerate(rows[1:], start=2):
        if len(row) != len(rows[0]):
            raise ValueError(
                f"'text' line {index} has {len(row)} fields, header has {len(rows[0])}"
            )
    return rows


class RuleRegistry:
    """The set of rules, and a refusal for anything unregistered.

    A missing rule is a FAIL, never a PASS. "We do not know how to check this" and
    "this is correct" are different answers, and a verifier that answers the
    second one for an unregistered tool would make the whole table decorative.
    """

    def __init__(self, rules: list[VerificationRule] | None = None) -> None:
        self._rules: dict[str, VerificationRule] = {}
        for rule in rules if rules is not None else _builtin_rules():
            self.register(rule)

    def register(self, rule: VerificationRule) -> None:
        if not isinstance(rule.tool_id, str) or not rule.tool_id:
            raise ValueError("a rule must declare a tool_id")
        existing = self._rules.get(rule.tool_id)
        if existing is not None and type(existing) is not type(rule):
            raise ValueError(
                f"a different rule is already registered for {rule.tool_id!r}"
            )
        self._rules[rule.tool_id] = rule

    def find(self, tool_id: object) -> VerificationRule | None:
        if not isinstance(tool_id, str):
            return None
        return self._rules.get(tool_id)

    def tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._rules))

    def verify(
        self, tool_id: object, arguments: Mapping[str, Any], result: Mapping[str, Any]
    ) -> RuleOutcome:
        """Judge one execution's recorded output, or refuse to judge it."""

        rule = self.find(tool_id)
        if rule is None:
            return RuleOutcome(
                verdict=FAIL,
                code=CODE_NO_RULE,
                detail=f"no deterministic rule is registered for {tool_id!r}",
            )
        return rule.compare(arguments, result)


def _builtin_rules() -> list[VerificationRule]:
    """One rule per deterministic built-in, in a fixed order.

    A rule is added here in the same change that adds the tool it judges. That
    pairing is the point: a registered tool with no rule would produce a FAIL on
    every run, and a rule with no tool would be dead code that only ever appears in
    coverage reports.

    Kept as an explicit list rather than discovered by import so that the registry
    contents are readable in one place and cannot drift silently as modules are
    added.
    """

    return [TextStatisticsRule(), NumericSummaryRule(), CsvStatisticsRule()]
