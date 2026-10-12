"""Synthetic, disconnected paper observations; no real account or source material."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.domain.risk_contracts import (
    AccountIdentity,
    AccountState,
    AdvisoryEvidence,
    DailyBaseline,
    EffectiveRiskConfig,
    FxInstrument,
    MarketState,
    Quote,
    RiskPolicy,
    RiskProposal,
    ServiceHealth,
    SessionCalendar,
    SessionWindow,
    SourceLimits,
    SymbolMapping,
)

NOW = datetime(2026, 10, 12, 10, tzinfo=UTC)
SOURCE = UUID(int=1)
SIGNAL = UUID(int=2)
MESSAGE = UUID(int=3)
IDENTITY = AccountIdentity(
    environment_id="test", broker_server="synthetic-paper", login="1", mode="paper"
)


def inputs():
    proposal = RiskProposal(
        account=IDENTITY,
        signal_id=SIGNAL,
        signal_version=1,
        message_id=MESSAGE,
        message_version=1,
        source_id=SOURCE,
        source_version=1,
        symbol="EURUSD",
        side="BUY",
        entry="1.10000",
        stop_loss="1.09500",
        take_profit="1.11000",
        published_at=NOW - timedelta(seconds=10),
        expires_at=NOW + timedelta(seconds=890),
    )
    account = AccountState(
        snapshot_id=UUID(int=4),
        account=IDENTITY,
        observed_at=NOW,
        currency="USD",
        equity="10000",
        free_margin="10000",
        broker_leverage="100",
        position_mode="hedging",
        safety_epoch=1,
        status="READY",
        reconciliation_complete=True,
        portfolio_complete=True,
        trading_permitted=True,
        positions=(),
        reservations=(),
        health=tuple(
            ServiceHealth(service=s, observed_at=NOW, healthy=True)
            for s in ("database", "risk", "executor")
        ),
        daily_baseline=DailyBaseline(
            snapshot_id=UUID(int=5),
            account=IDENTITY,
            currency="USD",
            day=NOW.date(),
            opening_equity="10000",
            net_cash_flow="0",
            history_complete=True,
            loss_latched=False,
        ),
    )
    instrument = FxInstrument(
        snapshot_id=UUID(int=6),
        observed_at=NOW,
        symbol="EURUSD.paper",
        base_currency="EUR",
        quote_currency="USD",
        margin_currency="EUR",
        profile="spot-fx-v1",
        contract_size="100000",
        point="0.00001",
        tick_size="0.00001",
        volume_min="0.01",
        volume_max="100",
        volume_step="0.01",
        stops_level_points=10,
        freeze_level_points=5,
        margin_rate="1",
        commission_per_lot_account="7",
        slippage_buffer_points="5",
        attached_stops_supported=True,
    )
    market = MarketState(
        snapshot_id=UUID(int=7),
        account=IDENTITY,
        instruments=(instrument,),
        quotes=(
            Quote(
                snapshot_id=UUID(int=8),
                observed_at=NOW,
                symbol="EURUSD.paper",
                bid="1.09990",
                ask="1.10000",
                market_open=True,
            ),
        ),
    )
    policy = RiskPolicy()
    config = EffectiveRiskConfig(
        now=NOW,
        policy_version=1,
        hard_limits=policy,
        policy=policy,
        source=SourceLimits(
            source_id=SOURCE,
            version=1,
            enabled=True,
            allowed_symbols=("EURUSD",),
            max_risk_per_trade="0.005",
        ),
        account_allowlist=(IDENTITY,),
        automation_enabled=True,
        expected_safety_epoch=1,
        allowed_instruments=(SymbolMapping(symbol="EURUSD", broker_symbol="EURUSD.paper"),),
        calendar=SessionCalendar(
            timezone="Europe/Rome",
            windows=tuple(
                SessionWindow(weekday=d, start_minute=0, end_minute=1440) for d in range(5)
            ),
        ),
        account_max_age_seconds=10,
        quote_max_age_seconds=5,
        metadata_max_age_seconds=300,
        health_max_age_seconds=10,
        signal_max_age_seconds=900,
        max_spread_points="20",
        max_deviation_points="10",
        conversion_buffer="0.001",
        max_symbol_exposure="5",
        advisory=AdvisoryEvidence(
            receipt_id=UUID(int=9),
            signal_id=SIGNAL,
            signal_version=1,
            message_version=1,
            source_version=1,
            outcome="PROPOSE",
            config_current=True,
            confidence="0.9",
            completed_stages=(
                "SIGNAL_CLASSIFIER",
                "SIGNAL_PARSER",
                "MARKET_ANALYST",
                "DECISION_AGENT",
            ),
        ),
        minimum_confidence="0.8",
    )
    return proposal, account, market, config


def data():
    return [record.model_dump(mode="python") for record in inputs()]
