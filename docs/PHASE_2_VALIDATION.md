# Phase 2 validation

Date: 8 October 2026 (Europe/Rome). Scope: domain/database foundation, continued after the user's request “procediamo da dove sei rimasto”. Infrastructure closure and Italian localization were already complete.

## Implemented

- Strict immutable domain contracts, exact financial decimals, UTC-aware timestamps and separate signal/order/command lifecycles.
- Revision `0002_domain` with 29 new tables, composite environment/account references, durable identities and frozen SQL migration inputs.
- Scoped transactional repositories, optimistic version conflicts, immutable event receipts, audit/outbox atomicity and bounded durable job leases.
- Versioned agent/prompt/risk configuration, reviewed offline model registry and repeat-safe disabled defaults.
- Raw Telegram/AI retention with current versioned policies, bounded resumable batches and protected active/open/uncertain evidence.
- Capability-specific runtime grants, protected history/payloads and safe database functions. No additional HTTP endpoints.

## Evidence

| Check | Result |
| --- | --- |
| Python lint and full suite | Passed; 160 tests, including 121 unit tests and 39 real PostgreSQL integration tests |
| Fresh/repeated migration, full downgrade/re-upgrade | Passed against isolated random test databases |
| Foundation upgrade preserves administrator credentials | Passed |
| Frozen SQL matches current ORM metadata | Passed; no drift |
| Concurrent settings/message/signal/job operations | Passed; conflict detection, deduplication, unique claims and lease-generation fencing |
| Event replay, uncertain execution and transaction rollback | Passed |
| Versioned registry/config and disabled bootstrap | Passed; later versions and model availability preserved |
| Environment/account integrity, exact decimals and large broker IDs | Passed |
| Raw retention, open-position protection and interrupted cleanup | Passed; expired bodies erased without deleting anchors or summaries |
| Runtime authority and immutable history/payload tests | Passed |
| Frontend typecheck, lint, tests and production build | Passed; eight tests |
| OpenAPI regeneration | Passed; no shared-contract drift |
| Backend/dashboard container build and local release | Passed; actual initializer upgraded the preserved primary database to `0002_domain` |
| Local readiness, defaults, heartbeat and cleanup command | Passed; API/proxy200, six disabled agents, no signals/orders, fresh heartbeats from all five services and zero-body cleanup |

The integration fixture explicitly selects the existing local PostgreSQL 17 test server, creates fresh random `trd_test_<uuid>` databases and drops only those disposable databases. Primary workspace records are not used as test fixtures. The existing primary stack was updated with the rebuilt container images; its data volume was preserved, migration/bootstrap completed, and both API readiness and dashboard proxy returned HTTP200 in paper mode with automation disabled. The served document retained Italian language and the updated “Non attivi” agent label. The operator cleanup task completed using the maintenance scope and reported zero expired raw bodies.

## Limits and next phase

No real AI, Telegram collection, MT5/EA, broker command, order simulator, risk evaluation, external notification or outbox dispatcher is active. The database stores the contracts needed for those later components. Declared broker evidence is supplied by the trusted risk role; authenticating and reconciling real broker events is future bridge work.

Agent/risk/model publication is currently operator-only; the bounded API setting function has no HTTP route. Login, sessions/RBAC/CSRF enforcement and the full Italian dashboard belong to Phase 3. Keep the application on loopback. Live trading and automation remain disabled.

Retention supplies a manual, schedulable bounded batch; no periodic cleanup process is enabled yet. Evidence writes are conservatively serialized per environment to avoid cleanup races. Native Windows service, MT5, hosted CI, reboot/restore and demo-broker acceptance remain unperformed.
