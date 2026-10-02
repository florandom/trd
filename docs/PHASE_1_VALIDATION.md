# Phase 1 validation

Date: 2 October 2026. Scope: repository and local infrastructure only, approved by the user's “go with phase 1”.

## Implemented

- Pinned Python3.13.16/uv0.12.22 and Node24.20.0/pnpm11.25.0 workspaces, frozen lockfiles, explicit cross-platform tasks and generated OpenAPI/TypeScript boundary.
- FastAPI health-only API and isolated bridge, service-scoped validated settings, structured redacted rotating logs, separate heartbeat processes and paper-only guards.
- PostgreSQL17.11 minimal users/settings-version/audit/heartbeat schema, explicit owner/migration/runtime roles, restricted public projections, protected heartbeat function and idempotent Argon2id administrator/default bootstrap.
- Non-root, read-only application containers, loopback published ports, PostgreSQL volume and optional Redis8.2.2; separate host-development override.
- Actual Astryx0.6.4 dark responsive shell with backend readiness, disabled future navigation and honest offline/stale states. No fabricated account or trading data.
- CI for Python/frontend checks, API drift, real PostgreSQL integration and Windows script previews; Windows native deployment planning/template generation with explicit write/artifact guards.

## Evidence

The final local acceptance run is recorded below after completion. Hosted CI execution and actual Windows native service installation are separate acceptance work.

| Check | Result |
| --- | --- |
| Python lint and warnings-as-errors unit suite | Passed; 106 tests |
| PostgreSQL17 upgrade/repeat/downgrade/upgrade and permissions suite | 17 integration tests passed |
| Bootstrap repeat, concurrent attempts and rollback | Passed in the real database suite |
| Future-function PUBLIC execution protection | Passed in the real database suite |
| Frontend strict typecheck/lint, proxy/readiness tests, production build | Passed; 8 tests |
| Desktop/mobile browser, navigation/refresh, standalone CSS | Passed |
| Docker backend and dashboard image builds | Passed; final backend update being checked |
| Full container initialization, API/proxy and process heartbeats | Passed; API/proxy200, fresh healthy heartbeats from all five Python services |
| Documented fresh-checkout local boot | In progress |
| Windows script preview/write guards | Passed under checksum-verified PowerShell7.4.20 on macOS; native Windows untested |
| Hosted CI | Configured and structurally checked; not run |

The database suite creates isolated `trd_test_<uuid>` databases and verifies every service login can write only its own heartbeat, cannot access raw tables, and cannot spoof another identity or shadow the function's target with a temporary table. API views omit hashes/internal audit details. Bootstrap does not reset existing passwords or settings and rolls back conflicting history atomically.

## Findings corrected

The actual locked installs exposed compatibility differences from the disposable Phase 0 spike. Starlette1.7's test client requires the separate httpx2 adapter; this is a test-only dependency. TypeScript6.0.3 replaces TypeScript7 because the pinned lint tooling rejects the newer API. pnpm's strict module resolution requires a direct StyleX Webpack carrier dependency. The dashboard uses the verified SWC/Webpack path and explicit standalone packaging.

pnpm11 uses `allowBuilds`; only the exact reviewed SWC/esbuild/resolver build scripts are allowed. Astryx's published artifacts work with package install scripts disabled. Its three exact0.6.4 packages are narrowly excluded from the release-age delay after actual CLI/build validation. No general supply-chain policy bypass was added.

Setup now rejects automation enablement and unresolved customized placeholders. Provisioning rejects dangerous existing role flags/memberships and inconsistent endpoints. Operational errors report exception classes instead of potentially secret-bearing third-party messages. The migration explicitly revokes global default PUBLIC execution on future functions; a regression test proved the PostgreSQL-specific behavior.

Actual container creation caught comma-separated tmpfs options being split by YAML flow syntax. Quoted mount specifications fixed it and a regression now checks bounded single-path mounts. A leftover host preview exposed supervisor SIGTERM cleanup gaps; handlers now run reverse child-group teardown, with termination/startup-failure regressions. Role provisioning validates every DSN before any catalog change and derives SCRAM verifiers locally so plaintext passwords do not enter role DDL. See [psycopg's password API](https://www.psycopg.org/psycopg3/docs/api/pq.html#psycopg.pq.PGconn.encrypt_password).

An initial failed integration connection produced a library traceback containing a disposable local PostgreSQL administrator credential. That credential was renewed and its connection verified; tests now use short tracebacks by default. It was never committed. Runtime configuration/logging redaction tests pass; this incident does not justify logging raw operator environments in future diagnostics.

## Limits and next phase

No Telegram, provider call, risk evaluation, broker command, EA or order simulator exists yet. The placeholder services persist process/database health only. API readiness means database connectivity plus compatible migration, and does not assert all workers or integrations are operational. Redis is intentionally outside that decision.

No login, session, settings mutation or trading endpoint is exposed. The bootstrap account exists for later authentication work. Keep the current app on loopback; production-looking remote API origins are rejected. Native Windows services, WSL boot supervision, TLS/Access, MT5 interactive-session behavior, reboot/reconciliation and demo broker acceptance remain unverified.

Phase 2 is the full domain/database implementation. Phase 1 approval does not authorize starting that phase or enabling automation/live trading.
