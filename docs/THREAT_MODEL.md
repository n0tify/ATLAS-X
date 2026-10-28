# Threat Model for ATLAS-X

## Overview

This document defines the threat model that ATLAS-X is designed to address.
The threat model drives the security architecture and benchmark scenarios.

## Trust Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│                      HOST SYSTEM                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ATLAS-X PROCESS (Trusted)              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌─────────────────┐  │   │
│  │  │ Planner  │  │Executor  │  │  Verifier       │  │   │
│  │  │ Service  │  │ Service  │  │  Service        │  │   │
│  │  └──────────┘  └──────────┘  └─────────────────┘  │   │
│  │         │            │                │           │   │
│  │         └────────────┼────────────────┘           │   │
│  │                      ▼                            │   │
│  │  ┌─────────────────────────────────────────┐     │   │
│  │  │      Authorization Service              │     │   │
│  │  │  (Single authorization boundary)        │     │   │
│  │  └─────────────────────────────────────────┘     │   │
│  └────────────────────────┬────────────────────────┘   │
│                           │                              │
│              ┌────────────┴────────────┐                 │
│              ▼                         ▼                 │
│  ┌─────────────────────┐  ┌─────────────────────┐       │
│  │   Tool Dispatcher   │  │  SQLite Database    │       │
│  │  (Authorization +   │  │  (Owner-scoped      │       │
│  │   Validation)       │  │   storage)          │       │
│  └──────────┬──────────┘  └─────────────────────┘       │
│             │                                          │
│             ▼                                          │
│  ┌─────────────────────────────────────────┐           │
│  │         SANDBOX (WSL2/bubblewrap)       │           │
│  │  ┌─────────────────────────────────┐   │           │
│  │  │  Guest Linux (Unprivileged)     │   │           │
│  │  │  - Separate user/PID/net/mount  │   │           │
│  │  │  - cgroup limits                │   │           │
│  │  │  - Denied host paths            │   │           │
│  │  └─────────────────────────────────┘   │           │
│  └─────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

## Assets to Protect

| Asset | Description | Protection |
|-------|-------------|------------|
| User tasks/goals | Task definitions and results | Owner-scoped DB, auth |
| Tool implementations | Registered tool code | Sandbox confinement |
| Execution results | Tool outputs | Verification, artifact integrity |
| Provenance chain | Execution history | Cryptographic chaining |
| Authorization grants | Tool permissions | Policy enforcement |
| Model interaction | Planner prompts/responses | Local-only, loopback |
| Host filesystem | Host OS files | Sandbox mount denial |
| Host network | External connections | Sandbox network namespace |
| Host processes | Other processes | Sandbox PID namespace |

## Threat Actors

### 1. Malicious/Compromised LLM (Primary Threat)
**Capabilities:**
- Generates arbitrary tool invocations
- Produces incorrect/malformed reasoning
- Attempts tool misuse, replay, injection
- Can request unauthorized tools
- Can craft path traversal, network payloads

**Trust Assumption**: **The LLM is completely untrusted.**

**Mitigations:**
- Model output ≠ Authorization (enforced by AuthorizationService)
- Model output ≠ Verification (enforced by VerifierService)
- Model output ≠ Provenance (enforced by append-only chain)
- Model output ≠ Database access (enforced by owner-scoped queries)
- Model output ≠ Arbitrary code execution (enforced by Sandbox)

### 2. Malicious User (Cross-User)
**Capabilities:**
- Valid authentication
- Owns their tasks/resources
- Attempts to access other users' data

**Mitigations:**
- Owner-scoped database queries
- Authorization checks on every operation
- Provenance isolation per user

### 3. Compromised Tool Implementation
**Capabilities:**
- Runs inside sandbox
- Attempts filesystem escape
- Attempts network access
- Attempts process escape
- Attempts resource exhaustion

**Mitigations:**
- WSL2/bubblewrap confinement
- Denied host paths
- cgroup limits (memory, CPU, PIDs)
- Network namespace isolation
- PID namespace isolation

### 4. Database/Storage Attacker
**Capabilities:**
- Direct database access (if compromised)
- Attempts to modify provenance
- Attempts to forge verification results
- Attempts to corrupt artifacts

**Mitigations:**
- Provenance chain verification (cryptographic)
- Verification results create-only (no update/delete)
- Artifact checksums on read
- Owner-scoped access (even if DB accessed directly)

## Attack Classes (Mapped to Benchmarks)

| Attack Class | Threat Actor | Benchmark Scenario | Mitigation |
|-------------|--------------|-------------------|------------|
| Unauthorized Tool | Malicious LLM | `sec_unauthorized_tool` | Authorization grants |
| Cross-User Access | Malicious User | `sec_cross_user_access` | Owner-scoped queries |
| Filesystem Escape | Compromised Tool | `sec_filesystem_escape` | Sandbox mount denial |
| Path Traversal | Malicious LLM | `sec_path_traversal` | Sandbox + validation |
| Network Access | Compromised Tool | `sec_network_access` | Network namespace |
| Environment Leak | Compromised Tool | `sec_environment_leak` | Sanitized env |
| Process Escape | Compromised Tool | `sec_process_escape` | PID namespace |
| Resource Exhaustion | Compromised Tool | `sec_resource_exhaustion` | cgroup limits |
| Malformed Request | Malicious LLM | `sec_malformed_tool_request` | Schema validation |
| Replayed Invocation | Malicious LLM | `sec_replayed_invocation` | Invocation ID uniqueness |

## Security Invariants

| Invariant | Description | Enforcement Point |
|-----------|-------------|-------------------|
| I1 | No executable tool runs without authorization | ToolDispatcher → AuthorizationService |
| I2 | No executable tool runs outside the sandbox | ToolDispatcher → SandboxSupervisor |
| I3 | No successful result is published without verification | VerifierService → AuthorizationService.finish_verified_task |
| I4 | Recovery cannot exceed configured bounds | RecoveryService → max_recovery_attempts |
| I5 | Provenance is append-only | ProvenanceRepo (no update/delete) |
| I6 | Cross-user resources cannot be accessed | AuthorizationService (owner-scoped) |
| I7 | Model output cannot grant authority | AuthorizationService (grants from DB, not model) |
| I8 | Artifacts are integrity protected | ArtifactService (checksums on write/read) |

## Out of Scope

The following are **not** addressed by ATLAS-X threat model:

1. **Host OS compromise** - Root/kernel exploits
2. **WSL2/hypervisor escape** - Virtualization layer vulnerabilities
3. **Side-channel attacks** - Timing, cache, power analysis
4. **Supply chain attacks** - Malicious dependencies
5. **Physical access** - Hardware tampering
6. **Model extraction** - Stealing model weights
7. **Prompt injection (user-facing)** - User prompts are trusted input
8. **Denial of service (host-level)** - Resource exhaustion of host

## Assumptions

1. **Local execution** - Model runs on localhost (loopback only)
2. **Single tenant per user** - No multi-user collusion
3. **Trusted deployment** - ATLAS-X code not modified at runtime
4. **Database integrity** - SQLite not corrupted externally
5. **Time synchronization** - Clocks roughly synchronized for ordering
6. **Sufficient entropy** - For cryptographic operations