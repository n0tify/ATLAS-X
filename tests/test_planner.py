"""Phase 11: the planner, the plan document, and the bounded local model adapter.

The tests are grouped by what each layer must refuse, because the planner's
whole job is refusing model output. Three layers are exercised separately:

* :mod:`atlas.planner.plan` -- structural bounds on untrusted JSON.
* :mod:`atlas.planner.validator` -- registry and graph checks.
* :mod:`atlas.planner.service` -- the end-to-end path, with the model stubbed.

The model is stubbed through :class:`ScriptedModel` rather than by running a real
daemon, so these tests are deterministic and do not need Ollama. The real daemon
is exercised separately by ``tests/test_planner_live.py`` when it is running.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

import pytest

from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.planner.errors import (
    ModelUnavailable,
    PlanOutputInvalid,
    PlanRejected,
)
from atlas.planner.model import LocalModelClient, ModelMessage, ModelResponse
from atlas.planner.plan import (
    MAX_ACTION_CHARS,
    MAX_STEP_INPUT_CHARS,
    MAX_SUMMARY_CHARS,
    PlanDocument,
)
from atlas.planner.prompt import build_messages, parse_plan_text
from atlas.planner.service import PlannerService
from atlas.planner.validator import FindingCode, PlanValidator
from atlas.security.errors import AuthorizationError
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.tools.registry import default_registry

PASSWORD = "correct horse battery staple"

TOOL_A = "text_statistics"
TOOL_B = "numeric_summary"


class ScriptedModel:
    """A local model stand-in that returns whatever a test dictates."""

    def __init__(self, reply: str | object, *, model_id: str = "stub-model:1b") -> None:
        self.model_id = model_id
        self._reply = reply
        self.calls: list[tuple[ModelMessage, ...]] = []

    def complete(self, messages: Sequence[ModelMessage]) -> ModelResponse:
        self.calls.append(tuple(messages))
        text = self._reply if isinstance(self._reply, str) else json.dumps(self._reply)
        return ModelResponse(text=text, model_id=self.model_id)


@pytest.fixture
def authz(db: Database, auth: AuthService) -> AuthorizationService:
    return AuthorizationService(db, auth)


@pytest.fixture
def alice_token(auth: AuthService) -> str:
    auth.register("alice", PASSWORD)
    return str(auth.login("alice", PASSWORD)["token"])


@pytest.fixture
def bob_token(auth: AuthService) -> str:
    auth.register("bobby", PASSWORD)
    return str(auth.login("bobby", PASSWORD)["token"])


@pytest.fixture
def task_id(authz: AuthorizationService, alice_token: str) -> int:
    return int(authz.create_task(alice_token, title="t", goal="Summarize the text")["id"])


@pytest.fixture
def settings() -> Settings:
    return Settings()


def _planner(
    authz: AuthorizationService, settings: Settings, reply: str | object
) -> tuple[PlannerService, ScriptedModel]:
    model = ScriptedModel(reply)
    return PlannerService(authz, settings=settings, model=model), model  # type: ignore[arg-type]


def _good_plan() -> dict[str, Any]:
    return {
        "summary": "Measure the text and then summarize the numbers.",
        "steps": [
            {
                "step_key": "measure",
                "tool_id": TOOL_A,
                "input": {"text": "hello world"},
                "depends_on": [],
                "action": "Measure word statistics for the supplied text.",
            },
            {
                "step_key": "summarize",
                "tool_id": TOOL_B,
                "input": {"values": [1, 2, 3]},
                "depends_on": ["measure"],
                "produces_artifact_kind": "numeric_summary",
                "action": "Summarize the measured numbers.",
            },
        ],
    }


# ------------------------------------------------------- plan document bounds


class TestPlanDocument:
    def test_a_well_formed_document_carries_its_steps_in_order(self) -> None:
        document = PlanDocument.from_payload(_good_plan(), max_steps=10)
        assert [step.step_key for step in document.steps] == ["measure", "summarize"]
        assert document.steps[1].depends_on == ("measure",)
        # Position is assigned by list order, never by the model.
        assert [step.position for step in document.steps] == [0, 1]

    def test_a_canonical_document_can_be_parsed_back(self) -> None:
        # ``plans.plan_json`` stores the canonical bytes, so a stored plan has to
        # be re-readable by the same parser that accepted the model's reply.
        # Found the hard way, against a real daemon: the canonical form emitted
        # ``position``, which the parser rejects because a model may not set it.
        document = PlanDocument.from_payload(_good_plan(), max_steps=10)
        round_tripped = PlanDocument.from_payload(
            json.loads(document.canonical_json()), max_steps=10
        )
        assert round_tripped.canonical_json() == document.canonical_json()
        assert round_tripped.digest() == document.digest()
        assert [step.step_key for step in round_tripped.steps] == [
            step.step_key for step in document.steps
        ]

    def test_a_model_may_not_choose_a_position(self) -> None:
        payload = _good_plan()
        payload["steps"][0]["position"] = 99
        with pytest.raises(PlanOutputInvalid, match="unknown fields"):
            PlanDocument.from_payload(payload, max_steps=10)
        # ...and position still follows the list order.
        document = PlanDocument.from_payload(_good_plan(), max_steps=10)
        assert [step.position for step in document.steps] == [0, 1]

    def test_the_digest_ignores_json_formatting(self) -> None:
        compact = PlanDocument.from_payload(_good_plan(), max_steps=10)
        # The same plan, written with different whitespace and with every object's
        # keys in a different order. This is the property ``sort_keys`` exists for,
        # and it is what makes two daemons that format differently agree.
        reformatted = json.dumps(
            {
                "steps": [
                    {
                        "depends_on": [],
                        "action": "Measure word statistics for the supplied text.",
                        "input": {"text": "hello world"},
                        "tool_id": TOOL_A,
                        "step_key": "measure",
                    },
                    {
                        "step_key": "summarize",
                        "tool_id": TOOL_B,
                        "input": {"values": [1, 2, 3]},
                        "produces_artifact_kind": "numeric_summary",
                        "depends_on": ["measure"],
                        "action": "Summarize the measured numbers.",
                    },
                ],
                "summary": "Measure the text and then summarize the numbers.",
            },
            indent=4,
            sort_keys=False,
        )
        assert (
            PlanDocument.from_payload(json.loads(reformatted), max_steps=10).digest()
            == compact.digest()
        )

    def test_reordering_independent_steps_changes_the_digest(self) -> None:
        # Position is assigned by list order and is part of what the plan means,
        # because it decides the order independent steps run in. So a reordering
        # is a different plan and must not collide.
        forward = PlanDocument.from_payload(_good_plan(), max_steps=10)
        swapped = _good_plan()
        swapped["steps"] = list(reversed(swapped["steps"]))
        reversed_plan = PlanDocument.from_payload(swapped, max_steps=10)
        assert reversed_plan.digest() != forward.digest()

    def test_the_default_configuration_can_render_a_whole_registry_prompt(
        self,
    ) -> None:
        # A default prompt ceiling below the size of the real prompt would mean
        # ATLAS-X cannot plan a task with its own tools without configuration
        # changes, so the bound is checked against the real catalogue.
        messages = build_messages(
            goal="g", registry=default_registry(), max_steps=10, max_tool_calls=12
        )
        total = sum(len(message.content) for message in messages)
        assert total <= Settings().model_max_prompt_chars

    def test_the_digest_changes_when_any_step_changes(self) -> None:
        first = PlanDocument.from_payload(_good_plan(), max_steps=10)
        altered = _good_plan()
        altered["steps"][0]["input"] = {"text": "hello worlds"}
        assert PlanDocument.from_payload(altered, max_steps=10).digest() != first.digest()

    def test_the_digest_is_a_usable_content_address(self) -> None:
        digest = PlanDocument.from_payload(_good_plan(), max_steps=10).digest()
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64

    @pytest.mark.parametrize(
        ("mutate", "detail"),
        [
            pytest.param(lambda p: p.update(steps=[]), "at least one step", id="no_steps"),
            pytest.param(lambda p: p.pop("summary"), "summary", id="no_summary"),
            pytest.param(lambda p: p.update(summary=""), "summary", id="blank_summary"),
            pytest.param(
                lambda p: p.update(summary="x" * (MAX_SUMMARY_CHARS + 1)),
                "longer than",
                id="summary_too_long",
            ),
            pytest.param(
                lambda p: p.update(steps="not a list"),
                "must be an array",
                id="steps_str",
            ),
            pytest.param(lambda p: p.update(extra=1), "unknown fields", id="unknown_plan_field"),
            pytest.param(
                lambda p: p["steps"][0].update(tool_id=""), "must name a tool", id="no_tool_id"
            ),
            pytest.param(
                lambda p: p["steps"][0].update(step_key="Not Snake"),
                "not lowercase snake_case",
                id="bad_step_key",
            ),
            pytest.param(
                lambda p: p["steps"][0].update(depends_on=["measure"]),
                "depends on itself",
                id="self_dependency",
            ),
            pytest.param(
                lambda p: p["steps"][0].update(depends_on=[7]),
                "holds a non-step-key",
                id="non_string_dependency",
            ),
            pytest.param(
                lambda p: p["steps"][0].update(depends_on="measure"),
                "must be an array of step keys",
                id="dependency_str",
            ),
            pytest.param(
                lambda p: p["steps"][0].update(nonsense=1),
                "unknown fields",
                id="unknown_step_field",
            ),
            pytest.param(
                lambda p: p["steps"][0].update(produces_artifact_kind=""),
                "non-empty string or absent",
                id="blank_artifact_kind",
            ),
            pytest.param(
                lambda p: p["steps"][0].update(action="   "),
                "non-empty string when present",
                id="blank_action",
            ),
            pytest.param(
                lambda p: p["steps"][0].update(action="x" * (MAX_ACTION_CHARS + 1)),
                "is longer than",
                id="action_too_long",
            ),
            pytest.param(
                lambda p: p["steps"][0].update(
                    input={"text": "x" * (MAX_STEP_INPUT_CHARS + 1)}
                ),
                "is larger than",
                id="input_too_large",
            ),
            pytest.param(
                lambda p: p["steps"].append(dict(p["steps"][0])),
                "duplicate step_key",
                id="duplicate_step_key",
            ),
        ],
    )
    def test_a_malformed_plan_is_refused(self, mutate: Any, detail: str) -> None:
        payload = _good_plan()
        mutate(payload)
        with pytest.raises(PlanOutputInvalid) as caught:
            PlanDocument.from_payload(payload, max_steps=10)
        assert detail in str(caught.value)

    def test_too_many_steps_is_refused_at_the_configured_ceiling(self) -> None:
        payload = {
            "summary": "s",
            "steps": [
                {"step_key": f"s{i}", "tool_id": TOOL_A, "input": {"text": "t"}}
                for i in range(4)
            ],
        }
        with pytest.raises(PlanOutputInvalid, match="at most 3 allowed"):
            PlanDocument.from_payload(payload, max_steps=3)

    def test_deeply_nested_input_is_refused(self) -> None:
        payload = _good_plan()
        nested: dict[str, Any] = {"leaf": 1}
        for _ in range(12):
            nested = {"child": nested}
        payload["steps"][0]["input"] = nested
        with pytest.raises(PlanOutputInvalid, match="nests deeper"):
            PlanDocument.from_payload(payload, max_steps=10)

    def test_a_non_mapping_plan_is_refused(self) -> None:
        with pytest.raises(PlanOutputInvalid, match="must be a JSON object"):
            PlanDocument.from_payload([1, 2, 3], max_steps=10)


# --------------------------------------------------------------- the validator


class TestPlanValidator:
    @pytest.fixture
    def validator(self) -> PlanValidator:
        return PlanValidator(default_registry(), max_steps=10, max_tool_calls=12)

    def _document(self, payload: Mapping[str, Any]) -> PlanDocument:
        return PlanDocument.from_payload(payload, max_steps=10)

    def test_a_good_plan_validates_and_yields_a_dependency_order(
        self, validator: PlanValidator
    ) -> None:
        report = validator.validate(self._document(_good_plan()))
        assert report.valid
        assert report.order == ("measure", "summarize")
        assert report.tool_calls == 2

    def test_an_unregistered_tool_is_refused_with_no_substitute(
        self, validator: PlanValidator
    ) -> None:
        payload = _good_plan()
        payload["steps"][0]["tool_id"] = "read_file"
        report = validator.validate(self._document(payload))
        assert not report.valid
        assert [f.code for f in report.findings] == [FindingCode.UNKNOWN_TOOL]
        assert report.order == ()

    def test_a_malformed_tool_id_is_refused(self, validator: PlanValidator) -> None:
        payload = _good_plan()
        payload["steps"][0]["tool_id"] = "../../etc/passwd"
        report = validator.validate(self._document(payload))
        assert not report.valid
        assert report.findings[0].code == FindingCode.UNKNOWN_TOOL

    def test_input_that_breaks_a_tool_schema_is_refused(self, validator: PlanValidator) -> None:
        payload = _good_plan()
        # ``text_statistics`` requires a string ``text``; a number is not one.
        payload["steps"][0]["input"] = {"text": 42}
        report = validator.validate(self._document(payload))
        assert not report.valid
        assert report.findings[0].code == FindingCode.INVALID_TOOL_INPUT

    def test_an_undeclared_input_field_is_refused(self, validator: PlanValidator) -> None:
        payload = _good_plan()
        payload["steps"][0]["input"] = {"text": "hi", "surprise": True}
        report = validator.validate(self._document(payload))
        assert not report.valid
        assert report.findings[0].code == FindingCode.INVALID_TOOL_INPUT

    def test_a_dependency_on_an_absent_step_is_refused(self, validator: PlanValidator) -> None:
        payload = _good_plan()
        payload["steps"][0]["depends_on"] = ["not_a_step"]
        report = validator.validate(self._document(payload))
        assert not report.valid
        assert report.findings[0].code == FindingCode.UNKNOWN_DEPENDENCY

    def test_a_dependency_cycle_is_refused(self, validator: PlanValidator) -> None:
        payload = {
            "summary": "s",
            "steps": [
                {"step_key": "a", "tool_id": TOOL_A, "input": {"text": "t"}, "depends_on": ["c"]},
                {"step_key": "b", "tool_id": TOOL_A, "input": {"text": "t"}, "depends_on": ["a"]},
                {"step_key": "c", "tool_id": TOOL_A, "input": {"text": "t"}, "depends_on": ["b"]},
            ],
        }
        report = validator.validate(self._document(payload))
        assert not report.valid
        assert [f.code for f in report.findings] == [FindingCode.DEPENDENCY_CYCLE]
        assert "->" in report.findings[0].message

    def test_a_plan_over_the_step_ceiling_is_refused(self) -> None:
        validator = PlanValidator(default_registry(), max_steps=1, max_tool_calls=12)
        report = validator.validate(self._document(_good_plan()))
        assert not report.valid
        assert report.findings[0].code == FindingCode.TOO_MANY_STEPS

    def test_a_plan_over_the_tool_call_ceiling_is_refused(self) -> None:
        validator = PlanValidator(default_registry(), max_steps=10, max_tool_calls=1)
        report = validator.validate(self._document(_good_plan()))
        assert not report.valid
        assert report.findings[0].code == FindingCode.TOO_MANY_STEPS

    def test_independent_steps_keep_the_models_own_order(self, validator: PlanValidator) -> None:
        payload = {
            "summary": "s",
            "steps": [
                {"step_key": "zeta", "tool_id": TOOL_A, "input": {"text": "t"}},
                {"step_key": "alpha", "tool_id": TOOL_A, "input": {"text": "t"}},
            ],
        }
        report = validator.validate(self._document(payload))
        assert report.valid
        assert report.order == ("zeta", "alpha")

    def test_findings_serialize_for_storage(self, validator: PlanValidator) -> None:
        payload = _good_plan()
        payload["steps"][0]["tool_id"] = "read_file"
        stored = validator.validate(self._document(payload)).to_json()
        assert json.loads(json.dumps(stored))["valid"] is False
        assert stored["findings"][0]["step_key"] == "measure"


# ---------------------------------------------------------------- the prompt


class TestPrompt:
    def test_the_catalogue_comes_from_the_registry_and_names_no_other_tool(
        self,
    ) -> None:
        registry = default_registry()
        messages = build_messages(
            goal="do a thing", registry=registry, max_steps=10, max_tool_calls=12
        )
        system = messages[0].content
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        for tool_id in registry.capabilities():
            assert f'"{tool_id}"' in system
        # A tool that does not exist must not be advertised, because the model
        # would plan against a capability ATLAS-X does not have.
        assert '"read_file"' not in system
        assert '"exec"' not in system

    def test_the_catalogue_carries_the_declared_schemas(self) -> None:
        messages = build_messages(
            goal="g", registry=default_registry(), max_steps=10, max_tool_calls=12
        )
        assert '"input_schema"' in messages[0].content
        assert '"maxLength"' in messages[0].content

    def test_narrowing_the_catalogue_removes_the_others(self) -> None:
        messages = build_messages(
            goal="g",
            registry=default_registry(),
            max_steps=10,
            max_tool_calls=12,
            tool_ids=[TOOL_A],
        )
        assert f'"{TOOL_A}"' in messages[0].content
        assert f'"{TOOL_B}"' not in messages[0].content

    def test_an_empty_catalogue_says_so_instead_of_inviting_invention(self) -> None:
        messages = build_messages(
            goal="g", registry=default_registry(), max_steps=10, max_tool_calls=12, tool_ids=[]
        )
        assert "no tools are available" in messages[0].content

    @pytest.mark.parametrize(
        "reply",
        [
            "",
            "   ",
            "I cannot help with that.",
            '{"summary": "s", "steps": [',
            "[1, 2, 3]",
            '"just a string"',
            '{"summary": "s", "steps": []} {"summary": "t", "steps": []}',
        ],
    )
    def test_a_reply_that_is_not_one_json_object_is_refused(self, reply: str) -> None:
        with pytest.raises(ValueError):
            parse_plan_text(reply)

    @pytest.mark.parametrize(
        "reply",
        [
            '```json\n{"summary": "s", "steps": [{"tool_id": "x"}]}\n```',
            '```\n{"summary": "s", "steps": [{"tool_id": "x"}]}\n```',
        ],
    )
    def test_a_bare_fenced_object_is_accepted(self, reply: str) -> None:
        assert parse_plan_text(reply)["summary"] == "s"

    def test_an_unterminated_fence_is_refused_rather_than_truncated(self) -> None:
        with pytest.raises(ValueError):
            parse_plan_text('```json\n{"summary": "s", "steps": []}')


# ------------------------------------------------------------ the model adapter


class TestLocalModelClient:
    def test_a_non_loopback_endpoint_is_refused_at_construction(self) -> None:
        # Settings refuses it first; this is the check at the socket.
        with pytest.raises(ValueError):
            LocalModelClient(Settings(model_base_url="http://example.com:11434"))  # type: ignore[call-arg]

    def test_an_https_endpoint_is_refused_because_no_local_daemon_uses_it(self) -> None:
        with pytest.raises(ValueError):
            LocalModelClient(Settings(model_base_url="https://127.0.0.1:11434"))  # type: ignore[call-arg]

    def test_a_message_with_an_unknown_role_is_refused(self) -> None:
        with pytest.raises(ValueError, match="role must be one of"):
            ModelMessage(role="system_prompt_injection", content="hi")

    def test_an_empty_transcript_is_refused(self) -> None:
        client = LocalModelClient(Settings())
        with pytest.raises(ValueError, match="at least one message"):
            client.complete([])

    def test_an_oversized_prompt_is_refused_before_it_is_sent(self) -> None:
        client = LocalModelClient(Settings(model_max_prompt_chars=100))
        with pytest.raises(ValueError, match="at most 100 allowed"):
            client.complete([ModelMessage(role="user", content="x" * 200)])

    def test_an_unreachable_daemon_fails_rather_than_degrading(self) -> None:
        # Port 1 on loopback has nothing listening, so this exercises the real
        # failure path: no template planner, no cached plan, no exception-free
        # success.
        client = LocalModelClient(Settings(model_base_url="http://127.0.0.1:1"))  # type: ignore[call-arg]
        with pytest.raises(ModelUnavailable):
            client.complete([ModelMessage(role="user", content="hello")])


# ------------------------------------------------------------------- end to end


class TestPlannerService:
    def test_a_valid_plan_is_persisted_with_its_verdict_and_model(
        self, authz: AuthorizationService, settings: Settings, task_id: int, alice_token: str
    ) -> None:
        planner, model = _planner(authz, settings, _good_plan())
        outcome = planner.plan_task(alice_token, task_id)

        assert outcome.executable
        assert outcome.plan["validated"] == 1
        assert outcome.plan["status"] == "validated"
        assert outcome.plan["source"] == "planner"
        assert outcome.plan["model_id"] == "stub-model:1b"
        assert outcome.plan["digest"].startswith("sha256:")
        assert json.loads(str(outcome.plan["plan_json"]))["steps"][0]["step_key"] == "measure"

    def test_the_stored_steps_match_the_document(
        self, authz: AuthorizationService, settings: Settings, task_id: int, alice_token: str
    ) -> None:
        planner, _ = _planner(authz, settings, _good_plan())
        outcome = planner.plan_task(alice_token, task_id)
        rows = authz.plan_steps(alice_token, outcome.plan["id"])

        assert [row["step_key"] for row in rows] == ["measure", "summarize"]
        assert [row["position"] for row in rows] == [0, 1]
        assert rows[0]["tool_id"] == TOOL_A
        assert json.loads(str(rows[1]["depends_on_json"])) == ["measure"]
        assert rows[1]["produces_artifact_kind"] == "numeric_summary"
        # The v2 free-text column is left null: ``tool_id`` supersedes it and
        # copying the id into both would let them disagree.
        assert rows[0]["tool_name"] is None
        assert rows[0]["action"] == "Measure word statistics for the supplied text."

    def test_the_model_is_asked_exactly_once(
        self, authz: AuthorizationService, settings: Settings, task_id: int, alice_token: str
    ) -> None:
        planner, model = _planner(authz, settings, _good_plan())
        planner.plan_task(alice_token, task_id)
        assert len(model.calls) == 1
        goal = "Summarize the text"
        assert goal in model.calls[0][1].content

    def test_a_plan_naming_an_unregistered_tool_is_persisted_as_rejected(
        self, authz: AuthorizationService, settings: Settings, task_id: int, alice_token: str
    ) -> None:
        payload = _good_plan()
        payload["steps"][0]["tool_id"] = "read_file"
        planner, _ = _planner(authz, settings, payload)

        with pytest.raises(PlanRejected):
            planner.plan_task(alice_token, task_id)

        head = authz.plan_head(alice_token, task_id)
        assert head["validated"] == 0
        assert head["status"] == "rejected"
        findings = json.loads(str(head["validation_json"]))
        assert findings["valid"] is False
        assert findings["findings"][0]["code"] == FindingCode.UNKNOWN_TOOL

    def test_a_reply_that_is_not_a_plan_persists_nothing(
        self, authz: AuthorizationService, settings: Settings, task_id: int, alice_token: str
    ) -> None:
        planner, _ = _planner(authz, settings, "I'm sorry, I can't do that.")
        with pytest.raises(PlanOutputInvalid):
            planner.plan_task(alice_token, task_id)
        with pytest.raises(AuthorizationError):
            authz.plan_head(alice_token, task_id)

    def test_planning_another_users_task_is_denied(
        self,
        authz: AuthorizationService,
        settings: Settings,
        task_id: int,
        bob_token: str,
    ) -> None:
        planner, model = _planner(authz, settings, _good_plan())
        with pytest.raises(AuthorizationError):
            planner.plan_task(bob_token, task_id)
        # The goal was never read and the model was never asked.
        assert model.calls == []

    def test_an_invalid_session_is_denied_before_the_model_is_asked(
        self, authz: AuthorizationService, settings: Settings, task_id: int
    ) -> None:
        planner, model = _planner(authz, settings, _good_plan())
        with pytest.raises(AuthorizationError):
            planner.plan_task("not-a-token", task_id)
        assert model.calls == []

    def test_a_revision_chains_onto_the_previous_plan(
        self, authz: AuthorizationService, settings: Settings, task_id: int, alice_token: str
    ) -> None:
        planner, _ = _planner(authz, settings, _good_plan())
        first = planner.plan_task(alice_token, task_id)

        payload = _good_plan()
        payload["steps"] = payload["steps"][:1]
        revised, _ = _planner(authz, settings, payload)
        second = revised.plan_task(alice_token, task_id, supersedes_plan_id=first.plan["id"])

        assert second.plan["supersedes_plan_id"] == first.plan["id"]
        # The head is the plan nothing supersedes, so the first plan is still
        # readable rather than overwritten.
        assert authz.plan_head(alice_token, task_id)["id"] == second.plan["id"]

    def test_a_revision_cannot_chain_across_tasks(
        self,
        authz: AuthorizationService,
        settings: Settings,
        task_id: int,
        alice_token: str,
    ) -> None:
        planner, _ = _planner(authz, settings, _good_plan())
        first = planner.plan_task(alice_token, task_id)
        other = int(authz.create_task(alice_token, title="t2", goal="g")["id"])

        revised, _ = _planner(authz, settings, _good_plan())
        with pytest.raises(AuthorizationError):
            revised.plan_task(alice_token, other, supersedes_plan_id=first.plan["id"])

    def test_a_revision_cannot_chain_onto_another_users_plan(
        self,
        authz: AuthorizationService,
        settings: Settings,
        alice_token: str,
        bob_token: str,
    ) -> None:
        alice_task = int(authz.create_task(alice_token, title="a", goal="g")["id"])
        bob_task = int(authz.create_task(bob_token, title="b", goal="g")["id"])
        planner, _ = _planner(authz, settings, _good_plan())
        bob_plan = planner.plan_task(bob_token, bob_task)

        revised, _ = _planner(authz, settings, _good_plan())
        with pytest.raises(AuthorizationError):
            revised.plan_task(alice_token, alice_task, supersedes_plan_id=bob_plan.plan["id"])

    def test_plan_steps_of_another_users_plan_are_denied(
        self,
        authz: AuthorizationService,
        settings: Settings,
        alice_token: str,
        bob_token: str,
    ) -> None:
        bob_task = int(authz.create_task(bob_token, title="b", goal="g")["id"])
        planner, _ = _planner(authz, settings, _good_plan())
        bob_plan = planner.plan_task(bob_token, bob_task)
        with pytest.raises(AuthorizationError):
            authz.plan_steps(alice_token, bob_plan.plan["id"])


# -------------------------------------------------- the local model is optional


class TestModelAvailability:
    def test_planning_without_a_daemon_fails_closed(
        self, authz: AuthorizationService, task_id: int, alice_token: str
    ) -> None:
        settings = Settings(model_base_url="http://127.0.0.1:1")  # type: ignore[call-arg]
        planner = PlannerService(authz, settings=settings)
        # No fallback planner exists, so an absent daemon is a failure and nothing
        # is written -- which is the only honest outcome, since any plan produced
        # here would not have come from a model.
        with pytest.raises(ModelUnavailable):
            planner.plan_task(alice_token, task_id)
        with pytest.raises(AuthorizationError):
            authz.plan_head(alice_token, task_id)
