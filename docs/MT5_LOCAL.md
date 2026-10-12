# Local MQL5 bridge — simulation only

Implemented on 12 October 2026, Europe/Rome. This delivers the native EA **source**
and repeatable local simulation, while external account credentials and connections
remain deferred. It does not implement broker submission. No `OrderSend`, trading
library, broker-account login, external URL or DLL import exists in this build.
MetaEditor compilation, the actual MT5 runtime and Windows acceptance are still gates.

## Components and authority

- `apps/mt5/Experts/TrdLocalBridge.mq5`: disabled-by-default `OnInit`/two-second
  `OnTimer` loop, signed HTTP, durable replay/clock state and synthetic snapshots.
- `apps/mt5/Include/TrdCore.mqh`: SHA-256, RFC HMAC construction, exact-byte bridge
  frame, bounded JSON, canonical base64, exact fixed-point laboratory arithmetic.
- `apps/mt5/Include/TrdLab.mqh`: exact immutable command checks, account ownership,
  append-only executor journal, separate synthetic broker ledger, outbox and recovery.
- `infra/scripts/mt5_lab.py` with `tests/mt5`: test-only C++ platform shim. The actual
  EA/core source is included with mechanical syntax adaptations; crypto, JSON,
  preflight, journal reducers and `OnInit`/`OnTimer` logic are not reimplemented.

The Python risk gateway and its isolated `trd_risk` credentials remain authoritative.
The EA has no database credential. ADMIN position requests still use the authenticated
confirmation/apply route. Existing profile enrollment, replay claims, approval and
reservation, immutable command hash, daily baseline/latch, economic deduplication and
uncertain-exposure retention are unchanged. No new migration or public API is needed.

Only the reviewed synthetic account `TRD-PAPER-SIMULATOR`, login `1`, paper mode,
USD/hedging and single `EURUSD.paper` profile are accepted. Lab runs use independent
`test-mt5-<random>` environment identities, temporary roles/keys and random loopback
ports. Fixed quotes are synthetic; metadata fixes contract size 100000, tick/point
0.00001, volume step/minimum 0.01, stops/freeze 10/5, round-trip commission 7 and
slippage buffer 5. The EA additionally caps full volume at one lot. Price/volume
arithmetic uses checked five-decimal integers; exact entry-value comparison uses ten
decimals. Unsupported precision/profile/modes fail closed. Full close and reducing
SL/TP are supported; partial fills/closes, pending orders and automatic stop execution
are outside this EA lab scope.

## Repeatable local acceptance

Run `pnpm mt5:accept` with Docker, the pinned repository dependencies and a local
C++17 compiler available. The command reads no operator `.env`, creates disposable
PostgreSQL and independent role credentials, enrolls a synthetic fixture and starts
the risk gateway on numeric loopback. It compiles the EA source into the test platform
and exercises real signed HTTP plus authenticated operator routes. Two openings,
restart after a result, duplicate suppression, stop update, two closes (one from
PAUSED), net result and controlled resume must pass. Resources are removed on exit.

This portable run validates source logic and Python interoperability. It does not
produce an `.ex5` or prove MetaEditor syntax, MQL memory/performance, Windows locks,
terminal scheduling, `WebRequest` or power-loss durability. Actual broker state is
never observed or certified. [Current evidence](MT5_LOCAL_VALIDATION.md).

## Preparing a native terminal test without external credentials

From an interactive terminal, run:

```text
pnpm mt5:lab --output-dir <new-private-directory>
```

1. Keep the disposable laboratory running. It generates keys locally and prints only
   its loopback origin. Restrict the output directory and terminal file copies to the
   operator; do not commit or share `config.json` or journal material.
2. Copy the generated `TRD` directory into `MQL5/Experts/TRD`. Open
   `TRD/Experts/TrdLocalBridge.mq5` in MetaEditor, compile and inspect all errors/warnings.
   Keep its sibling `Include` files together. No native compilation is claimed here.
3. Copy `config.json` into `MQL5/Files/TRD-LAB/config.json`. In MT5 options, authorize
   only the exact local HTTP origin printed by the laboratory for WebRequest.
   Do not authorize remote origins or enable broker execution as part of this test.
4. Attach the EA to one chart. Set `ActivateLocalSimulation=true`; keep
   `LocalCrashPoint` empty. No external account login or trading permission is used
   by its code. `ActivateLocalSimulation=false` needs no config and starts no timer.
5. Use the local console for synthetic openings, confirmed stop/close requests and
   state inspection. Position commands go through the existing ADMIN confirmation
   flow; their registration does not confirm execution. Native terminal initialization,
   HTTP allowlist behavior and a complete cycle remain to be tested on the target build.
6. Stop the EA before ending the lab. Exit the console or use Ctrl+C; temporary
   server/database resources and the generated source config are removed. Remove the
   config copy in the terminal too. Preserve journals when checking recovery.

WebRequest is synchronous, allowed in EAs/scripts and unavailable in Strategy Tester;
the EA refuses that tester environment. The one-second network timeout and two-second
timer require measurement in the actual terminal. [Official WebRequest reference](https://www.mql5.com/en/docs/network/webrequest).

Every lab session is limited to its provisioned UTC day. The immutable synthetic
opening equity remains 10000; closing results adjust later equity/free margin without
resetting the loss baseline. A new day requires a new isolated lab session. UTC clock
correctness is required. As TimeGMT has second precision, a durable snapshot clock
prevents same-second restart from inventing a newer observation or sending stale state.

## Journal and failure behavior

`FILE_COMMON` and absence of share flags hold the account journal exclusively across
charts/terminals of the same OS user. Independent environment identities isolate new
lab runs. Journal binding includes profile, origin, journal identity and purpose keys;
changed binding is refused. [Official file sandbox and sharing flags](https://www.mql5.com/en/docs/files/fileopen).

Executor and synthetic broker files contain bounded append-only, hash-chained records.
Sequences persist before transport; SEND_INTENT persists and flushes before the
synthetic broker write. Outcomes/events and acknowledgements persist before projection
or outbox release. Corrupt/truncated files, nonmonotonic sequences/states, missing
economic evidence or a ledger result without a durable intent fail initialization.
Checksums detect corruption; they do not protect against a trusted host administrator.

Recovery replays the independent broker ledger and uploads the original economic
event without submitting again. An intent without a proven result becomes UNKNOWN;
no absent deal, timeout, acknowledgement or restart removes its exposure. Conflicting
command bytes, authenticated response tampering, redirects, encoding changes,
duplicate required headers and changed ownership close the local gate. Contact loss
keeps evidence and retries transport later, without another broker operation.

Native `FileFlush` is used at critical boundaries, with errors checked. It is not a
cross-file or broker transaction and does not certify Windows power-loss behavior.
The portable shim uses POSIX locks/fsync; native disk-full/reboot/multiple-terminal
semantics remain acceptance items. Capacity is bounded (1000 commands/results,
4000 outbox events and 20000 replay records); no financial-evidence pruning occurs.
[Official FileFlush reference](https://www.mql5.com/en/docs/files/fileflush).

`OnTradeTransaction` makes no network calls and cannot turn unrelated terminal trades
into lab evidence. Real broker adapters must separately buffer and reconcile terminal
transactions, ownership and cash flows before any demo/live gate passes.
[Official transaction handler constraints](https://www.mql5.com/en/docs/event_handlers/ontradetransaction).

## Remaining implementation and native acceptance

Compile and inspect `.ex5` with MetaEditor, test the real terminal's HTTP/port/allowlist
and Unicode/binary behavior, journal faults, latency and restart on Windows. No broker
credentials are required to validate this synthetic code path. Later demo work needs
an actual adapter with broker metadata/history/cash-flow reconciliation, attached-stop
and fill capabilities, verified position identifiers and account mode, conservative
OrderCheck/OrderSend outcome handling and real shutdown/reboot recovery. HTTPS remote
transport and live authorization remain separate gates. The local EA cannot be
converted into broker execution by changing a config or a dashboard setting.

See [approved architecture](ARCHITECTURE.md), [paper protocol](PAPER_BRIDGE.md),
[position management](PAPER_POSITIONS.md) and [team guide](team/GUIDA_PREPARAZIONE.md).
