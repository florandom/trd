# Native MT5 read-only source validation

Date: 12 October 2026, Europe/Rome. Scope: native account/market/portfolio/history
reads, transaction buffering, current-ticket lookup and private local journal.
Source is tested against terminal API fixtures; actual MT5, MetaEditor, Windows
and demo-broker acceptance remain the operator's final tests. No `.ex5` or native
terminal execution is claimed. Submission and broker preflight are absent from the
MQL source; operator credentials and external accounts were not used.

## Measured checks

| Check | Result |
| --- | --- |
| New native connection unit cases | **54 passed** |
| MQL core/executor/broker/native test files | **193 passed** within the unit suite |
| Complete Python unit suite | **791 passed** |
| pnpm mt5:native:accept | Passed with native API fixtures |
| Complete signed paper HTTP/PostgreSQL cycle | Passed independently |
| pnpm mt5:native:prepare | Passed; private source bundle created, inactive and unconfigured |
| Ruff and Git whitespace checks | Passed |
| Word render and visual inspection | **3 customer pages and 7 team pages verified** |
| Native account/terminal/Windows/demo acceptance | **Still required** |
| Broker send/check API calls, real orders and external account connections | **Zero** |

The full PostgreSQL integration and dashboard suites were not rerun: this connection
adds no migration, backend/public API or dashboard change. The existing paper
acceptance creates temporary PostgreSQL with separate role credentials and loopback
HTTP. Prior integration evidence remains in [broker validation](MT5_BROKER_VALIDATION.md).
The operator's `.env`, installed services, primary database and real accounts remain unused.

## Native source behavior

Tests include the actual `TrdNativeReadOnly.mq5`, `TrdNative.mqh` and core source.
Mechanical syntax adaptation and compatible native API/file/time primitives are test
fixtures; observer, validation, lifecycle, buffering and journal logic remain MQL.
This does not establish MetaEditor syntax/type acceptance or Windows runtime behavior.

Default-off startup calls no terminal API and creates no journal. Missing inputs and
Strategy Tester are refused before native reads. Positive login/server must exactly
match a DEMO account; REAL, CONTEST and subsequent identity switches fail closed.
All account positions and orders are observed, including manual/unprotected/foreign
exposure. Large ticket and lifetime identifiers stay exact and separate; target lookup
rejects disconnected terminal cache. Netting and negative equity remain diagnostic,
without ownership or execution authority.

Metadata/quote/account/history omissions, nonfinite values, subprecision data that
would round to zero, non-ASCII metadata, stale/future ticks, duplicate tickets,
collection races and count/record capacities produce no partial or fresh snapshot.
Native broker-time history bounds remain separate from UTC observation timestamps.
Raw deposit, commission, swap and fee observations are retained; they never establish
a policy-day baseline or full reconciliation. A limited window explicitly leaves
`full_reconciliation=false`.

Transaction tests cover duplicate/reordered notifications without extra deals,
memory-only callbacks, REQUEST-only result use, discarded undefined REQUEST transaction
fields, ignored result fields on other types, overflow and flush failures. Journal
tests cover exclusive ownership, restart sequence, no stale snapshot adoption,
corruption and changed binding. Contact loss clears current data and can recover.
Buffer hints are released only after checked flush; no exactly-once or native power-loss
durability claim follows from POSIX fixture locks/fsync.

Valid open/close/SLTP requests remain blocked by `TrdNativeSend`, including with all
observed trading permission flags true. Source checks exclude OrderSend, OrderSendAsync,
OrderCheck, trading-library calls and DLL imports across MQL files. Native EA source
has no HTTP or command-acceptance path and cannot impersonate the authenticated paper EA.

## Sanitized acceptance output

```json
{
  "scope": "native-readonly",
  "runtime": "MQL5 source with native API fixtures",
  "terminal_observation_cycles": 3,
  "transaction_hints_buffered": 2,
  "all_account_positions_observed": 1,
  "pending_orders_observed": 1,
  "history_deals_observed": 2,
  "history_orders_observed": 1,
  "current_ticket_resolved": true,
  "restart_sequence_preserved": true,
  "send_gate_bypasses": 0,
  "broker_calls": 0,
  "external_connections": false,
  "native_metaeditor_terminal_acceptance": "still required",
  "operator_credentials_used": false
}
```

Native acceptance uses a private temporary directory and removes it on exit. The
prepared operator copy contains only three native/core source files and LEGGIMI,
with a fresh journal identity, empty account/symbol inputs and activation false.
No credentials, session material or actual trade messages are included.

Both Italian guides append a concise Europe/Rome revision. Matching Word files were
rebuilt with the Documents skill; all final pages were inspected at original resolution.
The customer guide stays on three pages without an orphan revision page. Shared
illustrations and offline HTML show native observation separately from paper execution.
Rendered PDFs/PNGs are internal QA intermediates only.

See [native procedure, limits and final gates](MT5_NATIVE_LOCAL.md) and
[approved architecture](ARCHITECTURE.md).
