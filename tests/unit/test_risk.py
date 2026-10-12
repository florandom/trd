"""Safety boundaries and independently calculated economics for the pure engine."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, getcontext, localcontext
from uuid import UUID

import pytest

from backend.domain.risk import RiskEngine
from backend.domain.risk_contracts import RiskReason as R
from tests.risk_fixtures import IDENTITY, NOW, SOURCE, data, inputs


def evaluate(records):
    return RiskEngine().evaluate(*records)


def reservation(**changes):
    return {
        "reservation_id": UUID(int=100),
        "slot_id": UUID(int=101),
        "signal_id": UUID(int=102),
        "source_id": SOURCE,
        "symbol": "EURUSD.paper",
        "risk_amount": "100",
        "notional_amount": "10000",
        "margin_amount": "100",
        "state": "HELD",
        **changes,
    }


def position(**changes):
    return {
        "position_id": "synthetic-position",
        "slot_id": UUID(int=103),
        "source_id": SOURCE,
        "symbol": "EURUSD.paper",
        "side": "BUY",
        "volume": "0.10",
        "stop_loss": "1.095",
        "take_profit": "1.11",
        "managed": False,
        "ownership_verified": False,
        **changes,
    }


def test_buy_economics_and_evidence_are_exact_and_disconnected():
    result = evaluate(inputs())
    assert result.status == "PASS"
    # Worst entry 1.10010, SL 1.09500: 510 USD/lot + 5 slippage + 7 fees.
    assert result.calculations.loss_per_lot == Decimal("522")
    assert result.calculations.risk_budget == Decimal("50")
    assert result.volume == Decimal("0.09")  # 50/522 rounded down to 0.01.
    assert result.calculations.estimated_trade_risk == Decimal("46.98")
    assert result.calculations.total_notional == Decimal("9900.90")
    assert result.calculations.required_margin == Decimal("99.009")
    assert result.calculations.spread_points == Decimal("10")
    assert result.calculations.position_slots == 1
    assert result.rules_version == "paper-spot-fx-v1"
    assert result.account_snapshot_id == UUID(int=4)
    assert result.metadata_snapshot_ids == (UUID(int=6),)
    assert result.quote_snapshot_ids == (UUID(int=8),)
    assert len(result.proposal_hash) == len(result.config_hash) == 64
    assert '"volume":"0.09"' in result.model_dump_json()


def test_sell_economics_use_bid_and_adverse_lower_entry():
    records = data()
    records[0].update(side="SELL", stop_loss="1.105", take_profit="1.09")
    result = evaluate(records)
    assert result.status == "PASS"
    assert result.calculations.worst_entry == Decimal("1.09990")
    assert result.calculations.loss_per_lot == Decimal("522")
    assert result.volume == Decimal("0.09")


def test_determinism_immutability_and_ambient_decimal_context():
    records = inputs()
    before = [r.model_dump_json() for r in records]
    expected = evaluate(records)
    context_before = getcontext().copy()
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        assert evaluate(records) == expected
        assert context.prec == 6 and context.rounding == ROUND_DOWN
    assert getcontext() == context_before or getcontext().prec == context_before.prec
    assert [r.model_dump_json() for r in records] == before


@pytest.mark.parametrize(
    "index,field,value,reason",
    [
        (3, "automation_enabled", False, R.AUTOMATION_DISABLED),
        (3, "account_allowlist", (), R.ACCOUNT_NOT_ALLOWED),
        (1, "status", "PAUSED", R.ACCOUNT_NOT_READY),
        (1, "status", "RECONCILING", R.ACCOUNT_NOT_READY),
        (1, "reconciliation_complete", False, R.ACCOUNT_NOT_READY),
        (1, "trading_permitted", False, R.ACCOUNT_NOT_READY),
        (1, "portfolio_complete", False, R.PORTFOLIO_INCOMPLETE),
        (1, "equity", "0", R.INVALID_EQUITY),
        (0, "action", "MODIFY_SL_TP", R.UNSUPPORTED_ACTION),
        (0, "action", "CREATE_PENDING", R.UNSUPPORTED_ACTION),
        (0, "action", "PARTIAL_CLOSE", R.UNSUPPORTED_ACTION),
        (0, "review_only", True, R.REVIEW_REQUIRED),
        (0, "signal_version", 2, R.VERSION_MISMATCH),
        (0, "message_version", 2, R.VERSION_MISMATCH),
        (0, "source_version", 2, R.VERSION_MISMATCH),
        (1, "safety_epoch", 2, R.VERSION_MISMATCH),
        (3, "blocked_symbols", ("EURUSD",), R.SYMBOL_BLOCKED),
        (3, "blocked_symbols", ("EURUSD.paper",), R.SYMBOL_BLOCKED),
        (3, "allowed_instruments", (), R.SYMBOL_NOT_ALLOWED),
        (1, "health", (), R.HEALTH_UNAVAILABLE),
        (1, "daily_baseline", None, R.DAILY_BASELINE_UNAVAILABLE),
        (1, "free_margin", "0", R.MARGIN_LIMIT),
    ],
)
def test_independent_gates_never_expose_volume(index, field, value, reason):
    records = data()
    records[index][field] = value
    result = evaluate(records)
    assert result.status in {"REJECT", "ERROR"}
    assert reason in result.reason_codes
    assert result.volume is None


@pytest.mark.parametrize("mode", ["demo", "live"])
def test_nonpaper_identity_cannot_pass_even_when_allowlisted(mode):
    records = data()
    identity = {**IDENTITY.model_dump(), "mode": mode}
    for index in (0, 1, 2):
        records[index]["account"] = identity
    records[1]["daily_baseline"]["account"] = identity
    records[3]["account_allowlist"] = (identity,)
    assert R.MODE_NOT_ALLOWED in evaluate(records).reason_codes


@pytest.mark.parametrize("index", [0, 2])
@pytest.mark.parametrize(
    "field,value",
    [
        ("environment_id", "foreign"),
        ("login", "2"),
        ("broker_server", "foreign"),
    ],
)
def test_account_tuple_and_environment_must_match(index, field, value):
    records = data()
    records[index]["account"][field] = value
    result = evaluate(records)
    assert result.status == "ERROR" and R.ACCOUNT_MISMATCH in result.reason_codes


@pytest.mark.parametrize(
    "kind,maximum,reason",
    [
        ("account", 10, R.STALE_ACCOUNT),
        ("quote", 5, R.STALE_MARKET),
        ("metadata", 300, R.STALE_METADATA),
        ("health", 10, R.HEALTH_UNAVAILABLE),
        ("signal", 900, R.STALE_SIGNAL),
    ],
)
@pytest.mark.parametrize("offset,passes", [(-1, True), (0, False), (1, False)])
def test_freshness_before_at_and_after_each_limit(kind, maximum, reason, offset, passes):
    records = data()
    target = {
        "account": records[1],
        "quote": records[2]["quotes"][0],
        "metadata": records[2]["instruments"][0],
        "health": records[1]["health"][0],
        "signal": records[0],
    }[kind]
    target["published_at" if kind == "signal" else "observed_at"] = NOW - timedelta(
        seconds=maximum + offset
    )
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    assert (reason in result.reason_codes) is not passes


@pytest.mark.parametrize("kind", ["account", "quote", "metadata", "health", "signal"])
def test_future_observations_fail_closed(kind):
    records = data()
    target = {
        "account": records[1],
        "quote": records[2]["quotes"][0],
        "metadata": records[2]["instruments"][0],
        "health": records[1]["health"][0],
        "signal": records[0],
    }[kind]
    target["published_at" if kind == "signal" else "observed_at"] = NOW + timedelta(seconds=1)
    result = evaluate(records)
    assert result.status == "ERROR" and R.FUTURE_OBSERVATION in result.reason_codes


@pytest.mark.parametrize("seconds,passes", [(-1, False), (0, False), (1, True)])
def test_proposal_expiry_is_exclusive(seconds, passes):
    records = data()
    records[0]["expires_at"] = NOW + timedelta(seconds=seconds)
    assert (evaluate(records).status == "PASS") is passes


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("profile", "CFD", R.UNSUPPORTED_PROFILE),
        ("margin_currency", "USD", R.UNSUPPORTED_PROFILE),
        ("base_currency", "GBP", R.UNSUPPORTED_PROFILE),
        ("attached_stops_supported", False, R.UNSUPPORTED_PROTECTION),
        ("symbol", "EURUSD", R.METADATA_UNAVAILABLE),
    ],
)
def test_instrument_profile_and_exact_mapping(field, value, reason):
    records = data()
    records[2]["instruments"][0][field] = value
    result = evaluate(records)
    assert result.status == "ERROR" and reason in result.reason_codes


@pytest.mark.parametrize("field", ["instruments", "quotes"])
def test_missing_or_duplicate_market_evidence(field):
    records = data()
    records[2][field] = ()
    assert evaluate(records).status == "ERROR"
    records = data()
    records[2][field] += (deepcopy(records[2][field][0]),)
    assert evaluate(records).reason_codes == (R.INVALID_INPUT,)


@pytest.mark.parametrize(
    "index,field",
    [(0, "entry"), (0, "stop_loss"), (0, "take_profit"), (1, "equity"), (1, "free_margin")],
)
@pytest.mark.parametrize("value", [1.1, True, "NaN", "Infinity", "-1", None])
def test_malformed_money_cannot_be_coerced(index, field, value):
    records = data()
    records[index][field] = value
    assert evaluate(records).reason_codes == (R.INVALID_INPUT,)


def test_bypassed_model_validation_is_rechecked():
    records = list(inputs())
    records[0] = records[0].model_copy(update={"entry": Decimal("-1")})
    assert evaluate(records).reason_codes == (R.INVALID_INPUT,)


@pytest.mark.parametrize(
    "change",
    [
        {"max_lots": "1"},
        {"max_open_positions": 3},
        {"max_daily_loss": "0.03"},
        {"max_risk_per_trade": "0.006"},
        {"max_total_open_risk": "0.03"},
        {"max_effective_leverage": "6"},
        {"require_stop_loss": False},
        {"require_take_profit": False},
    ],
)
def test_policy_cannot_expand_hard_limits(change):
    records = data()
    records[3]["policy"].update(change)
    assert evaluate(records).reason_codes == (R.INVALID_CONFIGURATION,)


def test_source_limits_cannot_expand_policy():
    records = data()
    records[3]["source"]["max_risk_per_trade"] = "0.006"
    assert evaluate(records).reason_codes == (R.INVALID_CONFIGURATION,)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"enabled": False}, R.SOURCE_DISABLED),
        ({"allowed_symbols": ()}, R.SOURCE_SYMBOL_NOT_ALLOWED),
        ({"version": 2}, R.VERSION_MISMATCH),
        ({"source_id": UUID(int=99)}, R.VERSION_MISMATCH),
    ],
)
def test_source_authority(change, reason):
    records = data()
    records[3]["source"].update(change)
    assert reason in evaluate(records).reason_codes


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"outcome": "WAIT"}, R.ADVISORY_INCOMPLETE),
        ({"outcome": "REJECT"}, R.ADVISORY_INCOMPLETE),
        ({"config_current": False}, R.ADVISORY_INCOMPLETE),
        ({"completed_stages": ("SIGNAL_PARSER",)}, R.ADVISORY_INCOMPLETE),
        ({"confidence": "0.7999999999"}, R.CONFIDENCE_TOO_LOW),
        ({"signal_version": 2}, R.VERSION_MISMATCH),
        ({"message_version": 2}, R.VERSION_MISMATCH),
        ({"source_version": 2}, R.VERSION_MISMATCH),
        ({"signal_id": UUID(int=99)}, R.VERSION_MISMATCH),
    ],
)
def test_advisory_cannot_bypass_versioned_route(change, reason):
    records = data()
    records[3]["advisory"].update(change)
    assert reason in evaluate(records).reason_codes


def test_required_critic_and_confidence_equality():
    records = data()
    records[3]["critic_required"] = True
    records[3]["advisory"]["confidence"] = "0.8"
    assert R.ADVISORY_INCOMPLETE in evaluate(records).reason_codes
    records[3]["advisory"]["completed_stages"] += ("CRITIC",)
    assert evaluate(records).status == "PASS"


@pytest.mark.parametrize("field", ["consumed_signal_ids", "consumed_message_ids", "reservations"])
def test_duplicate_intent_cannot_reenter_risk(field):
    records = data()
    records[1][field] = (
        (reservation(signal_id=records[0]["signal_id"]),)
        if field == "reservations"
        else (records[0]["signal_id" if field == "consumed_signal_ids" else "message_id"],)
    )
    assert R.DUPLICATE_SIGNAL in evaluate(records).reason_codes


@pytest.mark.parametrize("entry", ["1.100001", "1.1000000001"])
def test_no_silent_price_rounding(entry):
    records = data()
    records[0]["entry"] = entry
    assert R.PRICE_PRECISION in evaluate(records).reason_codes


@pytest.mark.parametrize(
    "bid,reason", [("1.09979", R.SPREAD_LIMIT), ("1.0998", None), ("1.09981", None)]
)
def test_spread_boundary(bid, reason):
    records = data()
    records[2]["quotes"][0]["bid"] = bid
    result = evaluate(records)
    assert (result.status == "PASS") is (reason is None)
    if reason:
        assert reason in result.reason_codes


@pytest.mark.parametrize("ask,passes", [("1.10009", True), ("1.10010", True), ("1.10011", False)])
def test_price_band_boundary(ask, passes):
    records = data()
    records[2]["quotes"][0].update(ask=ask, bid="1.10000")
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    if not passes:
        assert R.PRICE_OUTSIDE_BAND in result.reason_codes


@pytest.mark.parametrize(
    "volume,reason",
    [
        ("0.009", R.MINIMUM_VOLUME),
        ("0.015", R.VOLUME_PRECISION),
        ("0.50", R.TRADE_RISK_LIMIT),
        ("0.51", R.MAXIMUM_VOLUME),
    ],
)
def test_requested_volume_is_never_resized(volume, reason):
    records = data()
    records[0]["requested_volume"] = volume
    result = evaluate(records)
    assert reason in result.reason_codes and result.volume is None
    assert result.calculations.candidate_volume == Decimal(volume)


@pytest.mark.parametrize("volume,passes", [("0.009", False), ("0.01", True), ("0.02", True)])
def test_minimum_volume_boundary(volume, passes):
    records = data()
    records[0]["requested_volume"] = volume
    assert (evaluate(records).status == "PASS") is passes


def test_minimum_lot_is_not_rounded_up_to_fit_budget():
    records = data()
    records[3]["source"]["max_risk_per_trade"] = "0.0001"
    result = evaluate(records)
    assert R.MINIMUM_VOLUME in result.reason_codes
    assert result.calculations.candidate_volume == Decimal("0")


@pytest.mark.parametrize(
    "equity,passes,latch",
    [("9800.01", True, False), ("9800", False, True), ("9799.99", False, True)],
)
def test_daily_loss_below_at_and_above_limit(equity, passes, latch):
    records = data()
    records[1]["equity"] = equity
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    assert result.latch_daily_loss is latch


@pytest.mark.parametrize(
    "equity,cashflow,loss",
    [
        ("11000", "1000", "0"),
        ("9000", "-1000", "0"),
        ("10800", "1000", "200"),
        ("8800", "-1000", "200"),
    ],
)
def test_cashflows_adjust_loss_without_resetting_daily_budget(equity, cashflow, loss):
    records = data()
    records[1]["equity"] = equity
    records[1]["daily_baseline"]["net_cash_flow"] = cashflow
    result = evaluate(records)
    assert result.calculations.daily_loss == Decimal(loss)
    assert result.calculations.daily_loss_limit == Decimal("200")
    assert result.latch_daily_loss is (loss == "200")


def test_daily_loss_latch_survives_recovery_and_reset_rechecks_loss():
    records = data()
    records[1]["daily_baseline"]["loss_latched"] = True
    assert R.DAILY_LOSS_LATCHED in evaluate(records).reason_codes
    records[1]["daily_baseline"]["loss_latched"] = False
    records[1]["equity"] = "9800"
    assert evaluate(records).latch_daily_loss


@pytest.mark.parametrize(
    "change",
    [
        {"day": (NOW - timedelta(days=1)).date()},
        {"currency": "EUR"},
        {"account": {**IDENTITY.model_dump(), "login": "9"}},
        {"history_complete": False},
        {"net_cash_flow": "-10000"},
    ],
)
def test_baseline_must_be_complete_current_and_account_bound(change):
    records = data()
    records[1]["daily_baseline"].update(change)
    assert R.DAILY_BASELINE_UNAVAILABLE in evaluate(records).reason_codes


def test_all_account_exposure_includes_manual_positions_and_pending_reservations():
    records = data()
    records[1]["positions"] = (position(),)
    records[1]["reservations"] = (reservation(),)
    result = evaluate(records)
    assert result.calculations.existing_open_risk == Decimal("150.2")
    assert result.calculations.total_open_risk == Decimal("197.18")
    assert result.calculations.position_slots == 3
    assert R.POSITION_LIMIT in result.reason_codes


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"stop_loss": None}, R.UNPROTECTED_EXPOSURE),
        ({"take_profit": None}, R.UNPROTECTED_EXPOSURE),
        ({"stop_loss": "1.11"}, R.UNPROTECTED_EXPOSURE),
        ({"managed": True, "ownership_verified": False}, R.OWNERSHIP_UNVERIFIED),
        ({"stop_loss": "1.095001"}, R.PRICE_PRECISION),
    ],
)
def test_unverifiable_external_exposure_closes_gate(change, reason):
    records = data()
    records[1]["positions"] = (position(**change),)
    result = evaluate(records)
    assert result.status == "ERROR" and reason in result.reason_codes


def test_unknown_outcome_holds_exposure_and_cannot_pass():
    records = data()
    records[1]["reservations"] = (reservation(state="UNKNOWN"),)
    result = evaluate(records)
    assert R.UNCERTAIN_EXECUTION in result.reason_codes
    assert result.calculations.existing_open_risk == Decimal("100")


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"risk_amount": "153.03"}, R.OPEN_RISK_LIMIT),
        ({"notional_amount": "40100"}, R.LEVERAGE_LIMIT),
        ({"margin_amount": "9901"}, R.MARGIN_LIMIT),
    ],
)
def test_reservations_consume_risk_notional_and_margin(change, reason):
    records = data()
    records[1]["reservations"] = (reservation(**change),)
    assert reason in evaluate(records).reason_codes


def test_partial_fill_counts_remaining_risk_and_one_shared_slot():
    records = data()
    records[1]["positions"] = (
        position(managed=True, ownership_verified=True, signal_id=UUID(int=102)),
    )
    records[1]["reservations"] = (reservation(slot_id=UUID(int=103)),)
    result = evaluate(records)
    assert result.status == "PASS"
    assert result.calculations.position_slots == 2
    assert result.calculations.existing_open_risk == Decimal("150.2")


def test_arbitrary_shared_slots_and_duplicate_projection_cannot_hide_exposure():
    records = data()
    records[1]["positions"] = (position(),)
    records[1]["reservations"] = (reservation(slot_id=UUID(int=103)),)
    assert evaluate(records).reason_codes == (R.INVALID_INPUT,)
    records = data()
    records[1]["positions"] = (position(), position(position_id="other"))
    assert evaluate(records).reason_codes == (R.INVALID_INPUT,)


def test_source_risk_and_position_caps_are_independent():
    records = data()
    records[1]["reservations"] = (reservation(),)
    records[3]["source"].update(max_open_risk="0.01", max_open_positions=1)
    result = evaluate(records)
    assert R.SOURCE_RISK_LIMIT in result.reason_codes
    assert R.SOURCE_POSITION_LIMIT in result.reason_codes


@pytest.mark.parametrize(
    "field,reason",
    [
        ("max_consecutive_losses", R.CONSECUTIVE_LOSS_LIMIT),
        ("max_consecutive_failures", R.CONSECUTIVE_FAILURE_LIMIT),
    ],
)
def test_enabled_source_counters_require_current_evidence(field, reason):
    records = data()
    records[3]["source"][field] = 3
    assert R.SOURCE_COUNTERS_UNAVAILABLE in evaluate(records).reason_codes
    records[1]["source_counters"] = (
        {
            "source_id": SOURCE,
            "version": 1,
            "observed_at": NOW,
            "consecutive_losses": 3,
            "consecutive_failures": 3,
        },
    )
    assert reason in evaluate(records).reason_codes
    records[1]["source_counters"][0]["version"] = 2
    assert R.SOURCE_COUNTERS_UNAVAILABLE in evaluate(records).reason_codes


def test_several_rejections_are_retained_and_error_wins():
    records = data()
    records[3]["automation_enabled"] = False
    records[3]["source"]["enabled"] = False
    records[1]["daily_baseline"] = None
    result = evaluate(records)
    assert result.status == "ERROR"
    assert {R.AUTOMATION_DISABLED, R.SOURCE_DISABLED, R.DAILY_BASELINE_UNAVAILABLE}.issubset(
        result.reason_codes
    )
    assert len(result.reason_codes) == len(set(result.reason_codes))


def test_utc_day_rollover_does_not_invent_a_new_baseline():
    records = data()
    records[3]["now"] = datetime(2026, 10, 13, 0, tzinfo=UTC)
    assert R.DAILY_BASELINE_UNAVAILABLE in evaluate(records).reason_codes


@pytest.mark.parametrize(
    "fraction,passes",
    [
        ("0.0046979999", False),
        ("0.004698", True),
        ("0.0046980001", True),
    ],
)
def test_exact_per_trade_risk_boundary(fraction, passes):
    records = data()
    records[0]["requested_volume"] = "0.09"
    records[3]["source"]["max_risk_per_trade"] = fraction
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    if not passes:
        assert R.TRADE_RISK_LIMIT in result.reason_codes


@pytest.mark.parametrize(
    "amount,passes",
    [
        ("153.0199999999", True),
        ("153.02", True),
        ("153.0200000001", False),
    ],
)
def test_exact_total_open_risk_boundary(amount, passes):
    records = data()
    records[1]["reservations"] = (reservation(risk_amount=amount),)
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    if not passes:
        assert R.OPEN_RISK_LIMIT in result.reason_codes


@pytest.mark.parametrize(
    "amount,passes",
    [
        ("40099.0999999999", True),
        ("40099.1", True),
        ("40099.1000000001", False),
    ],
)
def test_exact_gross_leverage_and_symbol_boundary(amount, passes):
    records = data()
    records[1]["reservations"] = (reservation(notional_amount=amount),)
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    if not passes:
        assert R.LEVERAGE_LIMIT in result.reason_codes
        assert R.SYMBOL_EXPOSURE_LIMIT in result.reason_codes


@pytest.mark.parametrize(
    "amount,passes",
    [
        ("99.0089999999", False),
        ("99.009", True),
        ("99.0090000001", True),
    ],
)
def test_exact_free_margin_boundary(amount, passes):
    records = data()
    records[1]["free_margin"] = amount
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    if not passes:
        assert R.MARGIN_LIMIT in result.reason_codes


@pytest.mark.parametrize("slots,passes", [(0, True), (1, True), (2, False)])
def test_global_position_limit_below_at_and_above(slots, passes):
    records = data()
    records[1]["reservations"] = tuple(
        reservation(
            reservation_id=UUID(int=200 + n),
            slot_id=UUID(int=300 + n),
            risk_amount="1",
            notional_amount="1",
            margin_amount="1",
        )
        for n in range(slots)
    )
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    assert result.calculations.position_slots == slots + 1


def fx_inputs(pair, currency="USD", side="BUY"):
    records = data()
    usd_quote = pair.endswith("USD")
    entry, stop, target = (
        ("1.10000", "1.09500", "1.11000")
        if usd_quote
        else (
            ("150.000", "149.000", "152.000")
            if pair == "USDJPY"
            else ("1.50000", "1.49500", "1.51000")
        )
    )
    records[0].update(symbol=pair, entry=entry, stop_loss=stop, take_profit=target, side=side)
    if side == "SELL":
        records[0].update(stop_loss=target, take_profit=stop)
    records[1]["currency"] = records[1]["daily_baseline"]["currency"] = currency
    records[3]["source"]["allowed_symbols"] = (pair,)
    records[3]["allowed_instruments"][0].update(symbol=pair, broker_symbol=pair + ".paper")
    records[2]["instruments"][0].update(
        symbol=pair + ".paper",
        base_currency=pair[:3],
        quote_currency=pair[3:],
        margin_currency=pair[:3],
        point="0.001" if pair == "USDJPY" else "0.00001",
        tick_size="0.001" if pair == "USDJPY" else "0.00001",
    )
    point = Decimal(records[2]["instruments"][0]["point"])
    records[2]["quotes"][0].update(
        symbol=pair + ".paper", ask=entry, bid=str(Decimal(entry) - point * 10)
    )
    return records


@pytest.mark.parametrize(
    "pair",
    [
        "EURUSD",
        "GBPUSD",
        "AUDUSD",
        "NZDUSD",
        "USDJPY",
        "USDCHF",
        "USDCAD",
    ],
)
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_all_seven_supported_forex_profiles_have_paper_economics(pair, side):
    result = evaluate(fx_inputs(pair, side=side))
    assert result.status == "PASS"
    assert result.calculations.estimated_trade_risk <= result.calculations.risk_budget


def test_inverse_conversion_uses_buffered_stop_and_preserves_base_currency_margin():
    records = fx_inputs("USDJPY")
    result = evaluate(records)
    with localcontext() as context:
        context.prec = 80
        expected_loss = (Decimal("101500") / Decimal("148.995")) * Decimal("1.001") + 7
        expected_loss = expected_loss.quantize(Decimal("0.0000000001"), rounding="ROUND_CEILING")
    assert result.calculations.loss_per_lot == expected_loss
    assert result.calculations.required_margin == result.volume * 1000
    # At-stop USD valuation exceeds the tempting current-price-only calculation.
    assert result.calculations.loss_per_lot > Decimal("101500") / Decimal("149.99") + 7


def test_non_usd_account_uses_an_exact_inverse_rate():
    result = evaluate(fx_inputs("EURUSD", currency="EUR"))
    with localcontext() as context:
        context.prec = 80
        expected_loss = Decimal("515") / Decimal("1.09495") * Decimal("1.001") + 7
        expected_loss = expected_loss.quantize(Decimal("0.0000000001"), rounding="ROUND_CEILING")
    assert result.status == "PASS"
    assert result.calculations.loss_per_lot == expected_loss


def test_explicit_direct_conversion_and_all_conversion_snapshots_are_recorded():
    records = fx_inputs("USDJPY", currency="JPY")
    records[1]["equity"] = records[1]["free_margin"] = "1000000"
    records[1]["daily_baseline"]["opening_equity"] = "1000000"
    result = evaluate(records)
    assert result.status == "PASS"
    assert result.calculations.conversion_rate == Decimal("1")
    # USD base notional/margin is converted to JPY using the reviewed price band.
    assert result.calculations.required_margin == result.volume * Decimal("150010")


def test_missing_unapproved_or_stale_conversion_never_assumes_one_to_one():
    records = fx_inputs("USDJPY", currency="EUR")
    result = evaluate(records)
    assert result.status == "ERROR" and R.CONVERSION_UNAVAILABLE in result.reason_codes
    records = fx_inputs("EURUSD", currency="EUR")
    records[2]["quotes"][0]["observed_at"] = NOW - timedelta(seconds=5)
    assert evaluate(records).status == "ERROR"


def test_unimplemented_metals_and_crosses_cannot_masquerade_as_a_forex_profile():
    for pair in ("XAUUSD", "EURJPY"):
        assert R.UNSUPPORTED_PROFILE in evaluate(fx_inputs(pair)).reason_codes


@pytest.mark.parametrize("distance,passes", [(9, False), (10, True), (11, True)])
def test_stop_distance_boundary_across_whole_approved_band(distance, passes):
    records = data()
    records[0]["requested_volume"] = "0.01"
    records[3]["max_deviation_points"] = "0"
    records[2]["quotes"][0].update(bid="1.1", ask="1.1")
    records[0]["stop_loss"] = str(Decimal("1.1") - Decimal(distance) * Decimal("0.00001"))
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    if not passes:
        assert R.STOP_DISTANCE in result.reason_codes


@pytest.mark.parametrize("distance,passes", [(4, False), (5, False), (6, True)])
def test_freeze_distance_is_strict(distance, passes):
    records = data()
    records[0]["requested_volume"] = "0.01"
    records[3]["max_deviation_points"] = "0"
    records[2]["instruments"][0]["stops_level_points"] = 0
    records[2]["quotes"][0].update(bid="1.1", ask="1.1")
    records[0]["stop_loss"] = str(Decimal("1.1") - Decimal(distance) * Decimal("0.00001"))
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    if not passes:
        assert R.FREEZE_DISTANCE in result.reason_codes


def test_unexpected_calculation_failure_returns_safe_error_without_input_text(monkeypatch):
    def broken(*_args):
        raise RuntimeError("private observation must never appear in result")

    monkeypatch.setattr("backend.domain.risk._Evaluation.run", broken)
    result = evaluate(inputs())
    assert result.status == "ERROR" and result.reason_codes == (R.CALCULATION_ERROR,)
    assert result.volume is None
    assert "private observation" not in result.model_dump_json()


def test_direct_fx_conversion_uses_ask_buffer_and_binds_both_observations():
    records = fx_inputs("EURUSD", currency="JPY")
    extra = fx_inputs("USDJPY", currency="JPY")
    extra[2]["instruments"][0]["snapshot_id"] = UUID(int=56)
    extra[2]["quotes"][0]["snapshot_id"] = UUID(int=58)
    records[2]["instruments"] += extra[2]["instruments"]
    records[2]["quotes"] += extra[2]["quotes"]
    records[3]["allowed_instruments"] += extra[3]["allowed_instruments"]
    records[1]["equity"] = records[1]["free_margin"] = "1000000"
    records[1]["daily_baseline"]["opening_equity"] = "1000000"
    result = evaluate(records)
    assert result.status == "PASS"
    assert result.calculations.conversion_rate == Decimal("150.15")
    assert result.calculations.loss_per_lot == Decimal("77334.25")
    assert result.metadata_snapshot_ids == (UUID(int=6), UUID(int=56))
    assert result.quote_snapshot_ids == (UUID(int=8), UUID(int=58))
    records[2]["quotes"][1]["observed_at"] = NOW - timedelta(seconds=5)
    assert evaluate(records).status == "ERROR"


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("health", R.HEALTH_UNAVAILABLE),
        ("session", R.OUTSIDE_SESSION),
        ("market", R.MARKET_CLOSED),
    ],
)
def test_offline_health_closed_calendar_and_broker_market_gate(kind, reason):
    records = data()
    if kind == "health":
        records[1]["health"][0]["healthy"] = False
    elif kind == "session":
        records[3]["calendar"]["windows"] = ()
    else:
        records[2]["quotes"][0]["market_open"] = False
    result = evaluate(records)
    assert result.status != "PASS" and reason in result.reason_codes


@pytest.mark.parametrize("mode,passes", [("hedging", True), ("netting", False)])
def test_manual_exposure_on_netting_account_cannot_establish_managed_ownership(mode, passes):
    records = data()
    records[1]["positions"] = (position(),)
    records[1]["position_mode"] = mode
    result = evaluate(records)
    assert (result.status == "PASS") is passes
    if not passes:
        assert R.OWNERSHIP_UNVERIFIED in result.reason_codes


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_stop_crossing_approved_band_is_rejected(side):
    records = data()
    records[0]["side"] = side
    if side == "BUY":
        records[0]["stop_loss"] = "1.09999"
    else:
        records[0].update(stop_loss="1.10001", take_profit="1.095")
    assert R.INVALID_STOPS in evaluate(records).reason_codes


def test_nonpositive_band_and_conversion_stop_cannot_be_valued():
    records = data()
    records[3]["max_deviation_points"] = "200000"
    assert R.INVALID_STOPS in evaluate(records).reason_codes
    records = fx_inputs("USDJPY")
    records[2]["instruments"][0]["slippage_buffer_points"] = "200000"
    result = evaluate(records)
    assert result.status == "ERROR" and R.INVALID_STOPS in result.reason_codes


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"volume": "0.015"}, R.VOLUME_PRECISION),
        ({"volume": "100.01"}, R.MAXIMUM_VOLUME),
        ({"symbol": "unknown-symbol"}, R.METADATA_UNAVAILABLE),
    ],
)
def test_external_position_dimensions_are_not_silently_corrected(change, reason):
    records = data()
    records[1]["positions"] = (position(**change),)
    assert reason in evaluate(records).reason_codes


def test_sell_position_and_foreign_source_exposure_still_consume_global_limits():
    records = data()
    records[1]["positions"] = (
        position(side="SELL", stop_loss="1.105", take_profit="1.09", source_id=UUID(int=99)),
    )
    records[1]["reservations"] = (reservation(source_id=UUID(int=99)),)
    result = evaluate(records)
    assert result.calculations.existing_open_risk == Decimal("151.2")
    assert result.calculations.source_open_risk == Decimal("46.98")
    assert R.POSITION_LIMIT in result.reason_codes


@pytest.mark.parametrize(
    "field,value",
    [
        ("volume_min", "0.015"),
        ("volume_max", "0.001"),
        ("volume_step", "0.03"),
        ("point", "0"),
        ("base_currency", "USD"),
    ],
)
def test_inconsistent_metadata_is_invalid_input(field, value):
    records = data()
    records[2]["instruments"][0][field] = value
    assert evaluate(records).reason_codes == (R.INVALID_INPUT,)


def test_crossed_quote_duplicate_stages_and_ambiguous_mapping_are_errors():
    records = data()
    records[2]["quotes"][0]["bid"] = "1.2"
    assert evaluate(records).reason_codes == (R.INVALID_INPUT,)
    records = data()
    records[3]["advisory"]["completed_stages"] += ("SIGNAL_PARSER",)
    assert evaluate(records).reason_codes == (R.INVALID_CONFIGURATION,)
    records = data()
    records[3]["allowed_instruments"] += records[3]["allowed_instruments"]
    assert evaluate(records).reason_codes == (R.INVALID_CONFIGURATION,)


@pytest.mark.parametrize("kind", ["source-risk", "source-positions", "symbol"])
def test_source_and_symbol_configuration_cannot_expand_policy(kind):
    records = data()
    if kind == "source-risk":
        records[3]["source"]["max_open_risk"] = "0.03"
    elif kind == "source-positions":
        records[3]["source"]["max_open_positions"] = 3
    else:
        records[3]["max_symbol_exposure"] = "6"
    assert evaluate(records).reason_codes == (R.INVALID_CONFIGURATION,)


@pytest.mark.parametrize("index,field", [(0, "published_at"), (1, "observed_at"), (3, "now")])
def test_naive_input_timestamps_fail_closed(index, field):
    records = data()
    records[index][field] = NOW.replace(tzinfo=None)
    result = evaluate(records)
    assert result.status == "ERROR" and result.volume is None


def test_fractional_caps_are_rounded_down_without_changing_signed_volume():
    records = data()
    records[1]["equity"] = "10000.0000000001"
    records[0]["requested_volume"] = "0.09"
    result = evaluate(records)
    assert result.status == "PASS"
    assert result.calculations.risk_budget == Decimal("50.0000000000")
    assert result.volume == Decimal("0.09")
