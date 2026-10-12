# MQL5 local bridge validation — source and simulation

This records the original bridge delivery. The later request-adapter extension and
its current evidence are documented in [MT5 broker adapter validation](MT5_BROKER_VALIDATION.md).

Date: 12 October 2026, Europe/Rome. Delivered scope: a disabled-by-default native
EA source, portable source-level execution tests and a temporary native-test laboratory.
No broker adapter, external account API call or actual MT5 execution is certified.
MetaEditor/MT5 are not installed in the checked application locations on this host;
no `.ex5` was generated. External credentials remain reserved for final tests.

## Results

| Check | Result |
| --- | --- |
| New MQL core/executor unit cases | **80 passed** |
| Complete Python unit suite | **678 passed** |
| New native-source/PostgreSQL integration cases | **7 passed** |
| Complete PostgreSQL 17 integration suite | **151 passed** |
| Existing dashboard boundary tests | **16 passed** |
| Distinct passing cases | **845** |
| Ruff | Passed |
| Shared MQL source compiled in C++17 platform harness on macOS | Passed |
| Exact Python/MQL signing frame with durable journal identity | Passed |
| Signed loopback HTTP acceptance through the real risk gateway | Passed |
| Interactive lab setup, signed EA-source handshake, console state and cleanup | Passed |
| Native MetaEditor compilation, terminal/Windows runtime and broker acceptance | **Still required** |
| Real broker orders and external account API requests | **Zero** |

The harness mechanically expands the actual EA includes, removes MQL property/input
syntax and maps its dynamic char array declaration to a C++ vector. Crypto, JSON,
fixed-point checks, journal/ledger reducers, outbox, `OnInit` and `OnTimer` remain the
source under test. Platform functions are test shims: POSIX file locks/fsync, UTC
clock and an explicit Python relay to loopback HTTP. This is source interoperability
evidence, not an MQL compiler, native file API or WebRequest runtime test.

Core tests cover SHA-256 binary/UTF-8 inputs and block-padding boundaries, RFC/Python
HMAC including long keys, exact frames at signed 64-bit sequence limits, malformed
and duplicate/escaped JSON fields, oversized strings/depth, number rejection,
canonical base64 and conservative decimal limits. The runtime lab schema deliberately
accepts only its supported ASCII data; general Unicode broker metadata is not enabled.

Executor tests cover default-off startup without config/network, remote/production/
invalid-key and stale-day refusal, Strategy Tester refusal, exact types and allowed
fields even after authentication, volume/tick/risk/ownership/expiry rejection, BUY/SELL
protection and full close, exact entry-value/fees, missing/duplicate/altered response
headers and body, encoding/redirect rejection, contact recovery, restart around durable
intent/result, one-owner locking, corrupt journal and ledger-without-intent refusal.
Snapshot timestamps use the exact persisted clock observation; same-second restarts
wait without inventing time or producing a stale snapshot.

Seven new real PostgreSQL cases test restart before/after a simulated OPEN, SL/TP
update and CLOSE, retained uncertain exposure, independent result reconciliation,
no second economic operation and same-second restart. These run through signed
transport and the role-authenticated risk gateway. Position requests use real ADMIN,
CSRF/Origin and confirmation/apply routes. Full prior migration/role/financial-history
tests also pass; schema remains `0008_paper_positions` with 50 mapped tables.

## Complete acceptance

`pnpm mt5:accept` produced this sanitized report:

```json
{
  "mode": "paper",
  "executor": "MQL5 source with portable platform shim",
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

The synthetic spread/commission result is not a strategy evaluation. The run uses
a separate randomly named environment, disposable PostgreSQL, independent random
database role passwords and purpose keys, random loopback port and local files.
It reads no operator `.env` and touches no primary database/volume.

`pnpm mt5:lab --output-dir` was separately exercised in an interactive terminal: it
generated a private source/config bundle, accepted a synthetic opening through the
EA-source process, reported the OPEN position and removed its server/container/config
on normal exit. Broker/terminal credentials were never required. Copied terminal
config removal remains an explicit operator instruction. The native terminal itself
was not launched. Ubuntu CI checks the compiler and includes the new unit/integration
tests; actual CI and native Windows execution are not claimed.

## Documentation and visual verification

Current architecture, protocol and position contracts, README, both Italian guides,
shared flow/component diagrams and offline HTML distinguish local source simulation
from unpassed native/broker gates. Both guides append a concise 12 October revision.
The matching Word files were rebuilt using the Documents skill and **all final pages**
were rendered and inspected at original resolution: **three customer pages and seven
team pages**. Figures, tables, commands and pagination are readable, without clipping
or a customer orphan revision page. Intermediate PDFs/PNGs are QA files only.

## Remaining work

Native MetaEditor errors/warnings, MT5 HTTP origin/port/allowlist and timing, native
locks/flush/disk-full/corrupt-file behavior and Windows restart require actual target
tests. No compiled or installed native EA is claimed. Real broker execution needs a
separate adapter and demo acceptance for account mode, ownership, metadata, attached
stops/filling, terminal transaction buffering, history/cash-flow reconciliation and
conservative uncertain-result handling. Remote HTTPS, partial fills/closes, pending
orders and live activation remain disabled. Changing a dashboard setting or local
config cannot activate broker orders in this source build.

See [local contract and native-test procedure](MT5_LOCAL.md),
[approved architecture](ARCHITECTURE.md) and [team guide](team/GUIDA_PREPARAZIONE.md).
