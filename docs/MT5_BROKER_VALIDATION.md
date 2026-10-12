# Local MT5 request adapter validation

This records the request-adapter delivery. The subsequent native read-only connection
and its current evidence are in [native validation](MT5_NATIVE_VALIDATION.md).

Date: 12 October 2026, Europe/Rome. Delivered scope: MQL5 request construction,
synthetic terminal preflight/replies and durable conservative recovery through the
existing authenticated paper gateway. Native broker calls remain absent. No `.ex5`,
actual terminal execution, demo/live order or external account API acceptance is claimed.

## Measured results

| Check | Result |
| --- | --- |
| New broker-adapter unit cases | **59 passed** |
| All MQL core/executor/adapter cases | **139 passed** within the unit suite |
| Complete Python unit suite | **737 passed** |
| MT5/PostgreSQL integration file | **22 passed**, including 15 new adapter cases |
| Distinct unit and scoped integration cases | **759 passed** |
| Ruff and Git whitespace checks | Passed |
| Signed HTTP complete local acceptance | Passed |
| MetaEditor, terminal, Windows and demo broker | **Still required** |
| Native broker submissions and external account API calls | **Zero** |

The full unrelated PostgreSQL and dashboard suites were not rerun for this extension;
their earlier evidence remains in [bridge validation](MT5_LOCAL_VALIDATION.md). These
counts describe the checks actually run here. No dashboard/public API schema,
environment variable, migration or runtime database permission changed.

## Coverage and limits

The portable compiler includes the actual EA, request builder, journal and synthetic
terminal source; the harness mechanically adapts MQL syntax and supplies platform
primitives and compatible MqlTradeRequest/Result structures. Tests inspect the actual
request action/type/volume/price/stops/ticket fields for BUY and SELL, protective
updates and opposite-side full closes, including a current ticket above JavaScript's
safe integer bound and independent lifetime identifier.

Identity/currency/netting/symbol/precision/filling/attached-stop mismatches and manual
target changes fail before submission. A changed quote after broker check rejects
the request before intent. Preflight rejection releases only unsent gateway risk;
restart before intent rejects the abandoned command. DONE/PLACED without independent
history, partial reply, timeout, connection failure, false API result, post-intent
rejection and signed external error code retain intent and risk across restart.
Unknown commands stop subsequent polls and complete snapshots; outbox transport
remains available. Protective-update/close uncertainty preserves the original
position and the gateway's UNKNOWN operation.

Independent durable full economic history confirms execution even when the broker
reply says timeout or accepted. Existing before/after-intent/result crash tests,
outbox deduplication, exclusive ownership, tampered/corrupt journals and signature
checks remain passing. Original retcode_external is preserved as a signed 32-bit
value. Partial reply testing does not implement partial economic execution. Native
transaction buffering, broker metadata/history/cash flows and demo identity remain
outside the synthetic port and need their own implementation/acceptance.

All database tests use temporary PostgreSQL 17, separate role credentials and
randomly named test databases. Acceptance runs use independent synthetic environment
identities and numeric loopback HTTP with purpose keys generated locally. Operator
`.env`, primary database/volumes and external account credentials are not used.
Disposable resources are removed on exit.

## Complete acceptance report

`pnpm mt5:accept` exercises the extended adapter through the original full cycle:

```json
{
  "mode": "paper",
  "executor": "MQL5 source with portable platform shim",
  "broker_adapter": "MqlTradeRequest with synthetic terminal port",
  "broker_request_checks": 5,
  "external_connections": false,
  "real_orders": 0,
  "simulated_openings": 2,
  "stop_updates": 1,
  "full_closes": 2,
  "duplicate_operations": 0,
  "restart_reconciled": true,
  "close_while_paused": true,
  "controlled_resume": true,
  "realized_pnl_usd": "-3.0600000000",
  "native_metaeditor_compilation": "still required",
  "database_and_keys": "temporary"
}
```

The result reflects synthetic spread/commission and is not a strategy evaluation.
The return report verifies five request checks, correct opposite-side targeted close
and no opening stops on a close. Broker replies are separate from history and may
be absent after a crash; no exactly-once broker guarantee is inferred.

## Maintained documents

Both Italian guides, matching Word files, shared illustrations and offline HTML now
distinguish the implemented simulated request adapter from native/broker gates.
Revision entries are dated 12 October 2026 in Europe/Rome. Word files were regenerated
with the Documents skill and all final pages inspected at original resolution:
**three customer pages and seven team pages**. Revision spacing was adjusted locally
without reducing body font size to avoid an orphan customer revision page. No secrets,
sessions or personal source messages appear in the artifacts. Rendered PDFs/PNGs are
private QA intermediates, not deliverables.

See [adapter contract and final gates](MT5_BROKER_LOCAL.md),
[native synthetic-test preparation](MT5_LOCAL.md) and
[approved architecture](ARCHITECTURE.md).
