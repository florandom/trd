# Local paper bridge and simulator

Implemented on 12 October 2026, Europe/Rome. Scope is a disposable local paper
laboratory. Its Python simulator makes no external API requests. The separate
[MQL5 request adapter](MT5_BROKER_LOCAL.md) uses a synthetic terminal port only.
Real Telegram, paid AI, remote deployment credentials and broker acceptance are
deferred to the operator's final tests. A separate [local MQL5 bridge](MT5_LOCAL.md)
now provides a simulation-only EA source; MetaEditor/terminal acceptance remains required.

## Running the laboratory

Run `pnpm paper:accept` with the pinned Python/Node dependencies and Docker available.
The command does not read operator `.env`. It starts a uniquely named PostgreSQL 17
container, publishes a random loopback port, uses tmpfs storage and creates random
independent database-role passwords. It migrates to `0008_paper_positions`, enrolls a
synthetic account/source and uses a test-only mock that explicitly returns PROPOSE.
The ordinary mock remains WAIT. No account is enrolled through a runtime route.

An ephemeral risk HTTP process binds `127.0.0.1` on a random port. A separate executor
uses random 256-bit request/response keys and a private journal directory. The run
checks two simulated openings, a stop update, full closes, net realized results,
controlled resume, duplicate suppression and restart recovery. It prints a redacted
result and removes its container, keys and files
on normal/error exit. No primary database, operator credentials or volume is used.
An uncatchable host termination may require removing that run's temporary container.

`PAPER_BRIDGE_ENABLED` defaults false and is accepted only in development/test with
`PAPER_PROFILE_PATH`, `PAPER_REQUEST_KEY` and independent `PAPER_RESPONSE_KEY`.
Only the risk process receives these fields. Both global automation/live flags stay
false; demo/live modes and staging/production paper activation are rejected.
The immutable profile binds environment/account tuple, synthetic server
`TRD-PAPER-SIMULATOR`, bridge/instance/key identity, ownership generation, source IDs,
exact mappings, reviewed metadata, calendar and policy. Database enrollment binds
its digest and key digests; first authentication binds one durable executor journal.
Replacement is never an automatic ownership takeover.

## Authority and transactions

`PaperGateway` requires the `trd_risk` session user. It takes the environment evidence
advisory fence before account/enrollment row locks, matching source/message changes.
It derives safety epoch, consumed identities, remaining exposure and daily-loss latch
from persisted evidence. Input telemetry cannot supply these authoritative fields.
Current source, latest initial non-reply message, immutable signal version, completed
analyst/decision/required-critic results and all required agent versions gate admission.
Confidence is zero with a zero threshold in this synthetic route; there is no claim
of measured model confidence or real decision calibration.

Admission atomically writes risk evaluation, approval, exposure hold, immutable command
bytes/hash, order, legal lifecycle, audit and outbox. Message/signal uniqueness prevents
a second opening even after invalidation. Delivery reruns the same risk engine with
fixed approved volume and a verified own HELD reservation counted exactly once.
Risk cannot exceed the admitted hold; risk/notional/margin remain conservative.
Expired requests, changed policy/source/message/agent/epoch and failed financial or
freshness gates revoke unsent commands. Delivered/uncertain exposure is retained.

UTC opening equity is immutable for the day. Reaching the inclusive loss threshold
latches PAUSED persistently; equity recovery cannot clear it. The laboratory has no
deposit/withdrawal ledger and rejects nonzero cash-flow telemetry. A future real
adapter must authenticate and uniquely reconcile each cash flow rather than trust
a caller's adjustment. Contradictory authenticated evidence latches an account fault,
invalidates unsent commands and preserves uncertain exposure. Clearing the fault
requires explicit operator confirmation and fresh flat-account reconciliation.
Unauthenticated requests never change account state.

Dashboard ADMIN can tighten limits with the existing session/version/confirmation
contract. Enrolled synthetic accounts are fenced and paused; delivered exposure
survives. Active exposure outside the enrolled paper gateway still rejects that
change. Runtime credentials cannot enroll/replace accounts or rewrite financial
history. The migrator/operator remains trusted. The six new tables have append-only
or narrowly mutable guards; downgrade refuses any existing paper evidence.

## Exact-byte local protocol

Only POST `/bridge/v1/snapshot`, `/bridge/v1/poll` and `/bridge/v1/events` are accepted,
on numeric loopback transport with exact raw path and no query. JSON content type
is exact. Duplicate authentication/content-type headers, compression, alternate
paths and redirects are rejected. Body limit is 64 KiB; event batches contain at most
100 events. JSON rejects duplicate keys, floats/nonfinite numbers, BOM, NUL, invalid
UTF-8/surrogates and excessive depth/size. Financial values and broker tickets are text.

HMAC-SHA256 authenticates this ASCII LF-separated frame, including a trailing LF:

```text
TRD-BRIDGE-V1
REQUEST or RESPONSE
environment_id
bridge_id
instance_id
key_id
journal_id
POST
exact_path
http_status (0 for request)
request_sequence
issued_at_epoch_seconds
expires_at_epoch_seconds
lowercase_sha256_of_exact_body_bytes
```

`journal_id` is an explicit local extension of the research proposal, shared by both
implemented peers. The local EA source also uses this frame, verified against Python
in its portable harness; native runtime interoperability still requires terminal tests. Separate purpose keys
authenticate direction/status/path and the outstanding request's identity/sequence.
Validity is at most ten seconds, checked again on response. Sequences are positive
signed 64-bit integers and durably increment before transport. The database persists
high-water claims and exact signed response bytes. Same sequence/context/body reuses
the response; altered signed bytes fault the account. Expired retries authenticate
unsuccessfully. Old sequence values never authorize a new command. HMAC primitives
are checked against [RFC 4231](https://www.rfc-editor.org/info/rfc4231/).

The transport is plain HTTP only on loopback for the synthetic lab; it is not a
production HTTPS protocol implementation. Public API/OpenAPI expose none of these
private routes or keys. The simulator ignores proxy environment settings and follows
no redirect. [PostgreSQL lock semantics](https://www.postgresql.org/docs/17/explicit-locking.html).

## Durable execution and reconciliation

The executor owns an exclusive OS lock and SQLite WAL/FULL journal, separate from
its deliberately non-idempotent synthetic broker ledger. Receipt and SEND_INTENT
flush before broker submission. An already claimed intent cannot submit again.
Restart after intent without proven outcome becomes UNKNOWN; no absence of a deal,
expiry or acknowledgement releases its risk. Restart after a fill reconciles that
deal from the separate ledger without submitting a second order. Journal identity
and sequence fences prevent a new/rolled-back owner from silently taking over.

RECEIVED/SEND_INTENT/ACCEPTED are transport/preflight evidence, never EXECUTED. Unique
signed broker deals confirm fills. Event UUID deduplication and independent deal
deduplication handle retries/reordering. Partial fills retain proportional remaining
risk/notional/margin and share exactly one managed slot with the filled position.
Full fill consumes the hold and completes order/command/signal. A current complete
portfolio/history snapshot is required before recovering readiness from uncertainty.
Conflicting fills roll back the batch and quarantine the account; risk is retained.

## Scope and remaining gates

The repeatable end-to-end lab supports synthetic EURUSD market openings with USD
account currency and attached stops. The pure engine's seven Forex valuation
profiles remain separately tested. The [position extension](PAPER_POSITIONS.md) adds confirmed full closes,
risk-reducing stop changes, closed-position history and controlled resume. Other
executor conversions, pending orders, partial closes and real broker recovery still
require implementation and acceptance. Snapshots come from the trusted
synthetic executor, not authenticated real broker history. No exactly-once broker,
profitability, native Windows/MT5, demo or live guarantee follows from these tests.

Keep real trading off. The next native integration must preserve these authority,
identity, freshness, replay, journal and uncertain-outcome rules, add broker-history
and cash-flow reconciliation, then pass Windows/EA/demo tests before any live gate.
See [validation](PHASE_7_VALIDATION.md), [architecture](ARCHITECTURE.md),
[risk engine](RISK.md) and [team guide](team/GUIDA_PREPARAZIONE.md).
