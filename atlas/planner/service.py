"""The planner: goal in, validated plan out.

This is the orchestration and nothing else. Each step is owned by a module that
already knows how to do it correctly, and the planner's job is to run them in an
order where nothing untrusted is ever acted on:

1. Read the task through the authorization boundary, so the planner only ever
   holds a goal the caller owns.
2. Build the prompt from the frozen registry, so the model is offered only tools
   that exist.
3. Ask the local model once. There is no retry loop: a second attempt would mean
   a second, differently-shaped answer to the same question, and the stored
   ``model_id`` and digest describe one exchange.
4. Parse the reply under :mod:`atlas.planner.plan`'s bounds. Untrusted text in,
   a bounded document or a refusal out.
5. Validate against the registry. Findings, not exceptions.
6. Persist through the authorization boundary, recording the verdict. A plan is
   stored whether it validated or was rejected, because "the model proposed this
   and we refused it" is an answer the audit record has to be able to give.

The plan is *not* executed here, and nothing in this module can dispatch a tool.
Execution is Phase 12, and it must go through
:class:`~atlas.security.service.AuthorizationService` and
:class:`~atlas.tools.dispatch.ToolDispatcher` like any other path -- a plan is
proposal, never permission.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from atlas.config.settings import Settings
from atlas.planner.errors import PlanOutputInvalid, PlanRejected
from atlas.planner.model import LocalModelClient, ModelResponse
from atlas.planner.plan import PlanDocument, PlanStep
from atlas.planner.prompt import build_messages, parse_plan_text
from atlas.planner.validator import PlanValidator, ValidationReport
from atlas.security.service import AuthorizationService
from atlas.tools.registry import ToolRegistry, default_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanningOutcome:
    """The persisted plan row plus its validation verdict.

    ``plan`` is the stored row, so a caller reads ``validated``, ``status``,
    ``digest``, and ``model_id`` from storage rather than from a second in-memory
    copy that could disagree with what was written.
    """

    plan: dict[str, Any]
    validation: ValidationReport
    steps: tuple[PlanStep, ...]

    @property
    def executable(self) -> bool:
        """True only when validation passed. Execution checks this again."""

        return self.validation.valid and self.plan.get("validated") == 1


class PlannerService:
    """Turns an owned task's goal into a validated, persisted plan."""

    def __init__(
        self,
        authorization: AuthorizationService,
        *,
        settings: Settings,
        registry: ToolRegistry | None = None,
        model: LocalModelClient | None = None,
    ) -> None:
        self._authorization = authorization
        self._settings = settings
        self._registry = registry or default_registry()
        self._model = model or LocalModelClient(settings)
        self._validator = PlanValidator(
            self._registry,
            max_steps=settings.max_plan_steps,
            max_tool_calls=settings.max_tool_calls,
        )

    @property
    def model_id(self) -> str:
        """The model that will answer. Recorded on every plan this planner writes."""

        return self._model.model_id

    def plan_task(
        self,
        session_token: object,
        task_id: object,
        *,
        supersedes_plan_id: int | None = None,
        tool_ids: Sequence[str] | None = None,
    ) -> PlanningOutcome:
        """Produce and persist one plan for ``task_id``.

        Raises :class:`~atlas.planner.errors.PlanOutputInvalid` when the model is
        unreachable or its reply is not a plan at all -- in that case there is no
        document to record, so nothing is written.

        Raises :class:`~atlas.planner.errors.PlanRejected` when a plan *was*
        produced and refused, after the refusal has been persisted so the finding
        is inspectable. A caller that wants the rejected plan rather than the
        exception can read it back with ``plan_head``.
        """

        task = self._authorization.get_task(session_token, task_id)
        goal = str(task["goal"])
        messages = build_messages(
            goal=goal,
            registry=self._registry,
            max_steps=self._settings.max_plan_steps,
            max_tool_calls=self._settings.max_tool_calls,
            tool_ids=tool_ids,
        )
        response = self._model.complete(messages)
        document = self._parse(response)
        report = self._validator.validate(document)

        outcome = self._persist(
            session_token,
            task=task,
            document=document,
            report=report,
            model_id=response.model_id,
            supersedes_plan_id=supersedes_plan_id,
        )
        if not report.valid:
            logger.warning(
                "plan rejected task_id=%s model=%s findings=%s",
                task["id"],
                response.model_id,
                [finding.code for finding in report.findings],
            )
            raise PlanRejected(
                f"plan for task {task['id']} was rejected: "
                + "; ".join(finding.message for finding in report.findings[:3])
            )
        return outcome

    def _parse(self, response: ModelResponse) -> PlanDocument:
        try:
            payload = parse_plan_text(response.text)
            return PlanDocument.from_payload(
                payload, max_steps=self._settings.max_plan_steps
            )
        except ValueError as exc:
            raise PlanOutputInvalid(str(exc)) from exc

    def _persist(
        self,
        session_token: object,
        *,
        task: Mapping[str, Any],
        document: PlanDocument,
        report: ValidationReport,
        model_id: str,
        supersedes_plan_id: int | None,
    ) -> PlanningOutcome:
        rows = [
            {
                "step_key": step.step_key,
                "tool_id": step.tool_id,
                "input": step.input,
                "depends_on": list(step.depends_on),
                "produces_artifact_kind": step.produces_artifact_kind,
                "action": step.action,
            }
            for step in document.steps
        ]
        plan = self._authorization.create_plan(
            session_token,
            task_id=task["id"],
            plan_json=document.canonical_json(),
            digest=document.digest(),
            steps=rows,
            model_id=model_id,
            source="planner",
            validated=report.valid,
            validation_json=json.dumps(report.to_json(), ensure_ascii=True, sort_keys=True),
            supersedes_plan_id=supersedes_plan_id,
        )
        return PlanningOutcome(plan=plan, validation=report, steps=document.steps)
