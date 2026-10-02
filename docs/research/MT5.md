# MT5 bridge research and execution safety contract

Research date: 2026-10-02. Phase 0 design only; no EA implementation, compilation, broker connection, demo execution, or Windows reboot test has been performed. Facts below are verified against primary documentation. Protocol details and operational limits are proposed project decisions, not claims of broker guarantees.

## Decision

Use outbound authenticated HTTPS polling from one native Windows MQL5 EA, with signed JSON replies and event uploads. Use the same wire protocol in a deterministic Python paper simulator on macOS. Keep AI, risk evaluation, and the execution bridge separate. The EA accepts an immutable, expiring risk-approved command and applies an independent set of local checks before submitting a trade request.

Use synchronous `OrderSend` initially. Do not infer execution from an HTTP acknowledgement, successful `OrderCheck`, successful `OrderSend` boolean, or an order placement notification. Broker-confirmed deals and reconciliation establish fills. A lost response after a send creates `OUTCOME_UNKNOWN`, which prevents automated resubmission and retains the risk reservation.

## Verified capabilities and constraints

| Area | Verified fact | Design consequence |
|---|---|---|
| HTTPS transport | `WebRequest` accepts method, URL, millisecond timeout, byte body, custom headers, and response body/headers. Header lines use CRLF. It returns HTTP status or -1. Required URLs must be allowlisted in terminal settings. It is synchronous, available to EAs/scripts, and unavailable in Strategy Tester. The documented signature has no response-size ceiling parameter. | Poll from `OnTimer`; bounded requests, small replies, retry/backoff, an actual Windows test, and a separate simulator are necessary. |
| Timer scheduling | One timer per program; a new Timer event is omitted if a Timer event is queued or running. | Polling has no exact latency guarantee; measure elapsed time and heartbeat freshness, not timer counts. |
| Cryptography | `CryptEncode` operates on byte arrays. Its documented algorithms include SHA-256 and Base64; no HMAC method is listed. | Compose standard HMAC-SHA256 from SHA-256 and byte operations; require published test vectors and Python/MQL interoperation before enabling execution. |
| Encoding | `StringToCharArray` supports explicit code pages; its default can include terminal NUL and does not necessarily shrink an existing array. | Use explicit UTF-8, resize exactly, and exclude terminal NUL from HTTP bodies, hashes, and MACs. |
| Preflight | `OrderCheck` returns check results but does not guarantee a subsequent operation will execute. | Record the boolean, error, and check result; apply project risk policy separately. |
| Submission | `OrderSend(true)` does not by itself establish a fill. Inspect `retcode`, `retcode_external`, and later trade transactions. | Model SENT, ACCEPTED, PARTIALLY_FILLED, FILLED, and uncertain outcomes separately. |
| Trade events | `OnTradeTransaction` may describe manual trades and server activity. Arrival order is not guaranteed; the queue holds 1024 transactions. Request/result arguments apply only to `TRADE_TRANSACTION_REQUEST`. | Keep the handler short; queue observations for upload and reconcile with current state/history. Never make HTTPS calls from this handler. |
| Correlation | `MqlTradeResult.request_id` is assigned by the terminal. Requests and their IDs are held in terminal memory. | Persist terminal request ID as a hint; use broker order/deal/position identifiers for restart recovery. |
| Position identity | `POSITION_IDENTIFIER` relates orders/deals through `ORDER_POSITION_ID` and `DEAL_POSITION_ID`; `POSITION_TICKET` can change during service operations. | Store both lifetime identifier and current actionable ticket, scoped to the account. |
| Account identity | `ACCOUNT_LOGIN`, `ACCOUNT_SERVER`, trade mode, margin mode, trade/expert permissions, and currency are available. Modes distinguish DEMO, CONTEST, and REAL. | Pin login + server + trade mode; never identify an account by login alone. |
| Terminal/EA status | Terminal connection and trading permission, EA trading permission and tester status are exposed. | Recheck these before submission and report them in health state. |
| Broker metadata | Symbol properties expose volume minimum/maximum/step, tick size/value, stop/freeze levels, filling/order modes, currencies and calculation mode. | Permit only explicitly supported instrument profiles; reject missing/stale metadata and incompatible order modes. |
| Partial close | `CTrade.PositionClosePartial` is documented for hedging accounting and can operate by ticket. Its success boolean is not confirmation of execution. | Partial close is capability-gated; netting reduction requires a separate tested opposite-deal implementation. |
| Local journal | File APIs operate within the terminal file sandbox; `FileFlush` writes buffered file data. | Use a terminal-local append journal; Windows ACLs, corruption recovery, and power-loss behavior require tests. |
| Broker reconciliation | `HistorySelect` creates order/deal history lists for a server-time interval. | Track a broker-time cursor with overlap; preserve original broker timestamps rather than labeling them UTC without conversion. |

Primary references for the table: [WebRequest](https://www.mql5.com/en/docs/network/webrequest), [OnTimer](https://www.mql5.com/en/docs/event_handlers/ontimer), [CryptEncode](https://www.mql5.com/en/docs/common/cryptencode), [cryptographic methods](https://www.mql5.com/en/docs/constants/namedconstants/otherconstants), [StringToCharArray](https://www.mql5.com/en/docs/convert/stringtochararray), [OrderCheck](https://www.mql5.com/en/docs/trading/ordercheck), [OrderSend](https://www.mql5.com/en/docs/trading/ordersend), [OnTradeTransaction](https://www.mql5.com/en/docs/event_handlers/ontradetransaction), [MqlTradeResult](https://www.mql5.com/en/docs/constants/structures/mqltraderesult), [position properties](https://www.mql5.com/en/docs/constants/tradingconstants/positionproperties), [account properties](https://www.mql5.com/en/docs/constants/environment_state/accountinformation), [terminal properties](https://www.mql5.com/en/docs/constants/environment_state/terminalstatus), [EA properties](https://www.mql5.com/en/docs/constants/environment_state/mql5_programm_info), [symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants), [PositionClosePartial](https://www.mql5.com/en/docs/standardlibrary/tradeclasses/ctrade/ctradepositionclosepartial), [FileOpen](https://www.mql5.com/en/docs/files/fileopen), [FileFlush](https://www.mql5.com/en/docs/files/fileflush), [HistorySelect](https://www.mql5.com/en/docs/trading/historyselect).

No documented WebRequest certificate-pinning or client-certificate parameter has been established. Use a fixed HTTPS origin with a valid certificate, no application redirects, no browser challenge, and no URL supplied by a signal/command. Test untrusted/expired certificates and redirect behavior on the chosen MT5 build; do not create a TLS exception. Initial limits below are application controls, not claimed native WebRequest guarantees. Oversized replies can be rejected after receipt; WebRequest does not establish a preallocation memory bound from its public signature.

## Proposed protocol v1

### Routes and scheduling

Use fixed POST routes with no query strings:

- `/bridge/v1/poll`: latest heartbeat/account summary and freshness indicators; reply contains zero or one command.
- `/bridge/v1/events`: durable event batches; reply names the event IDs committed by the server.
- `/bridge/v1/snapshot`: paged account, open-order/position and history observations for reconciliation.

Initial proposal: poll every 2 seconds, WebRequest timeout 1000 ms, heartbeat stale after 10 seconds, jittered capped exponential retry, command submission expiry at most 10 seconds after issuance. These values must be measured against Windows/HTTPS/broker behavior in Phase 7. Timeouts pause new submissions; they never imply a broker rejected an earlier send. A periodic account snapshot is additional to heartbeats; a fresh heartbeat with an incomplete snapshot is insufficient to trade.

Limit poll replies to 16 KiB, other pages/uploads to 64 KiB, event batches to 100, and JSON nesting/string length explicitly. No compressed bodies. The service and reverse proxy enforce body and page limits; EA also rejects unexpected content types, invalid sizes, incomplete pages and schema mismatches. Upload the event outbox before polling another new command. Backlog, journal faults, or a reconciliation gap degrade health and close the new-trade gate.

### Byte-level signing, avoiding JSON reserialization

Sign the exact UTF-8 body bytes; do not parse and reserialize JSON for verification. The body uses strict JSON with no duplicate property names, BOM, NUL, NaN, Infinity, or unrecognized action fields. Python stores the immutable command payload bytes/hash. The EA authenticates before schema parsing. JSON key order and whitespace therefore have no cross-language canonicalization dependency; changes in bytes require a new signature.

The signature header carries the full 32-byte HMAC-SHA256 as lowercase hex. Header fields also include key ID, bridge ID, provisioned instance ID, persistent request sequence, issued-at and expires-at. Headers have exactly one occurrence each; identifiers are restricted ASCII with no newline or delimiter. MAC input is a fixed LF-separated sequence with a final LF:

```text
TRD-BRIDGE-V1
REQUEST or RESPONSE
environment_id
bridge_id
instance_id
key_id
UPPERCASE_HTTP_METHOD
exact_allowlisted_path
http_status (0 for a request)
request_sequence
issued_at_epoch_seconds
expires_at_epoch_seconds
lowercase_sha256_of_exact_body_bytes
```

Each token above occupies one line; REQUEST/RESPONSE and the placeholder values are replaced with their literal protocol values. Request and response signing uses different keys/purposes. A response echoes the sequence of the currently outstanding request; the EA rejects older, unsolicited or replayed responses. Command body includes its own immutable `command_id`, timestamp/expiry, account identity, execution mode, trace, risk approval ID/config version, lease generation, and expected state version, so redelivery of the same command cannot alter its semantics.

MQL5 feasibility is an inference from its SHA-256 primitive and byte arrays. Implement the [RFC 2104 HMAC construction](https://www.rfc-editor.org/info/rfc2104/) with SHA-256: normalize key, pad to 64 bytes, XOR inner/outer pads, and hash twice. Validate against [RFC 4231 HMAC-SHA256 test vectors](https://www.rfc-editor.org/info/rfc4231/), including long keys and binary inputs. Do not substitute `SHA256(secret + body)` or assume that the `CryptEncode` key argument creates an HMAC. Python uses its standard HMAC library and constant-time verification. MQL compares all decoded MAC bytes without early exit; timing properties of compiled MQL remain a review/test item. Fail initialization if the cryptographic self-test fails.

Provision independent 32-byte random keys outside the dashboard for request/event authentication and command/response signing, each with an allowlisted key ID. Bind every key to one environment, bridge, instance, account tuple and direction. Key rotation is explicit, bounded, audited and never occurs from AI output. Sharing an HMAC verification key means a compromised EA can forge commands to itself; HMAC does not protect against endpoint compromise. Treat the Windows host as a high-trust execution boundary and deny AI processes all bridge keys.

### Replay and event deduplication

The server provisions a random instance ID. The EA persists and advances a monotonic request sequence before sending, so `(environment, bridge, instance, sequence)` is unique even after a restart. A counter rollback fails closed and requires controlled re-pairing; do not use `MathRand` as a security nonce. Timestamp validation includes a small configured clock-skew bound, and both timestamp and expiry are signed. Synchronize Windows time; [TimeGMT](https://www.mql5.com/en/docs/dateandtime/timegmt) derives GMT using the local computer's time settings, so clock correctness is an operational dependency. Preserve server/broker timestamps separately.

The server persists replay claims transactionally. A retry of a byte-identical request may return its cached result without rerunning a mutation; the same request ID with different bytes is rejected/audited. A fresh request sequence is safe for resending already-persisted events because each event has a separate stable event ID and payload hash. Response expiry must be rechecked; the server must reissue a signed response for a fresh poll rather than revive an expired command.

For events, enforce unique `(environment, bridge, event_id)`. Same ID/same hash returns the existing acknowledgement; same ID/different hash is a security fault. Acknowledgement follows the database transaction commit. The EA retains its outbox until that acknowledgement. Deduplicate economic fills independently by account-scoped broker deal ticket, so repeated broker observations cannot double-count volume/P&L. Raw observations are append-only; revisions/reconciliations are additional records.

### Typed trading payload

Required command fields: schema version, environment/bridge/instance/account tuple, execution mode, command/trace/signal/approval IDs, issue/expiry times, action enum, exact broker symbol, side, entry mode, decimal volume/entry/SL/TP, maximum spread/deviation, approved price band and maximum risk amount, configuration version, risk reservation ID, managed magic number, expected position/order identity/version where relevant, and bounded diagnostic metadata.

Transmit monetary/price/volume values and 64-bit broker tickets as strings; backend uses Decimal and integer types. The EA validates lexical form, range and instrument precision before conversion to the broker API's doubles/integers. Never silently round volume upward, widen a stop, map a symbol alias heuristically, omit required SL, or reinterpret absent data as zero. A broker-normalized volume/price that changes the approved economic effect must be rejected or rerisked.

V1 capability policy:

| Command | Initial behavior |
|---|---|
| OPEN_MARKET | Enabled only for a supported broker/symbol/execution profile, with approved attached SL/TP. If atomic protective stops cannot be supported, reject that profile until a separately designed/tested protection workflow exists. |
| MODIFY_SL_TP | Target a verified managed position. Tightening/other reductions still undergo deterministic validation. Widening or removing protective stops is exposure-increasing and requires a fresh risk approval; missing required SL is rejected. |
| CLOSE | Target a verified managed position by lifetime identifier and resolved current ticket. Record expected volume/state; stop if it changed. |
| PARTIAL_CLOSE | Disabled until demonstrated for the chosen account mode. Close volume and remainder must satisfy step/minimum rules, and must never create an opposite position accidentally. |
| CREATE/MODIFY/CANCEL_PENDING | Feature-gated and disabled by default. Future enablement reserves risk at placement, accounts for simultaneous fills, and distinguishes command expiry from broker-order expiry. |
| CANCEL_PENDING_MANAGED / CLOSE_MANAGED | Backend expands a confirmed administrative action into individually targeted idempotent commands. Never send an untargeted close-all against manual positions. |

The underlying request supports deal, pending, SL/TP, modify, remove and close-by actions, but broker availability is separate from platform capability. See [trade operation types](https://www.mql5.com/en/docs/constants/tradingconstants/enum_trade_request_actions) and [MqlTradeRequest](https://www.mql5.com/en/docs/constants/structures/mqltraderequest).

## Durable idempotency and uncertain outcomes

Use a PostgreSQL command table and transactional outbox. Risk evaluation, account lock, risk/position-slot reservation and creation of immutable command/approval records commit atomically. The bridge can deliver only committed approvals. An EA receipt acknowledgement is operational evidence, never a fill. One command cannot be reassigned to another EA merely because its delivery lease expired.

The EA journal is keyed by environment + broker server + account login + command ID. It stores payload hash, received/check results, a flushed `SEND_INTENT` record before the broker call, broker request/result identifiers, observed deals, and event upload acknowledgements. Duplicate commands with the same hash return recorded state; altered payloads with the same ID are rejected. Journal unavailable/corrupt means new submissions stop. Critical records persist beyond seven-day verbose-log retention; deletion of history needed for open or uncertain trades is prohibited. `FileFlush` is not a claim of transactional equivalence to broker execution or a formally verified power-loss guarantee.

The crash between flushed SEND_INTENT and broker result has no atomic cross-system transaction. The broker request structure exposes magic/comment identifiers, not an established project-controlled idempotency key. Accordingly this architecture offers durable duplicate suppression and conservative uncertain-outcome recovery, not an exactly-once broker guarantee.

On restart/reconnect:

1. Enter RECONCILING; disable new exposure and retain outstanding risk reservations.
2. Read local journal and replay event outbox; fetch backend command/reservation state.
3. Observe current account identity/permissions, all open positions/orders, and broker history since an overlapping checkpoint in broker time.
4. Correlate known order/deal tickets, position identifiers, magic, command-specific comment hints, symbol/side/volume/time and terminal request ID where available. Do not treat comment retention or uniqueness as a guarantee.
5. Apply confirmed fills/closures idempotently and rebuild account risk. If an outcome cannot be established reliably, remain OUTCOME_UNKNOWN and escalate to manual reconciliation; absence of an immediately visible deal is not proof of no execution.
6. Resume only when account snapshots, reservations and command outcomes reconcile. Never automatically resend a SEND_INTENT command with an uncertain outcome.

Keep transport command status separate from order state. Proposed order states extend the specification with PARTIALLY_FILLED, CANCELED and OUTCOME_UNKNOWN/RECONCILING. A cancellation can race a pending fill; the broker evidence wins. Reservations release only on confirmed terminal outcome, or expiration before any send intent—not from an acknowledgement timeout. [Broker return codes](https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes) distinguish placement, completion, partial completion, rejection, timeout and connection errors; map them conservatively and retain originals.

Only one active EA/terminal instance may execute for an account. Use a local exclusive ownership mechanism plus server-side registration/lease generation and an immediate expiry/ownership recheck before sending. These mechanisms cannot fence a trade already in flight at the broker. Therefore failover to a second instance is manual: stop the former process, reconcile outstanding activity, then issue a new generation. Test multiple-chart/terminal conflicts; do not advertise seamless active-active execution or automatic lease-based takeover.

## Independent EA checks and Python risk authority

Immediately before submission the EA rejects invalid authentication/schema, expired command, wrong account/mode, unowned target, unexpected state, stale quote, disconnected terminal, missing trading permission, unsupported symbol/filling/action, invalid volume/tick/stop/freeze constraints, spread outside approval, price outside approved band, excessive lot/risk ceiling, missing protective stops, a conflicting duplicate, or a journal/reconciliation fault. Emit machine-readable rejection codes. Recheck expiry after preflight. It may reject or submit precisely the approved request; it cannot enlarge, reinterpret, or create a fresh trade from AI metadata.

The Python risk engine remains mandatory for *every* exposure-increasing action, including pending placement and stop widening. Calculate potential loss in account currency, including conservative fees/slippage buffers; round the allowed volume down; reject if minimum volume exceeds budget. Unsupported contract calculation/currency conversion fails closed. [OrderCalcProfit](https://www.mql5.com/en/docs/trading/ordercalcprofit) provides a current account-currency estimate useful for cross-checking a supported profile. [OrderCalcMargin](https://www.mql5.com/en/docs/trading/ordercalcmargin) ignores existing orders/positions, so it does not replace portfolio-aware risk or OrderCheck. Broker estimates are observations, not permissions to exceed hard server bounds.

Reservations include outstanding, accepted-but-unfilled, pending and uncertain requests. Apply a transaction lock per account so simultaneous signals cannot both consume the same remaining risk/position allowance. Recheck config and account/market freshness at delivery; tighter risk changes invalidate unsent approvals and trigger reevaluation. The maximum equity/daily/open-risk rules observe the entire account, including manual/unmanaged trades. Unknown exposure, an unprotected unmanaged position or a discontinuity in history closes the new-trade gate. Any manual modification of a managed position triggers reconciliation and a new risk assessment.

Use a UTC policy day for daily-loss controls, with a persisted start-of-day baseline and explicit cash-flow adjustment; broker-time conversion and fees/swap/deposit treatment must be verified for the chosen account. A loss threshold latches pause until explicit administrative reset under policy. Stop-based risk is a pretrade estimate, not a promise that gaps, slippage or broker failure cannot exceed it.

Risk-reducing maintenance has its own policy: closing a verified managed position or canceling a verified pending order remains available when automation is paused if authentication, account/ownership/state checks and explicit administrative authorization are valid. Never silently turn a kill switch into permission to act on unmanaged trades. Loss-of-contact behavior pauses new orders and relies on already-established broker SL/TP; it does not automatically liquidate the account.

## Paper, demo and live isolation

| Mode | Executor | Required isolation |
|---|---|---|
| paper (default) | Python simulator only; no MT5 broker calls | Dedicated environment identity/key and data scope. Broker events are clearly simulated. |
| demo | Native EA; exact allowlisted DEMO login/server | Distinct bridge keys and environment identity. REAL and CONTEST modes rejected. Full Windows/broker tests required. |
| live | Future explicit deployment activation | Hard server live flag, real account allowlist, dedicated live keys/environment, EA explicit allow-live input, visible dashboard mode and completed demo acceptance. Dashboard toggles/AI cannot authorize live. |

For production use a dedicated automation account. On netting accounts, manual and automated deals on a symbol share a position, making magic-number-only ownership unsafe. V1 must reject mixed ownership on managed symbols and freeze automation upon manual/foreign modifications; dedicated account operation is the deployment default. On hedging accounts, target individual verified tickets and still count all account exposure in risk. A second terminal, mobile/Web/manual trader can change account state; local risk checks are a final revalidation, not a global broker lock.

## Phase 7/11 acceptance evidence required

- Python/MQL signature and UTF-8 binary fixtures; published HMAC vectors; malformed/duplicate JSON keys; headers/body tampering; nonce/counter rollback; stale/expired replies; account/mode mismatch; key rotation.
- HTTPS allowlist, certificate failures, redirects, timeout behavior, payload limits and actual polling/handler latency on the target terminal build.
- Compile EA in MetaEditor; inspect warnings; test initialization and journal fault cases. No compiled artifact is claimed in Phase 0.
- Demo broker profiles for order/SL/TP, modification, targeted close, capability-gated partial close/pending; metadata freshness, precision/step, freeze levels, filling policies, market closure and selected broker errors.
- Duplicate/lost receipt/lost fill acknowledgement; repeated/reordered events; partial fills; journal crash before/after send; terminal restart; backend restart; corrupt/truncated journal; lost broker history; multiple EA instance conflict.
- Pause/daily loss/stale heartbeat behavior; all-account risk including manual changes; mode isolation and server/EA live guards.
- Windows reboot, terminal session/startup/reconnect behavior, event backlogs, disk-space failure and managed-position recovery. Simulator success does not satisfy demo or reboot acceptance.

## Remaining assumptions and blockers

There is no MT5-specific blocker to Phase 1 repository/infrastructure work. Broker credentials, Windows VPS, account model, certificate path and executable validation can be supplied before Phase 7/10/11. Treat them as later acceptance prerequisites, not requests to expose secrets in chat. Live remains disabled.

Before real EA execution, choose and record the demo broker/server/account, allowed symbols and supported contract profiles, terminal build, hedging/netting/FIFO mode, stop/fill behavior, available history, one-EA ownership mechanism, and tested local journal behavior. WebRequest TLS/redirect/runtime performance and MQL HMAC/JSON compilation remain unverified here. Do not claim production readiness until those checks and recovery tests pass.
