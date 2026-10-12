# Confirmed local paper position management

Implemented on 12 October 2026, Europe/Rome, extending the local paper bridge.
Only the enrolled synthetic EURUSD/USD laboratory is accepted end to end. External
API credentials, real Telegram/AI, MT5 and demo/live acceptance remain deferred.

## Operator request and authority

Authenticated ADMIN uses Posizioni → Gestisci simulazione, reviews one exact target
and confirms full close or protective SL/TP update. VIEWER remains read-only. The
existing CSRF/Origin/session-bound confirmation expires after two minutes and binds
target, expected position revision and normalized decimal levels. Only development/
test API accepts `paper_position` and `paper_resume`; no dashboard action enables
normal automation or live trading. API cannot sign commands or fabricate equity.

The role-authenticated database function rechecks the ADMIN session, confirmation,
environment, enrolled synthetic account, complete filled opening, OPEN position,
revision and absence of an active conflicting request. It queues an immutable
operator request, audit and outbox; confirmation reuse or a concurrent change fails.
No runtime role, including risk, can directly INSERT an operator request.

Under the existing evidence fence and account lock, risk rechecks current ownership,
full volume, entry-fill evidence, protections, epoch, profile and fresh complete
snapshot/quote/metadata. The stop may only move toward lower risk: up for BUY, down
for SELL. Tick precision, mandatory SL/TP, stops/freeze distances, market-open,
spread, deviation and expiry still apply. Partial close and removal of protection
are unavailable. A verified full close may proceed from PAUSED; a contradictory
account fault must first be reconciled. A stale or risk-increasing request is rejected
without sending a broker operation or inventing an execution result.

Maintenance shares the signed command transport, replay claims, immutable command
store, lifecycle, executor lock/journal, SEND_INTENT and separate broker ledger.
It adds no position slot or financial exposure. Its reservation ID is null only
because a database trigger requires the exact pending confirmed position request;
an unreserved opening cannot exploit this path. Creation/delivery/outbox are atomic.
The original opening approval, command, signal and deal history are preserved.

## Outcomes and uncertainty

Only signed POSITION_CLOSED/RECONCILED_CLOSE or STOPS_CHANGED/RECONCILED_STOPS evidence
can apply the position change. RECEIVED, SEND_INTENT and ACCEPTED never complete it.
Maintenance commands complete with BROKER_POSITION_UPDATE, permitted only for a
persisted maintenance request; it cannot mark an opening signal or order filled.

Transport UUID and independent synthetic operation identity deduplicate outcomes.
Full close binds target, entire current volume, allowed price and unique deal.
SL/TP confirmation must exactly match the signed levels. Contradictory batches roll
back projections/economics, mark uncertainty and latch the account fault. Positions
retain full volume/exposure until proven closure. Late/replayed transport observations
do not rewind a completed operation or apply a second close/result.

Restart before a proven outcome never repeats an uncertain SEND_INTENT. Restart
after a broker operation reconciles its independent durable ledger. A close removes
the position from later snapshots; a stop update projects the latest confirmed
protection. Old journal databases gain the new broker operation table without
replacing their sequence, identity, command or event records.

## Result history

The dashboard retains closed positions, closing time, confirmed current protections,
revision and net realized result. USD Forex P&L uses exact immutable opening fills:
`(exit_price × full_volume − sum(entry_price × fill_volume)) × side × contract_size`,
then subtracts the reviewed round-trip commission. Signed results round downward
to ten decimals so rounding cannot credit extra profit or hide loss. Rounded display
entry averages do not replace economic fill evidence.

The separate synthetic broker ledger and server compute the same result. Subsequent
lab snapshots include the accumulated realized change in equity/free margin while
preserving the original UTC opening baseline. Commission is a reviewed synthetic
assumption; no real broker valuation or billing is certified.
[Official Forex contract properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants)
and future [broker profit validation](https://www.mql5.com/en/docs/trading/ordercalcprofit).

## Controlled resume

Verifica ripresa queues another explicitly confirmed ADMIN request bound to account
safety epoch. Risk requires fresh complete portfolio/history and market observations,
no unresolved commands/operations/held risk, and compliant current portfolio limits.
It preserves the day baseline and never clears a daily-loss latch. Equity recovery
alone cannot resume that day; a new UTC day requires its own fresh baseline and a
new operator confirmation. No request force-enables a failed gate.

Clearing a contradictory-evidence fault additionally requires a verified flat
account, no outstanding/unknown exposure and the exact unexpired operator request.
The database enforces these constraints before clearing the fault. Reconciled
outcomes must resolve uncertain positions first; an absence of a deal or a click
cannot discard them. Successful resume increments the epoch and records audit/outbox;
journal binding and replay high-water never decrease. Ordinary successful unknown
outcome reconciliation still requires its complete snapshot before readiness.

## Schema and repeatable acceptance

`0008_paper_positions` adds current paper protection/revision, confirmed operator
requests and append-only operation outcomes, giving 50-table ORM/schema parity.
Runtime permissions remain separated. Upgrade seeds existing enrolled paper
protections from original commands; downgrade refuses operation evidence loss.

`pnpm paper:accept` remains isolated and requires no external credentials. It now
checks two openings, restart recovery, a stop update, two full closes, close while
paused, net realized results and controlled resume through real authenticated
dashboard routes plus signed loopback bridge HTTP. Resources are temporary and
removed. [Verification evidence](POSITION_MANAGEMENT_VALIDATION.md).

The [local MQL5 source](MT5_LOCAL.md) is now available for simulation; native
MetaEditor/terminal acceptance and the broker adapter, broker-history/cash-flow reconciliation, automatic broker-held
stop execution, partial closes/pending orders, other executor conversions, position
review agents, memory, notifications and Windows/server acceptance remain future
work. Synthetic results do not certify a trading strategy or production execution.
