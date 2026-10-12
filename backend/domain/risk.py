"""Pure, fail-closed paper Forex evaluation. PASS never creates an approval/order.

All time and observations are explicit inputs. The execution gateway must later
authenticate them, lock the account, persist reservations and rerun the same gates.
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext

from backend.domain.contracts import fingerprint
from backend.domain.risk_contracts import (
    AccountState,
    EffectiveRiskConfig,
    FxInstrument,
    MarketState,
    Quote,
    RiskCalculations,
    RiskProposal,
    RiskReason,
    RiskResult,
)

SUPPORTED_PAIRS = frozenset({"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"})
ZERO = Decimal("0")
ONE = Decimal("1")
UNIT = Decimal("0.0000000001")


def ceil(value: Decimal) -> Decimal:
    return value.quantize(UNIT, rounding=ROUND_CEILING)


def floor(value: Decimal) -> Decimal:
    return value.quantize(UNIT, rounding=ROUND_FLOOR)


def validate_input(kind, value):
    # Revalidate even frozen models: model_copy/update and model_construct bypass validators.
    return kind.model_validate(
        value.model_dump(mode="python") if isinstance(value, kind) else value
    )


class RiskEngine:
    def evaluate(
        self,
        proposal: object,
        account_state: object,
        market_state: object,
        effective_config: object,
    ) -> RiskResult:
        try:
            with localcontext() as context:
                context.prec = 80
                request = validate_input(RiskProposal, proposal)
                account = validate_input(AccountState, account_state)
                market = validate_input(MarketState, market_state)
        except Exception:
            return RiskResult(status="ERROR", reason_codes=(RiskReason.INVALID_INPUT,))
        try:
            with localcontext() as context:
                context.prec = 80
                config = validate_input(EffectiveRiskConfig, effective_config)
        except Exception:
            return RiskResult(status="ERROR", reason_codes=(RiskReason.INVALID_CONFIGURATION,))
        evidence = dict(
            policy_version=config.policy_version,
            source_version=config.source.version,
            safety_epoch=account.safety_epoch,
            proposal_hash=fingerprint(request),
            config_hash=fingerprint(config),
            account_snapshot_id=account.snapshot_id,
            market_snapshot_id=market.snapshot_id,
            baseline_snapshot_id=(
                account.daily_baseline.snapshot_id if account.daily_baseline else None
            ),
        )
        try:
            with localcontext() as context:
                context.prec = 80
                return _Evaluation(request, account, market, config, evidence).run()
        except Exception:
            # Exception details may contain caller data. Return only a stable safe code.
            return RiskResult(
                status="ERROR", reason_codes=(RiskReason.CALCULATION_ERROR,), **evidence
            )


class _Evaluation:
    def __init__(self, request, account, market, config, evidence):
        self.request: RiskProposal = request
        self.account: AccountState = account
        self.market: MarketState = market
        self.config: EffectiveRiskConfig = config
        self.evidence = evidence
        self.reasons: list[RiskReason] = []
        self.error = False
        self.latch = False
        self.values = {"equity": account.equity}
        self.instruments = {i.symbol: i for i in market.instruments}
        self.quotes = {q.symbol: q for q in market.quotes}
        self.mappings = {m.broker_symbol: m for m in config.allowed_instruments}
        self.used_metadata = set()
        self.used_quotes = set()

    def add(self, reason, *, error=False):
        if reason not in self.reasons:
            self.reasons.append(reason)
        self.error = self.error or error

    def fresh(self, observed_at, maximum, reason):
        age = (self.config.now - observed_at).total_seconds()
        if age < 0:
            self.add(RiskReason.FUTURE_OBSERVATION, error=True)
            return False
        if age >= maximum:
            self.add(reason, error=True)
            return False
        return True

    def result(self, volume=None):
        return RiskResult(
            status="ERROR" if self.error else "REJECT" if self.reasons else "PASS",
            reason_codes=tuple(self.reasons) or (RiskReason.PASS,),
            calculations=RiskCalculations(**self.values),
            volume=volume if not self.reasons else None,
            latch_daily_loss=self.latch,
            metadata_snapshot_ids=tuple(sorted(self.used_metadata, key=str)),
            quote_snapshot_ids=tuple(sorted(self.used_quotes, key=str)),
            **self.evidence,
        )

    def gates(self):
        p, a, c = self.request, self.account, self.config
        if not c.automation_enabled:
            self.add(RiskReason.AUTOMATION_DISABLED)
        if not c.source.enabled:
            self.add(RiskReason.SOURCE_DISABLED)
        if a.account not in c.account_allowlist:
            self.add(RiskReason.ACCOUNT_NOT_ALLOWED)
        if a.account.mode != "paper":
            self.add(RiskReason.MODE_NOT_ALLOWED)
        if p.account != a.account or self.market.account != a.account:
            self.add(RiskReason.ACCOUNT_MISMATCH, error=True)
        if a.status != "READY" or not a.reconciliation_complete or not a.trading_permitted:
            self.add(RiskReason.ACCOUNT_NOT_READY)
        if not a.portfolio_complete:
            self.add(RiskReason.PORTFOLIO_INCOMPLETE, error=True)
        if a.equity <= ZERO:
            self.add(RiskReason.INVALID_EQUITY, error=True)
        self.fresh(a.observed_at, c.account_max_age_seconds, RiskReason.STALE_ACCOUNT)
        if {h.service for h in a.health} != {"database", "risk", "executor"}:
            self.add(RiskReason.HEALTH_UNAVAILABLE, error=True)
        for health in a.health:
            if not health.healthy:
                self.add(RiskReason.HEALTH_UNAVAILABLE, error=True)
            self.fresh(health.observed_at, c.health_max_age_seconds, RiskReason.HEALTH_UNAVAILABLE)
        if p.action != "OPEN_MARKET":
            self.add(RiskReason.UNSUPPORTED_ACTION)
        if p.review_only:
            self.add(RiskReason.REVIEW_REQUIRED)
        if p.expires_at <= c.now:
            self.add(RiskReason.SIGNAL_EXPIRED)
        self.fresh(p.published_at, c.signal_max_age_seconds, RiskReason.STALE_SIGNAL)
        if (
            p.source_id != c.source.source_id
            or p.source_version != c.source.version
            or a.safety_epoch != c.expected_safety_epoch
            or c.advisory.signal_id != p.signal_id
            or c.advisory.signal_version != p.signal_version
            or c.advisory.message_version != p.message_version
            or c.advisory.source_version != p.source_version
        ):
            self.add(RiskReason.VERSION_MISMATCH)
        if (
            p.signal_id in a.consumed_signal_ids
            or p.message_id in a.consumed_message_ids
            or any(r.signal_id == p.signal_id for r in a.reservations)
        ):
            self.add(RiskReason.DUPLICATE_SIGNAL)
        required = {"SIGNAL_CLASSIFIER", "SIGNAL_PARSER", "MARKET_ANALYST", "DECISION_AGENT"}
        if c.critic_required:
            required.add("CRITIC")
        if (
            c.advisory.outcome != "PROPOSE"
            or not c.advisory.config_current
            or not required.issubset(c.advisory.completed_stages)
        ):
            self.add(RiskReason.ADVISORY_INCOMPLETE)
        if c.advisory.confidence < c.minimum_confidence:
            self.add(RiskReason.CONFIDENCE_TOO_LOW)
        if not c.calendar.is_open(c.now):
            self.add(RiskReason.OUTSIDE_SESSION)
        self.daily_loss()
        self.source_counters()

    def daily_loss(self):
        a, c, b = self.account, self.config, self.account.daily_baseline
        if (
            b is None
            or b.account != a.account
            or b.currency != a.currency
            or b.day != c.now.date()
            or not b.history_complete
            or b.opening_equity + b.net_cash_flow <= ZERO
        ):
            self.add(RiskReason.DAILY_BASELINE_UNAVAILABLE, error=True)
            return
        loss = ceil(max(ZERO, b.opening_equity + b.net_cash_flow - a.equity))
        # Deposits/withdrawals adjust loss, never rewrite the persisted daily risk budget.
        limit = floor(b.opening_equity * c.policy.max_daily_loss)
        self.values.update(
            daily_opening_equity=b.opening_equity,
            daily_cash_flow=b.net_cash_flow,
            daily_loss=loss,
            daily_loss_limit=limit,
        )
        if b.loss_latched:
            self.latch = True
            self.add(RiskReason.DAILY_LOSS_LATCHED)
        if loss >= limit:
            self.latch = True
            self.add(RiskReason.DAILY_LOSS_LIMIT)

    def source_counters(self):
        source = self.config.source
        if source.max_consecutive_losses is None and source.max_consecutive_failures is None:
            return
        counter = next(
            (s for s in self.account.source_counters if s.source_id == source.source_id), None
        )
        if counter is None:
            self.add(RiskReason.SOURCE_COUNTERS_UNAVAILABLE, error=True)
            return
        if counter.version != source.version:
            self.add(RiskReason.SOURCE_COUNTERS_UNAVAILABLE, error=True)
        self.fresh(
            counter.observed_at,
            self.config.account_max_age_seconds,
            RiskReason.SOURCE_COUNTERS_UNAVAILABLE,
        )
        if (
            source.max_consecutive_losses is not None
            and counter.consecutive_losses >= source.max_consecutive_losses
        ):
            self.add(RiskReason.CONSECUTIVE_LOSS_LIMIT)
        if (
            source.max_consecutive_failures is not None
            and counter.consecutive_failures >= source.max_consecutive_failures
        ):
            self.add(RiskReason.CONSECUTIVE_FAILURE_LIMIT)

    def observations(self, symbol):
        i: FxInstrument | None = self.instruments.get(symbol)
        q: Quote | None = self.quotes.get(symbol)
        mapping = self.mappings.get(symbol)
        if i is None:
            self.add(RiskReason.METADATA_UNAVAILABLE, error=True)
        if q is None:
            self.add(RiskReason.QUOTE_UNAVAILABLE, error=True)
        if i is None or q is None:
            return None
        self.used_metadata.add(i.snapshot_id)
        self.used_quotes.add(q.snapshot_id)
        valid = self.fresh(
            i.observed_at, self.config.metadata_max_age_seconds, RiskReason.STALE_METADATA
        )
        valid = (
            self.fresh(q.observed_at, self.config.quote_max_age_seconds, RiskReason.STALE_MARKET)
            and valid
        )
        if (
            mapping is None
            or mapping.symbol not in SUPPORTED_PAIRS
            or i.profile != mapping.profile
            or i.base_currency + i.quote_currency != mapping.symbol
            or i.margin_currency != i.base_currency
        ):
            self.add(RiskReason.UNSUPPORTED_PROFILE, error=True)
            valid = False
        if not i.attached_stops_supported:
            self.add(RiskReason.UNSUPPORTED_PROTECTION, error=True)
            valid = False
        if not q.market_open:
            self.add(RiskReason.MARKET_CLOSED)
            valid = False
        return (i, q) if valid else None

    def conversion(self, currency, *, instrument=None, stop=None):
        if currency == self.account.currency:
            return ONE
        candidates = []
        # Both direct and inverse observations must have an explicit approved mapping.
        for mapping in self.config.allowed_instruments:
            if mapping.symbol not in {
                currency + self.account.currency,
                self.account.currency + currency,
            }:
                continue
            observation = self.observations(mapping.broker_symbol)
            if observation is None:
                continue
            i, q = observation
            rate = q.ask if i.base_currency == currency else ONE / q.bid
            if instrument is not None and instrument.base_currency == self.account.currency:
                # Converting Forex loss back into its base currency at current price alone
                # underestimates BUY losses: also value at the adverse buffered stop price.
                if stop is None or stop <= ZERO:
                    self.add(RiskReason.INVALID_STOPS, error=True)
                    continue
                rate = max(rate, ONE / stop)
            candidates.append(rate)
        if not candidates:
            self.add(RiskReason.CONVERSION_UNAVAILABLE, error=True)
            return None
        return max(candidates) * (ONE + self.config.conversion_buffer)

    def value_position(self, position):
        if position.stop_loss is None or position.take_profit is None:
            self.add(RiskReason.UNPROTECTED_EXPOSURE, error=True)
            return None
        if position.managed and not position.ownership_verified:
            self.add(RiskReason.OWNERSHIP_UNVERIFIED, error=True)
        if self.account.position_mode == "netting" and not position.managed:
            self.add(RiskReason.OWNERSHIP_UNVERIFIED, error=True)
        observation = self.observations(position.symbol)
        if observation is None:
            return None
        i, q = observation
        if position.volume % i.volume_step or position.volume < i.volume_min:
            self.add(RiskReason.VOLUME_PRECISION, error=True)
        if position.volume > i.volume_max:
            self.add(RiskReason.MAXIMUM_VOLUME, error=True)
        if position.stop_loss % i.tick_size or position.take_profit % i.tick_size:
            self.add(RiskReason.PRICE_PRECISION, error=True)
        close = q.bid if position.side == "BUY" else q.ask
        if (
            position.side == "BUY"
            and not position.stop_loss < close < position.take_profit
            or position.side == "SELL"
            and not position.take_profit < close < position.stop_loss
        ):
            self.add(RiskReason.UNPROTECTED_EXPOSURE, error=True)
            return None
        buffer = i.slippage_buffer_points * i.point
        rate = self.conversion(i.quote_currency, instrument=i, stop=position.stop_loss - buffer)
        if rate is None:
            return None
        risk = ceil(
            (
                (abs(close - position.stop_loss) + buffer) * i.contract_size * rate
                + i.commission_per_lot_account
            )
            * position.volume
        )
        notional = ceil(i.contract_size * q.ask * rate * position.volume)
        return risk, notional

    def portfolio(self, broker_symbol):
        risk, notional, symbol_notional, source_risk = ZERO, ZERO, ZERO, ZERO
        slots, source_slots = set(), set()
        for p in self.account.positions:
            value = self.value_position(p)
            if value is None:
                continue
            r, n = value
            risk += r
            notional += n
            slots.add(p.slot_id)
            if p.symbol == broker_symbol:
                symbol_notional += n
            if p.source_id == self.config.source.source_id:
                source_risk += r
                source_slots.add(p.slot_id)
        reserved_margin = ZERO
        for r in self.account.reservations:
            # No expiry/acknowledgement releases a reservation. Remaining exposure is
            # supplied by the trusted projection; shared partial-fill slots count once.
            if r.state == "UNKNOWN":
                self.add(RiskReason.UNCERTAIN_EXECUTION, error=True)
            risk += r.risk_amount
            notional += r.notional_amount
            reserved_margin += r.margin_amount
            slots.add(r.slot_id)
            if r.symbol == broker_symbol:
                symbol_notional += r.notional_amount
            if r.source_id == self.config.source.source_id:
                source_risk += r.risk_amount
                source_slots.add(r.slot_id)
        return risk, notional, symbol_notional, source_risk, reserved_margin, slots, source_slots

    def run(self):
        self.gates()
        p, a, c = self.request, self.account, self.config
        mapping = next((m for m in c.allowed_instruments if m.symbol == p.symbol), None)
        if mapping is None:
            self.add(RiskReason.SYMBOL_NOT_ALLOWED)
            return self.result()
        symbol = mapping.broker_symbol
        if p.symbol in c.blocked_symbols or symbol in c.blocked_symbols:
            self.add(RiskReason.SYMBOL_BLOCKED)
        if p.symbol not in c.source.allowed_symbols:
            self.add(RiskReason.SOURCE_SYMBOL_NOT_ALLOWED)
        observation = self.observations(symbol)
        portfolio = self.portfolio(symbol)
        if observation is None or a.equity <= ZERO:
            return self.result()
        i, q = observation
        distance = c.max_deviation_points * i.point
        low, high = p.entry - distance, p.entry + distance
        if low <= ZERO:
            self.add(RiskReason.INVALID_STOPS)
            return self.result()
        worst = high if p.side == "BUY" else low
        spread = (q.ask - q.bid) / i.point
        self.values.update(
            spread_points=ceil(spread), price_band_low=low, price_band_high=high, worst_entry=worst
        )
        if spread > c.max_spread_points:
            self.add(RiskReason.SPREAD_LIMIT)
        executable = q.ask if p.side == "BUY" else q.bid
        if not low <= executable <= high:
            self.add(RiskReason.PRICE_OUTSIDE_BAND)
        if any(price % i.tick_size for price in (p.entry, p.stop_loss, p.take_profit, low, high)):
            self.add(RiskReason.PRICE_PRECISION)
        close = q.bid if p.side == "BUY" else q.ask
        valid_stops = (
            p.stop_loss < min(low, close) and p.take_profit > high
            if p.side == "BUY"
            else p.take_profit < low and p.stop_loss > max(high, close)
        )
        if not valid_stops:
            self.add(RiskReason.INVALID_STOPS)
        protective_distance = (
            min(min(low, close) - p.stop_loss, p.take_profit - max(high, close))
            if p.side == "BUY"
            else min(p.stop_loss - max(high, close), min(low, close) - p.take_profit)
        )
        if protective_distance < i.stops_level_points * i.point:
            self.add(RiskReason.STOP_DISTANCE)
        if i.freeze_level_points and protective_distance <= i.freeze_level_points * i.point:
            self.add(RiskReason.FREEZE_DISTANCE)
        buffer = i.slippage_buffer_points * i.point
        rate = self.conversion(i.quote_currency, instrument=i, stop=p.stop_loss - buffer)
        if rate is None:
            return self.result()
        loss_per_lot = ceil(
            (abs(worst - p.stop_loss) + buffer) * i.contract_size * rate
            + i.commission_per_lot_account
        )
        budget = floor(a.equity * c.source.max_risk_per_trade)
        volume = p.requested_volume
        if volume is None:
            ceiling = min(budget / loss_per_lot, c.policy.max_lots, i.volume_max)
            volume = (ceiling / i.volume_step).to_integral_value(
                rounding=ROUND_FLOOR
            ) * i.volume_step
        if volume < i.volume_min:
            self.add(RiskReason.MINIMUM_VOLUME)
        if volume > min(c.policy.max_lots, i.volume_max):
            self.add(RiskReason.MAXIMUM_VOLUME)
        if volume % i.volume_step:
            self.add(RiskReason.VOLUME_PRECISION)
        trade_risk = ceil(volume * loss_per_lot)
        trade_notional = ceil(volume * i.contract_size * max(high, q.ask) * rate)
        base_rate = ONE if i.base_currency == a.currency else max(high, q.ask) * rate
        margin = ceil(volume * i.contract_size / a.broker_leverage * i.margin_rate * base_rate)
        existing, total, symbol_total, source_total, held_margin, slots, source_slots = portfolio
        available_margin = max(ZERO, a.free_margin - held_margin)
        self.values.update(
            risk_budget=budget,
            loss_per_lot=loss_per_lot,
            candidate_volume=volume,
            estimated_trade_risk=trade_risk,
            existing_open_risk=existing,
            total_open_risk=existing + trade_risk,
            total_notional=total + trade_notional,
            effective_leverage=ceil((total + trade_notional) / a.equity),
            required_margin=margin,
            available_margin=available_margin,
            source_open_risk=source_total + trade_risk,
            symbol_notional=symbol_total + trade_notional,
            conversion_rate=ceil(rate),
            position_slots=len(slots) + 1,
        )
        if trade_risk > budget:
            self.add(RiskReason.TRADE_RISK_LIMIT)
        if existing + trade_risk > a.equity * c.policy.max_total_open_risk:
            self.add(RiskReason.OPEN_RISK_LIMIT)
        if len(slots) + 1 > c.policy.max_open_positions:
            self.add(RiskReason.POSITION_LIMIT)
        if total + trade_notional > a.equity * c.policy.max_effective_leverage:
            self.add(RiskReason.LEVERAGE_LIMIT)
        if symbol_total + trade_notional > a.equity * c.max_symbol_exposure:
            self.add(RiskReason.SYMBOL_EXPOSURE_LIMIT)
        if margin > available_margin:
            self.add(RiskReason.MARGIN_LIMIT)
        if c.source.max_open_risk is not None and (
            source_total + trade_risk > a.equity * c.source.max_open_risk
        ):
            self.add(RiskReason.SOURCE_RISK_LIMIT)
        if c.source.max_open_positions is not None and (
            len(source_slots) + 1 > c.source.max_open_positions
        ):
            self.add(RiskReason.SOURCE_POSITION_LIMIT)
        return self.result(volume)
