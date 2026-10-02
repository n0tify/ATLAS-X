# Configuration Review

Status: **Phase 5 review gate.** Review only — no configuration, code, or
architecture changes were made. Sources inspected: `atlas/config/settings.py`,
`atlas/config/__init__.py`, `tests/test_config.py`, `.env.example`,
`pyproject.toml`, `atlas/auth/service.py`, `atlas/cli.py`, and
`docs/TECHNOLOGY_STACK.md` / `docs/THREAT_MODEL.md` / `docs/ARCHITECTURE_RECONCILIATION.md`.

## 1. Configuration Sources

Exactly what exists in the repository (no assumed mechanisms):

| Source | Supported | Notes |
|---|---|---|
| Hard-coded defaults | **Yes** | Every field in `Settings` has a default value declared in `atlas/config/settings.py` |
| Environment variables | **Yes** | `Settings.from_environ()` reads the `ATLAS_` prefix only, case-normalized to lowercase field names |
| Configuration files (e.g. `.env`) | **No** | `.env.example` is a **template**; nothing in the codebase loads a `.env` file (no dotenv mechanism, `pydantic-settings` not used). Environment must be exported by the shell |
| Command-line configuration | **No** | `atlas/cli.py` calls `Settings.from_environ()` and takes no config flags |

Consumer inventory (who actually reads settings at runtime):
- `atlas/auth/service.py` — `auth_max_login_attempts`, `auth_lockout_minutes`,
  `auth_session_ttl_minutes`, `auth_failure_delay_seconds`.
- `atlas/cli.py` — `database_path`, `environment`.
- All execution/model/tool/plan/output/artifact/input/log/concurrency/CPU/memory
  settings: **no consumers yet** (by design — those components do not exist).

## 2. Current Configuration Values

Secrets are not printed; `application_secret_key` is reported as present/absent only.

| Setting | Purpose | Default | Range | Security-sensitive | User-configurable | Validation |
|---|---|---|---|---|---|---|
| `environment` | dev/prod mode | `development` | enum {development, production} | Yes (prod fail-closed) | Yes | Validator on allowed set |
| `database_path` | SQLite file | `data/atlas.db` | any non-empty path | Moderate | Yes | Path coercion only; **no project-scope constraint** |
| `application_secret_key` | future signing/encryption | `None` | any str, optional | **Yes** | Yes | Required when `environment=production`; below it is unused |
| `auth_session_ttl_minutes` | Session TTL | 60 | 1..1440 | Yes | Yes | `gt=0, le=1440` |
| `auth_max_login_attempts` | Lockout threshold | 5 | 1..50 | Yes | Yes | `gt=0, le=50` |
| `auth_lockout_minutes` | Lockout window | 15 | 1..1440 | Yes | Yes | `gt=0, le=1440` |
| `auth_failure_delay_seconds` | Enumeration blunting | 0.1 | 0..10 (0 allowed) | Yes | Yes | `ge=0, le=10` |
| `max_task_chars` | Task length cap | 4 000 | 1..100 000 | No | Yes | `gt=0, le=100000` |
| `max_plan_steps` | Plan length cap | 10 | 1..50 | No | Yes | `gt=0, le=50` |
| `max_tool_calls` | Per-run tool budget | 12 | 1..100 | No | Yes | `gt=0, le=100` |
| `max_recovery_attempts` | Recovery bound | 2 | 1..10 | No | Yes | `gt=0, le=10` |
| `max_execution_seconds` | Run timeout | 120 | 1..3600 | No | Yes | `gt=0, le=3600` |
| `max_subprocess_seconds` | Subprocess timeout | 30 | 1..600 | No | Yes | `gt=0, le=600` |
| `max_artifact_bytes` | Artifact size cap | 10 MB | >0, **no ceiling** | No | Yes | `gt=0` only |
| `max_input_dataset_bytes` | Dataset size cap | 50 MB | >0, **no ceiling** | No | Yes | `gt=0` only |
| `max_output_chars` | Output size cap | 20 000 | 1..1 000 000 | No | Yes | `gt=0, le=1000000` |
| `max_log_bytes` | Log size cap | 50 MB | >0, **no ceiling** | No | Yes | `gt=0` only |
| `max_concurrent_executions` | Concurrency cap | 1 | 1..16 | No | Yes | `gt=0, le=16` |
| `model_timeout_seconds` | Model call timeout | 60 | 1..3600 | No | Yes | `gt=0, le=3600` |
| `model_context_tokens` | Model context cap | 4 096 | 1..131 072 | No | Yes | `gt=0, le=131072` |
| `cpu_limit_cores` | Optional CPU cap | `None` | >0, **no ceiling** | No | Yes | `gt=0` only |
| `memory_limit_mb` | Optional memory cap | `None` | >0, **no ceiling** | No | Yes | `gt=0` only |

## 3. Resource Limits

The distinction demanded by this gate: **configured ≠ enforced.**

| Limit | Configured | Validated | Enforced now | Enforcement phase |
|---|---|---|---|---|
| Max task length (`max_task_chars`) | Yes | Yes | **No** | Planner / task validation (11) |
| Max plan steps (`max_plan_steps`) | Yes | Yes | **No** | Planner (11) |
| Max tool calls (`max_tool_calls`) | Yes | Yes | **No** | Tool registry / orchestrator (09/12) |
| Max recovery attempts (`max_recovery_attempts`) | Yes | Yes | **No** | Recovery (16) |
| Execution timeout (`max_execution_seconds`) | Yes | Yes | **No** | Orchestrator / sandbox (10/12) |
| Subprocess timeout (`max_subprocess_seconds`) | Yes | Yes | **No** | Sandbox (10) |
| Artifact size (`max_artifact_bytes`) | Yes | Partial (`gt=0`, no ceiling) | **No** | Sandbox (10) |
| Input size (`max_input_dataset_bytes`) | Yes | Partial (`gt=0`, no ceiling) | **No** | Data ingestion (21) |
| Output size (`max_output_chars`) | Yes | Yes | **No** | Verifier / orchestrator (13) |
| Log size (`max_log_bytes`) | Yes | Partial (`gt=0`, no ceiling) | **No** | Observability (14/20) |
| Concurrent executions (default 1) | Yes | Yes | **No** | Orchestrator (12) |
| Model timeout (`model_timeout_seconds`) | Yes | Yes | **No** | Model integration / planner (11) |
| Model context (`model_context_tokens`) | Yes | Yes | **No** | Model integration (11) |
| CPU limit (`cpu_limit_cores`) | Yes (optional) | Yes (`>0`) | **No** | Sandbox (10) |
| Memory limit (`memory_limit_mb`) | Yes (optional) | Yes (`>0`) | **No** | Sandbox (10) |
| Session TTL / lockout / attempts / delay | Yes | Yes | **Yes** (auth only) | Implemented |

The only settings with runtime effect today are the four authentication
settings consumed by `AuthService`. All other limits are **declared but not
enforced** because their consuming components do not exist.

## 4. Security Review

Can configuration currently be abused to…?

| Abuse | Possible today? | Why |
|---|---|---|
| Disable authentication | No | no auth-disable knob exists; auth cannot be switched off by config |
| Disable authorization | No | authorization itself does not exist; no future knob is enabled |
| Disable verification | No | no verification exists and no knob exists |
| Remove resource limits | No | all fields are `gt=0` (zero/unset-invalid); no "unlimited" sentinel |
| Enable unrestricted network access | No | no network-access configuration exists |
| Enable unrestricted filesystem access | No | no FS-scope knob exists; executed code does not exist |
| Enable host command execution | No | no execution knob exists; no subprocess call path |
| Expose secrets | No through dumps | `safe_dump()` excludes secret fields; no runtime logging of settings |
| Create unsafe paths | **Partially** | `database_path` accepts any path (e.g., outside the project). Not restricted; OS permissions are the outer boundary. See MEDIUM-1 |
| Bypass logging | No | no logging-level/bypass knob exists |

Note: absence-of-knob is not the same as enforcement. The future execution
phases must **not** add any "disable auth/verification/authorization" debug
flags — standing rule for Phase 8/11-13.

## 5. Fail-Closed Behavior

| Condition | Behavior | Verdict |
|---|---|---|
| Required config missing (prod secret key) | `ValidationError`, process refuses to start | **Fail-closed** ✓ |
| Malformed value (non-numeric to int/float field) | Pydantic `ValidationError` | Fail-closed ✓ |
| Limit is zero | `gt=0` rejects | Fail-closed ✓ |
| Limit is negative | `gt=0` rejects | Fail-closed ✓ |
| Limit exceeds ceiling | `le=…` rejects where a ceiling exists | Partial — three size fields + CPU/mem have no ceiling |
| Invalid enum (environment=staging) | Validator rejects | Fail-closed ✓ |
| Unexpected env var (`ATLAS_BOGUS=1`) | `extra="forbid"` rejects; tested | Fail-closed ✓ |
| Unknown non-ATLAS_ variable | Ignored (prefix filter) | Fail-open-but-inert — by design; untested |

## 6. Secret Handling

Paths inspected:

- **Logs** — settings are never logged; auth never logs hashes/tokens. The
  redaction filter exists but is **not wired into any application logger by
  default** (see HIGH-1).
- **Exceptions** — Pydantic `ValidationError` messages may echo raw offending
  env values on type errors (default `include_input`). The secret field is a
  `str`, so it will not fail type parsing; practical exposure is low (LOW-2).
- **Configuration dumps** — `safe_dump()` excludes `application_secret_key`;
  tested.
- **Test output** — config tests assert no secret leakage; pass.
- **README/.env.example** — only a placeholder value (`replace-with-a-long-random-value`), not a real secret.

No actual secret values are reproduced in this review.

## 7. Testing Coverage

Existing tests (`tests/test_config.py`, 9 tests):

1. defaults bounded & positive
2. env override
3. unknown env key rejected (extra=forbid)
4. production requires secret key
5. invalid environment rejected
6. zero/negative rejected
7. excessive value rejected (plan steps)
8. safe_dump excludes secrets
9. secret values never reach log output

Missing tests (no new tests added this phase — recorded for completion):

- Upper-bound rejection for the remaining `le` fields
- Rejection of huge byte-size values once ceilings are defined
- Non-`ATLAS_` variables are ignored
- `auth_failure_delay_seconds=0` (allowed) vs negative
- Validation error message does not embed secret values
- Deterministic smoke that `.env` is intentionally not loaded

## 8. Findings

Severity with concrete reasons:

**HIGH**
- HIGH-1 — *Redaction filter not wired into application logging.*
  `SecretsRedactionFilter` is implemented and tested but no runtime logging
  configuration attaches it; the application configures no logging at all.
  Nothing currently logs secrets, so risk is latent, but the moment any future
  component (tools/execution/provenance) logs task/artifact content, untested
  paths could leak a secret verbatim. Must be wired before Phase 9/10 logging.
  Test exists for the filter itself; none for the wiring.

**MEDIUM**
- MEDIUM-1 — *`database_path` unrestricted.* Any `ATLAS_DATABASE_PATH` value is
  accepted and the parent directory is auto-created, including paths outside the
  project. This contradicts the standing "project-scoped filesystem" rule and
  the Phase 4 execution-boundary statement. Mitigation options are a Phase 10+
  decision (constrain to project-relative, or document OS-level trust).
- MEDIUM-2 — *Three size limits lack upper ceilings*
  (`max_artifact_bytes`, `max_input_dataset_bytes`, `max_log_bytes`). They are
  bounded away from zero but can carry absurd configured magnitudes. Not a
  current exploit (unenforced), but they will become enforcement inputs in
  Phase 10 and 21; ceilings must be added then.
- MEDIUM-3 — *`application_secret_key` is required in production but unused.*
  Fail-closed is correct, but nothing consumes the value (no cookie signing, no
  encryption). Informational in effect, yet it signals either future-proofing or
  dead config; decide at the UI/cookie phase (20).

**LOW**
- LOW-1 — `.env` is documented but never loaded. Callers who copy
  `.env.example` to `.env` will silently run on shell-exported/default values.
  Either add an explicit loader or document "export these variables" — do not
  half-support dotfiles.
- LOW-2 — Pydantic validation errors may echo raw values on type failures.
  Exclude values in error rendering for secret-adjacent fields when convenient.
- LOW-3 — No test asserting non-`ATLAS_` variables are ignored (behavior is
  correct; coverage gap only).

**INFORMATIONAL**
- INFO-1 — Execution/model/tool/plan limits are deliberately unenforced until
  their components exist; this is the approved posture, not a defect.
- INFO-2 — `cpu_limit_cores` / `memory_limit_mb` are optional and unconsumed;
  Windows enforcement is partial; the sandbox gate must decide how much of them
  is actually enforceable.
- INFO-3 — `safe_dump()` is exercised by tests only; no production path dumps
  settings.

## 9. Required Changes Before Execution Features

Non-negotiable list before authorization/tool/sandbox/execution land:

1. **Wire `SecretsRedactionFilter` into application logging** (resolves HIGH-1)
   before any component that logs task/tool/artifact content.
2. **Decide and implement the enforcement call site for every limit** at its
   owning phase: timeout → orchestrator/sandbox; artifact/input/log size →
   sandbox/ingestion; plan/tool/recovery → planner + orchestrator. Enforcement
   code must be tested, not merely present in `Settings`.
3. **Add ceilings** to `max_artifact_bytes`, `max_input_dataset_bytes`,
   `max_log_bytes` (and optionally CPU/memory) before Phase 10.
4. **Constrain or explicitly document `database_path` scope** (MEDIUM-1).
5. **Add the "no security off-switches" standing rule** before Phase 8 builds
   authorization: no config flag may disable auth, authorization, targets of
   verification, or logging redaction.
6. **Codify the runtime logging configuration** (handlers, level, format) once
   an observability module exists (Phase 14/20), reusing the redaction filter
   and the log-size cap.
7. **Resolve `.env` support policy** (LOW-1) so configuration sources are what
   users believe them to be.

Applicable at which gates: (1) before 09; (2-3) at 10; (4) at 10; (5) at 08;
(6) at 14; (7) at 05-adjacent or 20. None performed in this phase.

## 10. Current Security Boundary

"Configuration currently defines intended limits, but limits associated with
future execution components are not yet runtime-enforced because those
execution components do not yet exist."

Enforced today: authentication controls only (session TTL, lockout threshold,
lockout window, failure delay) plus fail-closed startup validation and
secret-excluding dumps. Everything execution-related is aspirational
configuration until its owning phase ships enforcement and tests.

## Verification

- `pytest` → **36 passed**
- `ruff check .` → **All checks passed**
- `mypy atlas` → **Success: no issues found in 23 source files**

Files modified in this phase: `docs/CONFIGURATION_REVIEW.md` (created only). No
code, configuration, or schema changes.