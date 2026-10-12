# Phase 6 paper risk engine

Implemented and verified on 12 October 2026, Europe/Rome. This is the pure domain
calculation gate, with synthetic paper observations. It has no database, HTTP, clock,
AI or broker side effects. Phase 7 connects it to an isolated local paper gateway, authenticated synthetic
observations, atomic reservations, signing and reconciliation. See [paper bridge](PAPER_BRIDGE.md).
Native MT5 and real broker acceptance remain future work.

## Contract and authority

`RiskEngine.evaluate(proposal, account_state, market_state, effective_config)` returns
an immutable `RiskResult`: PASS, REJECT or ERROR, all observed reason codes, exact
calculations, rules/policy/source versions, safety epoch, proposal/config hashes and
account, baseline, instrument and quote snapshot identifiers actually used.
Only PASS exposes a volume. It is a calculation result, never an executable approval.

Inputs are frozen Pydantic contracts, revalidated even when supplied as constructed
or copied models. Financial values require finite decimal strings or Decimal;
floats, booleans, unknown fields, naive timestamps, conflicting observations and
malformed dimensions fail closed. UTC time is supplied explicitly. Decimal arithmetic
uses a private precision-80 context, independent of the caller's precision/rounding.
Unexpected calculation exceptions return a safe ERROR without supplied input text.

Reviewed configuration carries the hard envelope, bounded dashboard policy,
source limits, exact symbol mapping, account allowlist, freshness/spread/price-band
limits, session calendar and advisory evidence. Source and policy limits cannot
expand earlier layers. Required classifier/parser/analyst/decision stages and an
explicitly required critic must be complete and current. Confidence cannot weaken
the route. Default authority is disabled; only synthetic fixtures opt in. Demo and
live accounts, pending orders, stop changes and partial close are rejected here.

## Supported valuation

V1 accepts the seven tested spot-Forex pairs EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD,
USDCAD and NZDUSD. Each maps to one exact configured broker symbol; no suffix
inference. Metadata must describe matching base/profit currencies, a Forex
profile and base-currency margin. Missing, stale or unsupported profiles
and unavailable attached stops stop evaluation. Metals, CFDs, futures, crypto,
other Forex crosses and conversion chains remain unsupported.

The approved entry band is centered on the proposal and bounded in broker points.
Executable ask for BUY or bid for SELL must lie within it. Tick precision and
protective stop/freeze distances apply across the whole band. Adverse entry,
configured exit slippage and round-trip commission determine loss per lot.
Volume is the smaller of risk-budget sizing, policy lot cap and broker maximum,
floored to the broker step. A requested fixed volume is never resized.
If the minimum lot exceeds budget, reject.

Loss in profit currency is contract size × adverse price distance × lots, plus
declared buffers. Account-currency conversion requires an explicit approved fresh
direct ask or inverse bid and a positive reviewed conversion buffer. If account
currency is the instrument's base, the inverse buffered stop rate also bounds
conversion: current price alone would understate BUY risk. Same currency uses one.
Estimates round up to ten decimal places; monetary caps round down. Margin uses
broker leverage, margin rate and base-currency conversion. All-account gross
notional/equity is independently bounded.

These implement the supported project profile, based on official
[Forex profit and margin properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants).
Future broker acceptance must compare with
[OrderCalcProfit](https://www.mql5.com/en/docs/trading/ordercalcprofit) and
[OrderCalcMargin](https://www.mql5.com/en/docs/trading/ordercalcmargin), followed by
portfolio-aware OrderCheck. Estimates cannot authorize a trade or guarantee
realized loss during gaps, slippage or broker failure.

## Portfolio and daily loss

Every position contributes current-equity-to-stop loss, buffers and gross notional,
including manual/foreign-source positions. Missing protection, valuation or managed
ownership closes the gate. Unmanaged netting exposure closes it because managed
ownership cannot be inferred. All remaining HELD/SUBMITTED/UNKNOWN reservations
contribute risk, notional and margin; UNKNOWN also prevents PASS. No expiry or
acknowledgement releases exposure. A partial fill shares one slot only when its
position and remaining reservation bind the same managed signal, source and broker
symbol; arbitrary shared/duplicate slots are rejected.

Per-trade/total risk, global/source position counts, source risk, symbol exposure,
effective leverage and free margin have independent bounds. Enabled consecutive
loss/failure limits require fresh source/version-bound counters. Consumed signal/
message IDs and a reservation for the same signal prevent another opening.
Review-only inputs and changed advisory/source/message/safety versions stop evaluation.

Daily loss is `max(0, opening_equity + net_cash_flow - current_equity)`, including
unrealized changes and costs reflected in equity. Persisted opening equity sets
the original day's budget; deposits/withdrawals never reset it. Baseline account,
currency, UTC day and cash-flow history must match. Loss at or above the threshold
returns REJECT with `latch_daily_loss=true`; an existing latch survives recovery.
Reset never replaces the baseline or bypasses reevaluation. The phase 7 paper gateway persists this latch; its lab rejects unsupported cash flows.
Real deposits/withdrawals require uniquely evidenced broker reconciliation.

## Sessions and future wiring

Calendars use explicit IANA timezone, disjoint weekly windows and local holidays.
Windows are start-inclusive/end-exclusive; overnight sessions split at midnight.
Converting supplied UTC time handles both repeated autumn hours and spring gaps.
Broker market-open evidence remains independent. Windows timezone data is already
supplied by the locked psycopg dependency.
[Python zoneinfo behavior](https://docs.python.org/3.13/library/zoneinfo.html)

The ordinary mock still waits with `RISK_GATEWAY_UNAVAILABLE`; historical receipts
are preserved. The isolated paper gateway assembles current evidence and authenticates
synthetic observations, under the evidence fence and account lock. Its `revalidate`
call requires the exact HELD reservation, signal/source/symbol and fixed volume.
It counts that hold once, conservatively preserving admitted risk/notional/margin;
any increased risk or failed current gate revokes an unsent command. This adds no
broker side effect to the pure engine. [Phase 7 contract](PAPER_BRIDGE.md) and
[acceptance](PHASE_7_VALIDATION.md); original [phase 6 evidence](PHASE_6_VALIDATION.md).
