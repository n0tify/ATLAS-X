"""The bounded local model adapter.

One HTTP call to a model daemon on loopback, with every dimension bounded: the
prompt length, the request body, the reply length, and the wall-clock time. The
reply is a string of untrusted text and nothing else -- it is handed straight to
:mod:`atlas.planner.plan`, which decides whether it is a plan.

Design decisions that are constraints rather than preferences:

* **Loopback only, plain HTTP, no credentials.** The requirement is a model on
  this machine. :class:`~atlas.config.settings.Settings` refuses a non-loopback
  ``model_base_url`` at validation time, and this module re-checks the parsed host
  rather than trusting that the setting was already validated.
* **No streaming.** A streamed reply has no end, and "the first N bytes of a
  model reply" is not a plan. Asking for a single bounded JSON body means an
  over-long reply is a detectable failure instead of a silent truncation.
* **The reply is bounded by reading, not by trusting ``Content-Length``.** The
  read stops after ``max_response_bytes`` and the attempt fails, so a daemon that
  reports a small length and then streams more cannot fill memory.
* **No fallback of any kind.** If the daemon is absent, slow, or wrong, this
  raises. There is no template planner and no cached-plan path, because a plan
  that did not come from the model would make ``plans.model_id`` false and the
  H1 ablation meaningless.
* **No cloud provider, no API key, no telemetry field.** Nothing in the request
  identifies ATLAS-X, and the URL is the only thing that leaves this function.

``urllib`` is used from the standard library so that talking to a local model
does not add a dependency to a project whose whole premise is that the tool
surface stays small and auditable.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from atlas.config.settings import Settings
from atlas.planner.errors import ModelTimeout, ModelUnavailable, PlanOutputInvalid

#: Roles the adapter accepts in a request. Anything else is refused here rather
#: than forwarded, so a caller cannot put an unrecognized role in the transcript.
ALLOWED_ROLES = frozenset({"system", "user"})

MAX_MESSAGES = 8
MAX_CONTENT_CHARS = 64_000
MAX_REQUEST_BYTES = 512 * 1024
#: What the model is allowed to generate. Bounded because a plan is at most
#: ``max_plan_steps`` steps and a longer answer cannot be a longer plan.
MAX_COMPLETION_TOKENS = 2_048
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class ModelMessage:
    """One turn of the conversation. Role is validated at construction."""

    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in ALLOWED_ROLES:
            raise ValueError(f"role must be one of {sorted(ALLOWED_ROLES)}, got {self.role!r}")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("message content must be a non-empty string")
        if len(self.content) > MAX_CONTENT_CHARS:
            raise ValueError(f"message content is longer than {MAX_CONTENT_CHARS} characters")


@dataclass(frozen=True)
class ModelResponse:
    """A bounded reply, plus the identifier of the model that produced it."""

    text: str
    model_id: str


class LocalModelClient:
    """A bounded client for a local model daemon."""

    def __init__(self, settings: Settings) -> None:
        self._url = f"{settings.model_base_url}/api/chat"
        self._model_name = settings.model_name
        self._timeout = settings.model_timeout_seconds
        self._max_prompt_chars = settings.model_max_prompt_chars
        self._max_response_bytes = settings.model_max_response_bytes
        self._check_loopback(settings.model_base_url)

    @staticmethod
    def _check_loopback(base_url: str) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "http" or parts.hostname not in LOOPBACK_HOSTS:
            # Belt and braces against the settings validator: this module is the
            # one that actually opens the socket, so it holds the check.
            raise ValueError(f"model endpoint must be loopback http, got {base_url!r}")

    @property
    def model_id(self) -> str:
        return self._model_name

    def complete(self, messages: Sequence[ModelMessage]) -> ModelResponse:
        """Ask the local model for a plan. Raises rather than degrading."""

        if not messages:
            raise ValueError("at least one message is required")
        if len(messages) > MAX_MESSAGES:
            raise ValueError(f"at most {MAX_MESSAGES} messages are allowed")
        prompt_chars = sum(len(message.content) for message in messages)
        if prompt_chars > self._max_prompt_chars:
            # Refused locally rather than sent: an over-long prompt is a bug in the
            # planner, and posting it would spend the local model's memory on it.
            raise ValueError(
                f"prompt is {prompt_chars} characters, at most {self._max_prompt_chars} allowed"
            )

        body = self._request_body(messages)
        return self._post(body)

    def _request_body(self, messages: Sequence[ModelMessage]) -> bytes:
        payload: Mapping[str, Any] = {
            "model": self._model_name,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            # Constrained decoding where the daemon supports it, so a reply that is
            # not JSON cannot be produced in the first place. The parser still
            # refuses non-JSON, because a daemon may ignore this.
            "format": "json",
            "stream": False,
            "options": {
                # Determinism is what makes a plan's digest comparable across runs,
                # which is what H1 depends on.
                "temperature": 0,
                "top_p": 1,
                "seed": 0,
                "num_predict": MAX_COMPLETION_TOKENS,
            },
        }
        encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError(f"request body is larger than {MAX_REQUEST_BYTES} bytes")
        return encoded

    def _post(self, body: bytes) -> ModelResponse:
        request = urllib.request.Request(  # noqa: S310 - loopback http, checked above
            self._url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                raw = response.read(self._max_response_bytes + 1)
        except socket.timeout as exc:
            raise ModelTimeout(
                f"local model did not answer within {self._timeout}s"
            ) from exc
        except urllib.error.HTTPError as exc:
            raise ModelUnavailable(
                f"local model refused the request with status {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.timeout):
                raise ModelTimeout(f"local model did not answer within {self._timeout}s") from exc
            raise ModelUnavailable(f"local model endpoint is unreachable: {reason}") from exc
        except OSError as exc:
            raise ModelUnavailable(f"local model endpoint is unreachable: {exc}") from exc

        if len(raw) > self._max_response_bytes:
            # The reply was cut off, so what was read is not the whole answer.
            # Returning it would be inventing a plan.
            raise PlanOutputInvalid(
                f"model reply exceeded {self._max_response_bytes} bytes"
            )
        return self._parse(raw)

    def _parse(self, raw: bytes) -> ModelResponse:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelUnavailable("local model returned a body that is not JSON") from exc
        if not isinstance(payload, Mapping):
            raise ModelUnavailable("local model returned a JSON value that is not an object")
        message = payload.get("message")
        if not isinstance(message, Mapping):
            raise ModelUnavailable("local model response carries no 'message' object")
        content = message.get("content")
        if not isinstance(content, str):
            raise ModelUnavailable("local model message carries no string 'content'")
        model_id = payload.get("model")
        # The daemon's own echoed name is recorded when it is a usable one, and
        # the configured name is recorded otherwise, so ``plans.model_id`` is never
        # empty and never claims more than the daemon said.
        resolved = model_id.strip() if isinstance(model_id, str) and model_id.strip() else ""
        return ModelResponse(text=content, model_id=resolved or self._model_name)
