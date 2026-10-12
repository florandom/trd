# Phase 6 validation — pure paper risk

Date: 2026-10-12, Europe/Rome. Acceptance scope: deterministic domain evaluation
using synthetic paper account, portfolio and market observations. No broker account,
financial order, paid AI request or external deployment was activated.

## Delivered

- `RiskEngine.evaluate` with strict immutable inputs and typed PASS/REJECT/ERROR,
  complete observed reasons, calculation evidence, rule/configuration versions,
  hashes and snapshot references. PASS is a calculation, never an execution approval.
- Exact Decimal arithmetic independent of ambient precision/rounding; conservative
  loss/fees/slippage/conversion, price-band valuation, broker-step volume flooring
  and fixed-volume rejection without silently changing approved economics.
- Seven explicit spot-Forex profiles, exact broker mapping, fresh direct/inverse
  currency conversion and buffered stop conversion for base-currency accounts.
  Unsupported/missing/stale profiles or conversions fail closed.
- Hard/soft/source bounds; source/account/mode/version/duplicate/advisory/health gates;
  protective stops, tick/lot precision, spread, market/session and stop/freeze controls.
- All-account exposure, including manual/foreign positions and outstanding/uncertain
  reservations; independent open-risk, slot, symbol, leverage, margin and source limits.
  Partial-fill slots require matching managed identity; unowned netting exposure stops.
- UTC daily baseline and explicit cash-flow adjustment, inclusive drawdown stop and
  a latch requirement retained after recovery. Persistence/reset belongs to the gateway.
- Explicit local session calendars with holidays, split overnight windows, DST gaps
  and both repeated autumn hours; enabled failure/loss counters require fresh evidence.
- Italian risk-page explanation and current `RISK_GATEWAY_UNAVAILABLE` analysis reason.
  Historical receipts retain their old reason; no database or public contract migration.

## Automatic evidence

| Check | Result |
| --- | --- |
| New risk/calendar tests | **249 passed** |
| Complete Python unit suite | **501 passed** |
| Complete PostgreSQL 17 integration suite | **101 passed** |
| Dashboard tests | **16 passed** |
| Distinct passing test cases | **618** |
| New domain statement/branch coverage | 99.6% / 97.6% |
| Ruff, strict TypeScript and ESLint | Passed |
| Dashboard production Webpack build | Passed |
| Backend container build | Passed |
| Linux container risk/timezone smoke with networking disabled | Passed |
| Regenerated OpenAPI/shared types | Byte-identical; no public contract drift |

Tests include below/at/above financial, freshness, spread, stop/freeze, price-band,
volume, slot and drawdown bounds; absent/negative/nonfinite/float/bool/naive/conflicting
inputs; revalidation of bypassed model validation; BUY/SELL on all seven profiles;
direct/inverse/at-stop conversion; fees/slippage; current-equity exposure; netting
ownership; held margin and unknown outcomes; partial-fill and duplicate projection;
cash-flow/UTC day/reset behavior; policy/source authority and required critic;
calendar gaps/folds and private exception redaction. Inputs remain unchanged and
repeated evaluation is deterministic even with low caller Decimal precision.

PostgreSQL validation used an independent disposable PostgreSQL 17 container with
random runtime-role credentials and random `trd_test_*` databases. The container and
test databases were removed. Primary database, volumes, private environment and
credentials were not accessed or changed by this validation. Existing migrations,
41-table metadata parity and runtime permissions retain their passing checks.

Windows CI now explicitly includes the 249 risk/calendar tests. Its execution on
an actual Windows runner is not claimed here; Linux container success does not
certify native Windows services, MT5, demo broker or recovery.

## Documentation and visual evidence

Both maintained Italian guides identify phase 6 and the 12 October revision,
with concise history entries. They distinguish the verified local calculation engine
from absent authenticated account/market wiring, atomic reservations and execution.
Shared SVG/PNG diagrams and the standalone offline HTML flow reflect the same boundary.

The existing guide builders preserve the concise Italian guides and illustrations.
Both Word files were regenerated with the Documents skill's bundled dependencies,
rendered through its LibreOffice/Poppler helper, and every final PNG page inspected:
**three customer pages and six team pages**. Tables, repeated headers, variable names,
commands, figures, margins and footer pagination are readable; no orphan final page
remains. Intermediate PDFs/PNGs are private QA files outside the delivered documents.
The HTML flow was checked in the in-app browser at its default 1280×720 viewport;
the rendered diagram distinguishes local verification from future execution.

## Remaining execution gates

Phase 6 writes no latch, risk event, reservation, approval, outbox or command. It
offers no HTTP route for supplied account/market observations. Runtime paper,
automation-disabled and live-disabled guards remain in force. Existing sources,
agents and external AI activation gates are unchanged.

The next gateway/bridge work must authenticate and reconcile account/market/portfolio
observations, bind current advisory/configuration evidence, serialize account access,
persist daily-loss latches and exposure reservations atomically with immutable
approval/command/outbox, and rerun all financial gates before delivery while counting
its own reservation once. Durable duplicate suppression, HMAC/replay, uncertain
outcome recovery, simulator protocol, native MT5 and demo/live acceptance remain
separate required work. Pure PASS must never be reused as a broker authorization.

See [risk contract](RISK.md), [approved architecture](ARCHITECTURE.md),
[MT5 acceptance](research/MT5.md), [customer guide](cliente/GUIDA_CLIENTE.md)
and [team preparation](team/GUIDA_PREPARAZIONE.md).
