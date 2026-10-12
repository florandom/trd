from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from uuid import uuid4

import pytest

from backend.domain.bridge import (
    PaperOperatorAction,
    PaperPosition,
    PaperPositionCommand,
    ProtocolError,
    json_bytes,
)
from backend.domain.position_management import position_preflight, realized_pnl
from backend.trading.simulator import PaperSimulator, SimulatedCrash
from tests.unit.test_paper_simulator import ORIGIN, REQUEST_KEY, RESPONSE_KEY, fixture


def management_inputs(action="CLOSE", side="BUY"):
    profile, snapshot, opening = fixture()
    old_sl = Decimal("1.09500") if side == "BUY" else Decimal("1.10500")
    old_tp = Decimal("1.11000") if side == "BUY" else Decimal("1.09000")
    new_sl = Decimal("1.09700") if side == "BUY" else Decimal("1.10300")
    position = PaperPosition(
        broker_identifier="1",
        command_id=opening.command_id,
        symbol=opening.symbol,
        side=side,
        volume=opening.volume,
        entry_price="1.10000",
        stop_loss=old_sl,
        take_profit=old_tp,
    )
    snapshot = snapshot.model_copy(update={"positions": (position,)})
    price = snapshot.quotes[0].bid if side == "BUY" else snapshot.quotes[0].ask
    command = PaperPositionCommand(
        action=action,
        command_id=uuid4(),
        request_id=uuid4(),
        trace_id=opening.trace_id,
        account_id=profile.account_id,
        account=profile.account,
        bridge_id=profile.bridge_id,
        instance_id=profile.instance_id,
        generation=profile.generation,
        profile_hash=profile.digest,
        safety_epoch=1,
        position_id=uuid4(),
        position_revision=1,
        opening_command_id=opening.command_id,
        position_identifier="1",
        symbol=opening.symbol,
        side=side,
        volume=opening.volume,
        entry_price=position.entry_price,
        entry_value=position.entry_price * position.volume,
        previous_stop_loss=old_sl,
        previous_take_profit=old_tp,
        stop_loss=new_sl if action == "MODIFY_STOPS" else old_sl,
        take_profit=old_tp,
        price_band_low=price - Decimal("0.00020"),
        price_band_high=price + Decimal("0.00020"),
        max_spread_points=profile.max_spread_points,
        max_deviation_points=profile.max_deviation_points,
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    return profile, snapshot, opening, command


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("action", ["CLOSE", "MODIFY_STOPS"])
def test_owned_full_close_and_risk_reducing_stops(action, side):
    p, s, _, c = management_inputs(action, side)
    assert position_preflight(c, s, p, 1) > 0
    with localcontext() as context:
        context.prec = 3
        assert position_preflight(c, s, p, 1) > 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("stop_loss", "1.09000"),
        ("stop_loss", "1.09989"),
        ("take_profit", "1.0"),
        ("volume", "0.04"),
        ("opening_command_id", uuid4()),
        ("profile_hash", "0" * 64),
        ("position_identifier", "2"),
        ("safety_epoch", 2),
        ("price_band_low", "1.2"),
        ("expires_at", datetime.now(UTC) - timedelta(seconds=1)),
    ],
)
def test_changed_identity_or_risk_increase_is_rejected(field, value):
    p, s, _, c = management_inputs("MODIFY_STOPS")
    c = PaperPositionCommand.model_validate(c.model_dump(mode="json") | {field: value})
    with pytest.raises(ProtocolError):
        position_preflight(c, s, p, 1)


@pytest.mark.parametrize(
    "value",
    [
        {"action": "MODIFY_STOPS"},
        {"action": "CLOSE", "stop_loss": "1"},
        {"action": "RESUME", "take_profit": "1"},
        {"action": "CLOSE", "volume": "0.01"},
    ],
)
def test_operator_cannot_request_partial_close_or_drop_protection(value):
    with pytest.raises(ValueError):
        PaperOperatorAction.model_validate(value)


@pytest.mark.parametrize(
    "side,price,expected",
    [
        ("BUY", "1.10100", "7.4400000000"),
        ("BUY", "1.09900", "-8.5600000000"),
        ("SELL", "1.09900", "7.4400000000"),
        ("SELL", "1.10100", "-8.5600000000"),
    ],
)
def test_realized_pnl_includes_roundtrip_fees(side, price, expected):
    p, _, _, c = management_inputs(side=side)
    assert realized_pnl(c, Decimal(price), p.instruments[0]) == Decimal(expected)


@pytest.mark.parametrize("action", ["CLOSE", "MODIFY_STOPS"])
@pytest.mark.parametrize("crash", ["after_intent", "after_fill"])
def test_management_restart_never_repeats_broker_operation(tmp_path, action, crash):
    p, s, opening, c = management_inputs(action)
    sim = PaperSimulator(p, REQUEST_KEY, RESPONSE_KEY, tmp_path, ORIGIN)
    payload = json_bytes(opening)
    sim.accept(payload, sha256(payload).hexdigest(), s.model_copy(update={"positions": ()}), 1)
    s = s.model_copy(update={"positions": sim.broker.positions()})
    payload = json_bytes(c)
    digest = sha256(payload).hexdigest()
    try:
        with pytest.raises(SimulatedCrash):
            sim.accept(payload, digest, s, 1, crash=crash)
    finally:
        sim.close()
    resumed = PaperSimulator(p, REQUEST_KEY, RESPONSE_KEY, tmp_path, ORIGIN)
    try:
        resumed.recover()
        resumed.accept(payload, digest, s, 1)
        resumed.recover()
        assert resumed.broker.db.execute("SELECT count(*) FROM position_operations").fetchone()[
            0
        ] == (crash == "after_fill")
        if crash == "after_fill":
            positions = resumed.broker.positions()
            if action == "CLOSE":
                assert not positions
                assert resumed.broker.realized_pnl(p) < 0
            else:
                assert positions[0].stop_loss == c.stop_loss
    finally:
        resumed.close()


def test_pnl_uses_exact_fill_value_instead_of_rounded_display_entry():
    p, _, _, command = management_inputs(side="SELL")
    command = command.model_copy(
        update={"volume": Decimal("0.03"), "entry_value": Decimal("0.032999999999")}
    )
    assert realized_pnl(command, Decimal("1.099"), p.instruments[0]) == Decimal("2.7899999000")


def test_executor_rejects_incorrect_entry_evidence_before_send(tmp_path):
    p, s, opening, command = management_inputs()
    sim = PaperSimulator(p, REQUEST_KEY, RESPONSE_KEY, tmp_path, ORIGIN)
    try:
        payload = json_bytes(opening)
        sim.accept(payload, sha256(payload).hexdigest(), s.model_copy(update={"positions": ()}), 1)
        command = command.model_copy(update={"entry_value": Decimal("0.10")})
        payload = json_bytes(command)
        assert sim.accept(payload, sha256(payload).hexdigest(), s, 1) == "REJECTED"
        assert sim.broker.db.execute("SELECT count(*) FROM position_operations").fetchone()[0] == 0
    finally:
        sim.close()
