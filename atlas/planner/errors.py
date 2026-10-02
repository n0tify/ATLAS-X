"""Planning failure taxonomy.

Planning fails in ways a caller must be able to tell apart, so each one has its
own class. The distinction that matters most is between a failure that means
"there is no local model" and a failure that means "the local model said
something we will not run": the first is an availability problem the operator
can fix by starting a daemon, the second is a refusal that no amount of retrying
will turn into a plan.

Three rules hold across this taxonomy:

* **No failure degrades into a plan.** There is no heuristic planner, no
  template fallback, and no "use the last plan" path. If the local model is
  unreachable, planning fails; a plan that did not come from the model would
  silently invalidate every provenance record that names the model.
* **Model output is not trusted.** :class:`PlanOutputInvalid` covers every way a
  reply fails to be a plan document. It is the expected outcome of an adversarial
  or merely incompetent model, not an internal error.
* **Validation findings are not exceptions.** A plan that parses but breaks a
  rule is reported, not raised, so the refusal can be persisted and explained.
  Only the inability to obtain a document at all is an exception.
"""

from __future__ import annotations


class PlanErrorCode:
    """Stable programmatic classifications for planning failures."""

    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    PLAN_REJECTED = "plan_rejected"


class PlanError(Exception):
    """Base class for every planning failure. Never an authorization failure."""

    code = PlanErrorCode.MODEL_OUTPUT_INVALID

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class ModelUnavailable(PlanError):
    """The local model endpoint could not be reached or refused the request.

    Planning fails rather than falling back to anything else. This is raised for
    a refused connection, a timeout, an error status, or a reply that is not the
    documented shape -- all of which mean "there is no usable local model here",
    which is an operator problem and not something to paper over.
    """

    code = PlanErrorCode.MODEL_UNAVAILABLE


class ModelTimeout(ModelUnavailable):
    """The local model did not answer within the configured bound.

    Separate from the parent because a timeout is a distinct operational
    symptom: the daemon is running and is not answering, rather than absent.
    """

    code = PlanErrorCode.MODEL_TIMEOUT


class PlanOutputInvalid(PlanError):
    """The model's reply is not a plan document this build will accept.

    The single most likely thing to happen, by design: the reply is untrusted
    input, it is parsed under the same bounds as any other payload, and anything
    it cannot state within those bounds is a refusal rather than a repair.
    """

    code = PlanErrorCode.MODEL_OUTPUT_INVALID


class PlanRejected(PlanError):
    """A plan document was produced but breaks a validation rule.

    Raised by the planner after the rejection has been persisted, so the caller
    can point at the stored finding rather than re-deriving it.
    """

    code = PlanErrorCode.PLAN_REJECTED
