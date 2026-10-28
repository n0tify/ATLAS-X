# ATLAS-X Known Limitations

**Version:** 0.1.0
**Last Updated:** 2026-10-19

---

## Architecture Limitations

### Local-First Design
- **No multi-user collaboration** - Single-user per database, no real-time sync
- **No horizontal scaling** - SQLite backend, single-process FastAPI
- **No distributed tracing** - Provenance is per-task, not cross-service

### Authentication Model
- **Bearer tokens in localStorage** - Vulnerable to XSS; suitable only for trusted local environments
- **No refresh tokens** - Sessions expire after TTL (default 60 min), requiring re-login
- **No MFA/2FA** - Username/password only
- **No password reset flow** - Account recovery not implemented
- **No email verification** - Registration immediate, no verification step

### Authorization
- **Task-level ownership only** - No role-based access control (RBAC)
- **No resource sharing** - Users cannot share tasks or artifacts
- **Tool permissions coarse-grained** - Per-tool grants, not per-invocation

---

## Backend Limitations

### AI Planning
- **Requires local Ollama** - No cloud LLM fallback configured
- **No model selection UI** - Single model hardcoded
- **No prompt templating** - Plans use fixed prompts
- **No planning validation** - Generated plans not validated before approval

### Sandbox Execution
| Environment | Status | Notes |
|-------------|--------|-------|
| WSL2 (Windows) | ✅ Available | Requires WSL2 + kernel config |
| bubblewrap (Linux) | ✅ Available | Requires kernel.unprivileged_userns_clone=1 |
| macOS | ❌ Not tested | No sandbox implementation |
| Docker | ❌ Not implemented | Could be added |
| Firecracker | ❌ Not implemented | Overkill for local |

**Sandbox Limitations:**
- No network access control (allow/deny lists)
- No GPU access
- Resource limits (CPU, memory) configurable but not enforced per-invocation
- No snapshot/restore for bounded recovery testing

### Verification
- **Deterministic rules only** - No probabilistic/ML-based verification
- **No custom rule engine** - Rules hardcoded in `atlas/verifier/rules.py`
- **No verification result export** - Results only in provenance

### Provenance
- **Per-task chains only** - No cross-task provenance linking
- **No Merkle tree aggregation** - Linear chain only
- **No external anchoring** - No timestamping service integration

### Database
- **SQLite only** - No PostgreSQL/MySQL support
- **No connection pooling** - Single connection per request
- **No read replicas** - Single writer
- **Migration safety** - No rollback mechanism for failed migrations

---

## Frontend Limitations

### Responsive Design
- **Desktop only** - No tablet/mobile breakpoints implemented
- **Fixed three-column layout** - Does not collapse on narrow screens
- **Navigation rail** - Always visible, no hamburger menu
- **Inspector panel** - Fixed 320px width, no responsive behavior

### Living System Map
- **Real data integrated** - Status indicators connected to actual task states
- **No WebSocket/SSE** - Polling not implemented (manual refresh)
- **No connection lines** - Stages shown as grid, not flow diagram
- **No historical replay** - Cannot view past execution flows

### Tutorial System
- **SessionStorage only** - Cleared on browser close, not persistent across devices
- **No progress saving** - Interrupted tutorial restarts from beginning
- **No analytics** - No completion/funnel tracking
- **Single language** - English only, no i18n framework

### State Management
- **No global state library** - React Context only (sufficient for current scope)
- **No offline support** - No service worker, no IndexedDB caching
- **No optimistic updates** - All mutations wait for server response

### Accessibility
- **No reduced motion support** - `prefers-reduced-motion` not handled
- **Tutorial modal focus trap** - Focus not trapped in modal
- **ARIA dialog role** - Tutorial overlay missing `role="dialog"`
- **Color-only status indicators** - Some statuses use color only (no icon/text)
- **Keyboard shortcuts** - No global shortcuts (Cmd+K for command palette, etc.)

### Testing
- **Playwright tests passing** - All 14 tests pass
- **No visual regression tests** - No screenshot comparison
- **No performance budgets** - No bundle size or runtime limits
- **No accessibility test automation** - axe-core not integrated

---

## Research Platform Limitations

### ATLAS-BENCH
- **No benchmark runner service** - Cannot execute benchmark scenarios
- **No scenario registry** - No CRUD for benchmark definitions
- **No baseline configurations** - No ablation management
- **No metrics collection** - No standardized measurement framework
- **No result comparison UI** - No side-by-side run comparison
- **No report export** - No PDF/HTML/JSON export

### Experiments
- **No experiment tracking** - No MLflow/W&B integration
- **No hyperparameter sweeps** - Manual configuration only
- **No reproducibility guarantees** - Environment not captured
- **No artifact versioning** - Artifacts overwritten on re-run

### Contribution Workflow
- **No submission UI** - No form for benchmark contributions
- **No validation pipeline** - Submitted scenarios not validated
- **No review workflow** - No maintainer approval process
- **No safe execution** - Contributed code runs with full privileges

---

## Security Limitations

### Current Gaps
| Area | Limitation | Risk |
|------|------------|------|
| Token storage | localStorage (XSS) | Medium (local dev) |
| CSRF | Not implemented | Low (Bearer token) |
| Rate limiting | Not implemented | Medium (DoS) |
| Secrets in logs | Redaction filter not attached | Low (local dev) |
| Password policy | Minimal (length only) | Medium |
| Session fixation | Token not rotated on privilege change | Low |
| Audit logging | Provenance only, no security events | Medium |

### Production Hardening Needed
1. Move tokens to HttpOnly Secure cookies
2. Implement refresh token rotation
3. Add rate limiting (per-IP, per-user)
4. Attach SecretsRedactionFilter
5. Implement `application_secret_key` for signing
6. Add CSP headers
7. Enable HSTS
8. Configure secure CORS origins

---

## Deployment Limitations

### Local Development
- **Windows-only sandbox** - WSL2 required for isolation
- **No ARM64 support** - Not tested on Apple Silicon/ARM
- **Single-user database** - No concurrent access testing

### Railway/Cloud
- **SQLite on ephemeral filesystem** - Requires persistent volume
- **No managed database** - SQLite not suitable for multi-instance
- **No horizontal scaling** - Single container only
- **Ollama not available** - Cloud LLMs need configuration
- **Sandbox unavailable** - WSL2/bubblewrap not in containers

### Missing Infrastructure
- **No CI/CD pipeline** - GitHub Actions not configured
- **No staging environment** - Single production deployment
- **No feature flags** - All features always on
- **No blue-green deployment** - Downtime on deploy
- **No database migration strategy** - Manual intervention required

---

## Data & Privacy

### Data Retention
- **No automatic cleanup** - Tasks, artifacts, provenance kept forever
- **No GDPR compliance** - No right to deletion, no data export
- **No anonymization** - Usernames stored in plaintext

### Backup
- **Manual only** - No automated backup schedule
- **No point-in-time recovery** - Full database restore only
- **No cross-region replication** - Single database file

---

## Performance Limitations

### Frontend
- **No code splitting** - Single bundle (293 kB)
- **No lazy loading** - All routes loaded upfront
- **No virtualization** - Large task lists render all items
- **No Web Workers** - Heavy computations block main thread

### Backend
- **No request batching** - N+1 queries possible in task listing
- **No caching** - No Redis/memory cache for frequent reads
- **No async database** - Sync SQLite blocks event loop
- **No connection pooling** - New connection per request

### Scale Targets (Current Architecture)
| Metric | Limit | Notes |
|--------|-------|-------|
| Concurrent users | 1 | SQLite + localStorage |
| Tasks per user | ~10,000 | SQLite performance |
| Artifacts per task | ~100 | File system limits |
| Provenance events | ~1,000/task | Linear chain verification |
| Sandbox executions | Sequential | No parallel execution |

---

## Technical Debt

### Code Quality
- **Inline styles** - CSS-in-JS throughout (no CSS modules/Tailwind)
- **No design system package** - Tokens duplicated across frontend/backend
- **Error handling inconsistent** - Some try/catch, some unhandled

### Testing
- **Frontend unit tests** - None (Vitest not configured)
- **Integration tests** - Backend only, no frontend-backend integration
- **Contract tests** - No API contract validation
- **E2E tests** - Playwright configured and passing (14/14)

### Documentation
- **API docs auto-generated** - Swagger only, no narrative docs
- **Architecture decision records** - Partial (docs/DECISIONS.md)
- **Runbooks** - None for operations
- **Threat model** - Documented but not validated

---

## Future Work Categories

### Must Have (MVP Completion)
1. Railway deployment with persistent volume
2. HttpOnly cookie authentication
3. Responsive design (tablet breakpoint minimum)
4. CI/CD pipeline (GitHub Actions)
5. Refresh token implementation

### Should Have (Production Ready)
1. Rate limiting and CSP headers
2. Automated backup/restore
3. Benchmark runner service
4. Comprehensive accessibility audit

### Nice to Have (Differentiation)
1. Multi-user collaboration (WebRTC/WebSocket)
2. Experiment tracking (MLflow integration)
3. Visual provenance graph (D3.js/GraphViz)
4. Plugin system for custom tools/verifiers
5. Cloud deployment templates (AWS/GCP/Azure)
6. Mobile PWA support

---

## Environment-Specific Limitations

### Windows (WSL2)
- **WSL2 required** - No native Windows sandbox
- **File system performance** - /mnt/c slower than native Linux
- **Networking** - WSL2 localhost forwarding quirks

### Linux (Native)
- **bubblewrap dependencies** - Requires kernel config
- **No systemd service** - Manual process management

### macOS
- **No sandbox** - Not implemented
- **Ollama ARM64** - Works but untested in CI

### Docker/Containers
- **No sandbox** - Privileged containers defeat isolation
- **SQLite on overlayfs** - Potential locking issues
- **No GPU passthrough** - For ML workloads

---

## Decision Log (Key Trade-offs)

| Decision | Rationale | Revisit When |
|----------|-----------|--------------|
| SQLite over PostgreSQL | Simplicity, zero-config, local-first | Multi-user or cloud deployment |
| Bearer token + localStorage | SPA simplicity, no cookie complexity | Production deployment |
| CSS-in-JS (inline styles) | Zero config, co-located with components | Design system extraction |
| React Context over Redux | Low boilerplate, sufficient for scope | Complex global state |
| Ollama for planning | Free, local, privacy-preserving | Cloud LLM requirements |
| WSL2/bubblewrap sandbox | Best available local isolation | Container-native sandbox |

---

## Maintenance Burden

### Weekly
- Dependency updates (npm audit, pip-audit)
- Database backup verification

### Monthly
- Security scan (OWASP ZAP, bandit)
- Performance baseline check
- Log review for anomalies

### Quarterly
- Architecture review
- Threat model update
- Dependency license audit
- Documentation freshness check

---

## Support Matrix

| Component | Supported | Notes |
|-----------|-----------|-------|
| Python | 3.11+ | 3.12 tested |
| Node.js | 20+ | 22 LTS recommended |
| OS | Windows 10/11, Linux (Ubuntu 22.04+), macOS 13+ | Windows primary |
| Browser | Chrome 118+, Firefox 118+, Safari 17+, Edge 118+ | Modern evergreen |
| SQLite | 3.40+ | WAL mode enabled |

---

## Contact

For questions about limitations or to contribute fixes, see:
- GitHub Issues: [Repository Issues]
- Architecture Docs: `docs/ARCHITECTURE_RECONCILIATION.md`
- Threat Model: `docs/THREAT_MODEL.md`
- Decisions: `docs/DECISIONS.md`