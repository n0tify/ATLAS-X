# ATLAS-X Sandbox Design

Status: **Phase 10 design gate.** Design only. No sandbox runtime, supervisor,
worker, or isolation code was written by this phase. Every control named here is
`PLANNED` until Phase 10B implements it *and* tests it, at which point the label
changes and the test name is recorded.

This document exists because the next phase is a hard security gate and the
largest residual risk in the project. `docs/THREAT_MODEL.md` rates B3
(malicious generated code), C4 (arbitrary file access), and C5 (sandbox escape)
as **Hi** residual on this host, and the Phase 09 report states plainly that tool
bodies are still in-process, that the elapsed budget detects an overrun rather
than interrupting it, and that in-process code holding a registry can call a tool
body directly. A design that papered over those facts would make every later
security claim in the project worthless.

## 1. Scope and status of this document

**In scope.** What the sandbox is for, what it can and cannot guarantee on the
verified host, the trust boundaries, the workspace, filesystem, environment,
secret, network, process, resource, artifact, database, and cleanup models, the
integration with Phase 08 authorization and Phase 09 tool metadata, the
security invariants, the tests Phase 10B must write, and the performance
estimates.

**Out of scope.** Implementation of any kind; the planner, orchestrator, verifier,
recovery, provenance, and evaluation components; model integration; the UI. The
reconciliation of the `READY` / `CANCELLED` / `SECURITY_BLOCKED` state
contradiction and the `PASS` / `FAIL` / `INCONCLUSIVE` contradiction belong to
Phases 12 and 13 and are recorded as `docs/UI_ARCHITECTURE.md` C-02, C-03, and
C-04. They are **not** settled here. (Threat ids in this document are
`docs/THREAT_MODEL.md` ids unless the text names the other document; the two
series overlap on `C3`–`C6` and mean different things.)

**Not decided here.** Section 26 lists the decisions this design deliberately
leaves open rather than guessing.

## 2. The primary security question

> What happens if a tool implementation is malicious, compromised, buggy, or
> deliberately attempts to escape its intended authority?

The design is organised around that question rather than around a list of
features. Concretely it asks, for each of the thirty-six vectors in section 5,
whether ATLAS-X has an enforcement mechanism, what that mechanism actually
protects, and what it does not.

The honest answer, stated up front: on the verified host, ATLAS-X can build a
**process-level** boundary with real CPU, memory, process-count, timeout, and
kill-on-close enforcement, plus **application-level** workspace and output
controls. It cannot build a **container-level** or **VM-level** boundary, and it
cannot make filesystem or network isolation an OS-enforced guarantee without a
separate OS account, an elevation the operator does not have, or infrastructure
that is not installed. Section 9 and section 27 state this without softening it.

## 3. Verified host environment

Every row was re-measured for this phase, not carried forward from
`docs/environment-reconnaissance.md` (dated 2026-09-24). Values that changed are
marked. Probes were read-only capability checks; no files outside the project and
no system configuration were modified.

| Property | Verified value | Changed since recon? |
|---|---|---|
| OS | Microsoft Windows 11 Home Single Language, build 26200, 64-bit | no |
| CPU | 13th Gen Intel Core i5-1335U, 12 logical processors | no |
| RAM | 15.70 GB | no |
| Disk C: free | 193.6 GB free / 264.0 GB used | yes (was 197.4 GB free) |
| Elevation | **Not an administrator** | not previously recorded |
| Python | 3.11.0 in `.venv`, the project interpreter | no |
| `docker` | **not on PATH**; Docker Desktop not installed | no |
| WSL | `wsl.exe` present, default version 2, **no distributions installed** | no |
| Ollama | 0.34.4, **listening on 127.0.0.1:11434** (pid not recorded — it is ephemeral and would be stale on the next run) | new detail |
| Project venv packages | `pydantic` 2.13.5, `argon2-cffi` 23.1.0 (+ dev tools) | changed; recon predates the venv |
| `psutil` | **not installed** | new |
| `pywin32` | **not installed** | new |
| AppContainer API | present in `userenv.dll` | new |

### 3.1 Capability probes that change the design

These are the facts that actually constrain the architecture. Each was tested on
this host.

| Capability | Result | Design consequence |
|---|---|---|
| `kernel32!CreateJobObjectW` | available and **succeeds as non-admin** | Job Objects are usable without elevation or a new dependency |
| `AssignProcessToJobObject`, `SetInformationJobObject`, `TerminateJobObject`, `QueryInformationJobObject` | all available | full process-tree containment, CPU/memory/process limits, kill-on-close |
| `jobapi2.dll` | not a standalone module; functions live in `kernel32` | a `ctypes` binding must target `kernel32` |
| Current process already in a Job | **no** | a new job can be created and the worker assigned without a nested-job conflict |
| `advapi32!CreateRestrictedToken`, `SetTokenInformation`, `LogonUserW` | available | a restricted-token worker is technically possible; assessed in section 11 |
| `userenv!CreateAppContainerProfile` | present in the DLL | AppContainer is *available in principle*; not selected — see section 11 |
| `Get-NetFirewallProfile` | readable; rule changes need elevation | per-process network filtering is not available at this privilege |
| Directory **symlink** creation | **REFUSED** — "A required privilege is not held by the client" | symlink escape is much harder than expected on this host |
| Directory **junction** creation (`mklink /J`) | **SUCCEEDS as non-admin** (rc 0) | junction escape is real and is the primary filesystem risk |
| Traversal through a junction | **succeeds** — read host file content through it | confirms the escape is exploitable, not theoretical |
| Naive string-prefix check on a junction path | **passes** (reports the path inside the workspace) | string prefix checking is proven insufficient |
| `Path.resolve()` / `os.path.realpath` on that path | **resolves outside the workspace** | canonicalisation defeats the junction, and is the required mechanism |
| `Path.is_symlink()` on a junction | **`False`** | a symlink-only check misses junctions entirely |
| `os.path.isjunction` | **not available in Python 3.11** | reparse detection must use `os.lstat` / `st_file_attributes` or Win32, not `isjunction` |
| `python -I -E -s` | works, 51 env keys remain | flags alone do not sanitise the environment; the child env must be built explicitly |

Two of these deserve emphasis because they reverse an assumption the design would
otherwise have been built on.

**Symlinks are not the threat; junctions are.** A conventional "reject symlinks"
policy would pass every test written against symlinks and still be escapable on
this host, because a non-admin process can create a junction and traverse it
freely. Worse, `Path.is_symlink()` returns `False` for a junction, so the obvious
implementation of a symlink check has a silent hole. This is why section 12
specifies reparse-point handling rather than a symlink filter.

**Environment sanitisation cannot be delegated to interpreter flags.** `-I -E -s`
leaves 51 environment keys visible. A worker that inherits the parent environment
inherits `ATLAS_APPLICATION_SECRET_KEY`. The child environment must be
constructed key by key (section 13).

## 4. Platform reality: what this host can and cannot enforce

The distinction that governs the whole design: **application-level** control is
code in ATLAS-X that decides something; **process-level** control is the OS
constraining a process tree; **OS-level** control is a token, ACL, firewall rule,
or restricted token enforced by Windows; **container-level** is a namespace
boundary; **VM-level** is a hypervisor boundary.

| Guarantee | Best available here | Level actually achievable | Requires |
|---|---|---|---|
| Kill the whole process tree on timeout or violation | Job Object + `TerminateJobObject` | **process-level** | nothing extra |
| Kill the tree when the supervisor dies | `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` | **process-level** | nothing extra |
| Cap CPU time | `JOB_OBJECT_CPU_RATE_CONTROL` | **process-level** | nothing extra |
| Cap address space / commit charge | `JOB_OBJECT_LIMIT_JOB_MEMORY` | **process-level** | nothing extra |
| Cap concurrent processes | `JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 1` | **process-level** | nothing extra |
| Cap total processes over the job's life | `JOB_OBJECT_LIMIT_PROCESS_COUNT` | **process-level** | nothing extra |
| Cap threads | **no job flag exists** | none | thread count is bounded only indirectly, by the memory limit and by `JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION` |
| Hard wall-clock timeout that interrupts a running call | Job Object kill after a supervisor-side timer | **process-level** | nothing extra |
| Confine writes to a workspace | ATLAS-X never acts on an out-of-workspace path; untrusted code has no legitimate reason to write elsewhere | **application-level** only | the worker's own writes are not confined (§12.5); OS ACLs would be needed for a real guarantee |
| Prevent reading host files | **nothing at this privilege** | none | separate OS account, restricted token, AppContainer, or VM |
| Block all network | **nothing at this privilege** | none | firewall rule (needs elevation), WSL, container, or VM |
| Block loopback to Ollama on 11434 | **nothing at this privilege** | none | as above |
| Survive a malicious or buggy native extension | **nothing** | none | process boundary plus a hardened runtime |
| Survive an admin-rights attacker | **nothing** | none | out of scope by design |

The single most important sentence in this document: **on this host, filesystem
read confinement and network denial cannot be enforced by ATLAS-X at the
privilege level it runs.** Every design decision below follows from that. A
subprocess is a boundary for *lifetime, CPU, memory, and process count*; it is
not a boundary for *reach*.

## 5. Threat analysis against the primary question

Each row names the mechanism the design relies on and states what remains open.
"Application-level" here means the control works because the code enforces it,
not because the OS does.

| Vector | Planned mechanism | Level | Residual |
|---|---|---|---|
| Arbitrary code execution | worker runs a fixed entry point, never a caller-supplied string; no `eval`/`exec` of model output | application | untrusted code still runs in a real Python runtime with stdlib |
| Arbitrary filesystem read | deny-by-declaration; no Phase 10 tool declares host read; nothing is staged | application | **cannot be enforced against a hostile worker**; §4, §12.5 |
| Arbitrary filesystem write | supervisor never acts on an out-of-workspace path; staging, collection, and `relative_path` are canonicalised and reparse-checked | application | **the worker's own writes are not confined at all**; §12.5 |
| Path traversal | canonicalise then compare against a canonical workspace root | application | applies to supervisor-resolved paths only; TOCTOU, §12.4 |
| Symlink escape | reject any reparse point on any path ATLAS-X resolves | application | does not constrain the worker; §12.5 |
| Junction escape | same reparse rejection, **not** `is_symlink` | application | closes the ATLAS-X-side escape; proven exploitable without it (§3.1); worker-side escape remains, §12.5 |
| Reparse-point escape | `os.lstat` reparse-bit check on every component | application | any newly-privileged attacker method |
| Environment leakage | explicit allowlisted child environment | process | none for the built environment |
| Credential leakage | secret values never placed in the child env; worker holds no DB handle | application | worker can still read the user's files if host read is not denied |
| Process spawning | `JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 1` (plus `JOB_OBJECT_LIMIT_PROCESS_COUNT` as a lifetime cap) | **process-level** | counts processes, not intent; a failure to spawn surfaces as an exception inside the worker |
| Child-process inheritance | killed with the job | **process-level** | none for lifetime; contents are unconstrained |
| Internet access | no network control available at this privilege | **none** | **open**, §15 |
| Localhost access | same | **none** | **open**; Ollama is on 11434 and a worker could reach it |
| LAN access | same | **none** | **open** |
| DNS access | same | **none** | **open**; DNS is reachable without any TCP connection to the internet |
| Proxy access | proxy variables absent from the child env | application | an env var is not a network control |
| CPU exhaustion | `JOB_OBJECT_CPU_RATE_CONTROL` + `JOB_OBJECT_LIMIT_PROCESS_TIME` | **process-level** | soft rate control is cooperative at the OS scheduler level; hard kill is the backstop |
| Memory exhaustion | `JOB_OBJECT_LIMIT_JOB_MEMORY` | **process-level** | allocation failure surfaces as an exception inside the worker |
| Disk exhaustion | supervisor measures workspace growth and enforces `max_artifact_bytes` | application | a hostile writer can fill the volume between measurements; §17 |
| Output flooding | byte cap on worker stdout/stderr plus `HARD_OUTPUT_CEILING` | process | supervisor must read pipes continuously, not wait for exit |
| Process hanging | supervisor timer then `TerminateJobObject` | **process-level** | none, this is the mechanism that fixes the Phase 09 gap |
| Timeout bypass | wall-clock deadline enforced by the supervisor, independent of the child | **process-level** | a worker that stops responding cannot extend the deadline |
| Subprocess escape | process count limit plus job kill | **process-level** | a single spawned child is still allowed to exist within the count |
| Working-directory escape | worker `cwd` is the workspace; all paths are workspace-relative | application | `cwd` is a default, not a jail |
| Artifact escape | output collection from the workspace only, with canonicalisation and size caps | application | junction race, §12.4; worker-side escape, §12.5 |
| Host modification | ATLAS-X performs no out-of-workspace file operation | application | **cannot be enforced** against hostile code; §12.5 |
| Database modification | worker receives no connection and no DB path | application | none while the invariant holds; it is a code invariant, not an OS one |
| Secret access | no secret in child env; no DB handle | application | host files remain readable |
| Python runtime escape | fixed interpreter, `-I`, no user `site`, no PYTHONPATH | process | a real escape would need a runtime vulnerability; none claimed |
| Interpreter escape | worker is launched from a pinned venv path, never from a caller-supplied path | application | none |
| Privilege escalation | worker inherits the same non-admin token | OS | ATLAS-X is already non-admin, so there is nothing to escalate to |
| Cleanup failure | job kill-on-close + explicit workspace removal | process | power loss cannot run cleanup code; §19 |
| Orphaned processes | kill-on-job-close when the supervisor exits abnormally | **process-level** | a hard power loss relies on the job handle being closed by the OS |
| Temporary-file leakage | per-execution temp dir removed in a `finally`; `TEMP`/`TMP` point inside the workspace | application | a crash can leave a directory; startup sweep, §19 |
| Concurrent execution abuse | `max_concurrent_executions`, default 1, plus one job per execution | process | the default already serialises |
| Native code / compiled extension | not provided to workers | application | the stdlib can load DLLs; no guarantee |

Two vectors are **open by necessity** and are carried into the threat model
rather than hidden: arbitrary filesystem read and network access. Section 27
states what closing them would cost.

## 6. Security guarantee levels, per control

Format: control, implemented, tested, strength, limitation. Nothing in the
"implemented" column is `yes` for this phase.

| Control | Implemented | Tested | Strength | Limitation |
|---|---|---|---|---|
| Job Object process-tree kill | no (10B) | no (10B) | process-level | needs `ctypes`; no `pywin32` dependency wanted |
| CPU rate control | no (10B) | no (10B) | process-level | cooperative scheduling; hard kill is the backstop |
| Job memory limit | no (10B) | no (10B) | process-level | surfaces as a Python exception, not a clean failure; and `memory_limit_mb` defaults to `None`, so it is currently unspecified (U-12) |
| Process count limit | no (10B) | no (10B) | process-level | `ACTIVE_PROCESS` counts concurrent processes, not intent; thread count has no job flag at all |
| Kill on job close | no (10B) | no (10B) | process-level | depends on the handle being closed by the OS |
| Supervisor wall-clock timeout | no (10B) | no (10B) | process-level | supervisor is in-process; a supervisor crash leaves the job to the OS |
| Workspace allocation and teardown | no (10B) | no (10B) | application | not an ACL; isolates tasks from each other, not the workspace from the host (§12.5) |
| Path canonicalisation and reparse rejection | no (10B) | no (10B) | application | confines ATLAS-X's own operations only; TOCTOU between check and open |
| Output size caps | no (10B) | no (10B) | application | reads must be continuous |
| Artifact size and count caps | no (10B) | no (10B) | application | same measurement race |
| Environment allowlist | no (10B) | no (10B) | application | keys and values are controlled; the host filesystem the worker can read is not |
| No database handle in the worker | **yes (Phase 09)** | **yes** (`test_the_view_never_hands_back_a_connection`) | application | code invariant only; the worker can still open the database file by path (§12.5) |
| Bounded tool schemas | **yes (Phase 09)** | **yes** (`test_numeric_field_without_bounds_is_not_constructible`) | application | per-tool strictness |
| Authorization before execution | **yes (Phase 08/09)** | **yes** (`test_dispatch_without_a_grant_never_runs_the_implementation`) | application | in-process callers can bypass, §8 |
| Filesystem read confinement | **never available here** | n/a | **none** | needs a separate account, AppContainer, or VM |
| Filesystem write confinement | **never available here** | n/a | **none** | same requirement as read; no path check intercepts the worker's own syscalls |
| Network denial | **never available here** | n/a | **none** | needs elevation, WSL, container, or VM |

## 7. Architecture options compared

Each option is scored against the twelve criteria. "Filesystem isolation" means
*read* confinement, which is the hard one.

| | A. In-process | B. Plain subprocess | C. Job Object worker | D. Restricted token / separate account | E. WSL | F. Docker | G. Hybrid C+D |
|---|---|---|---|---|---|---|---|
| FS isolation | none | none | none | partial (ACL/token) | good (Linux fs boundary) | good | partial |
| Process isolation | none | good | good | good | good | good | good |
| Network isolation | none | none | none | none (token alone) | good | good | none |
| CPU control | none | supervisor kill only | **job rate control** | job rate control | cgroup | cgroup | job rate control |
| Memory control | none | none | **job limit** | job limit | cgroup | cgroup | job limit |
| Timeout that interrupts | **no** (Phase 09 gap) | yes | **yes** | yes | yes | yes | yes |
| Child containment | none | kill by PID tree only | **job kill** | job kill | namespace | namespace | job kill |
| Cleanup reliability | n/a | good | **good (kill-on-close)** | good | good | good | good |
| Implementation complexity | trivial | low | **moderate** | high | very high | high | high |
| Works on this host | yes | yes | **yes** | needs a new account | **no distro** | **not installed** | needs a new account |
| Laptop cost | none | ~50 MB | **~50 MB** | ~50 MB + account setup | WSL runtime cost | daemon + VM cost | as C + D |
| Reproducibility | high | high | **high** | medium | medium | **high** | medium |
| Security strength | none | resource only | **resource + lifetime** | resource + partial FS | strong | strong | stronger than C |
| Portability | high | high | **Windows-only** | Windows-only | Windows+Linux | portable | Windows-only |

Option A is today's state and is what makes every Phase 09 residual a real risk.
Option F is the strongest and is unavailable. Option E is strong and is
unavailable. Option C is the strongest option available today with no new
dependency, no elevation, and no new account. Option G is the target if the
operator is willing to create a dedicated low-privilege OS account, and is
recorded as a Phase 10B decision point rather than assumed.

## 8. Recommended architecture

**A dedicated worker process supervised by `ToolDispatcher`, contained by a
Windows Job Object, communicating over a size-capped pipe, with a per-execution
workspace and an explicit environment.** This is option C, with a reserved
upgrade path to G.

```
ToolDispatcher (trusted, in ATLAS-X process)
  |
  |-- 1. authenticate                    (Phase 08, existing)
  |-- 2. registry.find                   (Phase 09, existing)
  |-- 3. validate task id                (Phase 09, existing)
  |-- 4. require_tool_invocation         (Phase 08, existing)  <-- security gate
  |-- 5. enforce call budget             (Phase 09, existing)
  |-- 6. record tool.invoked             (Phase 09, existing)
  |-- 7. validate input + input bound    (Phase 09, existing)
  |
  |     ===== Phase 10 boundary begins here =====
  |-- 8. resolve sandbox policy          (NEW, from ToolDefinition metadata)
  |-- 9. allocate workspace              (NEW, per execution)
  |-- 10. create Job Object + set limits (NEW, ctypes -> kernel32)
  |-- 11. launch worker: pinned interpreter, explicit env, cwd=workspace
  |         stdio pipes, read continuously, capped
  |-- 12. await: exit / deadline / violation
  |         deadline or violation -> TerminateJobObject
  |
  |     ===== Phase 10 boundary ends here =====
  |
  |-- 13. validate output + output bound (Phase 09, existing)
  |-- 14. collect artifacts from workspace with canonicalisation (NEW)
  |-- 15. record provenance              (Phase 09, existing, extended)
  |-- 16. tear down workspace, close job (finally)
  |
  v
atlas.sandbox.worker (untrusted, separate process, no DB handle, no secrets)
```

Steps 1–7 are the real order in `atlas/tools/dispatch.py` and are not changed by
this design. Step 8 replaces the single `definition.invoke(context, validated)`
call at `atlas/tools/dispatch.py:261` with a supervisor launch; the validated
input, the workspace, and nothing else cross the boundary.

Four properties of this shape matter more than the mechanism names.

1. **The supervisor is trusted; the worker is not.** The reverse of Phase 09's
   current arrangement, where the tool body is in the trusted process.
2. **The Job Object is created before the worker starts**, so there is no window
   in which a worker exists outside containment.
3. **The deadline lives in the supervisor**, not in the worker. A worker cannot
   extend its own timeout, because it does not own the clock. This is what
   converts `ToolLimitExceeded` from detection into interruption.
4. **The worker holds no `Database` handle and no secret.** The `OwnedTaskView`
   invariant from Phase 09 is preserved by construction: data the worker needs is
   copied in or fetched through the supervisor, never by handing over a
   connection.

### 8.1 What this does not fix

It does not make filesystem read confinement real, and it does not block network.
Section 4 and section 27 are the honest statement of that. A worker that decides
to read `C:\Users\...\Documents` will succeed on this host. The mitigation is that
no Phase 10 worker is given a reason or a tool that does this, plus the
declaration-level refusal already in `atlas/tools/definition.py` — which is a
policy control, not a jail.

## 9. The strongest isolation achievable here, stated plainly

If the strongest possible isolation cannot be achieved on this machine, that
limitation is stated rather than concealed.

**It cannot be achieved.** There is no container, no VM, and no WSL
distribution, and the operator session is not an administrator, so no firewall
rule and no separate low-privilege OS account can be created. The restricted-token
and AppContainer APIs are present (§3.1) and are assessed in §11, but neither
yields a worker that can import the project venv while being denied the user's
files on the first attempt, and neither is adopted without a tested design of its
own (decision U-4). The honest ceiling on this host is:

> **Process-level containment of lifetime, CPU, memory, and process count, plus
> application-level workspace, output, and environment controls. Filesystem read
> confinement and network denial are not available and are recorded as open.**

Stated as a research consequence: ATLAS-X on this host is a system that *bounds
and observes* untrusted computation, and *declines to give it a tool that would
reach outward*. It is not a system that can *contain* arbitrary code. Any
experiment claiming the latter would be wrong. The Phase 10B hostile-code corpus
below is the first place that overclaiming can be caught, and the evaluation
phases (`docs/SYSTEM_SPECIFICATION.md` §9, Phases 21–33) are where a research
result built on this design would have to defend the same claim.

## 10. Workspace model

| Property | Value | Rationale |
|---|---|---|
| Root | `<project>/data/workspaces/` | project-scoped, gitignored, never `$HOME` or Desktop |
| Per-task | `<root>/task-<task_id>/` | ties to the Phase 08 ownership model |
| Per-execution | `<root>/task-<task_id>/exec-<execution_id>-<attempt>/` | one directory per attempt, so a retry never inherits state |
| Input | `.../in/` | supervisor-written, read-only to the worker by convention |
| Output | `.../out/` | the only directory collected as artifacts |
| Temp | `.../tmp/` | `TEMP` and `TMP` point here, not at `%TEMP%` |
| Metadata | `.../meta/` | supervisor-owned envelope: exit code, timings, digests |
| Workspace root file | `.../meta/workspace.json` | canonical root, task, execution, actor, limits — for audit |
| Forbidden | everything else on the host | no fallback path is ever consulted |
| Naming | `task-<positive int>/exec-<positive int>-<attempt 1..N>` | derived from validated row ids only, never from caller text |
| Ownership | the task owner, enforced by task id → `tasks.user_id` | §22 |
| Permissions | inherited; **no ACL is applied** | an ACL would need a second account — option G |

**Copy, mount, reference, or generate? Generated, and copied in.** The workspace
is created empty and the supervisor copies in only the bytes the invocation
actually needs, bounded by `max_input_dataset_bytes`. It is not a mount (Windows
would require a volume or a reparse target, both of which widen reach), and not
a reference to a live project path (which would let a worker read the source
tree, the `.env` file, and the SQLite database). Generating it is what makes
"the worker has nothing but what the supervisor chose to give it" true by
construction rather than by policy.

The task directory is named after the row id, so a second user's task gets a
different directory. Isolation between users is therefore a *consequence of the
ownership check* (`require_tool_invocation`, step 4 of §8), not a separate
mechanism.
Section 22 makes that dependency explicit, because it is the one place where a
storage bug becomes a cross-user filesystem leak.

## 11. Process and token model

**Selected:** a worker launched with the same non-privilege user token, inside a
Job Object, with `JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 1`.

- **May spawn children?** No. `JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 1` means the job
  holds at most one running process, and the worker already occupies that slot, so
  a child creation is refused by the OS at the moment it is attempted. The
  constant matters: `JOB_OBJECT_LIMIT_PROCESS_COUNT` is a *lifetime* cap on total
  processes associated with the job rather than a concurrent one, so it is
  configured too (also 1) as a second line, but `ACTIVE_PROCESS` is the control
  that actually blocks the spawn. A worker that tries will see a Win32 error from
  `CreateProcess`, not a signal from ATLAS-X.
- **`cmd.exe`, `powershell.exe`, `python.exe`?** Not reachable through any tool
  and not present in a minimal `PATH`. **The design does not rely on that**: the
  process limit and kill-on-job-close hold regardless of what is invoked, which
  is the difference between a policy control and a boundary.
- **Service creation, scheduled tasks, process inspection, process termination?** Nothing in the design provides these, and none is reachable from a tool. Note that a worker is *not* prevented from opening a handle to another process; the containment is on lifetime and count, not on the ability to call `OpenProcess`.
- **Token.** The worker inherits the operator's non-admin token. That token can
  read the user's files; nothing in this design reduces that. A restricted token
  (option D) or AppContainer would, and both are recorded as the Phase 10B
  decision in section 26.

**Why not a restricted token now?** `CreateRestrictedToken` and
`SetTokenInformation` are available, so it is technically reachable, but
producing a token that can still import the standard library while being denied
the user's home directory is delicate, untested territory, and a mistake produces
a worker that cannot run at all. It is proposed as a staged Phase 10B option with
its own tests, not assumed.

**Why not AppContainer?** The API is present, but creating a profile requires
`SeCreateAppContainerProfilePrivilege` or a pre-provisioned profile, and a worker
that needs to import the project's venv would need an explicit filesystem grant to
the venv — which is a package directory inside the project, and granting read
access to it is a step that must be right on the first attempt. Recommended for a
later hardening phase, not for 10B.

## 12. Filesystem policy

**Read this before the table.** The policy below is *what the supervisor permits
and what the supervisor itself will do*. For a well-behaved tool it is the
complete filesystem contract. For a hostile one it is not a jail, and the
distinction is stated in §12.5. A worker process holds the same non-admin token
as ATLAS-X, so it can open, read, create, and overwrite any file the operator
can; no path check in ATLAS-X intercepts a `CreateFile` the worker issues itself.
What path validation buys is that ATLAS-X never *acts* on a path outside the
workspace — it does not stage a file it should not, collect an artifact it
should not, or tear down a directory it should not.

Operations and defaults. Every default is deny.

| Operation | Default | Enforced how | Notes |
|---|---|---|---|
| READ outside workspace | **deny** | policy only; not interceptable | no tool declares it, nothing is staged, no OS control (§4, §12.5) |
| READ inside workspace | allow | supervisor policy | `in/`, `out/` |
| WRITE inside `out/` | allow | supervisor policy | the only write target the design blesses |
| WRITE elsewhere in workspace | deny | supervisor policy | `meta/`, `tmp/` are supervisor-owned |
| WRITE outside workspace | **deny** | **supervisor paths only** | the worker's own writes are not confined; §12.5 |
| CREATE directories | allow inside `out/`, bounded depth and count | supervisor policy | depth cap prevents `a/a/a/...` blowup |
| DELETE | deny outside `out/`; inside `out/` allowed before collection | supervisor policy | after collection the directory is torn down |
| RENAME / MOVE / COPY | allow inside `out/` only | supervisor policy | resolved targets re-validated, not the source |
| SYMLINK | **deny** | host refuses creation; supervisor rejects input paths | creation is already refused on this host |
| JUNCTION | **deny** | **supervisor rejects on every path it touches** | creatable by non-admin here — the primary risk, and the one the canonicalisation control addresses |
| REPARSE POINT | **deny** | superset of the two above | checked via `st_file_attributes`, not `is_symlink` |
| `..` traversal | **deny** | rejected before resolution | |
| absolute paths | **deny** unless inside the canonical workspace | supervisor policy | |
| UNC paths (`\\server\share`) | **deny** | rejected at validation | network redirector |
| device paths (`\\?\`, `\\.\`) | **deny** | rejected at validation | bypasses normal path parsing |
| alternate data streams (`file.txt:stream`) | **deny** | rejected at validation | invisible to size checks otherwise |
| mixed separators, case variation, `8.3` short names | normalise then re-validate | supervisor policy | case-insensitive comparison on NTFS |

### 12.1 Why string prefix checking is not sufficient

Measured on this host: a junction created inside the workspace pointing outside it
produces a path that **passes** `str(path).lower().startswith(workspace.lower())`
and **still reads the outside file**. The check is not merely weak here; it
passes on a working escape. It is rejected as a mechanism.

### 12.2 The required mechanism: canonicalise, then compare

1. Reject the path outright if it contains `..`, a UNC prefix, a device prefix, an
   alternate-data-stream colon after the drive, or a NUL.
2. `os.path.realpath()` / `Path.resolve()` to canonicalise — this is what
   collapsed the junction to its true target in the probe.
3. Compare the **canonical** result against the **canonical** workspace root using
   `os.path.commonpath`, not `startswith` (which has its own `C:\ws-evil` vs
   `C:\ws` class of bug).
4. Walk every component of the canonical path and reject any whose
   `os.lstat` shows `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`.

Step 4 uses `st_file_attributes` because `Path.is_symlink()` returned `False` for
a junction in the probe and `os.path.isjunction` does not exist in Python 3.11.

### 12.3 Order of operations

Canonicalisation happens **before** the size and content checks, so a path is
either inside the workspace or it never reaches a file operation at all. The
reverse order would let a traversal string influence a size measurement.

### 12.4 TOCTOU, stated rather than hidden

Between step 2 (canonicalise) and the actual open, a hostile writer inside the
workspace could swap a directory for a junction. Closing that window properly
requires opening with `FILE_FLAG_OPEN_REPARSE_POINT` and validating the *handle*,
which is a Win32-level implementation with its own complexity.

**The honest position:** the canonicalise-then-compare control defeats every escape
that exists in a static filesystem, and it is the control Phase 10B will test. It
does **not** defeat a race by a process that can write into the workspace
concurrently. The mitigation is to reduce the attacker to that: the worker is the
only process in the workspace, and Phase 10B will test the TOCTOU case explicitly
and record the outcome. A design that claimed race-free validation here would be
claiming a control the implementation does not have.

### 12.5 What this section does not confine, stated plainly

The mechanism above governs **paths ATLAS-X resolves and acts on**: staging input,
collecting artifacts, resolving `relative_path`, sweeping stale workspaces. It
governs nothing the worker does on its own.

A hostile worker can:

- open and read any file the operator can read, including `.env` and the SQLite
  database, because it holds the same non-admin token and no ACL separates it
  from the user's data;
- create, overwrite, or delete files anywhere the operator can, including outside
  the workspace, because nothing intercepts its syscalls;
- use a junction or a hard link it created itself to make a path that *looks*
  workspace-relative, and the canonicalise-then-compare control only sees that if
  ATLAS-X is the one resolving the path.

Confinement of the worker's own I/O requires an OS-enforced boundary — a separate
account, an AppContainer token with an explicit venv grant, or a VM — and §4 and
§27 record that none is available at this privilege. **Write confinement is
therefore the same open item as read confinement**, not a lesser one. What the
path policy does buy is real and worth keeping: ATLAS-X will not be the component
that reads, writes, collects, or deletes outside the workspace, and a worker
cannot trick it into doing so with a crafted string.

The 31 hostile-code scenarios in §20 are written against this distinction: each
one asserts what the *supervisor* does, and the scenarios that would succeed
against a hostile worker are labelled as such rather than marked as passing
controls.


## 13. Environment and secret policy

The child environment is **built key by key from an allowlist**. It is never
inherited, and interpreter flags are not relied on: `-I -E -s` still left 51 keys
visible in the probe.

| Variable | Visible to worker | Reason |
|---|---|---|
| `PATH` | yes, **overridden** to a minimal value | the worker needs the interpreter, not a search path |
| `TEMP`, `TMP` | yes, **inside the workspace** | keeps temp files in the sandbox |
| `USERPROFILE`, `HOME`, `APPDATA`, `LOCALAPPDATA` | **no** | these point at the user's real data |
| `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP` | **no** | interpreter behaviour must not be steerable |
| `PYTHONWARNINGS`, `PYTHONINSPECT` | **no** | no warnings rewriting, no REPL |
| `PYTHONHASHSEED` | yes, **fixed to a constant** | determinism only; it is not a control |
| `OLLAMA_*` | **no** | Ollama is on 11434; the worker has no business knowing |
| `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY` | **no** | removes proxy steering |
| `AWS_*`, `AZURE_*`, `GCP_*`, `GOOGLE_*` | **no** | cloud credentials |
| `*_API_KEY`, `*_TOKEN`, `*_SECRET*` | **no**, by pattern **and** by value | belt and braces |
| `ATLAS_APPLICATION_SECRET_KEY` | **no** | the application secret must never reach untrusted code |
| `ATLAS_DATABASE_PATH` | **no** | the worker gets no database |
| `ATLAS_*` generally | **no** — not one of them | the worker needs no `ATLAS_` variable: it gets its validated input in the envelope and no configuration at all. A future variable needed by a specific tool must be named individually, never matched by prefix |
| anything else | **no** | default deny |

**Secrets that must never enter the sandbox:** the application secret key; any
`password_hash`; any session token (raw or digest); the database path and
credentials; API keys; cloud credentials; the user's environment wholesale.

Two belt-and-braces rules beyond the allowlist, because an allowlist with one gap
is a leak: the supervisor strips any value equal to a known secret (via
`Settings.secret_values()`, `atlas/config/settings.py:79`) and any key matching a
secret-shaped pattern, even if a future edit adds it to the allowlist by mistake;
and the worker is launched with a **sanitised environment that is asserted empty
of secrets** before launch, failing closed if the assertion does not hold.

`secret_values()` today returns only `application_secret_key`, because that is
the only secret in `Settings` (`_SECRET_FIELDS`). The value-based check is
therefore a floor, not a complete inventory: a session token, a proxy
credential, or a database password read from elsewhere in ATLAS-X would not be
caught by it, which is why the pattern rule and the key allowlist both apply
independently.

The sandbox must not become an exfiltration mechanism, and the honest limit is
stated in section 27: without network denial, "no secrets in the environment"
still leaves a worker that can read host files.

## 14. Network policy

**Default: DENY.** That is the declared policy, and this is the honest accounting
of what it can be.

| Target | Policy | Enforceable here? |
|---|---|---|
| Internet | deny | **no** |
| LAN | deny | **no** |
| Loopback (127.0.0.1) | deny | **no** |
| Ollama at `127.0.0.1:11434` | deny | **no** — and it is listening, verified in §3 |
| DNS resolution | deny | **no** |
| Proxies | deny | **no**, though proxy variables are absent |

"No internet" is not "no network", and this design says so explicitly. On this
host, with no elevation, a worker can open a socket to anything the operator's
machine can reach — including a local model server and anything on the LAN.

What the design *can* do honestly, and should be credited only for this:

1. **Remove the intent and the affordance** — no proxy variables, no `OLLAMA_*`,
   no tool that has any use for a network, and `NetworkAccess.ALLOWED` refused at
   registration (already implemented, `test_network_access_is_refused`).
2. **Detect** a violation attempt: the Phase 10B hostile-code corpus (§20,
   scenarios 13–15) includes a worker that attempts a connection, and the attempt
   is recorded as a security violation rather than treated as a tool error.
3. **Enforce** it at the next gate, when the operator can choose: a firewall rule
   for the worker (needs elevation), a WSL distribution, a container, or a VM.

**Recommendation for the human gatekeeper:** if network denial is a requirement
rather than an aspiration, the cheapest real fix on this host is to install a WSL
distribution and run workers inside it, which converts network and filesystem
confinement from "not available" to "OS-enforced". That is a host change, not a
code change, and it is the single highest-value hardening step available. It is
recorded as decision **U-1** in section 26 rather than assumed.

## 15. Resource limits, and the detect/interrupt distinction

The distinction the Phase 09 report demands: a timeout checked after the call
returns is **not** a timeout.

| Limit | Source | Level | Detect or interrupt |
|---|---|---|---|
| wall-clock | `min(ToolLimits.timeout_seconds, Settings.max_subprocess_seconds)`, hard ceiling 600 | process | **interrupts** — supervisor deadline then job kill |
| CPU time | `JOB_OBJECT_LIMIT_PROCESS_TIME` (per-process, 100 ns units) and rate control | process | **interrupts** at the hard ceiling |
| memory | `JOB_OBJECT_LIMIT_JOB_MEMORY`, `memory_limit_mb` | process | **interrupts**; surfaces as an exception in the worker |
| process count | `JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 1` | process | **prevents** |
| output bytes | `HARD_OUTPUT_CEILING` 4 MiB + `max_output_bytes` + `max_output_chars` | application | **detects**, then the worker is killed |
| artifact bytes | `max_artifact_bytes` (needs a ceiling added) | application | **detects** |
| input bytes | `max_input_dataset_bytes` | application | **refuses** before launch |
| disk | supervisor measures workspace growth | application | **detects**; cannot prevent a fast fill, and cannot prevent a write outside the workspace at all (§12.5) |
| threads | no job flag | none | not enforced |
| open handles | not enforced | none | n/a |
| concurrent executions | `max_concurrent_executions` (default 1) | application | serialises sandboxed executions; enforced by ATLAS-X, not the OS |
| tool calls per task | `max_tool_calls` (already enforced) | application | **refuses** |

Two source notes, both from the real configuration. The wall-clock deadline is
the **minimum** of the tool's declared `timeout_seconds`
(`MAX_TIMEOUT_SECONDS = 600`) and `Settings.max_subprocess_seconds` (default 30,
ceiling 600, currently unenforced and unused); taking the minimum means a tool
cannot declare a budget longer than the operator allows. And
`JOB_OBJECT_LIMIT_PROCESS_TIME` is a *per-process* limit, so it applies to the
worker individually — which is the right semantics here, since the job is meant to
contain exactly one process.

`cpu_limit_cores` and `memory_limit_mb` are `None` by default and have no
ceiling, which `docs/CONFIGURATION_REVIEW.md` MEDIUM-2 already flags. Phase 10B
must add ceilings, because a limit that can be configured to an absurd magnitude
is not a bound. With `memory_limit_mb` unset, the job memory limit is proposed
from a documented default rather than from configuration, and that default is
itself a decision this document does not make silently: it belongs with U-9.

A limit that is **detectable** here is not stated as enforced. Disk and output
caps are measured by the supervisor in a loop, so a worker that fills the volume
between two measurements wins a race; the honest control is the volume, not the
loop.

## 16. Windows process supervision

The Job Object is created and configured **before** the worker is launched, and
the worker is assigned to it as the first step of creation. Proposed sequence for
Phase 10B, via `ctypes` against `kernel32` (no `pywin32`, keeping the dependency
count at zero):

1. `CreateJobObjectW(NULL, NULL)` — verified to succeed as non-admin.
2. `SetInformationJobObject` with `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`:
   `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`,
   `JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 1`,
   `JOB_OBJECT_LIMIT_PROCESS_COUNT = 1` (lifetime cap, second line),
   `JOB_OBJECT_LIMIT_JOB_MEMORY`,
   `JOB_OBJECT_LIMIT_PROCESS_TIME`,
   `JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION`.
3. `CreateProcessW` with `CREATE_SUSPENDED`, `CREATE_NO_WINDOW`, and
   `CREATE_UNICODE_ENVIRONMENT` (mandatory when an explicit `lpEnvironment` block
   is supplied), plus an explicit Unicode double-NUL-terminated environment block
   and working directory; **not** `shell=True`, never a command string.
4. `AssignProcessToJobObject(job, pi.hProcess)`.
5. `ResumeThread(pi.hThread)`.

`CREATE_UNICODE_ENVIRONMENT` is called out because omitting it with a custom
`lpEnvironment` is the classic cause of a worker that starts with a mangled or
empty environment — a failure that would look like a secret-leak bug during
testing rather than a flag mistake.

Suspending first is what closes the race in which a worker exists outside
containment for a few milliseconds. `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is what
guarantees no orphan: if the supervisor crashes or is killed, the OS closes the
handle and the tree dies.

Two constraints recorded honestly: the worker runs the project's own venv
interpreter, so the allowlisted environment (§13) must not break importing it —
that is a tension between minimising the environment and keeping the interpreter
functional, and it is why the environment module is built and tested before
`job.py`; and the supervisor itself must never be placed *inside* the job, or a
timeout kill would take down ATLAS-X. The probe confirmed the current process is
not already in a job, so no nesting conflict exists today.

`JOB_OBJECT_CPU_RATE_CONTROL` is a *rate* control and is scheduler-cooperative.
The design therefore treats it as a throttle, with `JOB_OBJECT_LIMIT_PROCESS_TIME`
as the hard ceiling and job kill as the backstop. Describing rate control as a
hard CPU limit would be inaccurate.

## 17. Cleanup

| Situation | Guarantee | Level |
|---|---|---|
| success | worker exits, stdout drained, workspace collected, directory removed | application |
| tool failure | same, plus the failure is recorded | application |
| timeout | `TerminateJobObject`, drain what was written, then remove | process + application |
| killed by the job on violation | supervisor observes non-zero exit and the violation marker | process |
| supervisor exception | `finally` still runs: job closed, workspace removed | application |
| supervisor process crash | kill-on-job-close kills the tree; workspace **remains** | process only |
| hard power loss | nothing runs; workspace and job rely on OS cleanup | none |
| orphaned child | impossible while the job handle is held, by kill-on-job-close | process |
| partial artifact generation | collection is a copy from `out/`; a partial file is size-capped and recorded as partial, never as a complete artifact | application |

"Cleanup is guaranteed" would be false in the power-loss row, so the design does
not claim it. The compensating control is a **startup sweep**: on supervisor
start, stale workspace directories older than the configured retention window are
removed and their existence is logged. That converts an unbounded leak into a
bounded one without pretending a crash handler can run during a power cut.

## 18. Artifact and database boundary

**Artifacts.** A file becomes an artifact only if it is inside `out/`, survives
canonicalisation plus reparse rejection, is within `max_artifact_bytes`, and its
count is within a bounded number of entries. Collection is a **copy** into the
artifact store, then the workspace is torn down, so an artifact never depends on
the workspace continuing to exist. `artifacts.relative_path` is written as a path
**relative to the workspace root**, never absolute and never caller-supplied —
`docs/STORAGE_REVIEW.md` §13 records that the column is currently unvalidated,
and this is where that stops being true. The Phase 09 statement stands: owning a
row still authorises no host path, and this boundary is about the *writer*, not
the reader.

**Database.** The worker receives **no database access** in any form: no
connection, no path, no credentials. Data it needs is either in the copied input
files or fetched by the supervisor through the existing `OwnedTaskView`. This
extends the Phase 09 invariant rather than replacing it, and it means the worker
cannot modify the database even maliciously, because it never learns where it is.

## 19. Integration with the tool registry and authorization

**The sandbox consumes Phase 09 declarations; it does not invent a second
permission system.** From `ToolDefinition`: `filesystem_access`,
`network_access`, `requires_sandbox`, `limits.timeout_seconds`,
`limits.max_artifact_bytes`, `determinism`, and `provenance_fields`. Where a
declaration is outside the admissible set, the sandbox **refuses** the invocation
— the same fail-closed pattern as `atlas/tools/definition.py`, and widening
`ADMISSIBLE_FILESYSTEM_ACCESS` or `ADMISSIBLE_NETWORK_ACCESS` becomes a reviewed
source change made together with the phase that supplies the real control. The
Phase 09 record of this contract is `docs/TOOL_REGISTRY_REVIEW.md`; this section
extends it and contradicts none of it.

One registration-time refusal is Phase 10's to lift, and it cannot be lifted by
configuration: `requires_sandbox=True` raises `ToolUnsupported` at
`atlas/tools/definition.py:301-304`, so today a tool cannot even declare that it
wants confinement. `FilesystemAccess.HOST_READ` and `HOST_WRITE` are refused the
same way. Until those two refusals are changed in source, the sandbox has no
eligible tool (see U-6 and U-12), and the honest Phase 10B deliverable is
"boundary plus a reviewed declaration change", not "boundary alone".

**Order, and it is not negotiable.** This is the real order in
`ToolDispatcher.dispatch` (`atlas/tools/dispatch.py:231-283`), not an idealised
one:

```
authenticate                       dispatch.py:231
  -> registry.find                 dispatch.py:232   metadata only; allows nothing
  -> validate task id              dispatch.py:233
  -> require_tool_invocation       dispatch.py:235   <-- the authorization gate
  -> enforce call budget           dispatch.py:241
  -> record tool.invoked           dispatch.py:244
  -> validate input + bound        dispatch.py:253-255
  -> [Phase 10] sandbox policy     NEW
  -> [Phase 10] workspace          NEW
  -> [Phase 10] launch + await     NEW
  -> validate output + bound       dispatch.py:281-283
  -> artifact collection           NEW
  -> record provenance             dispatch.py:297
  -> cleanup                       finally
```

Registry resolution sits *before* authorization by deliberate Phase 09 design: the
capability name authorization checks is read from the resolved definition, and
resolving metadata discloses no user data. The gate is
`require_tool_invocation`, and the sandbox is strictly downstream of it. **No
workspace is allocated, no process is created, and no job object is opened before
authorization succeeds.** The existing test
`test_dispatch_without_a_grant_never_runs_the_implementation` is the invariant
that must keep passing after Phase 10B — extended to assert the *worker* is never
launched, not merely that no result comes back.

The design does not reorder Phase 09. Reordering would change a frozen,
tested boundary for no security gain, and the ordering above already satisfies
the requirement that authorization precede every sandbox effect.

`ATLAS_TOOL_SANDBOX_MODE` is explicitly **not** introduced. A configuration switch
that bypasses the sandbox would be exactly the kind of "disable security" knob
`docs/CONFIGURATION_REVIEW.md` §4 forbids.

## 20. Malicious-tool scenarios Phase 10B must test

Thirty-one negative tests, each of which must fail safely rather than merely
fail: the worker is killed or refused, the violation is recorded, and no state
*outside the workspace* is left changed **by ATLAS-X**.

The **Class** column is the part that keeps this table honest, and it exists
because of §12.5:

- **supervisor control** — a real, testable ATLAS-X behaviour. The test asserts
  ATLAS-X does the right thing.
- **policy only** — ATLAS-X never provides the affordance (nothing staged, no
  capability declared, no path passed through). The test asserts the affordance
  is absent, which is weaker than denial.
- **known-open** — the hostile action is expected to **succeed** on this host.
  The test asserts the sandbox does not stop it and that the attempt is recorded.
  Marking these as passing controls would make the suite green by lying.

| # | Class | Scenario | Expected |
|---|---|---|---|
| 1 | policy only | read the parent directory | nothing above the workspace is staged or referenced; a worker that reaches out anyway is **not stopped** (§12.5) |
| 2 | policy only | read ATLAS-X application source | not copied in and not referenced; a worker that opens the source path directly is **not stopped** |
| 3 | policy only | read `.env` | not copied in; no secret in the workspace; a direct open of the real `.env` is **not stopped** |
| 4 | policy only | open the SQLite database | no path, connection, or handle is passed to the worker; a worker that guesses the path is **not stopped** |
| 5 | policy only | reach another user's workspace | the supervisor allocates only the authorized task's directory; a worker that constructs a sibling path is **not stopped** |
| 6 | supervisor control | ATLAS-X writes outside the workspace via a crafted path | canonicalisation plus reparse rejection rejects it; nothing written, nothing collected |
| 7 | supervisor control | `../` traversal in a tool-supplied path | rejected before resolution |
| 8 | supervisor control | symlink escape via a tool-supplied path | explicitly rejected; creation is separately refused by the host |
| 9 | supervisor control | **junction escape via a tool-supplied path** | reparse rejection blocks it — the control the probe proved necessary |
| 10 | process-level | spawn a child process | process-count limit; no second process survives |
| 11 | process-level | spawn PowerShell | same; and it is not reachable via a minimal `PATH` |
| 12 | process-level | spawn `cmd.exe` | same |
| 13 | known-open | internet request | **expected to succeed on this host** — recorded as a known-open vector, not a passing test |
| 14 | known-open | localhost request | **expected to succeed** — Ollama is on 11434 |
| 15 | known-open | DNS lookup | **expected to succeed** |
| 16 | supervisor control | read `ATLAS_APPLICATION_SECRET_KEY` | absent from the child environment; asserted at launch |
| 17 | process-level | infinite loop | job kill at the deadline; `ToolLimitExceeded` |
| 18 | process-level | memory exhaustion | job memory limit; worker dies; recorded as a limit failure |
| 19 | supervisor control | disk exhaustion | supervisor measures; recorded as a violation; volume not guaranteed intact |
| 20 | supervisor control | stdout flooding | output cap enforced while running, not after exit |
| 21 | process-level | process-tree explosion | process-count limit; tree killed |
| 22 | process-level | exceed the timeout | interrupted, not merely detected |
| 23 | supervisor control | crash mid-execution | recorded as a failure; no partial artifact recorded as complete |
| 24 | supervisor control | write a partial output file | recorded as partial |
| 25 | process-level | orphan a child then exit | kill-on-job-close; no orphan |
| 26 | supervisor control | artifact escape via a path | `relative_path` written relative and re-validated |
| 27 | supervisor control | cross-task workspace access | a task id the actor does not own is refused at step 4; no directory allocated |
| 28 | supervisor control | bypass authorization to reach the sandbox | `require_tool_invocation` denies; no launch |
| 29 | supervisor control | environment secret scan | the launch-time assertion catches a regression |
| 30 | known-open | worker creates its own junction, then writes through it | **expected to succeed** — no OS control confines the worker (§12.5); ATLAS-X's own collection must still refuse the path |
| 31 | process-level | supervisor killed mid-execution | tree dies via kill-on-close; workspace swept at next startup |

Scenarios 1–5 and 30 are the uncomfortable ones, and they are listed as they are
because the alternative is a suite that passes by asserting something the design
cannot deliver. A hostile worker *will* read `.env` if it guesses the path. What
the design prevents is ATLAS-X handing it the path, staging the file, or granting
the capability — and §27 states the rest.

Scenarios 13, 14, and 15 are listed as **expected to succeed**. Marking them
"expected to fail" would make the suite green by lying, which is the specific
failure mode this project is built to avoid.

## 21. Security invariants

Stated as testable assertions.

1. An unauthorized tool invocation never reaches sandbox launch, worker creation,
   or workspace allocation.
2. A workspace is allocated only after `require_tool_invocation` has allowed.
3. **ATLAS-X never reads, writes, collects, or deletes outside the workspace**, and
   no crafted path can make it do so; canonicalisation plus reparse rejection is
   the mechanism. The worker's own I/O is *not* confined on this host (§12.5), and
   no invariant may be written or tested as though it were.
4. The worker receives no secret, asserted at launch.
5. Network is denied **by policy**; on this host it is not denied by enforcement,
   and no document or test may claim otherwise.
6. Every limit is bounded; a limit that can be configured to an absurd magnitude
   fails validation.
7. A timeout interrupts execution rather than merely detecting it.
8. Child processes are contained by the job for the job's lifetime.
9. Cleanup runs on normal and abnormal completion; the power-loss case is
   mitigated by a startup sweep and is not claimed as guaranteed.
10. Artifacts remain task-scoped and are written relative to the workspace root.
11. A sandbox failure can never become a successful task completion; it maps to
    a recorded failure, never to a result.
12. Every security violation fails closed: the worker is killed, the violation is
    recorded, and the invocation fails.
13. The job is created and configured before the worker process exists.
14. The supervisor is never placed inside the job it supervises.
15. No configuration switch can disable the sandbox, authorization, or redaction.

## 22. Resource ownership

A workspace path is `task-<id>/exec-<id>-<attempt>`, and `task_id` reaches
allocation only through `require_tool_invocation`, which established that the
authenticated actor owns that task. Ownership of a workspace is therefore
inherited from the Phase 08 check rather than re-derived.

**The dependency is explicit and it is the weakest link in this design:** if
`tasks.user_id` were ever wrong, a workspace would be allocated for a task the
actor does not own. The design does not add obscurity — random directory names,
unguessable paths — as a substitute. The guarantee is "the same check that
authorises a tool call also decides which directory it may write to". The
cross-user matrix for this surface belongs in the Phase 10B test set
(`tests/test_sandbox_workspace.py`, §25), alongside the authorization check
`docs/STORAGE_REVIEW.md` §12 requires before execution features exist: "require
authorization before every tool dispatch and every read/write of an
execution-owned resource". A workspace directory *is* an execution-owned resource,
so that requirement lands here.

This is a guarantee about the supervisor's allocation, not about the
filesystem's secrecy. Per §12.5, a hostile worker that guesses a sibling
directory name can read it; the isolation is that ATLAS-X never allocates, writes,
or collects across tasks.

Two further properties: workspaces are named from validated positive row ids only,
so no caller-supplied string ever reaches a path component; and collection copies
`out/` into the artifact store under the owning execution, so another task's
artifacts are unreachable by construction.

## 23. Performance

Estimates for this host, stated as expectations to be measured in the benchmark
phases (`docs/SYSTEM_SPECIFICATION.md` §9, Phases 21–33) rather than as measured
results. Nothing here has been benchmarked.

| Stage | Estimate | Note |
|---|---|---|
| Job Object create + configure | < 1 ms | a few kernel calls |
| Python interpreter startup | 40–120 ms | the dominant fixed cost |
| `atlas` package import in the worker | 20–60 ms | keep the worker entry point minimal to cut this |
| Workspace create + teardown | < 10 ms | |
| Input copy | dominated by `max_input_dataset_bytes` | 50 MB is the current default ceiling |
| Output drain | proportional to output | must be continuous |
| Memory per idle worker | ~20–30 MB RSS | |
| Per-execution peak | bounded by the job memory limit | `memory_limit_mb` is `None` by default and needs a ceiling |
| With `max_concurrent_executions = 1` | one worker at a time | the default already serialises |

Two consequences worth stating. A Python worker costs on the order of 100 ms and
tens of MB per invocation, which is cheap against `max_execution_seconds = 120`
and irrelevant next to a local model call. And `max_concurrent_executions = 1`
means concurrency is not a throughput mechanism here; the benchmark phases should
measure whether raising it is ever worth it before anyone tries.

## 24. Phase 10B implementation plan

In dependency order. Steps 1–4 are prerequisites; 5–8 are the boundary itself.

1. `atlas/sandbox/paths.py` — canonicalisation, reparse rejection, and the
   traversal corpus. Pure functions, no I/O beyond `lstat`, fully unit-testable.
2. `atlas/sandbox/policy.py` — resolve a `ToolDefinition` into a sandbox policy;
   refuse inadmissible declarations. No second permission system (§19).
3. `atlas/sandbox/workspace.py` — allocation, layout, staging, collection, and
   teardown, including the startup sweep (§17).
4. `atlas/sandbox/environment.py` — the explicit allowlisted child environment and
   the launch-time secret assertion (§13).
5. `atlas/sandbox/job.py` — the `ctypes` Job Object binding (§16). Isolate this
   module so every unsafe call is in one reviewable place.
6. `atlas/sandbox/worker.py` — the child entry point: receive a validated envelope,
   run the named body, return a size-capped result, exit non-zero on any violation.
7. `atlas/sandbox/supervisor.py` — launch, deadline, continuous drain, kill,
   cleanup, and provenance. Orchestrates 1–6.
8. Wire `atlas/tools/dispatch.py` to the supervisor, replacing the single
   `definition.invoke(context, validated)` call at `atlas/tools/dispatch.py:261`
   and leaving steps 1–7 untouched, so `require_tool_invocation` stays upstream of
   every launch. Extend
   `test_dispatch_without_a_grant_never_runs_the_implementation` to assert **no
   launch**, not merely no result.
9. Lift the `requires_sandbox` registration refusal in
   `atlas/tools/definition.py:301-304` and add at least one tool that declares it,
   so the boundary has a caller (U-6). This step exists because without it steps
   1–8 ship a sandbox nothing can reach.
10. Ceilings in `Settings` for `max_artifact_bytes`, `memory_limit_mb`, and
    `cpu_limit_cores` (U-9 / `docs/CONFIGURATION_REVIEW.md` MEDIUM-2), and a
    default job memory limit that is never unset (U-12).
11. `database_path` scope decision (U-8 / MEDIUM-1), since the workspace root sits
    under the project data directory and the two must be reasoned about together.

Sequenced deliberately: 1–4 are pure logic and can be exhaustively tested without
ever starting a process, so the security-critical decisions are verified before
any unsafe code exists. 5 is the only module that calls Win32, and 7 is the only
one that can kill anything. 9–11 are last because they are the steps that change
what the product *permits*, and they should be reviewed against a boundary that
is already tested.

Whether step 8 routes every tool or only sandbox-declaring ones is decision U-5;
this plan assumes route-everything, and the difference is described in §26.

## 25. Tests planned for Phase 10B

`tests/test_sandbox_paths.py` — the traversal and reparse corpus: `..`, absolute,
UNC, `\\?\`, `\\.\`, alternate data streams, mixed separators, case variation, 8.3
short names, symlink, junction, reparse point, a junction created between check
and access, and a positive control proving canonicalisation does not reject
legitimate in-workspace paths.

`tests/test_sandbox_policy.py` — declarations map to policies; inadmissible
declarations are refused; no second permission system exists.

`tests/test_sandbox_workspace.py` — layout, staging bounds, collection, teardown,
the startup sweep, cross-task separation, and traversal-named paths never reaching
the filesystem.

`tests/test_sandbox_environment.py` — the allowlist; every forbidden variable
absent; the launch-time secret assertion; and a regression test that fails if a
variable is added to the allowlist while holding a secret value.

`tests/test_sandbox_job.py` — job creation and limit configuration; tree kill;
kill-on-close; `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` blocking a real spawn attempt;
and that the supervisor is not inside the job.

`tests/test_sandbox_supervisor.py` — timeout **interrupts** (asserts the worker
did not exit on its own); memory limit; output flood; crash; partial output; and
cleanup on every path.

`tests/test_sandbox_integration.py` — the dispatcher wires the supervisor; the
unauthorized case launches nothing; provenance records the sandbox outcome; no
database path, connection, or handle reaches the child; and the Phase 09 suite
still passes unchanged.

`tests/test_sandbox_malicious.py` — the 31 scenarios in section 20, each tagged
with its **Class** column value. The 13/14/15/30 known-open cases assert that the
sandbox does *not* stop the action and that the attempt is recorded — they are
written to fail if a future change accidentally starts enforcing network denial,
so the guarantee can never be claimed by accident. Scenarios 1–5 assert absence
of affordance, not denial. A test module that cannot express that distinction
should not be written, because a suite asserting denial here would be lying.

The negative tests matter more than the positive ones here. A suite that only
proves a sandbox *works* would not have caught the junction hole, and the junction
hole was found by probing the host, not by testing the code.

## 26. Unresolved decisions

Carried to the human gatekeeper rather than guessed.

| ID | Decision | Why it is open | Recommendation |
|---|---|---|---|
| U-1 | Is network denial a requirement or an aspiration? | cannot be enforced at this privilege; a WSL distro would make it OS-enforced | install a WSL distro if the answer is "requirement"; it is the highest-value hardening step available |
| U-2 | Is filesystem **read and write** confinement a requirement? | needs a second OS account, AppContainer, or a VM; write confinement is exactly as unavailable as read (§12.5) | if yes, option G; if no, say so in writing so the non-guarantee is a decision rather than a failure |
| U-3 | Do sandboxed tools need host read at all? | determines whether U-2 is urgent | no tool currently needs it; keep the refusal |
| U-4 | Restricted token or AppContainer in 10B? | both reachable in principle; both delicate | plain Job Object first; token as a later hardening phase |
| U-5 | Should the 5 built-in tools run in the sandbox at all? | they are pure functions or owner-scoped reads; a process costs ~100 ms for no added safety | **recommend route everything in 10B**, so the boundary has a real caller, and revisit once a sandbox-only tool exists — paying ~100 ms for continuous coverage is cheaper than an untested code path |
| U-6 | Who may grant `requires_sandbox`? | a sandbox-requiring tool is refused today; widening is a source change | keep it a reviewed source change, never a grant |
| U-7 | Retention window for the startup sweep | affects disk bound | 24 hours, configurable, logged |
| U-8 | Does `database_path` move under the project root? | MEDIUM-1; the workspace root depends on it | yes, in 10B |
| U-9 | Add ceilings to `max_artifact_bytes`, `memory_limit_mb`, `cpu_limit_cores` | MEDIUM-2 | yes, in 10B |
| U-10 | Worker I/O mechanism | stdin/stdout envelope vs a file in the workspace | stdin/stdout with a cap; a file adds a TOCTOU surface |
| U-11 | `SECURITY_BLOCKED` as an execution status | `docs/UI_ARCHITECTURE.md` C-04; no such status, column, or record exists in the schema | a Phase 12 decision; this design does not create it |
| U-12 | Default job memory limit when `memory_limit_mb` is unset | `JOB_OBJECT_LIMIT_JOB_MEMORY` needs a number; `None` means "no job memory limit", which defeats C6 | propose a bounded default and reject the unset case, or refuse to launch — but do not launch unbounded by default |

U-5 is worth the reviewer's attention, and it changes the shape of Phase 10B, so
the consequence is stated rather than left implied. Two routings are possible:

- **Route everything (the conservative default in §8 and §24).** Every invocation
  crosses the boundary. The sandbox is continuously exercised by real traffic, so
  it cannot rot into an untested code path, and there is no second execution mode
  to reason about. Cost: roughly 100 ms and tens of MB per call, on five tools
  that gain no confinement from it.
- **Route on declaration.** Only tools that declare `requires_sandbox=True` (or
  request a non-`NONE` `filesystem_access`) launch a worker; the rest stay
  in-process. Cheaper and more honest about the five existing tools, but the
  sandbox then has **no production caller** until a tool needs it, so its only
  evidence of working is the test suite.

The document describes the boundary as if everything routes through it, because
that is the version in which the guarantees in §27 are actually true for every
invocation. Routing on declaration is a per-tool optimisation, not a different
architecture, and it narrows those guarantees to the tools that opt in. This
design does not choose; the gatekeeper does, and §27 is written to be read
alongside the answer.

Whichever is chosen, one consequence is identical: `requires_sandbox=True` is
refused at registration in `atlas/tools/definition.py:301-304`, so **no tool can
currently declare it**. Routing on declaration therefore requires a reviewed
source change to that refusal (U-6) and produces zero sandboxed invocations
until such a tool exists. A Phase 10B that ships the boundary without also
widening that refusal ships a sandbox with no caller.

## 27. Security guarantees and non-guarantees

**Enforceable on this host, and what each actually protects.** These apply to
tools that actually run in the worker, which under decision U-5 may be none of
the current five:

1. **A runaway or malicious tool is killed.** CPU, memory, process count, and
   wall-clock are bounded by the OS, and the whole tree dies on timeout, on
   violation, and if the supervisor dies. This closes the Phase 09 gap where the
   elapsed budget only detected an overrun.
2. **Tool computation cannot outlive or outgrow its bounds**, and cannot spawn an
   unbounded process tree.
3. **Untrusted code receives no secret, no database handle, and no ambient
   environment** — by construction of the launch, and asserted before it.
4. **ATLAS-X acts only on canonical, in-workspace paths.** Traversal, absolute
   paths, UNC, device paths, alternate data streams, symlinks, junctions, and
   reparse points are all rejected before any file operation ATLAS-X performs.
   This is a guarantee about ATLAS-X's own behaviour, not about the worker's.
5. **Authorization precedes every launch**, and the existing Phase 09 test proves
   no implementation is reached without it.
6. **Security violations fail closed** and are recorded as violations rather than
   as ordinary tool errors.

**Not guaranteed, and this list is the point of the document:**

1. **Filesystem read confinement. Not available at this privilege.** Malicious
   code can read the user's files, including `.env` and the SQLite database, by
   opening a path it constructs itself. Nothing is staged or passed to it, and no
   tool declares host read — but that is the absence of an affordance, not a jail.
2. **Filesystem write confinement. Also not available, and equal to item 1.** A
   worker can create, overwrite, or delete anywhere the operator can, and can
   create its own junction or hard link. ATLAS-X confines its own operations
   (§12.5); it does not confine the worker's. Claiming otherwise in any document
   or test is a defect.
3. **Network denial. Not available at this privilege.** Malicious code can reach
   the internet, the LAN, localhost, and the local model on 11434, and can resolve
   DNS. "Deny" is the declared policy; it is not an enforced one.
4. **No container or VM isolation.** `docs/THREAT_MODEL.md` non-guarantee 1 stands
   unchanged, and residual B3/C4/C5 remains **Hi** until a WSL distribution, a
   container, or a VM exists. **A design document changes none of this.**
5. **No protection against the local admin**, a kernel or runtime vulnerability, or
   a malicious native extension.
6. **Race-free path validation is not claimed.** Canonicalise-then-compare defeats
   every static escape ATLAS-X must resolve; a concurrent attacker inside the
   workspace is a narrower but open window (§12.4).
7. **Cleanup is not guaranteed after power loss.** A startup sweep bounds the
   leak.
8. **Disk exhaustion is detected, not prevented.**
9. **In-process callers still bypass authorization.** Phase 09's residual stands:
   the guarantee is that every *request* is authorized, not that in-process code
   cannot skip it.
10. **Provenance is not tamper-evident**; digests are not a chain.
11. **The sandbox may have no caller.** Under decision U-5 with the
    `requires_sandbox` refusal left in place, nothing in the product routes
    through the worker, and the boundary's only evidence of correctness is its
    test suite.

## 28. Documentation updates this phase requires

This phase changes one document and adds references, and deliberately does not
rewrite others.

- **`docs/SANDBOX_DESIGN.md`** (this file), created.
- **`SECURITY.md`** — one short pointer, added after the design is approved rather
  than now, so no document claims a control that does not exist.
- **`docs/THREAT_MODEL.md`** — B3, C3, C4, C5, and C6 mitigation lines become
  `(design)` referencing this document, and their residual ratings are re-stated
  against §27 rather than lowered. **They do not improve in Phase 10.** A design
  document changes nothing about the host, and claiming a mitigation that is only
  written down would be the single most damaging thing this project could do at
  this gate. When that edit is made, C4 ("a subprocess shares the OS filesystem
  view") should also be extended to name **write** access, since §12.5 shows read
  and write are equally unconfined; the threat as currently worded understates it.
- **No other document is modified.** `docs/UI_ARCHITECTURE.md` is left alone; its
  Part 13 sandbox rules and C-02/C-03/C-04 contradictions belong to their phases.
  `docs/environment-reconnaissance.md` is left as a dated historical snapshot
  rather than edited, because §3 supersedes it and a second source of host truth
  is worse than an out-of-date one that says its date.

## 29. Design verification

Checks performed on this document, and what each found. The "found" column records
defects this pass actually caught, because a verification table that only ever
says "yes" is not a verification.

| Check | Result | Found / evidence |
|---|---|---|
| All required sections present | pass | §1–§29 |
| Every security claim names an enforcement mechanism | pass after fix | §4 and §6 give the level for each; §12.5 added because the first draft attributed confinement to the supervisor's path checks and a reader could have taken it for a jail |
| Dispatch order matches the real code | pass after fix | §8 and §19 now quote `atlas/tools/dispatch.py:231-283`. The first draft ordered `require_tool_invocation` before `registry.find`; the code does the opposite deliberately, because the capability name being authorized comes from the resolved definition. Both were corrected, not reconciled by hand-waving |
| Every referenced symbol exists | pass | `Settings.secret_values()` (`settings.py:79`), `MAX_TIMEOUT_SECONDS`, `MAX_OUTPUT_BYTES`, `HARD_OUTPUT_CEILING` (`dispatch.py:100`), `max_subprocess_seconds`, `Settings.secret_values`, `ADMISSIBLE_FILESYSTEM_ACCESS`, and the four cited test names all resolve. The first draft's "except the three the worker needs" for `ATLAS_*` named no three; it now names none |
| Win32 constants correct | pass after fix | the first draft used `JOB_OBJECT_LIMIT_PROCESS_COUNT` as the concurrency control; it is a *lifetime* cap. `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is now named as the control that blocks a spawn, and `CREATE_UNICODE_ENVIRONMENT` was added because omitting it silently corrupts a custom `lpEnvironment` |
| Section and finding citations resolve | pass after fix | `docs/STORAGE_REVIEW.md` has no §12.2; the citation now names §12's actual requirement. `docs/UI_ARCHITECTURE.md` C-04 is disambiguated from `docs/THREAT_MODEL.md` C4, and §1 now states the two id series differ |
| No invented phase numbers | pass after fix | "Phase 19", "Phase 29", and "Phase 33" were cited as if named elsewhere; only Phase 19 exists in the project's own documents. Phase 19 references are now to the Phase 10B corpus in §20, and the benchmark references point at `docs/SYSTEM_SPECIFICATION.md` §9, Phases 21–33 |
| Every stated limitation is explicit | pass after fix | §27 carries eleven, not nine. Filesystem **write** confinement was added as its own item after §12.5 established it is exactly as unavailable as read — the first draft implied path validation prevented it |
| Windows assumptions grounded in the measured host | pass | §3 re-measured for this phase; the §3.1 probe table lists every probe and the design consequence of each |
| No future implementation marked implemented | pass | the "implemented" column in §6 is `no (10B)` for every sandbox control; only Phase 08/09 rows say `yes` |
| No TODO / TBD / FIXME / placeholder | pass | the only match is this table's own row |
| No decorative ASCII banner separators | pass | the project uses no such style; the §8 diagram and §19 order block are architecture, not decoration |
| Markdown structure consistent | pass | `##` for sections, `###` for subsections, tables for comparisons |
| No contradictory isolation claims | pass after fix | §4, §9, §12.5, §14, and §27 now agree that read confinement, write confinement, and network denial are all unavailable; §20's Class column marks scenarios 1–5 as *policy only* and 13–15/30 as *known-open* |
| Internal counts correct | pass after fix | §2 said "thirty-one vectors" for a 36-row table; corrected |
| No new dependency proposed | pass | Job Objects via `ctypes` against `kernel32`; `pywin32` and `psutil` are neither required nor installed |
| No second permission system | pass | §19 states the sandbox consumes `ToolDefinition` metadata |
| No sandbox-disable configuration knob | pass | §19 refuses `ATLAS_TOOL_SANDBOX_MODE` |
| Routing decision made explicit | pass after fix | the first draft recommended *against* sandboxing the built-ins while §8 and §24 wired all of them through the worker, and `requires_sandbox=True` is refused at registration — which would have shipped a sandbox with no caller. U-5 now recommends routing everything, records the cost, and §27 item 11 states the consequence of the alternative |
| Unbounded default surfaced | pass after fix | `memory_limit_mb` defaults to `None`, which means no job memory limit; recorded as decision U-12 rather than left implicit |

Three things this verification deliberately does **not** do. It does not run the
application to test any design claim, because nothing is implemented. It does not
mark a single threat as mitigated, because a document is not a control. And it
does not treat "the design says deny" as "the host enforces deny" — the
distinction between those two sentences is most of what this document exists to
preserve. The only claims here that rest on measurement are the host facts in §3,
and each one names the probe that produced it.
