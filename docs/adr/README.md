# Phase 0 architecture decision records

The phase 0 direction was approved and phases 1–5 were implemented. Historical
decisions date from 2 October 2026; ADR 011 records preparation authorized on
12 October 2026. Real deployment and broker acceptance remain independent gates.

| ADR | Decision |
| --- | --- |
| 001 | Modular monolith with privilege-separated entrypoints |
| 002 | PostgreSQL durable jobs/outbox; optional Redis |
| 003 | Conditional WSL2 production and full native Windows fallback |
| 004 | Advisory AI, deterministic risk authority, atomic reservations |
| 005 | Signed HTTPS EA polling with uncertain-outcome recovery |
| 006 | Opaque local sessions and private edge access |
| 007 | Registry-controlled models, versioned prompts and bounded AI costs |
| 008 | Astryx/React19/Next16 with verified StyleX build path |
| 009 | Paper-first isolation; conservative broker capabilities |
| 010 | Compact evidence retention; approval-only adaptive proposals |
| 011 | Vercel dashboard, persistent portable backend and gated OpenRouter |

## ADR 001 — monolith with separate runtime privileges

**Context:** Small team, one VPS, strict reasoning/risk/secrets separation. **Decision:** One Python package/release with collector, AI worker, risk/bridge executor, maintenance and administrative API entrypoints. Use separate OS/env/database roles. Risk/bridge alone signs commands and verifies authoritative EA telemetry. **Trade-off:** More service identities than a single omnipotent process, much less deployment overhead than independently versioned microservices. **Rejected:** Kubernetes/microservice network and one shared all-secrets process. **Evidence:** [architecture boundaries](../ARCHITECTURE.md). **Acceptance:** AI/API/collector DB grants cannot write approvals or account projections; their environments lack bridge keys.

## ADR 002 — durable PostgreSQL queue and optional Redis

**Context:** Replays/reservations must survive restarts; Windows fallback must not require unsupported Celery/Redis ports. **Decision:** Transactional outbox, `SKIP LOCKED` leased jobs, unique IDs, explicit retries/dead letters; PostgreSQL sessions/replay/rate limits. Redis accelerates only optional operations. **Trade-off:** Implement a small leased queue with contention tests; no high-volume streaming guarantee. **Rejected:** Redis-only queue/locks and mandatory Celery. **Evidence:** [backend research](../research/BACKEND.md), [PostgreSQL locking](https://www.postgresql.org/docs/17/sql-select.html). **Acceptance:** Concurrent claim/restart/outbox tests on real PostgreSQL; Redis-off mode passes core E2E.

## ADR 003 — two Windows production paths

**Context:** Windows MT5/RDP/browser must coexist with backend auto-start; Docker Desktop unsupported on Windows Server. **Decision:** Server2022 first target. Mode A only after provider nesting/WSL/Docker/pre-login continuity proof. Mode B native Python/Node/PostgreSQL services with pinned WinSW, Caddy/cloudflared. Build native Windows artifacts on Windows. **Trade-off:** Maintain both deploy adapters and separate real reboot gates. MT5 GUI recovery remains login-dependent by secure default; optional Autologon needs a later explicit decision. **Rejected:** Docker Desktop assumption, Linux-only backend, GUI as Session0 service. **Evidence:** [Windows research](../research/WINDOWS.md). **Acceptance:** Non-GUI services return without RDP login, MT5 reconnection/reconciliation and restore tested on chosen host.

## ADR 004 — advisory AI and transactional risk authority

**Context:** Valid JSON or high confidence is not trading permission. Concurrent orders can exceed aggregate caps. **Decision:** Pure Decimal-based typed PASS/REJECT/ERROR risk rules, hard-envelope intersection, account-locked reservations/immutable approvals, complete risk reevaluation before delivery, independent EA checks. Every exposure increase uses the gateway; reductions use a targeted authorization policy. **Trade-off:** Conservative refusal on unsupported/unknown inputs and retained unknown exposure can reduce availability. **Rejected:** AI tool execution, dashboard order issuance, unknown-as-zero, eventual-consistency risk counters. **Acceptance:** Every rule boundaries/errors plus simultaneous proposals, tightened config and changed equity/drawdown tests.

## ADR 005 — signed HTTPS polling and conservative recovery

**Context:** MQL5 WebRequest is synchronous; broker API has no established application idempotency key or transaction shared with DB. **Decision:** Small outbound HTTPS requests, exact-byte HMAC-SHA256 with signed identity/expiry/sequence, durable EA journal/outbox, broker deal dedup. OUTCOME_UNKNOWN retains reservations and forbids resending until reliable reconciliation. Single EA ownership; manual failover. **Trade-off:** Poll latency and MQL HMAC/JSON implementation/testing; no exactly-once broker claim. **Rejected:** Custom WebSocket first, unsigned polling, blind retry after ACK timeout, automated lease-based EA takeover. **Evidence:** [MT5 protocol proposal](../research/MT5.md). **Acceptance:** Python/MQL vectors, compile, demo crash/duplicate/history tests, certificate trust and redirects.

## ADR 006 — simple private-dashboard authentication

**Context:** Private ADMIN/VIEWER application, no public tenant onboarding. **Decision:** Argon2id local credentials, hashed opaque PostgreSQL sessions, Secure/HttpOnly/SameSite cookies, CSRF/Origin, DB-shared throttles, RBAC. Access MFA for external production; equivalent implemented MFA required before another external path. TOTP extension contract, no invented completed MFA feature. **Trade-off:** Local account lifecycle plus Access operational setup; database dependency intentionally fails closed. **Rejected:** Browser API keys, unauthenticated admin backend, JWT in localStorage, trusting arbitrary Access email headers. **Acceptance:** RBAC/session/CSRF/throttle/header/confirmation tests.

## ADR 007 — controlled models/prompts/costs

**Context:** Provider choice should change without arbitrary model IDs, runaway spend or relaxed analysis. **Decision:** Reviewed model registry, versioned agent configs/prompts, strict schemas, bounded timeout/tokens/fallback attempts and atomic priced spend reservations. Mock+OpenAI first; optional future adapters. No network tools in agents. **Trade-off:** Pricing/capability manifests need updates; unknown usage remains conservatively reserved. **Rejected:** Hardcoded model strings throughout domain, mandatory all-provider integrations, silent bypass on budget outage, prompt self-rewriting. **Evidence:** [backend provider research](../research/BACKEND.md). **Acceptance:** Refusals/invalid JSON/timeouts, wrong/disabled models, fallback cycles, parallel budget exhaustion, pricing unknown.

## ADR 008 — Astryx and a verified compiler path

**Context:** User mandates Astryx, React19+, latest compatible stable Next and no invented APIs. **Decision:** Next16.3.8, React19.3, Astryx core/CLI/theme-neutral0.6.4, StyleX0.19.0; prebuilt theme CSS and per-component imports. Authored xstyle uses the successfully tested community SWC plugin0.19.0 with Webpack. Inspect CLI layouts/templates/component contracts before views; use compact operational tables. **Trade-off:** Community compiler plugin must be pinned/scanned; custom Turbopack extraction is deferred. **Rejected:** Invented design-system primitives/APIs, copying outdated example assumptions, untested bundler default for authored styles. **Evidence:** [actual CLI and disposable build record](../research/ASTRYX.md). **Acceptance:** Linux/Windows builds, typecheck/lint, browser theme/accessibility/confirmation tests and CSS emission checks.

## ADR 009 — isolated paper/demo/live and tested capabilities

**Context:** Developer on macOS has no native MT5; broker/account modes vary. **Decision:** Default paper protocol simulator and disabled automation/live flags. Demo requires separate enrolled DEMO tuple/keys. Live requires deployment+EA gates and recorded demo acceptance. Start market opens with attached stops, validated modification and targeted close; pending/partial close remain off until demonstrated. Prefer dedicated automation account; reject mixed netting ownership. **Trade-off:** Simulator cannot certify broker mechanics; native demo remains mandatory. **Rejected:** Simulator success marketed as demo validation, magic-only ownership, naked order plus best-effort later stop. **Acceptance:** Isolation, account mismatch, stop/filling/hedging/netting/history and reboot demo gates.

## ADR 010 — evidence-aware retention and non-autonomous learning

**Context:** Verbose data should expire without losing explanations or recovery state. User wants learning without self-changing safety. **Decision:** Seven-day raw logs/Telegram/AI defaults; long-term compact validated decision/risk/economic records, audit/config versions and trade memory. Preserve anchors/journal/replay for open/pending/unknown execution. History aggregates may suggest changes; ADMIN approves bounded changes. **Trade-off:** Long-term summaries need data-minimization review and storage monitoring; raw exact text may no longer be available after policy expiry. **Rejected:** Cascading deletion of trade evidence, free prompt edits and autonomous safety/trust updates. **Acceptance:** Cleanup interruption/open-position/unknown-command fixtures; history cannot mutate policy; restore remains paused.

## ADR 011 — Vercel dashboard and gated OpenRouter

Updated 12 October 2026, implementing the user's requested topology before phase 6.
The Python modular backend and separate roles remain approved. Next BFF runs on
Vercel; persistent workers/PostgreSQL remain on Windows with a Linux adapter.
Staging and production use separate PostgreSQL instances, accounts and storage.
Fixed Access human identity with MFA, a separate API service token, BFF key and
bidirectional environment checks protect administrative requests. Preview uses
only an approved staging hostname. Existing password/RBAC/CSRF/confirmation controls
remain. Cloudflare in front of Vercel adds an operational DNS/TLS/cache acceptance
requirement; the real host has not been certified by local tests.

OpenRouter is the implemented external route; the direct OpenAI adapter stays offline.
Explicit bounded synthetic tests generate a private expiring environment/key-bound
receipt; operator import creates immutable profiles. The worker reserves full published
context and caps output/provider prices. Unknown cost retains budget and prevents
resubmission. Reported billing remains distinct from conservative accounted cost.
Account/model/provenance/privacy/billing acceptance and authorized fixture quality
review are required; no model result grants risk or execution authority.

Evidence and operator steps: [Vercel](../DEPLOYMENT_VERCEL.md),
[OpenRouter](../OPENROUTER.md), [validation](../PHASE_5B_VALIDATION.md).
