# Phase 7 validation — local paper execution

Date: 12 October 2026, Europe/Rome. Scope: local simulation with synthetic data,
independent database roles and temporary signing keys. External API connections and
credentials are deferred to the operator's final tests. Real trading remains off.

## Delivered within this scope

- Opt-in risk-only gateway with signed synthetic snapshots, persistent ownership,
  replay fencing and exact-byte request/response authentication. Normal startup is off;
  remote, demo and live activation remains rejected.
- Current source/message/agent/advisory evidence, shared pure engine admission and
  dispatch revalidation under evidence/account locks. Lock contention cannot extend
  signature validity or telemetry freshness. A command's own hold is counted once.
- Atomic risk event, approval/reservation, immutable command/hash, order, lifecycle,
  audit and outbox. Commands bind trace, approval, reservation, ownership generation,
  account, policy/source versions, stops, volume, price band and deviation/spread limits.
- Durable UTC baseline and inclusive loss latch; recovery cannot erase the latch.
  Unsupported cash-flow adjustments are rejected. Source/message/policy changes
  invalidate only unsent commands; submitted/unknown exposure remains reserved.
- Durable executor journal and separate non-idempotent synthetic broker ledger.
  SEND_INTENT commits before submission; crash recovery never blindly resubmits.
  Transport acknowledgements cannot complete a trade. Full/partial fill evidence,
  independent event/deal deduplication and contradictory-evidence quarantine are tested.
- Repeatable `pnpm paper:accept` using disposable PostgreSQL, random loopback ports,
  synthetic fixtures and local keys. No operator `.env` or primary database is accessed.
- Migration `0007_paper_bridge`, 47-table ORM/schema parity, fenced financial history,
  narrow runtime grants and evidence-preserving downgrade refusal.

## Verification results

| Check | Result |
| --- | --- |
| New phase 7 unit/configuration cases | 69 passed |
| Complete Python unit suite | **570 passed** |
| New phase 7 PostgreSQL cases | 26 passed |
| Complete PostgreSQL 17 integration suite | **127 passed** |
| Dashboard tests | **16 passed** |
| Distinct passing cases | **713** |
| Ruff, strict TypeScript and ESLint | Passed |
| Dashboard production Webpack build | Passed |
| Backend container build | Passed |
| Linux container journal/lock/restart/deduplication, networking disabled | Passed |
| Generated OpenAPI and shared types | Byte-identical; private bridge absent |
| Signed loopback HTTP paper acceptance | Passed: two simulated orders, zero duplicates |
| Real broker orders and external API requests | **Zero** |

Protocol tests cover RFC 4231, exact-body mutation, all authenticated context headers,
direction/status/path/outstanding-sequence binding, validity edges, overflow and
bounded strict JSON. Simulator tests cover fixed numeric loopback, ignored proxies,
unsigned/stale/mismatched responses, owner locking, persistent binding, duplicate
delivery, changed command hash, immutable financial preflight, deviation limits,
already claimed SEND_INTENT and restart before/after broker submission.

Real PostgreSQL cases cover concurrent admission, transaction rollback, replay cache
and signed conflicts, authentication failure without writes, current metadata/spread,
default WAIT provider, source/message/policy invalidation, partial fills and economic
deduplication, late/out-of-order evidence, unknown retention, expiry after delivery,
fill-batch rollback, immutable baseline/latch, unsupported cash flows, role separation,
new-journal takeover refusal and expiry while blocked behind the evidence fence.

Integration runs used an independent temporary PostgreSQL 17 container and random
`trd_test_*` databases, with randomly generated distinct role passwords. The disposable
container and databases were removed. Primary volumes, database and private operator
configuration were not accessed or modified. The local acceptance run also removed
its temporary HTTP server, container, profile, keys and journal after completing.

CI includes the pure engine, protocol, revalidation and simulator tests in its Windows
job. Actual Windows-runner execution is not claimed; Linux container checks do not
certify native Windows services or MT5.

## Documentation and visual verification

Affected technical contracts, environment template, Italian dashboard copy, maintained
customer/team guides and shared diagrams describe the isolated paper availability.
The offline HTML shares the updated flow. Guides retain the 12 October revision and
append a concise phase 7 entry; external account setup remains a final-test action.

Both Word guides were regenerated through the Documents skill's bundled runtime,
rendered and visually inspected at original resolution on every final page:
**three customer pages and six team pages**. Figures, tables, variable names, commands,
headers and footer pagination are readable. The final team guide has no orphan
revision page. Intermediate render PDFs/PNGs are QA artifacts, not deliverables.

## Remaining implementation and acceptance

This completes phase 7 only within the requested local simulation scope. The lab
executes synthetic EURUSD market openings with a USD account and attached stops;
the pure engine's seven profiles retain their separate calculation tests. Native
MQL5, MT5/demo broker transport, cash-flow/history reconciliation, real account
ownership, stop modifications, closes, fault/latch reset and deployment/reboot/restore
acceptance remain future work. Pending orders, partial closes and live remain disabled.
No production, profitability or exactly-once broker claim is made.

See [paper bridge](PAPER_BRIDGE.md), [approved architecture](ARCHITECTURE.md),
[risk contract](RISK.md) and the [team procedure](team/GUIDA_PREPARAZIONE.md).
