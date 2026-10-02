# SANDBOX DESIGN AMENDMENT — Isolation Substrate Decision

Status: **APPROVED AND IMPLEMENTED** (Phase 10B complete — see §12)
Amends: `docs/SANDBOX_DESIGN.md` (the Job-Object proposal in that document is
superseded; §12 below records what was actually built)
Phase 10B implementation status: **IMPLEMENTED AND TESTED**
U-1 and U-2: **ENFORCED STRUCTURALLY AND VERIFIED BY TEST**

Sections 1–11 are the design decision as it was made and are retained unedited,
because the reasoning for choosing this substrate still holds. §12 records the
implementation against it, including the two places where the implementation
diverged from what §6 sketched.

---

## 1. Purpose

`docs/SANDBOX_DESIGN.md` proposed a Windows Job Object worker as the isolation
substrate. The Phase 10 host investigation established that a Job Object cannot
satisfy either approved security requirement. This amendment records that
finding, selects a substrate that can, and lists the host prerequisites that
must exist before Phase 10B begins.

This document does not weaken U-1 or U-2, does not authorise a reduced-scope
sandbox, and does not implement anything.

---

## 2. Requirements (restated, unchanged)

| ID | Requirement | Scope |
|----|-------------|-------|
| **U-1** | Network denial | Internet, DNS, LAN, proxy, and **host loopback services (e.g. Ollama on `127.0.0.1:11434`)** |
| **U-2** | Filesystem read/write confinement | Worker must not read or write outside the explicitly authorised workspace and runtime paths |

Both are requirements, not aspirations. There is no "degraded mode" in which a
tool runs without these controls.

---

## 3. Corrected AppContainer finding

An earlier working note stated that a non-administrator could create an
AppContainer profile on this host. **That statement was wrong and is withdrawn.**
It was a false positive caused by declaring `CreateAppContainerProfile` with a
`BOOL` return type when the API returns `HRESULT`: `S_OK` (0) read as failure
and a failure code read as success.

Corrected result, from the corrected binding:

- `CreateAppContainerProfile` returned `E_INVALIDARG` (`0x80070057`) for every
  AppContainer name tried, including names in the canonical
  `Publisher.App_8wekyb3d8bbwe` form.
- `DeriveAppContainerSidFromAppContainerName` returned `E_INVALIDARG` for those
  same names **and** for monikers already registered on this host
  (`adobe.acrobatreaderdc.protectedmode`, `aimgr_8wekyb3d8bbwe`,
  `pythonsoftwarefoundation.python.3.13_qbz5n2kfra8p0`).
- Because derive failed even for known-good names, the precise cause is not
  fully isolated. What is established: **AppContainer profile creation did not
  succeed through the tested non-admin path on this host.**
- `CreateProcessW` with `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` did return
  success, so token creation was not obviously blocked. However the child
  interpreter never started (exit code `87`, `ERROR_INVALID_PARAMETER`) and no
  result was produced, so the AppContainer route was **never validated
  end-to-end**.

Even had it worked, AppContainer would not have satisfied U-1 without a loopback
exemption (host services such as Ollama remain reachable unless explicitly
exempted), and it would depend on a fragile per-path ACL maintenance model
rather than a structural boundary.

**Conclusion: AppContainer is removed as a candidate substrate for this project.**

---

## 4. What Windows Job Objects do and do not provide

| Capability | Job Object | Note |
|---|---|---|
| Process lifetime containment | **Yes** | `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` |
| Orphan prevention | **Yes** | child tree dies with the job |
| Process count limit | **Yes** | `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` |
| Memory limit | **Yes** | `JOB_OBJECT_LIMIT_PROCESS_MEMORY` |
| CPU rate limit | **Yes** | `JOB_OBJECT_LIMIT_RATE_CONTROL` |
| **Filesystem read confinement** | **No** | no filesystem namespace exists |
| **Filesystem write confinement** | **No** | worker runs with the parent's token |
| **Network denial** | **No** | no network namespace exists |

A Job Object is a resource and lifetime container. It is not a security
boundary against a hostile worker.

---

## 5. Candidate substrates compared

Constraints applied: Windows 11 **Home** Single Language (build 26200, x64),
current account is **non-administrator**, WSL engine present with **no
distribution**, Docker **unavailable**, local-first required, free/open-source
required, laptop-class hardware (i5-1335U / 12 threads / 15.7 GB RAM).

| Substrate | U-1 network | U-2 filesystem | Host change needed | Verdict |
|---|---|---|---|---|
| **Job Object only** | No | No | none | **Rejected** |
| **AppContainer** | Not satisfied (loopback reachable) | Fragile per-path ACLs | unavailable non-admin | **Rejected** (§3) |
| **Restricted token / separate Windows account** | No — needs admin firewall rules or AppContainer | Deny-ACE model, brittle | needs admin to create account | **Rejected** |
| **Windows Sandbox / Hyper-V VM** | Yes | Yes | **Pro/Enterprise only + admin** | **Rejected** — Home edition |
| **Docker / containers** | Yes (`--network none`) | Yes (namespaces) | admin install, heavier, licensing | Deferred — not practical now |
| **WSL2 + Linux namespaces (`bwrap` / `unshare`)** | **Yes** | **Yes** | install one distro (per-user) | **SELECTED** |

### Why WSL2 + Linux namespaces satisfies both requirements structurally

- **U-1:** `unshare --net` creates a fresh, empty network namespace. It contains
  no interfaces. Bringing `lo` up yields a loopback that is *private to the
  namespace* and therefore **cannot reach the host's `127.0.0.1:11434`** or any
  other host service. This is a structural guarantee, not a rule that can be
  forgotten.
- **U-2:** `unshare --mount` plus an explicit bind-mount allowlist makes the
  host filesystem unreachable. Critically, this must also mask WSL2's Windows
  drive mounts (`/mnt/c`, `/mnt/d`, …), which otherwise expose the entire host
  filesystem. Sealing `/mnt` is a mandatory part of the design, not an
  optional hardening step.
- **Bonus:** resource limits move to Linux **cgroup v2**, which is a better fit
  than Job Objects for per-worker CPU/memory accounting.

---

## 6. Selected architecture

```text
ATLAS-X supervisor  (native Windows, trusted, authorization gate)
  │  authenticated + authorized tool invocation
  ▼
wsl.exe -d <distro> -- /opt/atlasx/launcher <tool-id>     ← boundary crossing
  │
  ▼
launcher (inside distro)
  ├─ cgroup v2: memory.max, cpu.max, pids.max
  ├─ bubblewrap / unshare:
  │    --unshare-net            → U-1
  │    --unshare-pid            → process containment
  │    --ro-bind /usr /lib /bin root filesystem
  │    --bind  <workspace>      → the only writable path
  │    --tmpfs /mnt             → Windows drives hidden
  │    --dev /dev/null only
  │    --die-with-parent
  ▼
worker process (Linux, unprivileged, no network, sealed filesystem)
  │
  ▼
stdout/stderr + result file  → back over the boundary, re-validated by supervisor
```

### Division of responsibility

**The isolation substrate (WSL2 + namespaces) will:**
- Deny all network egress, including host loopback services (U-1)
- Confine filesystem reads and writes to the allowlist (U-2)
- Hide the Windows host filesystem from the worker
- Enforce memory, CPU, and process-count limits via cgroup v2
- Kill the entire worker process tree on timeout or supervisor death

**Windows Job Objects will still:**
- Contain and kill the **Windows-side `wsl.exe` client** and its descendants, so
  a crashed or hung supervisor cannot leave orphaned client processes
- Provide a backstop so a closed supervisor tears down the client side

**Honest limitation:** the worker does **not** run as a Windows process, so
Windows Job Objects no longer bound the worker's actual CPU or memory. `wsl.exe`
is a thin RPC client and the guest VM's resources are not charged to it. Real
per-worker resource enforcement therefore **moves to cgroup v2 inside the
distro**. Job Objects are retained in a deliberately narrow, secondary role.
Claiming Job Objects as the worker's resource boundary after this change would
be incorrect.

---

## 7. Required host prerequisites (NOT performed in this task)

Nothing below has been installed, enabled, or configured.

1. **Confirm the WSL2 engine can launch.** The Virtual Machine Platform feature
   is *probably* already enabled (`wsl --status` reports default version 2 and
   `HypervisorPresent=True`), but this is **not proven** — the earlier
   `Get-WindowsOptionalFeature -Online` check failed with
   *"The requested operation requires elevation."* Verification must use a
   non-elevated method. If the feature is **not** enabled, this route requires
   one admin action and the decision returns to the human.
2. **Install one Linux distribution, per-user.** Preferred order:
   - `wsl --install -d Ubuntu-24.04` (Store, per-user, no admin), or
   - `wsl --import ATLASX <install-path> <ubuntu-rootfs.tar.gz>` (per-user, no
     admin, no Store dependency).
3. **Inside the distro:** install `bubblewrap`. Confirm `cgroup v2` is mounted
   (`/sys/fs/cgroup/cgroup.controllers`) and that `unshare -n` yields an empty
   network namespace.
4. **Inside the distro:** create a Linux virtualenv and install the project's
   runtime dependencies. This is unavoidable — the worker runs Linux Python.
5. **Decide interop policy.** WSL2 interop must be disabled for worker
   invocations (`--disable-interop` and/or `[interop] enabled=false` in
   `/etc/wsl.conf`) so the worker cannot reach Windows binaries or `\\wsl$`
   paths.

Expected cost: a one-time setup of a few hundred MB and a Linux dependency
install. Fits the laptop constraint and the free/open-source requirement.

---

## 8. What remains impossible or residual risk

- **A native Windows worker cannot satisfy U-1 or U-2 on this host.** With no
  admin (no firewall rules) and no working AppContainer, there is no
  Windows-native mechanism to deny network access. The design must therefore
  treat the Linux-isolated worker as the **only** execution path.
- **Fail-closed is mandatory.** There must be no native fallback that silently
  executes a tool without isolation. If WSL is unavailable or the launcher
  cannot apply its controls, the invocation must be refused and recorded.
- **The supervisor remains trusted and unconfined.** ATLAS-X on Windows performs
  authorized file I/O and talks to the local model. Worker confinement does not
  confine the supervisor. This is the existing §12.5 caveat and it is unchanged.
- **Kernel and bubblewrap are a trusted computing base.** A worker exploit in
  the guest is out of scope for this project.
- **WSL2 is not a hard real-time boundary.** Defence in depth still applies:
  least-privilege tool inputs, authorization before dispatch, and independent
  verification of results.

---

## 9. Consequences for Phase 10B

Phase 10B must be re-scoped before implementation. Required changes:

- The worker runtime target becomes **Linux**, not Windows.
- The supervisor gains a WSL launcher component; the Windows-side process
  boundary becomes `wsl.exe`.
- Resource limits move from Job Object fields to **cgroup v2** settings, with
  Job Objects demoted to client-side lifecycle containment.
- `/mnt` masking, interop disabling, and empty-network-namespace creation are
  **required controls**, each independently testable.
- U-12's default memory limit (`1024 MB` per execution) is carried over as the
  cgroup `memory.max` default.
- The `requires_sandbox=True` registration refusal and the U-5
  route-every-tool requirement are unchanged.

---

## 10. FAST-TRACK DECISION

| Item | Decision |
|---|---|
| **Selected isolation substrate** | WSL2 Linux distribution + `bubblewrap`/`unshare` namespaces + cgroup v2 |
| **Required host prerequisite** | One WSL2 distro installed per-user, `bubblewrap` present, cgroup v2 confirmed, WSL2 engine confirmed launchable. **Admin required only if the Virtual Machine Platform feature turns out to be disabled.** |
| **Why selected** | It is the only remaining route that enforces U-1 and U-2 *structurally* on this host: it needs no admin, no Windows edition upgrade, no paid software, and it keeps the system local-first. Network denial and filesystem sealing come from kernel namespaces rather than from rules that can be forgotten. |
| **What Job Objects still do** | Windows-side `wsl.exe` client containment, kill-on-close, orphan prevention. **No longer** the worker's CPU/memory boundary. |
| **What the substrate does** | U-1 via empty network namespace; U-2 via mount namespace plus `/mnt` masking; resource limits via cgroup v2; full process-tree teardown. |
| **What remains impossible** | Native Windows execution meeting U-1/U-2 on this account; confinement of the trusted supervisor; guest-kernel escape. |
| **Exact next implementation step** | Human decision on the WSL route, then a **bounded prerequisite check only**: (a) confirm WSL2 launches a distro without elevation, (b) install one distro per-user, (c) confirm `bubblewrap`, cgroup v2, and an empty netns. If (a) fails without admin, stop and return to the human. Only after all three pass does Phase 10B implementation planning begin. |

---

## 11. Status as recorded before implementation

- `docs/SANDBOX_DESIGN.md`: **unchanged.** It still contained the superseded
  Job-Object-only proposal.
- Phase 10B: **not started.** Phase 11: **not started.**
- U-1 and U-2: **intact.**
- No code, configuration, packages, or Windows settings were changed to produce
  this document.

---

## 12. Implementation record (Phase 10B)

This section is what the amendment predicted, checked against what was built and
tested. The status vocabulary is deliberate and used strictly: **IMPLEMENTED**,
**TESTED**, **DETECTED ONLY**, **NOT ENFORCED**, **LIMITATION**. Nothing below is
claimed more strongly than it was verified.

### 12.1 Substrate as built

The substrate is the one selected in §10. A tool body is a Linux process in a
`bubblewrap` mount, PID, network, IPC, UTS, user, and cgroup namespace, inside the
`Ubuntu-24.04` WSL2 distribution, with a cgroup v2 leaf. Verified versions on this
host: `bubblewrap 0.9.0`, kernel `6.6.87.2-microsoft-standard-WSL2`, cgroup v2.

The argv the guest executes, which `tests/test_sandbox.py` asserts directly:

```
--unshare-user --unshare-pid --unshare-net --unshare-ipc --unshare-uts
--unshare-cgroup --uid 65534 --gid 65534 --cap-drop ALL --new-session
--die-with-parent --clearenv
--ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/sbin /sbin
--symlink usr/lib /lib --symlink usr/lib64 /lib64
--dir /etc --chmod 555 /etc
--ro-bind /etc/ld.so.cache|conf|conf.d
--ro-bind /opt/atlasx/lib /opt/atlasx/lib --ro-bind /opt/atlasx/venv /opt/atlasx/venv
--proc /proc --remount-ro /proc --dev /dev
--tmpfs /tmp --chmod 1777 /tmp
--bind /workspace /workspace --chdir /workspace
```

### 12.2 Requirement status

| Control | Status | Evidence |
|---|---|---|
| **U-1 network denial** | **IMPLEMENTED, TESTED** | `--unshare-net`; no routes, no interface enumeration, all external destinations and both DNS paths refused. Host loopback `127.0.0.1:11434` (Ollama) refused with `ECONNREFUSED`. |
| **U-2 filesystem confinement** | **IMPLEMENTED, TESTED** | `/workspace` is the only `RW_BIND`; `fs.absent.*` asserts `/mnt`, `/home`, `/root`, `/run`, `/srv`, `/media` do not exist; traversal to `/` finds nothing mounted. |
| WSL interop disabled | **IMPLEMENTED, TESTED** | `[interop] enabled=false`, `appendWindowsPath=false` in `/etc/wsl.conf`; `WSL_INTEROP` absent; `cmd.exe` execution fails; no drive letter on `PATH`. |
| Capability drop | **IMPLEMENTED, TESTED** | `--cap-drop ALL` plus `identity.capabilities` probe. |
| Identity confinement | **IMPLEMENTED, TESTED** | uid/gid 65534, own PID namespace, no `core_pattern` write. |
| Memory / PID / CPU limits | **IMPLEMENTED, TESTED** | cgroup v2 leaf; `pids.fork_refused` and `memory.probe_ran` demonstrate kernel enforcement rather than a readable file. |
| Process-tree teardown | **IMPLEMENTED, TESTED** | A `setsid` grandchild ignoring `SIGTERM` and `SIGKILL` is reported gone in `surviving_descendants` after the wall clock. |
| Cgroup hierarchy hidden | **IMPLEMENTED, TESTED** | `cgroup.view_is_namespaced` reads `0::/`; `/sys/fs/cgroup` not mounted. |
| Environment allowlist | **IMPLEMENTED, TESTED** | Built from a closed allowlist; no host variable is read. |
| Supervisor confinement | **NOT ENFORCED** | The Windows supervisor is trusted and runs unconfined. This is the standing A12.5 caveat. |
| Guest-kernel escape | **NOT ENFORCED** | Out of scope; the kernel and `bubblewrap` are trusted computing base. |
| Cross-invocation isolation of the workspace | **LIMITATION** | See §12.5. |
| Windows Job Object client containment | **DETECTED ONLY** | The Windows-side `wsl.exe` lifetime backstop is designed for but not exercised by an automated test; the guest-side teardown is the tested control. |

### 12.3 Divergences from the §6 sketch

Two, both deliberate and both recorded so a later reader does not treat the sketch
as a specification:

1. **Job Objects are not used at all.** §6 retained them in a narrow
   client-side role. Implementing that would have meant creating a Windows job
   object per invocation for a process (`wsl.exe`) whose resources are not the
   ones being bounded, in exchange for a guarantee about a thin RPC client. It was
   dropped rather than built and then described as a control. The guest-side
   cgroup teardown covers the same failure mode — a hung invocation — and is
   tested. **This is a narrowing of §6, not a strengthening.**
2. **The launcher is a third process.** §6 sketched supervisor → launcher →
   worker. As built, the launcher creates the namespace, applies the cgroup, execs
   `bwrap`, and supervises the deadline, so the timeout is enforced *outside* the
   process group it is timing. The sketch's two-process form had no component that
   could observe and kill the tree.

### 12.4 A real escape found and fixed

The first implementation mounted `/proc` with `--proc` and nothing else. Inside that
namespace, uid 65534 could write `/proc/sys/kernel/core_pattern` — and
`core_pattern` is **host-global**: the value survived the sandbox and appeared in
the host kernel's crash handling. `--unshare-all` does not prevent this, because
`/proc/sys` is not namespaced. `/proc/sys/kernel/hostname` and
`/proc/sys/net/ipv4/ip_forward` were writable for the same reason.

Fixed by emitting `--remount-ro /proc` and by asserting writability at runtime
rather than by writing a marker. The probe now writes each sysctl's *current*
value back to itself, so it fails if the path is writable and never alters host
state when it succeeds. The host's `core_pattern` was restored to its natural WSL
value, `|/wsl-capture-crash %t %E %p %s`.

This is recorded because it is the reason §12.2 lists `/proc` remounts as a
control rather than a default.

### 12.5 Residual limitations

- **`memory.max` bounds and reclaims; it does not guarantee termination.** The
  wall clock is the backstop that guarantees a process ends. Both are required and
  neither is sufficient alone.
- **A tool body that exhausts the memory cap may be killed before reporting.**
  The cap is enforced correctly; the report may simply be absent.
- **A whole-workspace check is not implemented.** U-2 as tested is about paths
  being absent and unwritable. Whether a tool wrote *only* inside its own workspace
  is not checked, by design — the workspace is per-execution and discarded.
- **The supervisor is not confined.** A compromised ATLAS-X process is not
  contained by anything in this phase.
- **Timing is not a hard real-time boundary.** An in-process `timeout_seconds`
  check on the host detects an overlong call after it returns; only the guest-side
  deadline interrupts one.

### 12.6 Verification

`tests/test_sandbox.py` (37 tests) and the existing `tests/test_tools.py` run
against the real guest — real `wsl.exe`, real `bubblewrap`, real cgroup v2 — with
no mocks of the isolation layer. Phase-09 dispatch guarantees that were previously
asserted by counting calls to a host-side callable are now asserted at the
boundary, because the host no longer calls the body at all; the audit record is the
observable that remains honest. Full suite, `ruff check .`, and `mypy atlas` pass.
