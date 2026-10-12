from decimal import Decimal
from uuid import uuid4

import pytest

from backend.domain.risk import RiskEngine
from backend.domain.risk_contracts import ReservationExposure, RiskReason
from tests.risk_fixtures import inputs


def held():
    proposal, account, market, config = inputs()
    result = RiskEngine().evaluate(proposal, account, market, config)
    assert result.status == "PASS"
    hold = ReservationExposure(
        reservation_id=uuid4(),
        slot_id=uuid4(),
        signal_id=proposal.signal_id,
        source_id=proposal.source_id,
        symbol=market.instruments[0].symbol,
        risk_amount=result.calculations.estimated_trade_risk,
        notional_amount=result.calculations.estimated_trade_notional,
        margin_amount=result.calculations.required_margin,
        state="HELD",
        volume=result.volume,
    )
    proposal = proposal.model_copy(update={"requested_volume": result.volume})
    account = account.model_copy(
        update={
            "reservations": (hold,),
            "consumed_signal_ids": (proposal.signal_id,),
            "consumed_message_ids": (proposal.message_id,),
        }
    )
    return proposal, account, market, config, hold, result


def test_own_hold_counted_once_and_immutable_volume():
    proposal, account, market, config, hold, original = held()
    result = RiskEngine().revalidate(
        proposal, account, market, config, reservation_id=hold.reservation_id
    )
    assert result.status == "PASS"
    assert result.volume == original.volume
    assert result.calculations.total_open_risk == hold.risk_amount
    assert result.calculations.position_slots == 1
    assert RiskEngine().evaluate(proposal, account, market, config).status == "REJECT"


@pytest.mark.parametrize(
    "change",
    [
        {"state": "SUBMITTED"},
        {"state": "UNKNOWN"},
        {"volume": Decimal("0.01")},
        {"signal_id": uuid4()},
        {"source_id": uuid4()},
        {"symbol": "other"},
    ],
)
def test_cannot_remove_unverified_or_submitted_hold(change):
    proposal, account, market, config, hold, _ = held()
    account = account.model_copy(update={"reservations": (hold.model_copy(update=change),)})
    result = RiskEngine().revalidate(
        proposal, account, market, config, reservation_id=hold.reservation_id
    )
    assert result.status == "ERROR" and result.reason_codes == (RiskReason.INVALID_INPUT,)


def test_other_hold_and_tighter_limits_still_apply():
    proposal, account, market, config, hold, _ = held()
    other = hold.model_copy(
        update={"reservation_id": uuid4(), "slot_id": uuid4(), "signal_id": uuid4()}
    )
    account = account.model_copy(update={"reservations": (hold, other)})
    config = config.model_copy(
        update={"policy": config.policy.model_copy(update={"max_open_positions": 1})}
    )
    result = RiskEngine().revalidate(
        proposal, account, market, config, reservation_id=hold.reservation_id
    )
    assert RiskReason.POSITION_LIMIT in result.reason_codes
    assert result.calculations.position_slots == 2


def test_cost_increase_cannot_expand_reserved_risk_or_resize():
    proposal, account, market, config, hold, _ = held()
    instrument = market.instruments[0].model_copy(
        update={"commission_per_lot_account": Decimal("8")}
    )
    market = market.model_copy(update={"instruments": (instrument,)})
    result = RiskEngine().revalidate(
        proposal, account, market, config, reservation_id=hold.reservation_id
    )
    assert RiskReason.RESERVED_RISK_LIMIT in result.reason_codes and result.volume is None
