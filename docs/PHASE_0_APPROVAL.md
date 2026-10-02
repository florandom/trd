# Architecture Approval Gate

Phase 0 only — 2 October 2026. **Awaiting approval. Phase 1 has not started.**

## Final stack

Next.js16.3.8, React19.3, strict TypeScript, Node24/pnpm; Astryx core/CLI/neutral theme0.6.4 and StyleX0.19.0. The disposable production build passed, including authored StyleX using the tested SWC/Webpack path. Python3.13, FastAPI/Pydantic2, SQLAlchemy2.0/psycopg3, Alembic and PostgreSQL17. Telethon ingestion, provider-neutral AI contracts, mock then OpenAI adapter, deterministic Python risk, MQL5 executor and protocol-compatible paper simulator. Redis is optional. Exact package evidence: [Astryx](research/ASTRYX.md), [backend](research/BACKEND.md).

## Deployment strategy

| Target | Selected path |
| --- | --- |
| macOS | Compose with PostgreSQL/optional Redis/app services; host-development override; simulator for paper E2E |
| Windows A | Conditional WSL2 Ubuntu + Docker Engine/Compose; requires provider-enabled nested virtualization and Windows-managed boot/continuity tests |
| Windows B | Native PostgreSQL/Python/Uvicorn/Node standalone, pinned WinSW services; no Docker Desktop or Redis prerequisite |
| Windows host | Native MT5/EA, RDP/browser, Caddy and cloudflared; first supported target Server2022 Desktop Experience |

Backend services must restart before desktop login. MT5/EA uses an interactive trading session. Default after reboot is paused until login and reconciliation. Hands-free GUI recovery requires an optional explicitly accepted Autologon policy and actual reboot tests. [Deployment evidence](research/WINDOWS.md)

## Repository tree

Proposed, not scaffolded:

```text
apps/          dashboard, api, worker, telegram, simulator entrypoints
backend/       domain, application, infrastructure, api, ai, trading, integrations
packages/      generated shared-types, reviewed config manifests
mt5/           AutonomousTraderEA and protocol fixtures
migrations/    Alembic and bootstrap
infra/         docker, windows, cross-platform scripts
tests/         unit, integration, e2e, fixtures
docs/          architecture, threat model, env, ADRs, research, phase evidence
```

Root lockfiles, Compose, CI, `.env.example` and task runner are Phase 1 work. Phase 0 has only documentation and repository housekeeping. [Full structure](ARCHITECTURE.md#12-proposed-repository-layout)

## Security and execution model

- AI produces advisory schemas, has no tools/bridge keys and cannot write approvals.
- Isolated risk/bridge worker owns hard-limit evaluation, atomic account reservations, signing, replay checks and authenticated portfolio telemetry. Normal admin API cannot fabricate account equity or positions.
- Hard env → server policy → versioned bounded dashboard config → agent proposal; later layers can only tighten authority. Full risk revalidation precedes delivery.
- Signed, short-lived HTTPS commands; persistent command/event identities and EA journal. Lost broker outcomes stay OUTCOME_UNKNOWN for reconciliation; no blind retries or exactly-once claim.
- ADMIN/VIEWER, Argon2id, opaque secure sessions, CSRF/Origin, throttling, confirmations and audit. External production access requires Access MFA or an implemented equivalent.
- Default paper, automation off, live off. Demo and live identities/keys isolated; live needs deployment and EA gates plus demonstrated demo acceptance.

[Data-flow/trust diagrams](ARCHITECTURE.md#3-data-flow), [threat model](THREAT_MODEL.md), [ten ADRs](adr/README.md).

## Environment matrix

| Group | Browser visibility / storage |
| --- | --- |
| App/runtime | Safe mode/status only; validated deploy config |
| DB/cache | Per-service secret DSNs; separate migration role; Redis optional |
| Auth | Password hash/hashed sessions; encrypted optional MFA material; no public defaults |
| Telegram | Encrypted session and separate collector-only key/API credentials |
| AI | Provider keys only in AI worker; allowlisted model/prompt manifests; cost envelope |
| MT5 | Separate request/event and command/response HMAC keys; enrolled account tuple and instance |
| Risk/live | Hard fractions/symbol/size/freshness limits and live flag are deployment-only |
| Retention/alerts | Seven-day raw defaults; durable trade/recovery evidence protected; fixed alert recipient |

The [complete variable/default/secret/consumer matrix](ENVIRONMENT.md#variable-matrix) specifies Phase 1 `.env.example` and validation.

## Checks and unresolved assumptions

Passed: environment inspection, actual Astryx CLI discovery, package metadata checks, disposable Next/Astryx builds and custom StyleX CSS emission, architecture/security peer review and document integrity checks. [Detailed evidence](PHASE_0_VALIDATION.md)

Not tested: full backend graph, Docker local boot, migrations, browser interactions, real Telegram/AI, native EA compile/demo broker, Windows services/TLS/reboot/restore. No production code or trading tests exist yet.

Local default Python is3.9 and Docker was not found in PATH/standard app location; Phase 1 must provision/locate the documented runtimes before claiming fresh-clone boot. Actual VPS/nesting, broker account mode/symbol valuation, off-host backup/RPO/RTO and optional GUI autologon remain later deployment acceptance prerequisites. These do not block a paper foundation. No technical design question currently requires a user answer.

## Proposed Phase 1

1. After approval, establish pinned Python/Node/pnpm tools, lockfiles and cross-platform task runner; locate/verify Docker.
2. Create the monorepo entrypoints, typed strict config/redaction, minimal API and isolated bridge skeleton, safe public schemas and generated client boundary.
3. Add Compose services and host-development override, PostgreSQL persistence, optional Redis, non-root/restricted service env, and paper-only defaults.
4. Add initial Alembic migration/role grants, explicit bootstrap and default config lifecycle; seed no live credentials or permissions. Full trading schema/versioning belongs to Phase 2.
5. Add Next/Astryx theme/shell smoke screen using real CLI contracts, health/readiness and component heartbeat skeletons. Full dashboard/auth UI belongs to Phase 3; no unauthenticated admin mutation routes are exposed meanwhile.
6. Add CI: backend unit/config checks, frontend typecheck/lint/build, fresh PostgreSQL migration smoke and Windows backend/build compatibility.
7. Verify fresh-clone boot from documented commands, record failures/limits, update docs and commit logical work. Stop on a true blocker; otherwise continue the approved phase plan.

Approval needed now is only to begin Phase 1. No approval for live trading, broker execution, Autologon or external publishing is implied.
