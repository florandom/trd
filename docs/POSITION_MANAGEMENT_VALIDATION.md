# Position management validation — local simulation

Date: 12 October 2026, Europe/Rome. Scope: confirmed operator requests on the
enrolled synthetic EURUSD/USD account. External APIs and credentials remain
deferred to the operator's final tests; MT5 and real trading remain disabled.

## Delivered

- Authenticated ADMIN can review and confirm a full simulated close or an SL/TP
  update that cannot increase stop-loss risk. VIEWER remains read-only. Requests
  bind the position revision, account safety epoch and expiring confirmation.
- Risk alone validates, creates and signs the maintenance command. Existing
  replay fences, account locks, durable executor journal and independent synthetic
  broker ledger cover delivery and restart. Uncertain submission is never retried
  blindly, and full position exposure remains until a proven result.
- Confirmed protection, closed positions, closing time and net realized results
  remain visible in the dashboard. Exact immutable entry fills drive USD Forex
  P&L, including the reviewed synthetic commission and conservative rounding.
- Explicit controlled resume requires current complete reconciliation and compliant
  limits. It preserves the UTC baseline and daily-loss latch. Clearing a contradictory
  evidence fault additionally requires a verified flat account.
- Migration `0008_paper_positions` adds three fenced tables, scoped safe dashboard
  views and guarded operator submission: **50-table ORM/schema parity**. Runtime
  database roles remain separate; even risk cannot directly insert operator requests.
  A maintenance command without a reservation requires its exact confirmed request.

## Verification results

| Check | Result |
| --- | --- |
| New position-management unit cases | **28 passed** |
| Complete Python unit suite | **598 passed** |
| New position-management PostgreSQL cases | **17 passed** |
| Complete PostgreSQL 17 integration suite | **144 passed** |
| Dashboard tests | **16 passed** |
| Distinct passing cases | **758** |
| Ruff, strict TypeScript and ESLint | Passed |
| Dashboard production Webpack build | Passed |
| Backend Linux container build | Passed |
| Linux offline journal, full close, net P&L and restart smoke | Passed |
| Generated OpenAPI and shared types | Updated for the two confirmed actions |
| Signed loopback HTTP and authenticated API acceptance | Passed |
| Real broker orders and external account API requests | **Zero** |

Unit tests cover BUY/SELL close and protective updates, identity and volume changes,
freshness and precision checks, risk increase, unsupported partial close/protection
removal, net profit/loss/fees, exact fill value versus a rounded display average,
incorrect entry evidence rejected before submission, and restart before/after a
broker operation for both actions.

Real PostgreSQL tests exercise ADMIN login, CSRF, Origin and confirmation/apply
routes, safe result history, duplicate economic outcomes with different transport
IDs, unknown retention, unresolved-operation resume refusal, close while paused,
daily-loss latch and baseline preservation, explicit flat fault reset, VIEWER and
confirmation-reuse rejection, stale revisions, all five runtime-role request
forgery denials, contradictory-outcome rollback and corrected reconciliation, and
unreserved opening rejection. The complete integration suite also checks migration
upgrade/downgrade, schema parity and existing role and lifecycle boundaries.

`pnpm paper:accept` produced the following sanitized report using temporary resources:

```json
{
  "mode": "paper",
  "external_connections": false,
  "real_orders": 0,
  "simulated_orders": 2,
  "duplicate_orders": 0,
  "restart_reconciled": true,
  "stop_update_confirmed": true,
  "full_closes_confirmed": 2,
  "close_while_paused": true,
  "controlled_resume": true,
  "realized_pnl_usd": "-3.0600000000",
  "database_and_keys": "temporary"
}
```

The reported loss is a deterministic synthetic spread/commission result, not a
strategy evaluation. The acceptance path uses real authenticated dashboard routes
and the signed loopback bridge, with random ports and in-memory operator credentials.
Temporary PostgreSQL containers, keys, profiles, journals and HTTP servers were
removed. Primary database volumes and private operator configuration were untouched.
The Linux smoke ran with networking disabled. Native Windows execution and interactive
browser usability acceptance have not been performed; Windows CI includes the new
pure tests.

## Documentation and visual verification

Affected architecture/database/bridge contracts, customer and preparation guides,
shared flow illustration and offline HTML describe the new local availability.
Both Italian guides append a concise 12 October revision and distinguish verified
simulation from remaining configuration and implementation.

The matching Word files were regenerated using the Documents skill and every final
page was rendered and inspected at original resolution: **three customer pages and
six team pages**. Tables, figures, commands and pagination remain readable; there are
no orphan revision pages. Intermediate QA PDFs/PNGs are not deliverables.

## Remaining gates

This extension completes local full-close, protective-update, result-history and
controlled-resume behavior. The subsequent [local MQL5 source](MT5_LOCAL.md) has a
separate simulation scope. Native terminal acceptance and broker transport, real broker history/cash-flow
reconciliation, automatic broker-held stop execution, partial closes/pending orders,
additional executor conversions, position-review agents, memory, notifications and
deployment/reboot/restore acceptance remain future work. External Telegram/AI/broker
account setup and credentials are still reserved for the user's final tests.

See [position contract](PAPER_POSITIONS.md), [original phase 7 checkpoint](PHASE_7_VALIDATION.md)
and [team procedure](team/GUIDA_PREPARAZIONE.md).
