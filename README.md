# ATLAS-X

A local-first research platform for studying **reliable, verifiable, secure
multi-step AI agents**.

Two-line thesis: *How do explicit planning, deterministic verification,
provenance tracking, controlled tool execution, and bounded recovery affect the
reliability and auditability of local multi-step AI agents?*

Design constraints are recorded in `docs/DECISIONS.md`; environment findings in
`docs/environment-reconnaissance.md`.

## Status

| Area | State |
|---|---|
| Environment recon | done (`docs/environment-reconnaissance.md`) |
| Architecture decisions | done (`docs/DECISIONS.md`) |
| Technology stack | done (`docs/TECHNOLOGY_STACK.md`) |
| System specification | done (`docs/SYSTEM_SPECIFICATION.md`) |
| Threat model | done (`docs/THREAT_MODEL.md`) |
| Architecture reconciliation | done (`docs/ARCHITECTURE_RECONCILIATION.md`) |
| Configuration + resource bounds | done (`atlas/config/`) |
| Persistence (SQLite) | done (`atlas/storage/`) |
| Authentication | done (`atlas/auth/`) |
| Planner / orchestrator / tools / sandbox / verifier / recovery | not started (placeholders only) |
| Benchmarking / UI / model integration | not started |

## Layout

```
atlas/
  config/     bounded, validated settings (env-driven, fail-closed)
  storage/    sqlite connection, migrations, repository layer
  auth/       registration, login, sessions, lockout, password change
  security/   redaction helpers
  util.py     time helpers
tests/
  test_config.py
  test_storage.py
  test_auth.py
docs/
```

## Quick start

```
python -m venv .venv          # Python 3.11 on this machine
.\.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m pytest
atlas-x                        # smoke health check
```

No model downloads, no cloud services, no network calls at runtime.

## Security

See `SECURITY.md` and the threat model work pending in Phase 3. Two standing
rules: nothing reads or writes outside the project directory, and nothing logs
or returns authenticating material (passwords, hash secrets, session tokens).

## License

License choice not yet approved. See `LICENSE`.