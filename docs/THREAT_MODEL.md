# ATLAS-X Threat Model

Status: **threat-model gate (Phase 3).** No security controls were implemented
by this phase. This document is the input to Phase 4+ hardening and to Phase 19
(Security Testing). Claims below about existing controls refer to code already
committed (config, storage, auth); "planned" means a later phase must deliver
the control **and** its test before the threat can be called mitigated.

## Assets

| # | Asset | Notes |
|---|---|---|
| A1 | User accounts | usernames, credentials |
| A2 | Password-derived authentication material | Argon2id hashes |
| A3 | Session identifiers | opaque tokens, digests at rest |
| A4 | Authorization state | ownership, roles, tool permissions |
| A5 | Task data | user goals/plans |
| A6 | Datasets | benchmark inputs |
| A7 | Generated code | model outputs destined for execution |
| A8 | Tool configuration | tool registry + policies |
| A9 | Execution artifacts | sandbox outputs |
| A10 | Provenance records | audit trail |
| A11 | Benchmark results | evaluation_runs |
| A12 | Local model interaction data | prompts/responses to Ollama |
| A13 | Application configuration | `Settings`, env, `.env` |

## Trust boundaries

| # | Boundary |
|---|---|
| T1 | Browser/UI |
| T2 | Application layer |
| T3 | Authentication layer |
| T4 | Authorization layer |
| T5 | Local LLM runtime (Ollama) |
| T6 | Tool registry |
| T7 | Sandbox |
| T8 | Host filesystem |
| T9 | Database (SQLite) |
| T10 | Artifact storage |

Cross-boundary rule: data crossing **toward** the host (T7→T8) is hostile by
default; data crossing out of the model (T5→T2) is untrusted until verified.

## Legend

- Likelihood: Lo / Med / Hi. Impact: Lo / Med / Hi / Crit.
- Rating: (likelihood × impact) residual after mitigation; stated per threat.

---

## A. Identity and sessions

### A1. Unauthorized access
- Threat: caller acts without valid authentication.
- Asset: A1, A3, A5. Boundary: T3. Attack path: guess/paste credentials, stale token.
- Likelihood: Med. Impact: Hi.
- Mitigation (existing): Argon2id; opaque session tokens (32 bytes, url-safe);
  token digests at rest; expiry on every validation; per-account lockout; generic
  errors. **Phase 8:** the T4 gate now exists — `AuthorizationService` refuses
  every operation without a validated session, so authentication is a
  prerequisite of authorization and never a permission.
- Residual: Lo–Med (brute force at network scale would need external rate limiting).
- Test required: `tests/test_auth.py` (wrong password, invalid/expired session);
  **Phase 8:** `test_missing_or_malformed_identity_is_denied`,
  `test_unknown_session_token_is_denied`, `test_expired_session_is_denied`,
  `test_unauthenticated_actor_cannot_read_a_protected_resource`.

### A2. Session theft
- Threat: attacker obtains a live session token.
- Asset: A3. Boundary: T1/T3. Attack path: XSS (future UI), logged token, token in URL/logs.
- Likelihood: Med. Impact: Hi. Boundary: T3.
- Mitigation (existing): raw token returned once and never logged; HttpOnly/
  SameSite cookie guidance (future UI); revocation on logout and password change.
- Residual: Med (no transport-layer protection on plaintext localhost HTTP).
- Test required: hash-never-in-logs; revocation tests; (planned) UI cookie tests.

### A3. Broken object-level authorization
- Threat: user accesses another user's task/artifact by id.
- Asset: A4, A5. Boundary: T4. Attack path: id enumeration in CRUD calls.
- Likelihood: Med. Impact: Hi.
- Mitigation (existing): all reads/deletes scope by `WHERE user_id = ?`
  (`TaskRepo.get/delete`). **Phase 8:** every task-descendant read joins to
  `tasks.user_id` (`atlas/storage/owned_resources.py`) and is reachable only
  through `AuthorizationService`, which derives the actor from a session token.
- Residual: Lo for storage-facing operations; **Med** for any future component
  that queries SQLite directly, and the check must be re-applied at every new
  API surface. `evaluation_runs` has no owner and is denied by name.
- Test required (existing): `test_cross_user_session_isolation`,
  `test_ownership_relationships_are_enforced`. **Phase 8:**
  `tests/test_authorization.py` sections B, C, E (cross-user read, list, delete,
  provenance append, guessed ids, repeated denials).

### A4. Privilege escalation
- Threat: user raises own role or reaches admin-only tools.
- Asset: A4. Boundary: T4. Attack path: forged role field, tool bypass.
- Likelihood: Med. Impact: Crit.
- Mitigation: **Phase 8 implements the deny-by-default layer.** No roles exist
  and none can be created; no permission is stored in the database; ownership is
  the only grant; no repository can reassign `tasks.user_id`; the actor is never
  caller-supplied. Tool capability names for arbitrary shell, subprocess, Python
  eval, filesystem, and network can never be granted, checked before the grant
  lookup.
- Mitigation (Phase 9): **the grant store is now implemented and reviewed.** Rows
  in `tool_permissions` are explicit, owner-scoped, revocable, and hold no
  secret; absence of a row is the denial; a stored scope outside `NULL` /
  `task:<id>` is dropped rather than repaired; writing a grant is an operator
  action with no session path. `ToolDispatcher.dispatch` resolves the actor from
  the session token, then calls `require_tool_invocation` **before** validating
  input or touching an implementation, so an ungranted caller cannot probe a
  tool's schema by comparing failures. The tool set is code, not rows: five
  frozen built-ins, no runtime registration, no unregister, and a tool id that
  cannot be read as a module or file path. A definition requiring the sandbox,
  filesystem, network, or non-determinism is refused at registration.
- Residual: **Lo.** Reduced further, not closed: `ToolDefinition.implementation`
  is a plain attribute, so in-process code holding a registry can call a body
  and skip dispatch (Phase 10 must supply a process boundary); grants name a
  capability by string with no foreign key to an implemented tool, so a grant
  can reference something that does not exist; `change_password` is still not
  bound to a session principal (finding AZ-03).
- Test required: **Phase 8:** `test_no_public_service_method_accepts_a_user_id`,
  `test_task_ownership_cannot_be_reassigned_by_any_repository`,
  `test_ungranted_operations_are_denied`,
  `test_prohibited_capability_classes_can_never_be_granted`,
  `test_authentication_does_not_imply_update_permission`.
  **Phase 9:** `test_dispatch_without_a_grant_never_runs_the_implementation`,
  `test_authorization_runs_before_input_validation`,
  `test_a_revoked_grant_stops_the_implementation_on_the_next_call`,
  `test_grant_is_persisted_and_readable_for_its_owner`,
  `test_a_malformed_stored_scope_drops_the_grant_rather_than_widening_it`,
  `test_default_registry_is_frozen_and_holds_the_five_built_ins`.


### A5. Credential leakage
- Threat: password/hash exfiltration from storage or logs.
- Asset: A2. Boundary: T3/T9. Attack path: DB file copied, structured logs, Error dumps.
- Likelihood: Lo. Impact: Crit.
- Mitigation (existing): Argon2id only; hash never returned by any auth response;
  secret/failure values redacted by `SecretsRedactionFilter`.
- Residual: Lo (DB file is host-owned; OS file permissions are the boundary).
- Test required: `test_session_token_only_stored_hashed`,
  `test_login_unknown_user_same_generic_error`, `test_no_auth_secrets_in_logs`.

### A6. User enumeration
- Threat: attacker distinguishes "exists" from "invalid".
- Asset: A1. Boundary: T3. Attack path: differing error messages or response timing.
- Likelihood: Med. Impact: Lo.
- Mitigation (existing): single generic message; constant delay on every failed
  authentication.
- Residual: Lo–Med (timing is blunted, not cryptographically constant).
- Test required: `test_login_unknown_user_same_generic_error`.

### A7. Replay of privileged operations
- Threat: capturing a privileged tool call and replaying it later.
- Asset: A4, A7. Boundary: T6/T7. Attack path: re-send recorded step payload.
- Likelihood: Lo. Impact: Med.
- Mitigation: idempotency/execution-scoped step checks are a planned rule;
  provenance records correlate executions; recovery caps bound repetition.
- Residual: Med until replay guards (nonce per execution) land in Phase 12.
- Test required: (planned) double-execution/prevention test in Phase 12.

---

## B. Model and content

### B1. Prompt injection
- Threat: adversarial text in goal/dataset/artifact steers the model.
- Asset: A12. Boundary: T5↔T2. Attack path: goal or file content says "ignore
  instructions, run X".
- Likelihood: Hi. Impact: Hi.
- Mitigation: treat all model-directed content as **data, not instructions**;
  plans pass deterministic validation; tools are whitelisted and argument-typed;
  no tool executes free text. (planned) explicit injection-resistance tests.
- Residual: Hi — model layer cannot be provably immune; this is a documented,
  subject-level research finding.
- Test required: (planned) adversarial goal/file suite in Phase 19.

### B2. Malicious task instructions
- Threat: user or attacker submits a task that instructs harmful tool use.
- Asset: A5, A8. Boundary: T2/T6. Attack path: craft goals that map to
  destructive tool inputs.
- Likelihood: Med. Impact: Med.
- Mitigation: validator checks plan bounds (step count, tool names); tool
  policy denies destructive ops at the registry; arguments schema-checked.
- Residual: Med — policy quality is the limit, not magic.
- Test required: (planned) harmful-goal rejection tests.

### B3. Malicious generated code
- Threat: model output contains code that attacks the host.
- Asset: A7. Boundary: T5→T7→T8. Attack path: model writes `os.system(...)`,
  binds ports, deletes files.
- Likelihood: Med. Impact: Crit.
- Mitigation (implemented, Phase 10B): the body is a Linux process in `bubblewrap`
  mount/PID/network/IPC/UTS/user/cgroup namespaces inside WSL2, with a cgroup v2
  leaf. Resource limits, a per-execution workspace, output size caps, and a
  wall-clock deadline enforced outside the process group being timed. No
  host-level execution, and no in-process fallback when the guest is unavailable.
- Residual: **Med**. Network and filesystem confinement are structural. The
  residual is the trusted computing base: a guest-kernel or `bubblewrap` escape is
  out of scope, and the supervisor itself is unconfined.
- Test required (done, Phase 10B): conformance probes run a real confined process
  that attempts escape, in `tests/test_sandbox.py`. A wider hostile-code corpus
  remains Phase 19 work.

### B4. Poisoned benchmark inputs
- Threat: datasets mutated to bias ablation results.
- Asset: A6, A11. Boundary: T2. Attack path: edit JSONL/gold files between runs.
- Likelihood: Lo. Impact: Hi (research integrity).
- Mitigation: datasets versioned; EvaluationRun serializes config; results tied
  to run; deliverables policy: full results, no cherry-picking.
- Residual: Lo (local trust), assumes operator discipline.
- Test required: (planned) reproducibility re-run test comparing stored results.

### B5. Verification bypass
- Threat: execution that skips or fakes the verifier.
- Asset: A11. Boundary: T2. Attack path: calling finalize without a PASS record.
- Likelihood: Med. Impact: Crit.
- Mitigation: final result is produced only by the orchestrator after a
  recorded PASS; verifier is code, not model; (planned) orchestrator invariant
  test.
- Residual: Lo–Med until orchestrator (Phase 12) enforces the invariant.
- Test required: (planned) "no verified result without PASS" test.

### B6. False verification
- Threat: verifier passes something incorrect (logic bug, weak predicate).
- Asset: A9, A11. Boundary: T2. Attack path: verifier checks only "file exists"
  while content is wrong.
- Likelihood: Med. Impact: Hi.
- Mitigation: verifiers must assert content-level properties, not existence
  alone; each verifier ships its own tests; benchmark tasks have gold
  expectations.
- Residual: Med — verification strength is a research variable, not an axiom.
- Test required: (planned) per-verifier unit tests + false-negative/false-positive suites.

---

## C. Tool and execution

### C1. Malicious or malformed tool arguments
- Threat: a step passes hostile/malformed arguments to a tool.
- Asset: A8. Boundary: T6. Attack path: crafted `input_json` exploiting a tool's permissiveness.
- Likelihood: Med. Impact: Med.
- Mitigation (existing, Phase 9): every tool declares a `ToolSchema`; input is
  validated against it before the implementation runs, and the output is
  validated against the declared output schema before it is returned. A schema
  that leaves a numeric, string, or array bound undeclared cannot be
  constructed, so "unbounded" is not a default a future tool can inherit. Input
  and output byte bounds and a per-task call budget bound each call. A tool
  returning something its own schema forbids fails the invocation; output is
  never truncated.
- Residual: Lo–Med — strictness is per-tool, so this reduces argument-driven risk
  rather than eliminating it. A payload that is well-formed but semantically
  abusive (a large array inside its declared limit) is still bounded, not
  understood.
- Test required (existing): `test_numeric_field_without_bounds_is_not_constructible`,
  `test_unexpected_field_is_rejected`,
  `test_non_mapping_payload_is_rejected_rather_than_crashing`,
  `test_output_that_breaks_its_own_schema_is_a_failure_not_a_result`,
  `test_oversized_output_fails_rather_than_being_truncated`.

### C2. Command injection
- Threat: tool input escapes into a shell.
- Asset: A7, A8. Boundary: T6/T7. Attack path: `input` containing `; rm -rf`.
- Likelihood: Med. Impact: Crit.
- Mitigation (existing, Phase 9): the registry is a frozen set of five built-in
  implementations in `atlas/tools/builtin/`; there is no "run arbitrary shell",
  subprocess, `eval`, or command-string tool, and a tool id is a single lowercase
  `snake_case` segment, so no id can be resolved as a module path, file path, or
  command. A definition declaring `network_access` or any non-`NONE` filesystem
  access is refused at registration. No runtime registration, unregister, or
  reload path exists.
- Residual: Lo for the current set — this is a property of what the five
  implementations do, so **every future tool re-opens it**. A tool added in a
  later phase that accepts a path, a query, or a template would reintroduce
  Med.
- Test required (existing): `test_no_tool_layer_module_can_reach_a_shell_or_an_import`,
  `test_host_filesystem_access_requires_the_sandbox_and_is_refused`,
  `test_network_access_is_refused`,
  `test_frozen_registry_refuses_further_registration`.

### C3. Path traversal
- Threat: artifact/step references `../../outside` paths.
- Asset: A9. Boundary: T7/T8. Attack path: relative path escapes sandbox root.
- Likelihood: Med. Impact: Hi.
- Mitigation (existing, Phase 9): no Phase 09 tool opens a host path at all.
  `artifact_metadata` reads database rows through an owner-scoped, read-only
  view and explicitly returns neither `content` nor `relative_path`, so a
  traversal string in an artifact row has nothing to escape into at this layer.
  Owning a row authorizes no host path, and the authorization layer performs no
  path validation.
- Residual: Med — this is a *withdrawal* of the tool's reach, not a confinement
  mechanism. `artifacts.relative_path` is still unvalidated
  (`docs/STORAGE_REVIEW.md` §13) and any future file-reading tool would restore
  the full traversal surface until Phase 10 confines it.
- Test required (existing): `test_artifact_metadata_reports_metadata_and_no_content`,
  `test_artifact_metadata_cannot_reach_another_users_execution`,
  `test_the_view_applies_the_owner_predicate`. (planned) traversal corpus
  (`.`/`..`/UNC/alternative separators) in Phase 10.

### C4. Arbitrary file access
- Threat: sandbox reads any host file.
- Asset: A5..A9. Boundary: T7/T8. Attack path: generated code reads
  `C:\...\personal` files.
- Likelihood: Med. Impact: Crit.
- Mitigation (implemented, Phase 10B): `/workspace` is the only writable bind;
  `/mnt`, `/home`, `/root`, `/run`, `/srv`, and `/media` are asserted absent after
  the namespace is built; WSL interop is disabled, so Windows binaries and drive
  letters are unreachable; the project tree, database, and `.env` all live under
  `/mnt/c` and are therefore out of reach. Reads are an owner-scoped column
  snapshot, so there is no connection to hold.
- Residual: **Lo** for paths. One caveat is recorded rather than claimed away: a
  body that exhausts its memory cap may be killed before reporting, and whether it
  wrote inside its own workspace is not checked.
- Test required (done, Phase 10B): `fs.absent.*` and traversal probes assert the
  paths are gone from inside the real confinement.

### C5. Sandbox escape
- Threat: the sandbox process breaks its constraints.
- Asset: A7, A8. Boundary: T7. Attack path: exploit handler, native call, exit
  sandbox.
- Likelihood: Lo. Impact: Crit.
- Mitigation (implemented, Phase 10B): kernel namespaces, `--cap-drop ALL`, uid/gid
  65534, and a hidden cgroup hierarchy. One **real** escape was found and fixed
  during Phase 10B: `/proc` was mounted without `--remount-ro`, letting uid 65534
  write the host-global `core_pattern`. `--unshare-all` does not prevent this,
  because `/proc/sys` is not namespaced.
- Residual: **Med**. The kernel and `bubblewrap` are trusted computing base, so an
  exploit of either is out of scope by decision, not by oversight. Stated in
  `SECURITY.md` and `docs/SANDBOX_DESIGN_AMENDMENT.md` §12.5.
- Test required (done, Phase 10B): the `sysctl` probe writes each host-global
  sysctl's current value back to itself and fails if the path is writable, which is
  how the `/proc` escape is detected without ever altering host state.

### C6. Resource exhaustion
- Threat: a step/run consumes unbounded RAM/CPU/disk/time.
- Asset: A9. Boundary: T7. Attack path: infinite loop, huge allocation.
- Likelihood: Med. Impact: Med.
- Mitigation (existing, Phase 9): `ToolDefinition` refuses a schema that leaves
  a numeric, string, or array bound undeclared, so no unbounded value can reach a
  body. `ToolLimits` caps input and output bytes; `DispatchLimits` caps calls
  per task and output characters; rows a tool may read are capped in SQL rather
  than after the read. The call budget is counted from the audit log, so a
  process restart cannot reset it. `Settings` bounds and WAL remain as before.
- Residual: **Med** — the elapsed budget is checked *after* the call returns, so
  a body that hangs is detected but not interrupted, and there is no memory or
  CPU ceiling. These are the Phase 10 gaps and they are unchanged by anything in
  this phase.
- Test required (existing): `test_the_per_task_call_budget_is_enforced`,
  `test_the_budget_survives_a_new_dispatcher`,
  `test_oversized_output_fails_rather_than_being_truncated`,
  `test_an_oversized_input_is_refused_before_the_implementation_runs`,
  `test_the_view_limit_is_pushed_into_the_query`. (planned) interruption and
  memory enforcement tests in Phase 10.

### C7. Denial of service
- Threat: repeated tasks crowd out legitimate use.
- Asset: whole system. Boundary: T2. Attack path: trigger many concurrent tasks.
- Likelihood: Lo. Impact: Med.
- Mitigation (existing): `max_concurrent_executions=1` default; (planned)
  queue/back-pressure in orchestrator.
- Residual: Lo (single-user local tool).
- Test required: (planned) concurrency-saturation test.

---

## D. Data, records, and disclosure

### D1. Cross-user data access (non-BOLA residual)
- Threat: batch/graph queries leak across users.
- Asset: A5, A9, A10. Boundary: T4. Attack path: provenance/artifact queries without owner scope.
- Likelihood: Med. Impact: Hi.
- Mitigation: provenance and artifact queries carry ownership through task
  linkage. **Phase 8:** every descendant read and list carries the owner
  predicate, and the boundary refuses a task the caller does not own before
  listing anything beneath it.
- Residual: Med. Reduced for existing surfaces, but every new query still needs
  the cross-user matrix; provenance events with no task and no execution have no
  resolvable owner and are denied to all users; `evaluation_runs` is unowned and
  denied by name.
- Test required: **Phase 8:** `test_non_owner_cannot_list_another_users_descendants`
  (parametrized over all eight owned resource kinds),
  `test_provenance_without_a_resolvable_owner_is_invisible_to_everyone`,
  `test_evaluation_runs_are_denied_by_name`.

### D2. Accidental secret disclosure
- Threat: user goal/artifact contains API keys or private text that the system echoes.
- Asset: A13. Boundary: T2/T9. Attack path: task text includes credentials; stored/showed in clear.
- Likelihood: Med. Impact: Hi.
- Mitigation: redaction filter for configured secrets; never log task/artifact
  bodies by default; artifact content stored but not echoed in logs/UI summaries.
- Residual: Med (content-at-rest in SQLite is plaintext by design; OS file perms
  are the boundary).
- Test required: (planned) secret-in-task ingestion negative tests.

### D3. Unsafe logging
- Threat: code logs passwords, tokens, hashes, or full bodies.
- Asset: A2, A3, A5. Boundary: T2. Attack path: logging frame includes sensitive arg.
- Likelihood: Med. Impact: Med.
- Mitigation (existing): redaction filter; audit of auth path; log-size caps.
- Residual: Lo–Med (new code must follow the same rule).
- Test required (existing): `test_no_auth_secrets_in_logs`; (planned) logging-review gate per phase.

### D4. Corrupted provenance
- Threat: audit trail altered or incomplete.
- Asset: A10. Boundary: T9. Attack path: direct DB edit, dropped events, cascade wipe.
- Likelihood: Lo. Impact: Med (research integrity).
- Mitigation: append-only application policy; events survive task deletion with
  nullable keys; (design) future integrity checksum over event chain.
- Residual: Lo (operator with DB access can still edit files on disk).
- Test required (existing): `test_provenance_records_and_survives_task_delete`.

---

## Security Properties ATLAS-X Does NOT Guarantee

Stated plainly; do not exceed these in documentation or claims.

1. **No guarantee against a guest-kernel or `bubblewrap` exploit.** Phase 10B gives
   tool bodies structural namespace confinement: no network, no host filesystem,
   no capabilities, kernel-enforced resource limits, and a wall clock that ends the
   process tree. What it does not give is a guarantee against code that exploits the
   kernel or `bubblewrap` itself. Both are trusted computing base, by decision.
   The supervisor is also unconfined, so a compromised ATLAS-X process is contained
   by nothing in this phase.
2. **No transport-layer security.** Localhost plaintext HTTP is assumed for a
   single-user tool; credentials/tokens would be exposed to any local
   keystroke/network observer. Trusted network deployments (LAN/multi-user)
   require TLS and are out of scope.
3. **No immunity to prompt injection.** The model layer is not provably
   safe; research output treats injection resistance as a measured variable.
4. **No internet-scale auth.** No MFA, recovery, or distributed rate limiting.
   Lockout is per-account, in-process, and resets on restart.
5. **No host-hardening guarantees.** If the attacker already has local admin
   rights, ATLAS-X cannot protect the machine; the OS file-permission model is
   the outer boundary for the SQLite database and artifacts.
6. **No anti-tamper for at-rest data.** Anyone who can read the SQLite file /
   artifact directory can read (though not silently forge, absent integrity
   chains) the plaintext content it stores.
7. **Verification is only as strong as its predicates.** A weak verifier can
   PASS weak results; verifier strength is itself an experimental variable.
8. **No authorization for code that bypasses the boundary.** Phase 8 gates
   callers that go through `AuthorizationService`. Any component that queries
   SQLite directly is trusted code and is not covered by the policy, and the
   policy covers no host path, only database rows.
9. **No grants beyond ownership, and no grant administration.** There is no
   role, no permission table, and no tool-grant store, so nothing can be
   widened — but neither can anything be granted legitimately. Resources with
   no resolvable owner (`evaluation_runs`; provenance events with no task and
   no execution) are denied to everyone rather than authorized to anyone.
   Tool permission is a decision interface only: no tool can be invoked, since
   tool execution is Phase 09.

## Threat → control map

`done` marks a control that is implemented and tested; other values are phases
that still own the control.

| Threat | Existing control | Control phase | Negative test phase |
|---|---|---|---|
| A1 Unauthorized access | auth layer + T4 gate (done, Phase 8) | 08 done | 19 |
| A2 Session theft | auth (done) | UI cookies | 19 |
| A3 BOLA | repo scoping + `AuthorizationService` (done, Phase 8) | 08 done; re-test per surface | 19 |
| A4 Privilege escalation | deny-by-default policy, no roles (done, Phase 8) | 08 done; revisit with tool grants in 09 | 08 done / 19 |
| A5 Credential leakage | argon2/redaction (done) | — | 19 |
| A6 User enumeration | generic errors/delay (done) | — | 19 |
| A7 Replay of privileged ops | — | 12 | 12 |
| B1 Prompt injection | validation (design) | 09-13 | 19 |
| B2 Malicious task instructions | validator (design) | 11 | 19 |
| B3 Malicious generated code | namespaces + cgroups + deadline (done, 10B) | **10B done** | 10B done / 19 |
| B4 Poisoned benchmark inputs | run-config serialization (design) | 21-33 | 21 |
| B5 Verification bypass | finalize invariant (design) | 12 | 12 |
| B6 False verification | — | 13 | 13 |
| C1 Malformed tool args | tool schemas (design) | 09 | 09 |
| C2 Command injection | no-shell rule (design) | 09 | 19 |
| C3 Path traversal | relative-path rule (design) | 10 | 10 |
| C4 Arbitrary file access | namespace FS confinement (done, 10B) | 10B done | 10B done |
| C5 Sandbox escape | namespaces + ro-bind (done, 10B); kernel is TCB | **10B done** | 10B done / 19 |
| C6 Resource exhaustion | config bounds (done) | 10 enforcement | 10 |
| C7 DoS | concurrency cap (done) | 12 queue | 12 |
| D1 Cross-user data access | owner-scoped descendant queries (done, Phase 8) | 14 | 19 |
| D2 Accidental secret disclosure | redaction (done) | 20 UI | 19 |
| D3 Unsafe logging | redaction filter (done) | every phase | 19 |
| D4 Corrupted provenance | append policy (done) | 14 integrity | 14 |