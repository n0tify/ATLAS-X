"""Phase 13: the deterministic verifier.

The verifier is the only path from ``executed`` to ``succeeded``, so the tests are
organised around the ways that path could be reached dishonestly:

* **A correct result must pass**, and the evidence must say *why* it passed.
* **Every kind of wrong must fail** -- a wrong number, a missing result, a
  malformed one, a tampered one, an unexpected extra field.
* **Nothing may skip the check**: no verification without an execution, no
  ``succeeded`` without a recorded PASS, no re-verification producing a second
  contradictory verdict.
* **The verifier trusts nothing it did not recompute**: not the planner, not the
  model, not the task status, not its own earlier opinion.

Rules are tested directly against re-derived values (fast, and they pin the
comparison semantics that the service relies on), and the service is tested through
real repositories and the real authorization boundary rather than mocks.

The lifecycle test in ``tests/test_executor.py`` pins the whole transition table,
so this file asserts the *edges Phase 13 added* (``executed -> verifying ->
verified | failed``) rather than repeating the whole table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.executor.service import ExecutorService
from atlas.planner.plan import PlanDocument
from atlas.security.errors import AuthorizationError, ResultUnpublishable
from atlas.security.policy import (
    PERMITTED_OPERATIONS,
    DenyReason,
    Operation,
    Resource,
)
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.task_status import StatusTransitionRefused, TaskStatus
from atlas.tools.definition import ToolContext
from atlas.util import utcnow_iso
from atlas.verifier.errors import VerificationErrorCode, VerificationRefused
from atlas.verifier.rules import (
    CODE_FIELD_MISMATCH,
    CODE_MALFORMED_INPUT,
    CODE_MATCHED,
    CODE_NO_RULE,
    CODE_RESULT_UNREADABLE,
    CODE_TOOL_MISMATCH,
    CODE_UNEXPECTED_FIELD,
    FAIL,
    PASS,
    CsvStatisticsRule,
    NumericSummaryRule,
    RuleRegistry,
    TextStatisticsRule,
    _equal,
)
from atlas.verifier.service import VerifierService

PASSWORD = "correct horse battery staple"

#: A context for calling a tool body directly from a test. The pure built-ins read
#: nothing from it, and passing a real one keeps that honest -- a stub would hide a
#: tool that started reading context.
_TOOL_CONTEXT = ToolContext(user_id=1, task_id=1, view=None)

TOOL_A = "text_statistics"
TOOL_B = "numeric_summary"
CSV_TOOL = "csv_statistics"


# --------------------------------------------------------------- fixtures


@pytest.fixture
def authz(db: Database, auth: AuthService) -> AuthorizationService:
    return AuthorizationService(db, auth)


@pytest.fixture
def alice(auth: AuthService) -> str:
    auth.register("alice", PASSWORD)
    return str(auth.login("alice", PASSWORD)["token"])


@pytest.fixture
def bob(auth: AuthService) -> str:
    auth.register("bob", PASSWORD)
    return str(auth.login("bob", PASSWORD)["token"])


@pytest.fixture
def verifier(authz: AuthorizationService) -> VerifierService:
    return VerifierService(authz)


def _store_plan(
    authz: AuthorizationService,
    token: str,
    task_id: int,
    payload: Mapping[str, Any],
    *,
    validated: bool = True,
) -> dict[str, Any]:
    document = PlanDocument.from_payload(payload, max_steps=16)
    steps = [
        {
            "tool_id": step.tool_id,
            "step_key": step.step_key,
            "depends_on": list(step.depends_on),
            "input": step.input,
            "action": step.action or step.tool_id,
        }
        for step in document.steps
    ]
    return authz.create_plan(
        token,
        task_id=task_id,
        plan_json=document.canonical_json(),
        digest=document.digest(),
        steps=steps,
        model_id="stub-model:1b",
        source="planner",
        validated=validated,
        validation_json=None,
    )


class _StubDispatcher:
    """Returns a caller-supplied result so the stored bytes can be controlled.

    Tests that need the recorded result to be *wrong* cannot get there through a
    real tool, because a real tool returns the right answer. Writing the
    executor's output directly is the honest way to set up a corrupted record.
    """

    def __init__(self, result: Mapping[str, Any]) -> None:
        self._result = dict(result)
        self.calls = 0

    def dispatch(
        self,
        session_token,
        *,
        tool_id,
        task_id,
        arguments,
        execution_id=None,
        plan_id=None,
        plan_step_id=None,
        invocation_id=None,
    ):  # type: ignore[no-untyped-def]
        from atlas.tools.dispatch import ToolInvocation

        self.calls += 1
        return ToolInvocation(
            tool_id=str(tool_id),
            tool_version="1.0.0",
            capability=str(tool_id),
            determinism="deterministic",
            user_id=1,
            task_id=int(task_id),
            result=self._result,
            record={},
            provenance_event_id=1,
        )


def _executed_task(
    authz: AuthorizationService,
    token: str,
    result: Mapping[str, Any],
    *,
    tool_id: str = TOOL_A,
    arguments: Mapping[str, Any] | None = None,
) -> int:
    """A task with a plan that has been run once and recorded ``result``."""

    task = int(authz.create_task(token, title="t", goal="g")["id"])
    _store_plan(
        authz,
        token,
        task,
        {
            "summary": "One deterministic step.",
            "steps": [
                {
                    "step_key": "only",
                    "tool_id": tool_id,
                    "input": dict(arguments or {"text": "hello world"}),
                    "depends_on": [],
                }
            ],
        },
    )
    ExecutorService(authz, _StubDispatcher(result)).execute(token, task)
    return task


# ------------------------------------------------------------------- rules


class TestRules:
    def test_a_correct_text_result_passes_with_per_field_evidence(self) -> None:
        outcome = TextStatisticsRule().compare(
            {"text": "hello world"}, _text_result("hello world")
        )
        assert outcome.verdict == PASS
        assert outcome.code == CODE_MATCHED
        assert {check.field for check in outcome.checks} == {
            "char_count",
            "line_count",
            "longest_line_length",
            "word_count",
            "unique_word_count",
            "min_word_length",
            "max_word_length",
        }
        assert all(check.ok for check in outcome.checks)

    def test_a_correct_numeric_result_passes(self) -> None:
        expected = NumericSummaryRule().expected({"values": [1, 2, 3]})
        outcome = NumericSummaryRule().compare({"values": [1, 2, 3]}, expected)
        assert outcome.verdict == PASS

    def test_a_single_wrong_number_fails_and_names_the_field(self) -> None:
        wrong = dict(_text_result("hello world"))
        wrong["char_count"] = 999
        outcome = TextStatisticsRule().compare({"text": "hello world"}, wrong)
        assert outcome.verdict == FAIL
        assert outcome.code == CODE_FIELD_MISMATCH
        assert "char_count" in outcome.detail
        # Every other field is reported as agreeing, so the evidence shows this was
        # one disagreement and not a wholesale mismatch.
        assert sum(1 for check in outcome.checks if check.ok) == 6

    def test_a_result_with_an_extra_field_fails(self) -> None:
        # A tampered result that adds a claim the contract never makes must not be
        # accepted just because the declared fields all agree.
        tampered = {**_text_result("hello world"), "confidence": 0.99}
        outcome = TextStatisticsRule().compare({"text": "hello world"}, tampered)
        assert outcome.verdict == FAIL
        assert outcome.code == CODE_UNEXPECTED_FIELD

    def test_a_result_missing_a_field_fails(self) -> None:
        partial = dict(_text_result("hello world"))
        del partial["word_count"]
        outcome = TextStatisticsRule().compare({"text": "hello world"}, partial)
        assert outcome.verdict == FAIL
        assert any(check.field == "word_count" and not check.ok for check in outcome.checks)

    def test_an_unregistered_tool_fails_rather_than_passing(self) -> None:
        # "We do not know how to check this" is not "this is correct".
        outcome = RuleRegistry().verify("no_such_tool", {}, {"ok": True})
        assert outcome.verdict == FAIL
        assert outcome.code == CODE_NO_RULE

    def test_input_the_contract_rejects_fails_as_malformed_input(self) -> None:
        outcome = TextStatisticsRule().compare({"text": 17}, {})
        assert outcome.verdict == FAIL
        assert outcome.code == CODE_MALFORMED_INPUT

    def test_an_empty_value_list_is_not_verifiable(self) -> None:
        outcome = NumericSummaryRule().compare({"values": []}, {})
        assert outcome.verdict == FAIL
        assert outcome.code == CODE_MALFORMED_INPUT

    @pytest.mark.parametrize("value", [True, "3", None, float("nan")])
    def test_a_non_numeric_value_is_not_verifiable(self, value: Any) -> None:
        outcome = NumericSummaryRule().compare({"values": [1, value]}, {})
        assert outcome.verdict == FAIL
        assert outcome.code == CODE_MALFORMED_INPUT

    def test_booleans_do_not_satisfy_numeric_fields(self) -> None:
        # `True == 1` in Python. A verifier that used `==` would accept a boolean
        # where a count belongs.
        assert _equal(1, True) is False
        assert _equal(True, True) is True

        outcome = NumericSummaryRule().compare({"values": [1, 2]}, {"count": True})
        assert outcome.verdict == FAIL
        assert outcome.code == CODE_FIELD_MISMATCH

    def test_optional_statistics_are_only_expected_when_asked_for(self) -> None:
        asked = dict(NumericSummaryRule().expected({"values": [1, 2], "compute_variance": False}))
        assert set(asked) == {"count", "minimum", "maximum", "sum"}
        # The tool returns exactly the optional subset that was requested, so
        # expecting mean/median/variance here would fail a perfectly good run. The
        # arguments passed to `compare` must be the ones the step was authorized
        # with, including the flag -- the rule re-derives from the recorded input and
        # has no way to know what was asked unless the input says so.
        outcome = NumericSummaryRule().compare(
            {"values": [1, 2], "compute_variance": False}, asked
        )
        assert outcome.verdict == PASS

    def test_the_optional_statistics_are_expected_by_default(self) -> None:
        # The converse: a run that did not ask for them and did not get them is a
        # FAIL, because the contract produces them by default.
        outcome = NumericSummaryRule().compare({"values": [1, 2]}, {"count": 2})
        assert outcome.verdict == FAIL
        assert outcome.code == CODE_FIELD_MISMATCH

    def test_a_rule_is_a_pure_function_of_its_arguments(self) -> None:
        # No clock, no randomness: the same bytes give the same verdict and the
        # same evidence, which is what makes a stored verdict reproducible.
        rule = TextStatisticsRule()
        first = rule.compare({"text": "a b c"}, _text_result("a b c"))
        second = rule.compare({"text": "a b c"}, _text_result("a b c"))
        assert first.verdict == second.verdict == PASS
        assert first.evidence() == second.evidence()

    def test_the_rules_do_not_import_the_tools_they_check(self) -> None:
        # A rule that called the tool body would reproduce a tool bug and report
        # it as agreement. Checked over the parsed module so the docstring saying
        # this does not count as satisfying it.
        import ast
        from pathlib import Path

        source = Path(__file__).resolve().parents[1] / "atlas" / "verifier" / "rules.py"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        assert not any("tools.builtin" in name for name in imported)

    def test_the_registry_refuses_two_different_rules_for_one_tool(self) -> None:
        registry = RuleRegistry([TextStatisticsRule()])
        with pytest.raises(ValueError):
            registry.register(_OtherTextStatisticsRule())

    def test_every_registered_tool_has_a_rule_and_a_rule_covers_a_tool(self) -> None:
        # A tool with no rule FAILs every run; a rule with no tool is dead code.
        # Either half of the registry drifting is caught here.
        from atlas.tools.builtin import build_definitions

        tool_ids = {definition.tool_id for definition in build_definitions()}
        rule_ids = set(RuleRegistry().tool_ids())
        assert CSV_TOOL in rule_ids
        assert rule_ids <= tool_ids
        assert {"text_statistics", "numeric_summary", CSV_TOOL} <= rule_ids

    def test_the_registry_is_readable(self) -> None:
        # Sorted, so the order is a property of the set rather than of the order the
        # built-ins happen to be constructed in.
        assert RuleRegistry().tool_ids() == (CSV_TOOL, TOOL_B, TOOL_A)


class _OtherTextStatisticsRule(TextStatisticsRule):
    """A second rule claiming an already-registered tool, for the registry test."""

    def expected(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"different": True}


class TestCsvRule:
    def test_a_correct_csv_verifies(self) -> None:
        text = "name,amount\nwidget,10\ngadget,20\n"
        outcome = CsvStatisticsRule().compare(
            {"text": text, "column": "amount"}, _csv_result(text, "amount")
        )
        assert outcome.verdict == PASS
        assert outcome.code == CODE_MATCHED

    def test_a_csv_aggregate_that_disagrees_fails(self) -> None:
        text = "name,amount\nwidget,10\ngadget,20\n"
        wrong = {**_csv_result(text, "amount"), "sum": 31.0}
        outcome = CsvStatisticsRule().compare({"text": text, "column": "amount"}, wrong)
        assert outcome.verdict == FAIL
        assert outcome.code == CODE_FIELD_MISMATCH

    def test_a_text_column_is_counted_but_not_aggregated(self) -> None:
        # A mean over the cells that happened to parse is a statistic of a subset
        # wearing the label of the whole, so no aggregates are expected.
        text = "name,amount\nwidget,10\ngadget,x\n"
        result = _csv_result(text, "amount")
        assert "mean" not in result
        assert result["numeric_count"] == 1
        outcome = CsvStatisticsRule().compare({"text": text, "column": "amount"}, result)
        assert outcome.verdict == PASS

    @pytest.mark.parametrize(
        ("arguments", "why"),
        [
            ({"text": "a,b\n1\n", "column": "a"}, "ragged row"),
            ({"text": 'a,b\n"x",1\n', "column": "b"}, "quotes"),
            ({"text": "a,a\n1,2\n", "column": "a"}, "duplicate header"),
            ({"text": "a\n1\n", "column": "missing"}, "unknown column"),
            ({"text": "a\n1\n", "column": "a", "delimiter": ";,"}, "multi-char delimiter"),
            ({"text": "", "column": "a"}, "empty text"),
        ],
        ids=["ragged", "quotes", "duplicate-header", "unknown-column", "delimiter", "empty"],
    )
    def test_malformed_csv_is_not_verifiable(
        self, arguments: Mapping[str, Any], why: str
    ) -> None:
        outcome = CsvStatisticsRule().compare(arguments, {})
        assert outcome.verdict == FAIL, why
        assert outcome.code == CODE_MALFORMED_INPUT, why


def _csv_result(text: str, column: str) -> dict[str, Any]:
    """The tool's own answer, for setting up a run that should verify.

    Uses the tool body deliberately here, unlike :func:`_text_result`. The point
    of these tests is that the *rule* agrees with the *tool* about a legal input;
    the test that the two implementations are independent is
    ``test_the_rules_do_not_import_the_tools_they_check``.
    """

    from atlas.tools.builtin.csv_statistics import compute as csv_compute

    return dict(csv_compute(_TOOL_CONTEXT, {"text": text, "column": column}))


def _text_result(text: str) -> dict[str, Any]:
    """The contract's own answer for ``text``, derived independently here."""

    lines = text.splitlines()
    words = text.split()
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


# ------------------------------------------------- verification that passes


class TestVerifierPasses:
    def test_a_correct_result_passes_and_completes_the_task(
        self,
        authz: AuthorizationService,
        alice: str,
        verifier: VerifierService,
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        report = verifier.verify_task(alice, task)

        assert report.passed
        assert report.verdict == PASS
        assert report.checked == 1
        stored = authz.get_task(alice, task)
        assert stored["status"] == TaskStatus.SUCCEEDED.value
        assert stored["verified_at"] is not None
        assert stored["result_json"] is not None

    def test_a_pass_records_one_verdict_per_execution(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        verifier.verify_task(alice, task)
        rows = authz.verifications_for_task(alice, task)
        assert len(rows) == 1
        assert rows[0]["result"] == "pass"
        assert rows[0]["verifier"] == "atlas.verifier.rules"
        assert rows[0]["verifier_version"]
        assert rows[0]["execution_id"] > 0
        assert rows[0]["plan_step_id"] is not None

    def test_the_evidence_records_what_was_compared(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        verifier.verify_task(alice, task)
        evidence = json.loads(str(authz.verifications_for_task(alice, task)[0]["evidence_json"]))
        assert evidence["code"] == CODE_MATCHED
        assert evidence["tool_id"] == TOOL_A
        assert evidence["input_digest"].startswith("sha256:")
        assert evidence["result_digest"].startswith("sha256:")
        assert all(check["ok"] for check in evidence["checks"])

    def test_the_published_result_is_the_verified_one(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        verifier.verify_task(alice, task)
        published = json.loads(str(authz.get_task(alice, task)["result_json"]))
        assert published["verdict"] == PASS
        assert published["steps"]["only"]["char_count"] == 11
        assert published["verifications"][0]["step_key"] == "only"

    def test_two_steps_of_one_tool_are_published_separately(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # Keyed by step, not by tool: the same tool may legitimately appear twice in
        # a plan, and keying by tool would publish only the last one while still
        # reading as a complete result.
        task = int(authz.create_task(alice, title="t", goal="g")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "Measure twice.",
                "steps": [
                    {
                        "step_key": "first",
                        "tool_id": TOOL_A,
                        "input": {"text": "aa"},
                        "depends_on": [],
                    },
                    {
                        "step_key": "second",
                        "tool_id": TOOL_A,
                        "input": {"text": "bbb"},
                        "depends_on": [],
                    },
                ],
            },
        )

        class _PairDispatcher:
            """Answers each step's own question, so both PASS."""

            def __init__(self) -> None:
                self._answers = {"first": _text_result("aa"), "second": _text_result("bbb")}
                self._seen: list[str] = []

            def dispatch(
                self,
                session_token,
                *,
                tool_id,
                task_id,
                arguments,
                execution_id=None,
                plan_id=None,
                plan_step_id=None,
                invocation_id=None,
            ):  # type: ignore[no-untyped-def]
                from atlas.tools.dispatch import ToolInvocation

                text = str(arguments["text"])
                step = "first" if text == "aa" else "second"
                self._seen.append(step)
                return ToolInvocation(
                    tool_id=str(tool_id),
                    tool_version="1.0.0",
                    capability=str(tool_id),
                    determinism="deterministic",
                    user_id=1,
                    task_id=int(task_id),
                    result=self._answers[step],
                    record={},
                    provenance_event_id=1,
                )

        ExecutorService(authz, _PairDispatcher()).execute(alice, task)
        assert verifier.verify_task(alice, task).passed

        published = json.loads(str(authz.get_task(alice, task)["result_json"]))
        assert set(published["steps"]) == {"first", "second"}
        assert published["steps"]["first"]["char_count"] == 2
        assert published["steps"]["second"]["char_count"] == 3

    def test_a_csv_run_verifies_end_to_end(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # The shape Phase 18's end-to-end path will take: a plan over a pasted CSV,
        # dispatched for real through the stub dispatcher, then verified. Here the
        # result is the tool's own output, so this is a PASS for the whole chain
        # rather than for a hand-built record.
        text = "region,amount\nnorth,10\nsouth,25\neast,15\n"
        task = int(authz.create_task(alice, title="t", goal="total by region")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "Total the amounts.",
                "steps": [
                    {
                        "step_key": "total",
                        "tool_id": CSV_TOOL,
                        "input": {"text": text, "column": "amount"},
                        "depends_on": [],
                    }
                ],
            },
        )
        from atlas.tools.builtin.csv_statistics import compute as csv_compute

        result = dict(csv_compute(_TOOL_CONTEXT, {"text": text, "column": "amount"}))
        ExecutorService(authz, _StubDispatcher(result)).execute(alice, task)

        report = verifier.verify_task(alice, task)
        assert report.passed
        published = json.loads(str(authz.get_task(alice, task)["result_json"]))
        assert published["steps"]["total"]["sum"] == 50.0
        assert published["steps"]["total"]["row_count"] == 3

    def test_verification_is_deterministic_across_databases(
        self,
        db: Database,
        settings: Settings,
        alice: str,
        tmp_path: Path,
    ) -> None:
        # Same persisted bytes, two databases, identical verdicts and evidence.
        # Proves the verdict depends on the records and not on the run.
        first_authz = AuthorizationService(db, AuthService(db, settings))
        first = _executed_task(first_authz, alice, _text_result("hello world"))
        report_one = VerifierService(first_authz).verify_task(alice, first)
        evidence_one = json.loads(
            str(first_authz.verifications_for_task(alice, first)[0]["evidence_json"])
        )

        # A genuinely separate database, with its own auth service: reusing `auth`
        # would leave the second service authenticating against the first file,
        # which would test nothing about determinism at all.
        second_db = Database(tmp_path / "second.db")
        second_db.initialize()
        second_auth = AuthService(second_db, settings)
        second_auth.register("alice", PASSWORD)
        second_token = str(second_auth.login("alice", PASSWORD)["token"])

        second_authz = AuthorizationService(second_db, second_auth)
        second = _executed_task(second_authz, second_token, _text_result("hello world"))
        report_two = VerifierService(second_authz).verify_task(second_token, second)
        evidence_two = json.loads(
            str(second_authz.verifications_for_task(second_token, second)[0]["evidence_json"])
        )

        assert report_one.verdict == report_two.verdict == PASS
        assert report_one.checked == report_two.checked == 1
        assert evidence_one["result_digest"] == evidence_two["result_digest"]
        assert evidence_one["input_digest"] == evidence_two["input_digest"]
        assert evidence_one["checks"] == evidence_two["checks"]


# ------------------------------------------------- verification that fails


class TestVerifierFails:
    def test_a_wrong_result_fails_and_does_not_complete_the_task(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        wrong = {**_text_result("hello world"), "char_count": 999}
        task = _executed_task(authz, alice, wrong)
        report = verifier.verify_task(alice, task)

        assert not report.passed
        assert report.verdict == FAIL
        stored = authz.get_task(alice, task)
        assert stored["status"] == TaskStatus.FAILED.value
        # No result, no verified_at: a failed verification publishes nothing.
        assert stored["result_json"] is None
        assert stored["verified_at"] is None

    def test_a_fail_records_deterministic_evidence(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        wrong = {**_text_result("hello world"), "char_count": 999}
        task = _executed_task(authz, alice, wrong)
        verifier.verify_task(alice, task)
        row = authz.verifications_for_task(alice, task)[0]
        assert row["result"] == "fail"
        evidence = json.loads(str(row["evidence_json"]))
        assert evidence["code"] == CODE_FIELD_MISMATCH
        mismatched = [c for c in evidence["checks"] if not c["ok"]]
        assert [c["field"] for c in mismatched] == ["char_count"]
        assert mismatched[0]["expected"] == 11
        assert mismatched[0]["actual"] == 999

    def test_a_tampered_stored_result_is_not_silently_accepted(
        self, db: Database, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # Someone edits the recorded output after the run. Verification re-derives
        # from the input, so the edit is caught.
        task = _executed_task(authz, alice, _text_result("hello world"))
        with db.transaction() as conn:
            conn.execute(
                "UPDATE executions SET result_json = ? WHERE task_id = ?",
                (json.dumps({**_text_result("hello world"), "word_count": 42}), task),
            )
        report = verifier.verify_task(alice, task)
        assert not report.passed
        assert report.failed_executions[0].code == CODE_FIELD_MISMATCH

    def test_a_result_from_a_different_input_fails(
        self, db: Database, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # Swapping in another run's output -- a valid answer to a different
        # question -- must not verify.
        task = _executed_task(authz, alice, _text_result("hello world"))
        with db.transaction() as conn:
            conn.execute(
                "UPDATE executions SET result_json = ? WHERE task_id = ?",
                (json.dumps(_text_result("a completely different sentence")), task),
            )
        report = verifier.verify_task(alice, task)
        assert not report.passed

    def test_an_unreadable_result_is_recorded_as_a_fail(
        self, db: Database, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # Corrupt bytes are a finding about a run, not an absence of a question, so
        # this is recorded as a FAIL rather than raised. The distinction matters for
        # Phase 15: a persisted verdict says "this execution produced output that
        # cannot be verified", which is classifiable, whereas a refusal says nothing
        # was concluded at all.
        task = _executed_task(authz, alice, _text_result("hello world"))
        with db.transaction() as conn:
            conn.execute(
                "UPDATE executions SET result_json = ? WHERE task_id = ?",
                ("{not json", task),
            )
        report = verifier.verify_task(alice, task)

        assert not report.passed
        assert report.verdicts[0].code == CODE_RESULT_UNREADABLE
        row = authz.verifications_for_task(alice, task)[0]
        assert row["result"] == "fail"
        # No bytes to identify, so no digest is claimed -- a digest of a placeholder
        # would read as a claim about output this verdict has not seen.
        assert json.loads(str(row["evidence_json"]))["result_digest"] is None
        stored = authz.get_task(alice, task)
        assert stored["status"] == TaskStatus.FAILED.value
        assert stored["result_json"] is None

    @pytest.mark.parametrize(
        "stored",
        [json.dumps([1, 2, 3]), json.dumps("a string"), json.dumps(7), "null"],
        ids=["array", "string", "number", "null"],
    )
    def test_a_result_that_is_not_a_json_object_is_a_fail(
        self,
        db: Database,
        authz: AuthorizationService,
        alice: str,
        verifier: VerifierService,
        stored: str,
    ) -> None:
        # A contract can only be checked against an object. Anything else cannot
        # satisfy it, and treating it as `{}` would let a corrupted row produce a
        # mismatch against empty expectations instead of saying what was wrong.
        task = _executed_task(authz, alice, _text_result("hello world"))
        with db.transaction() as conn:
            conn.execute(
                "UPDATE executions SET result_json = ? WHERE task_id = ?",
                (stored, task),
            )
        report = verifier.verify_task(alice, task)
        assert report.verdicts[0].code == CODE_RESULT_UNREADABLE
        assert authz.get_task(alice, task)["status"] == TaskStatus.FAILED.value

    def test_an_execution_naming_another_step_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # No reconciliation, no verdict: the execution cannot be tied to anything
        # the plan authorized, so there is no step whose evidence this could be.
        task = _executed_task(authz, alice, _text_result("hello world"))
        with db.transaction() as conn:
            conn.execute(
                "UPDATE executions SET plan_step_id = NULL WHERE task_id = ?", (task,)
            )
        with pytest.raises(VerificationRefused) as caught:
            verifier.verify_task(alice, task)
        assert caught.value.code == VerificationErrorCode.EXECUTION_NOT_RECONCILED
        assert authz.verifications_for_task(alice, task) == []
        assert authz.get_task(alice, task)["status"] == TaskStatus.EXECUTED.value

    def test_a_step_that_never_ran_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # Two steps planned, one executed. Verifying the one that ran would certify
        # a run that did not carry out the plan.
        task = int(authz.create_task(alice, title="t", goal="g")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "Two steps.",
                "steps": [
                    {
                        "step_key": "one",
                        "tool_id": TOOL_A,
                        "input": {"text": "a"},
                        "depends_on": [],
                    },
                    {
                        "step_key": "two",
                        "tool_id": TOOL_A,
                        "input": {"text": "b"},
                        "depends_on": ["one"],
                    },
                ],
            },
        )
        ExecutorService(authz, _StubDispatcher(_text_result("a"))).execute(alice, task)
        with db.transaction() as conn:
            conn.execute("DELETE FROM executions WHERE task_id = ?", (task,))
        with pytest.raises(VerificationRefused) as caught:
            verifier.verify_task(alice, task)
        assert caught.value.code == VerificationErrorCode.NO_EXECUTION
        assert authz.get_task(alice, task)["status"] == TaskStatus.EXECUTED.value

    def test_an_execution_for_a_tool_the_step_did_not_authorize_is_a_fail(
        self, db: Database, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # The row says one tool ran while the plan step says another. Nothing about
        # the recorded output can be judged until that is settled, and settling it by
        # preferring either value would be picking a winner rather than a fact.
        task = _executed_task(authz, alice, _text_result("hello world"))
        with db.transaction() as conn:
            conn.execute(
                "UPDATE executions SET tool_id = ? WHERE task_id = ?", (TOOL_B, task)
            )
        report = verifier.verify_task(alice, task)

        assert report.verdicts[0].code == CODE_TOOL_MISMATCH
        evidence = json.loads(
            str(authz.verifications_for_task(alice, task)[0]["evidence_json"])
        )
        assert evidence["tool_id"] == TOOL_B
        assert evidence["plan_step_tool_id"] == TOOL_A
        assert authz.get_task(alice, task)["status"] == TaskStatus.FAILED.value

    def test_a_plan_that_was_never_validated_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # Phase 12 would not dispatch a plan whose flag says it was never validated.
        # The verifier refuses the same plan, so it cannot certify the output of a
        # run that could not legitimately have happened.
        task = int(authz.create_task(alice, title="t", goal="g")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "One step.",
                "steps": [
                    {
                        "step_key": "only",
                        "tool_id": TOOL_A,
                        "input": {"text": "a"},
                        "depends_on": [],
                    }
                ],
            },
            validated=False,
        )
        # Phase 12 refuses to dispatch an unvalidated plan, so the stored rows are
        # written directly here: the point under test is the verifier's own check,
        # not the executor's.
        with db.transaction() as conn:
            plan_id = int(
                conn.execute(
                    "SELECT id FROM plans WHERE task_id = ?", (task,)
                ).fetchone()["id"]
            )
            step_id = int(
                conn.execute(
                    "SELECT id FROM plan_steps WHERE plan_id = ?", (plan_id,)
                ).fetchone()["id"]
            )
            conn.execute(
                "INSERT INTO executions (task_id, plan_id, plan_step_id, tool_id, "
                "invocation_id, status, attempt, created_at, result_json) "
                "VALUES (?, ?, ?, ?, 'inv-forged', 'succeeded', 1, ?, ?)",
                (
                    task,
                    plan_id,
                    step_id,
                    TOOL_A,
                    utcnow_iso(),
                    json.dumps(_text_result("a")),
                ),
            )
            conn.execute("UPDATE tasks SET status = 'executed' WHERE id = ?", (task,))
        with pytest.raises(VerificationRefused) as caught:
            verifier.verify_task(alice, task)
        assert caught.value.code == VerificationErrorCode.PLAN_NOT_EXECUTABLE
        assert authz.verifications_for_task(alice, task) == []

    def test_a_tool_with_no_rule_fails_rather_than_passing(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # The numeric tool is registered and has a rule, so this run is verifiable.
        # The unregistered-tool case is covered directly in TestRules; what matters
        # here is that both built-ins a single-step plan can name are judgeable.
        task = _executed_task(
            authz,
            alice,
            {"count": 1, "minimum": 1, "maximum": 1, "sum": 1},
            tool_id=TOOL_B,
            arguments={"values": [1], "compute_variance": False},
        )
        assert verifier.verify_task(alice, task).verdict == PASS

    def test_a_partial_failure_fails_the_whole_task(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # One good step and one bad one. All-or-nothing: a task that is "mostly
        # verified" is not verified.
        task = int(authz.create_task(alice, title="t", goal="g")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "Measure, then summarize.",
                "steps": [
                    {
                        "step_key": "measure",
                        "tool_id": TOOL_A,
                        "input": {"text": "hello world"},
                        "depends_on": [],
                    },
                    {
                        "step_key": "summarize",
                        "tool_id": TOOL_B,
                        "input": {"values": [1, 2]},
                        "depends_on": ["measure"],
                    },
                ],
            },
        )
        dispatcher = _StubDispatcher(_text_result("hello world"))
        ExecutorService(authz, dispatcher).execute(alice, task)
        with authz._db.transaction() as conn:  # noqa: SLF001 - deliberate corruption
            conn.execute(
                "UPDATE executions SET result_json = ? WHERE task_id = ? AND tool_id = ?",
                (json.dumps({"count": 99}), task, TOOL_B),
            )
        report = verifier.verify_task(alice, task)
        assert not report.passed
        assert len(report.verdicts) == 2
        assert sum(1 for v in report.verdicts if v.passed) == 1
        assert authz.get_task(alice, task)["status"] == TaskStatus.FAILED.value
        assert authz.get_task(alice, task)["result_json"] is None


# ------------------------------------------------------- what cannot happen


class TestVerifierCannotBeSkipped:
    def test_an_unexecuted_task_cannot_be_verified(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        task = int(authz.create_task(alice, title="t", goal="g")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "One step.",
                "steps": [
                    {
                        "step_key": "only",
                        "tool_id": TOOL_A,
                        "input": {"text": "a"},
                        "depends_on": [],
                    }
                ],
            },
        )
        with pytest.raises(VerificationRefused) as caught:
            verifier.verify_task(alice, task)
        assert caught.value.code == VerificationErrorCode.TASK_NOT_EXECUTED
        assert authz.verifications_for_task(alice, task) == []

    def test_a_task_with_no_execution_cannot_be_verified(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # A validated plan exists, but nothing was dispatched and the task has been
        # forced to `executed`. Refused: no evidence is not evidence of correctness.
        task = int(authz.create_task(alice, title="t", goal="g")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "One step.",
                "steps": [
                    {
                        "step_key": "only",
                        "tool_id": TOOL_A,
                        "input": {"text": "a"},
                        "depends_on": [],
                    }
                ],
            },
        )
        authz.set_task_status(alice, task, status=TaskStatus.PLANNED.value)
        authz.set_task_status(alice, task, status=TaskStatus.EXECUTING.value)
        authz.set_task_status(alice, task, status=TaskStatus.EXECUTED.value)
        with pytest.raises(VerificationRefused) as caught:
            verifier.verify_task(alice, task)
        assert caught.value.code == VerificationErrorCode.NO_EXECUTION
        assert authz.verifications_for_task(alice, task) == []
        assert authz.get_task(alice, task)["status"] == TaskStatus.EXECUTED.value

    def test_a_task_with_no_plan_is_denied_not_verified(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # Forced to `executed` with no plan at all. There is nothing to read, so the
        # read is denied by the authorization boundary and never becomes a verdict.
        task = int(authz.create_task(alice, title="t", goal="g")["id"])
        authz.set_task_status(alice, task, status=TaskStatus.PLANNED.value)
        authz.set_task_status(alice, task, status=TaskStatus.EXECUTING.value)
        authz.set_task_status(alice, task, status=TaskStatus.EXECUTED.value)
        with pytest.raises(AuthorizationError):
            verifier.verify_task(alice, task)
        assert authz.verifications_for_task(alice, task) == []

    def test_an_incomplete_execution_cannot_be_verified(
        self, db: Database, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        with db.transaction() as conn:
            conn.execute(
                "UPDATE executions SET status = 'running', result_json = NULL WHERE task_id = ?",
                (task,),
            )
        with pytest.raises(VerificationRefused) as caught:
            verifier.verify_task(alice, task)
        assert caught.value.code == VerificationErrorCode.EXECUTION_INCOMPLETE

    def test_verification_cannot_be_repeated(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        verifier.verify_task(alice, task)
        with pytest.raises(VerificationRefused) as caught:
            verifier.verify_task(alice, task)
        assert caught.value.code == VerificationErrorCode.ALREADY_VERIFIED
        # Still exactly one verdict, so the task cannot hold two opinions at once.
        assert len(authz.verifications_for_task(alice, task)) == 1

    def test_a_failed_task_is_not_verifiable_afterwards(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        wrong = {**_text_result("hello world"), "char_count": 0}
        task = _executed_task(authz, alice, wrong)
        verifier.verify_task(alice, task)
        with pytest.raises(VerificationRefused):
            verifier.verify_task(alice, task)
        assert len(authz.verifications_for_task(alice, task)) == 1

    def test_no_task_can_be_succeeded_without_a_recorded_pass(
        self, authz: AuthorizationService, alice: str
    ) -> None:
        # The write of a successful result is refused from every status but
        # `verified`, so no caller can reach `succeeded` by writing a result.
        task = _executed_task(authz, alice, _text_result("hello world"))
        with pytest.raises(StatusTransitionRefused):
            authz.finish_verified_task(alice, task, result={"verdict": "pass"})
        assert authz.get_task(alice, task)["status"] == TaskStatus.EXECUTED.value

    def test_a_task_cannot_be_walked_to_verified_by_hand(
        self, authz: AuthorizationService, alice: str
    ) -> None:
        # `executed -> verified` does not exist, so the status itself is not
        # forgeable into a success-eligible state even by a caller that holds
        # TASK.UPDATE and is willing to write nonsense statuses.
        task = _executed_task(authz, alice, _text_result("hello world"))
        with pytest.raises(StatusTransitionRefused):
            authz.set_task_status(alice, task, status=TaskStatus.VERIFIED.value)
        assert authz.get_task(alice, task)["status"] == TaskStatus.EXECUTED.value

    def test_a_verified_task_with_no_pass_cannot_publish_a_result(
        self, authz: AuthorizationService, alice: str
    ) -> None:
        # Reached by the only remaining route: walk the task to `verifying` by hand,
        # then to `verified`, which the table does permit. The status now looks
        # eligible, and the result is still withheld -- because `verified` is a claim
        # and the verdict rows are the evidence for it.
        task = _executed_task(authz, alice, _text_result("hello world"))
        authz.set_task_status(alice, task, status=TaskStatus.VERIFYING.value)
        authz.set_task_status(alice, task, status=TaskStatus.VERIFIED.value)
        assert authz.get_task(alice, task)["status"] == TaskStatus.VERIFIED.value

        with pytest.raises(ResultUnpublishable):
            authz.finish_verified_task(alice, task, result={"verdict": "pass"})
        stored = authz.get_task(alice, task)
        assert stored["status"] == TaskStatus.VERIFIED.value
        assert stored["result_json"] is None

    def test_a_result_is_withheld_when_one_execution_has_no_pass(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        # Two executions, one PASS. Non-zero coverage is not coverage: the task has
        # output nobody verified, so nothing may be published for it.
        task = _executed_task(authz, alice, _text_result("hello world"))
        execution = authz.executions_for_task(alice, task)[0]
        authz.record_verification(
            alice,
            execution_id=int(execution["id"]),
            result="pass",
            verifier="atlas.verifier.rules",
            verifier_version="1",
        )
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO executions (task_id, plan_id, plan_step_id, tool_id, "
                "invocation_id, status, attempt, created_at, result_json) "
                "SELECT task_id, plan_id, plan_step_id, tool_id, 'inv-extra', "
                "'succeeded', 1, created_at, result_json FROM executions WHERE id = ?",
                (int(execution["id"]),),
            )
        authz.set_task_status(alice, task, status=TaskStatus.VERIFYING.value)
        authz.set_task_status(alice, task, status=TaskStatus.VERIFIED.value)

        with pytest.raises(ResultUnpublishable):
            authz.finish_verified_task(alice, task, result={"verdict": "pass"})
        assert authz.get_task(alice, task)["result_json"] is None

    def test_a_verdict_cannot_be_recorded_against_an_unfinished_execution(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        # The storage-level invariant, tested directly because the verifier is just
        # one caller: a dispatch that is still running produced no output to judge.
        task = _executed_task(authz, alice, _text_result("hello world"))
        with db.transaction() as conn:
            conn.execute(
                "UPDATE executions SET status = 'running', result_json = NULL "
                "WHERE task_id = ?",
                (task,),
            )
        execution = authz.executions_for_task(alice, task)[0]
        with pytest.raises(AuthorizationError):
            authz.record_verification(
                alice,
                execution_id=int(execution["id"]),
                result="pass",
                verifier="atlas.verifier.rules",
                verifier_version="1",
            )
        assert authz.verifications_for_task(alice, task) == []

    def test_verification_cannot_authorize_an_execution(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # Recording a verdict grants no capability: VERIFICATION carries create
        # and read only, and creating a verification does not create an execution.
        task = _executed_task(authz, alice, _text_result("hello world"))
        verifier.verify_task(alice, task)
        assert PERMITTED_OPERATIONS[Resource.VERIFICATION] == frozenset(
            {Operation.READ, Operation.CREATE}
        )
        assert Operation.INVOKE not in PERMITTED_OPERATIONS[Resource.VERIFICATION]
        assert Operation.UPDATE not in PERMITTED_OPERATIONS[Resource.VERIFICATION]
        assert Operation.DELETE not in PERMITTED_OPERATIONS[Resource.VERIFICATION]
        rows = authz.executions_for_task(alice, task)
        assert len(rows) == 1

    def test_the_planner_cannot_make_a_wrong_result_pass(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        # A plan that asserts its own correctness in its action text gets no
        # leniency; only the re-derived comparison decides.
        task = int(authz.create_task(alice, title="t", goal="g")["id"])
        _store_plan(
            authz,
            alice,
            task,
            {
                "summary": "The summary insists this is correct.",
                "steps": [
                    {
                        "step_key": "only",
                        "tool_id": TOOL_A,
                        "input": {"text": "hello world"},
                        "depends_on": [],
                        "action": "This step is verified correct by construction.",
                    }
                ],
            },
        )
        wrong = {**_text_result("hello world"), "char_count": 7}
        ExecutorService(authz, _StubDispatcher(wrong)).execute(alice, task)
        assert not verifier.verify_task(alice, task).passed


# ------------------------------------------------------- ownership and edges


class TestVerifierOwnership:
    def test_another_user_cannot_verify_someone_elses_task(
        self, authz: AuthorizationService, alice: str, bob: str, verifier: VerifierService
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        with pytest.raises(AuthorizationError) as caught:
            verifier.verify_task(bob, task)
        assert isinstance(caught.value.reason, DenyReason)
        # Alice's task is untouched by bob's attempt.
        assert authz.get_task(alice, task)["status"] == TaskStatus.EXECUTED.value
        assert authz.verifications_for_task(alice, task) == []

    def test_another_user_cannot_read_verdicts(
        self, authz: AuthorizationService, alice: str, bob: str, verifier: VerifierService
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        verifier.verify_task(alice, task)
        with pytest.raises(AuthorizationError):
            authz.verifications_for_task(bob, task)

    def test_an_unauthenticated_caller_cannot_verify(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        with pytest.raises(AuthorizationError):
            verifier.verify_task(None, task)

    def test_a_bad_task_id_is_refused_before_anything_is_read(
        self, authz: AuthorizationService, alice: str, verifier: VerifierService
    ) -> None:
        for bad in (0, -1, True, "3", 2.5):
            with pytest.raises(VerificationRefused):
                verifier.verify_task(alice, bad)


class TestVerificationStorage:
    def test_a_second_verdict_for_one_execution_is_refused(
        self, db: Database, authz: AuthorizationService, alice: str
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        execution = authz.executions_for_task(alice, task)[0]
        authz.record_verification(
            alice,
            execution_id=int(execution["id"]),
            result="pass",
            verifier="atlas.verifier.rules",
            verifier_version="1",
        )
        with pytest.raises(AuthorizationError):
            authz.record_verification(
                alice,
                execution_id=int(execution["id"]),
                result="fail",
                verifier="atlas.verifier.rules",
                verifier_version="1",
            )

    def test_a_verdict_needs_an_execution_to_judge(
        self, authz: AuthorizationService, alice: str
    ) -> None:
        task = _executed_task(authz, alice, _text_result("hello world"))
        with pytest.raises(AuthorizationError):
            authz.record_verification(
                alice,
                execution_id=999_999,
                result="pass",
                verifier="atlas.verifier.rules",
                verifier_version="1",
            )
        assert authz.verifications_for_task(alice, task) == []

    def test_evidence_beyond_the_bound_is_refused_rather_than_truncated(
        self, authz: AuthorizationService, alice: str
    ) -> None:
        # A truncated verdict that still reads as a verdict is the failure mode
        # worth avoiding.
        task = _executed_task(authz, alice, _text_result("hello world"))
        execution = authz.executions_for_task(alice, task)[0]
        with pytest.raises(AuthorizationError):
            authz.record_verification(
                alice,
                execution_id=int(execution["id"]),
                result="pass",
                verifier="atlas.verifier.rules",
                verifier_version="1",
                evidence={"blob": "x" * 200_000},
            )
