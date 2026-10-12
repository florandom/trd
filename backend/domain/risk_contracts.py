"""Immutable inputs for paper risk evaluation; observations are never authority.

The future authenticated gateway must assemble these records under an account lock.
No database, clock, network, provider or broker adapter belongs in these contracts.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from backend.domain.contracts import (
    AccountIdentity,
    Checksum,
    Contract,
    ExactDecimal,
    Fraction,
    NonnegativeDecimal,
    PositiveDecimal,
    Proposal,
    RiskPolicy,
)

RULES_VERSION = "paper-spot-fx-v1"
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Symbol = Annotated[str, Field(min_length=1, max_length=64)]
SignedMoney = Annotated[ExactDecimal, Field(allow_inf_nan=False, max_digits=28, decimal_places=10)]
Confidence = Annotated[NonnegativeDecimal, Field(le=1)]
Stage = Literal["SIGNAL_CLASSIFIER", "SIGNAL_PARSER", "MARKET_ANALYST", "DECISION_AGENT", "CRITIC"]


class RiskReason(StrEnum):
    PASS = "PASS"
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    CALCULATION_ERROR = "CALCULATION_ERROR"
    AUTOMATION_DISABLED = "AUTOMATION_DISABLED"
    SOURCE_DISABLED = "SOURCE_DISABLED"
    ACCOUNT_NOT_ALLOWED = "ACCOUNT_NOT_ALLOWED"
    MODE_NOT_ALLOWED = "MODE_NOT_ALLOWED"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    ACCOUNT_NOT_READY = "ACCOUNT_NOT_READY"
    HEALTH_UNAVAILABLE = "HEALTH_UNAVAILABLE"
    STALE_ACCOUNT = "STALE_ACCOUNT"
    STALE_MARKET = "STALE_MARKET"
    STALE_METADATA = "STALE_METADATA"
    FUTURE_OBSERVATION = "FUTURE_OBSERVATION"
    INVALID_EQUITY = "INVALID_EQUITY"
    PORTFOLIO_INCOMPLETE = "PORTFOLIO_INCOMPLETE"
    UNPROTECTED_EXPOSURE = "UNPROTECTED_EXPOSURE"
    OWNERSHIP_UNVERIFIED = "OWNERSHIP_UNVERIFIED"
    UNCERTAIN_EXECUTION = "UNCERTAIN_EXECUTION"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
    STALE_SIGNAL = "STALE_SIGNAL"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    ADVISORY_INCOMPLETE = "ADVISORY_INCOMPLETE"
    CONFIDENCE_TOO_LOW = "CONFIDENCE_TOO_LOW"
    SYMBOL_NOT_ALLOWED = "SYMBOL_NOT_ALLOWED"
    SOURCE_SYMBOL_NOT_ALLOWED = "SOURCE_SYMBOL_NOT_ALLOWED"
    SYMBOL_BLOCKED = "SYMBOL_BLOCKED"
    METADATA_UNAVAILABLE = "METADATA_UNAVAILABLE"
    QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"
    UNSUPPORTED_PROFILE = "UNSUPPORTED_PROFILE"
    UNSUPPORTED_PROTECTION = "UNSUPPORTED_PROTECTION"
    CONVERSION_UNAVAILABLE = "CONVERSION_UNAVAILABLE"
    MARKET_CLOSED = "MARKET_CLOSED"
    OUTSIDE_SESSION = "OUTSIDE_SESSION"
    PRICE_PRECISION = "PRICE_PRECISION"
    INVALID_STOPS = "INVALID_STOPS"
    STOP_DISTANCE = "STOP_DISTANCE"
    FREEZE_DISTANCE = "FREEZE_DISTANCE"
    SPREAD_LIMIT = "SPREAD_LIMIT"
    PRICE_OUTSIDE_BAND = "PRICE_OUTSIDE_BAND"
    VOLUME_PRECISION = "VOLUME_PRECISION"
    MINIMUM_VOLUME = "MINIMUM_VOLUME"
    MAXIMUM_VOLUME = "MAXIMUM_VOLUME"
    TRADE_RISK_LIMIT = "TRADE_RISK_LIMIT"
    OPEN_RISK_LIMIT = "OPEN_RISK_LIMIT"
    POSITION_LIMIT = "POSITION_LIMIT"
    SYMBOL_EXPOSURE_LIMIT = "SYMBOL_EXPOSURE_LIMIT"
    LEVERAGE_LIMIT = "LEVERAGE_LIMIT"
    MARGIN_LIMIT = "MARGIN_LIMIT"
    RESERVED_RISK_LIMIT = "RESERVED_RISK_LIMIT"
    DAILY_BASELINE_UNAVAILABLE = "DAILY_BASELINE_UNAVAILABLE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    DAILY_LOSS_LATCHED = "DAILY_LOSS_LATCHED"
    SOURCE_RISK_LIMIT = "SOURCE_RISK_LIMIT"
    SOURCE_POSITION_LIMIT = "SOURCE_POSITION_LIMIT"
    SOURCE_COUNTERS_UNAVAILABLE = "SOURCE_COUNTERS_UNAVAILABLE"
    CONSECUTIVE_LOSS_LIMIT = "CONSECUTIVE_LOSS_LIMIT"
    CONSECUTIVE_FAILURE_LIMIT = "CONSECUTIVE_FAILURE_LIMIT"


class RiskProposal(Proposal):
    account: AccountIdentity
    signal_id: UUID
    signal_version: int = Field(strict=True, ge=1)
    message_id: UUID
    message_version: int = Field(strict=True, ge=1)
    source_id: UUID
    source_version: int = Field(strict=True, ge=1)
    published_at: datetime
    action: str = Field(default="OPEN_MARKET", min_length=1, max_length=32)
    review_only: bool = Field(default=False, strict=True)
    requested_volume: PositiveDecimal | None = None

    @model_validator(mode="after")
    def publication_precedes_expiry(self):
        if self.published_at >= self.expires_at:
            raise ValueError("proposal expiry must follow original publication")
        return self


class SessionWindow(Contract):
    weekday: int = Field(strict=True, ge=0, le=6)
    start_minute: int = Field(strict=True, ge=0, le=1439)
    end_minute: int = Field(strict=True, ge=1, le=1440)

    @model_validator(mode="after")
    def positive_window(self):
        if self.start_minute >= self.end_minute:
            raise ValueError("overnight sessions must be split at midnight")
        return self


class SessionCalendar(Contract):
    timezone: str
    windows: tuple[SessionWindow, ...] = Field(max_length=64)
    holidays: tuple[date, ...] = Field(default=(), max_length=366)

    @field_validator("timezone")
    @classmethod
    def installed_timezone(cls, value):
        ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def disjoint_windows(self):
        ordered = sorted(self.windows, key=lambda w: (w.weekday, w.start_minute))
        for before, after in zip(ordered, ordered[1:], strict=False):
            if before.weekday == after.weekday and before.end_minute > after.start_minute:
                raise ValueError("session windows must not overlap")
        return self

    def is_open(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("session evaluation requires an aware timestamp")
        local = now.astimezone(ZoneInfo(self.timezone))
        minute = local.hour * 60 + local.minute
        return local.date() not in self.holidays and any(
            w.weekday == local.weekday() and w.start_minute <= minute < w.end_minute
            for w in self.windows
        )


class SymbolMapping(Contract):
    symbol: Annotated[str, Field(pattern=r"^[A-Z]{6}$")]
    broker_symbol: Symbol
    profile: Literal["spot-fx-v1"] = "spot-fx-v1"


class FxInstrument(Contract):
    snapshot_id: UUID
    observed_at: datetime
    symbol: Symbol
    base_currency: Currency
    quote_currency: Currency
    margin_currency: Currency
    profile: str = Field(min_length=1, max_length=32)
    contract_size: PositiveDecimal
    point: PositiveDecimal
    tick_size: PositiveDecimal
    volume_min: PositiveDecimal
    volume_max: PositiveDecimal
    volume_step: PositiveDecimal
    stops_level_points: int = Field(strict=True, ge=0, le=1_000_000)
    freeze_level_points: int = Field(strict=True, ge=0, le=1_000_000)
    margin_rate: PositiveDecimal
    commission_per_lot_account: NonnegativeDecimal
    slippage_buffer_points: NonnegativeDecimal
    attached_stops_supported: bool = Field(strict=True)

    @model_validator(mode="after")
    def supported_dimensions(self):
        if (
            self.volume_min > self.volume_max
            or self.volume_min % self.volume_step
            or self.volume_max % self.volume_step
            or self.base_currency == self.quote_currency
        ):
            raise ValueError("inconsistent instrument dimensions")
        return self


class Quote(Contract):
    snapshot_id: UUID
    observed_at: datetime
    symbol: Symbol
    bid: PositiveDecimal
    ask: PositiveDecimal
    market_open: bool = Field(strict=True)

    @model_validator(mode="after")
    def ordered_quote(self):
        if self.bid > self.ask:
            raise ValueError("crossed quote")
        return self


class MarketState(Contract):
    snapshot_id: UUID
    account: AccountIdentity
    instruments: tuple[FxInstrument, ...] = Field(max_length=128)
    quotes: tuple[Quote, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def unique_symbols(self):
        for records in (self.instruments, self.quotes):
            if len({r.symbol for r in records}) != len(records):
                raise ValueError("conflicting instrument observations")
        return self


class PositionExposure(Contract):
    position_id: str = Field(min_length=1, max_length=64)
    slot_id: UUID
    symbol: Symbol
    side: Literal["BUY", "SELL"]
    volume: PositiveDecimal
    stop_loss: PositiveDecimal | None
    take_profit: PositiveDecimal | None
    source_id: UUID | None = None
    signal_id: UUID | None = None
    managed: bool = Field(strict=True)
    ownership_verified: bool = Field(strict=True)


class ReservationExposure(Contract):
    reservation_id: UUID
    slot_id: UUID
    signal_id: UUID
    source_id: UUID
    symbol: Symbol
    risk_amount: PositiveDecimal
    notional_amount: PositiveDecimal
    margin_amount: NonnegativeDecimal
    state: Literal["HELD", "SUBMITTED", "UNKNOWN"]
    volume: PositiveDecimal | None = None


class ServiceHealth(Contract):
    service: Literal["database", "risk", "executor"]
    observed_at: datetime
    healthy: bool = Field(strict=True)


class DailyBaseline(Contract):
    snapshot_id: UUID
    account: AccountIdentity
    currency: Currency
    day: date
    opening_equity: PositiveDecimal
    net_cash_flow: SignedMoney
    history_complete: bool = Field(strict=True)
    loss_latched: bool = Field(strict=True)


class SourceCounters(Contract):
    source_id: UUID
    version: int = Field(strict=True, ge=1)
    observed_at: datetime
    consecutive_losses: int = Field(strict=True, ge=0)
    consecutive_failures: int = Field(strict=True, ge=0)


class AccountState(Contract):
    snapshot_id: UUID
    account: AccountIdentity
    observed_at: datetime
    currency: Currency
    equity: NonnegativeDecimal
    free_margin: NonnegativeDecimal
    broker_leverage: PositiveDecimal
    position_mode: Literal["hedging", "netting"]
    safety_epoch: int = Field(strict=True, ge=1)
    status: Literal["PAUSED", "RECONCILING", "READY"]
    reconciliation_complete: bool = Field(strict=True)
    portfolio_complete: bool = Field(strict=True)
    trading_permitted: bool = Field(strict=True)
    positions: tuple[PositionExposure, ...] = Field(max_length=1000)
    reservations: tuple[ReservationExposure, ...] = Field(max_length=1000)
    consumed_signal_ids: tuple[UUID, ...] = Field(default=(), max_length=10_000)
    consumed_message_ids: tuple[UUID, ...] = Field(default=(), max_length=10_000)
    health: tuple[ServiceHealth, ...] = Field(max_length=3)
    daily_baseline: DailyBaseline | None
    source_counters: tuple[SourceCounters, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def unique_evidence(self):
        for records, key in (
            (self.positions, "position_id"),
            (self.positions, "slot_id"),
            (self.reservations, "reservation_id"),
            (self.reservations, "slot_id"),
            (self.health, "service"),
            (self.source_counters, "source_id"),
        ):
            if len({getattr(r, key) for r in records}) != len(records):
                raise ValueError("duplicate portfolio or health evidence")
        positions = {p.slot_id: p for p in self.positions}
        for reservation in self.reservations:
            position = positions.get(reservation.slot_id)
            if position is not None and (
                not position.managed
                or position.signal_id != reservation.signal_id
                or position.source_id != reservation.source_id
                or position.symbol != reservation.symbol
            ):
                raise ValueError("partial-fill slot must refer to the same managed exposure")
        return self


class SourceLimits(Contract):
    source_id: UUID
    version: int = Field(strict=True, ge=1)
    enabled: bool = Field(default=False, strict=True)
    allowed_symbols: tuple[Symbol, ...] = Field(max_length=128)
    max_risk_per_trade: Fraction
    max_open_risk: Fraction | None = None
    max_open_positions: int | None = Field(default=None, strict=True, ge=1, le=100)
    max_consecutive_losses: int | None = Field(default=None, strict=True, ge=1)
    max_consecutive_failures: int | None = Field(default=None, strict=True, ge=1)


class AdvisoryEvidence(Contract):
    receipt_id: UUID
    signal_id: UUID
    signal_version: int = Field(strict=True, ge=1)
    message_version: int = Field(strict=True, ge=1)
    source_version: int = Field(strict=True, ge=1)
    outcome: Literal["PROPOSE", "WAIT", "REJECT", "ESCALATE"]
    completed_stages: tuple[Stage, ...] = Field(max_length=5)
    config_current: bool = Field(strict=True)
    confidence: Confidence

    @model_validator(mode="after")
    def unique_stages(self):
        if len(set(self.completed_stages)) != len(self.completed_stages):
            raise ValueError("duplicate advisory stages")
        return self


class EffectiveRiskConfig(Contract):
    now: datetime
    policy_version: int = Field(strict=True, ge=1)
    hard_limits: RiskPolicy
    policy: RiskPolicy
    source: SourceLimits
    account_allowlist: tuple[AccountIdentity, ...] = Field(max_length=16)
    automation_enabled: bool = Field(default=False, strict=True)
    expected_safety_epoch: int = Field(strict=True, ge=1)
    allowed_instruments: tuple[SymbolMapping, ...] = Field(max_length=128)
    blocked_symbols: tuple[Symbol, ...] = Field(default=(), max_length=128)
    calendar: SessionCalendar
    account_max_age_seconds: int = Field(strict=True, ge=1, le=60)
    quote_max_age_seconds: int = Field(strict=True, ge=1, le=30)
    metadata_max_age_seconds: int = Field(strict=True, ge=1, le=3600)
    health_max_age_seconds: int = Field(strict=True, ge=1, le=60)
    signal_max_age_seconds: int = Field(strict=True, ge=1, le=900)
    max_spread_points: NonnegativeDecimal
    max_deviation_points: NonnegativeDecimal
    conversion_buffer: Fraction
    max_symbol_exposure: PositiveDecimal
    advisory: AdvisoryEvidence
    critic_required: bool = Field(default=False, strict=True)
    minimum_confidence: Confidence

    @model_validator(mode="after")
    def bounded_authority(self):
        self.policy.within(self.hard_limits)
        if (
            self.source.max_risk_per_trade > self.policy.max_risk_per_trade
            or self.source.max_open_risk is not None
            and self.source.max_open_risk > self.policy.max_total_open_risk
            or self.source.max_open_positions is not None
            and self.source.max_open_positions > self.policy.max_open_positions
            or self.max_symbol_exposure > self.policy.max_effective_leverage
        ):
            raise ValueError("source and symbol limits must remain within server policy")
        for key in ("symbol", "broker_symbol"):
            if len({getattr(m, key) for m in self.allowed_instruments}) != len(
                self.allowed_instruments
            ):
                raise ValueError("symbol mapping must be unambiguous")
        return self


class RiskCalculations(Contract):
    equity: NonnegativeDecimal | None = None
    daily_opening_equity: PositiveDecimal | None = None
    daily_cash_flow: SignedMoney | None = None
    daily_loss: NonnegativeDecimal | None = None
    daily_loss_limit: NonnegativeDecimal | None = None
    risk_budget: NonnegativeDecimal | None = None
    loss_per_lot: PositiveDecimal | None = None
    candidate_volume: NonnegativeDecimal | None = None
    estimated_trade_risk: NonnegativeDecimal | None = None
    estimated_trade_notional: NonnegativeDecimal | None = None
    existing_open_risk: NonnegativeDecimal | None = None
    total_open_risk: NonnegativeDecimal | None = None
    total_notional: NonnegativeDecimal | None = None
    effective_leverage: NonnegativeDecimal | None = None
    required_margin: NonnegativeDecimal | None = None
    available_margin: NonnegativeDecimal | None = None
    source_open_risk: NonnegativeDecimal | None = None
    symbol_notional: NonnegativeDecimal | None = None
    spread_points: NonnegativeDecimal | None = None
    price_band_low: PositiveDecimal | None = None
    price_band_high: PositiveDecimal | None = None
    worst_entry: PositiveDecimal | None = None
    conversion_rate: PositiveDecimal | None = None
    position_slots: int | None = Field(default=None, strict=True, ge=0)


class RiskResult(Contract):
    status: Literal["PASS", "REJECT", "ERROR"]
    reason_codes: tuple[RiskReason, ...] = Field(min_length=1)
    rules_version: Literal["paper-spot-fx-v1"] = RULES_VERSION
    policy_version: int | None = None
    source_version: int | None = None
    safety_epoch: int | None = None
    proposal_hash: Checksum | None = None
    config_hash: Checksum | None = None
    account_snapshot_id: UUID | None = None
    market_snapshot_id: UUID | None = None
    baseline_snapshot_id: UUID | None = None
    metadata_snapshot_ids: tuple[UUID, ...] = ()
    quote_snapshot_ids: tuple[UUID, ...] = ()
    calculations: RiskCalculations = RiskCalculations()
    volume: PositiveDecimal | None = None
    latch_daily_loss: bool = False

    @model_validator(mode="after")
    def pass_is_calculation_only(self):
        if (self.status == "PASS") != (self.volume is not None):
            raise ValueError("only a passing evaluation may expose a selected volume")
        return self
