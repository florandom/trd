import json
import subprocess
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from backend.domain.bridge import PaperPositionCommand, json_bytes
from infra.scripts.mt5_lab import MqlLabProcess
from tests.mt5.helpers import FakeBridge, config_and_command
from tests.unit.test_mt5_core import core


def request(binary, command, **context):
    result = subprocess.run(
        [str(binary)],
        input=json.dumps({"op": "broker_request", "hex": json_bytes(command).hex(), **context})
        + "\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_mql_adapter_maps_market_and_attached_stops_exactly(mql_binary, side):
    _, command = config_and_command()
    if side == "SELL":
        command = type(command).model_validate(
            {**command.model_dump(), "side": side, "stop_loss": "1.105", "take_profit": "1.09"}
        )
    result = request(mql_binary, command)
    mapped = json.loads(result["answer"])
    native = result["native_request"]
    assert mapped["action"] == "DEAL" and mapped["side"] == side
    assert mapped["filling"] == "FOK" and mapped["position_ticket"] == "0"
    assert mapped["magic"] == "20261012" and len(mapped["comment"]) == 28
    assert native["action"] == 1 and native["type"] == (side == "SELL")
    assert native["volume"] == pytest.approx(float(command.volume))
    assert native["sl"] == pytest.approx(float(command.stop_loss))
    assert native["tp"] == pytest.approx(float(command.take_profit))
    assert native["price"] == pytest.approx(1.1 if side == "BUY" else 1.0999)


def position_command(opening, action):
    entry = Decimal("1.1" if opening.side == "BUY" else "1.0999")
    return PaperPositionCommand(
        **{k: v for k, v in opening.model_dump().items() if k in PaperPositionCommand.model_fields},
        action=action,
        request_id=uuid4(),
        position_id=uuid4(),
        position_revision=1,
        opening_command_id=opening.command_id,
        position_identifier="1",
        entry_price=entry,
        entry_value=opening.volume * entry,
        previous_stop_loss=opening.stop_loss,
        previous_take_profit=opening.take_profit,
    )


@pytest.mark.parametrize("action", ["CLOSE", "MODIFY_STOPS"])
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_mql_adapter_resolves_current_ticket_independently_of_lifetime_id(mql_binary, action, side):
    _, opening = config_and_command()
    if side == "SELL":
        opening = type(opening).model_validate(
            {**opening.model_dump(), "side": side, "stop_loss": "1.105", "take_profit": "1.09"}
        )
    command = position_command(opening, action)
    if action == "MODIFY_STOPS":
        command = command.model_copy(
            update={"stop_loss": Decimal("1.097" if side == "BUY" else "1.103")}
        )
    result = request(
        mql_binary,
        command,
        ticket="10000000000000001",
        identifier="1",
        volume="8000",
        entry="110000" if side == "BUY" else "109990",
        sl="109500" if side == "BUY" else "110500",
        tp="111000" if side == "BUY" else "109000",
        revision="1",
        side=side,
        opening=str(opening.command_id),
    )
    native = result["native_request"]
    assert native["position"] == "10000000000000001"
    if action == "CLOSE":
        assert native["action"] == 1 and native["type"] == (side == "BUY")
        assert native["volume"] == pytest.approx(0.08)
        assert native["sl"] == native["tp"] == 0
    else:
        assert native["action"] == 6 and native["volume"] == native["price"] == 0
        assert native["sl"] == pytest.approx(1.097 if side == "BUY" else 1.103)


@pytest.mark.parametrize(
    "changed",
    [
        {"owned": False},
        {"magic": "0"},
        {"ticket": "0"},
        {"identifier": "2"},
        {"volume": "9000"},
        {"entry": "110001"},
        {"sl": "109501"},
        {"tp": "111001"},
        {"revision": "2"},
        {"opening": str(uuid4())},
        {"side": "SELL"},
    ],
)
def test_broker_adapter_refuses_manual_or_foreign_position_changes(mql_binary, changed):
    _, opening = config_and_command()
    context = dict(
        ticket="1",
        identifier="1",
        volume="8000",
        entry="110000",
        sl="109500",
        tp="111000",
        revision="1",
        side="BUY",
        opening=str(opening.command_id),
    )
    assert (
        request(mql_binary, position_command(opening, "CLOSE"), **{**context, **changed})["answer"]
        == "BROKER_POSITION_CHANGED"
    )


@pytest.mark.parametrize(
    "context",
    [
        {"server": "REAL"},
        {"login": "2"},
        {"currency": "EUR"},
        {"position_mode": "netting"},
        {"symbol": "EURUSD"},
        {"connected": False},
        {"trade_allowed": False},
        {"point": "10"},
        {"tick": "10"},
        {"volume_step": "100"},
        {"volume_max": "200000"},
        {"fok": False},
        {"attached_stops": False},
        {"stops": "0"},
        {"freeze": "0"},
    ],
)
def test_mql_adapter_refuses_unreviewed_terminal_capabilities(mql_binary, context):
    _, command = config_and_command()
    assert request(mql_binary, command, **context)["answer"] == "BROKER_CONTEXT_UNSUPPORTED"


@pytest.mark.parametrize(
    "api_ok,retcode,expected",
    [
        (True, "10009", "AWAIT_EVIDENCE"),
        (True, "10008", "AWAIT_EVIDENCE"),
        (True, "10010", "PARTIAL_UNSUPPORTED"),
        (True, "10012", "UNKNOWN"),
        (True, "10031", "UNKNOWN"),
        (True, "10006", "UNKNOWN"),
        (False, "10009", "UNKNOWN"),
        (True, "12345", "UNKNOWN"),
    ],
)
def test_broker_reply_never_implies_economic_completion(mql_binary, api_ok, retcode, expected):
    assert core(mql_binary, op="disposition", api_ok=api_ok, retcode=retcode) == expected


@pytest.mark.parametrize(
    "scenario",
    [
        "check_false",
        "check_rejected",
        "disconnected",
        "permissions",
        "stale_quote",
        "history_gap",
        "quote_changed_after_check",
    ],
)
def test_broker_preflight_never_creates_send_intent(mql_binary, tmp_path, scenario):
    config, command = config_and_command()
    bridge = FakeBridge(command)
    executor = MqlLabProcess(
        mql_binary, tmp_path, config, scenario=scenario, transport=httpx.MockTransport(bridge)
    )
    try:
        result = executor.cycle()
        assert result["operations"] == result["broker_replies"] == 0
        assert [e["kind"] for e in bridge.events] == ["RECEIVED", "REJECTED"]
    finally:
        executor.close()


@pytest.mark.parametrize(
    "scenario",
    [
        "placed",
        "done_without_evidence",
        "partial",
        "timeout",
        "connection",
        "send_false",
        "send_rejected",
        "external_error",
    ],
)
def test_unproven_broker_result_is_durable_and_blocks_next_command(mql_binary, tmp_path, scenario):
    config, command = config_and_command()
    bridge = FakeBridge(command)
    executor = MqlLabProcess(
        mql_binary, tmp_path, config, scenario=scenario, transport=httpx.MockTransport(bridge)
    )
    try:
        result = executor.cycle()
        assert result["operations"] == 0 and result["unknown"] == result["broker_replies"] == 1
        assert "FILL" not in [e["kind"] for e in bridge.events]
        bridge.command = command.model_copy(update={"command_id": uuid4()})
        bridge.sent = False
        before = len(bridge.requests)
        assert executor.cycle()["status"] == "RECONCILING"
        assert len(bridge.requests) == before
    finally:
        executor.close()
    resumed = MqlLabProcess(mql_binary, tmp_path, config, transport=httpx.MockTransport(bridge))
    try:
        assert resumed.initial["unknown"] == 1
        assert resumed.cycle()["broker_replies"] == 1
        assert not bridge.sent
        records = [
            json.loads(line[65:])
            for line in next(tmp_path.rglob("journal.log")).read_text().splitlines()
        ]
        reply = next(r for r in records if r["type"] == "BROKER_REPLY")
        assert reply["request_id"] == "1"
        if scenario == "partial":
            assert reply["retcode"] == "10010" and reply["volume"] == "4000"
        if scenario == "external_error":
            assert reply["retcode_external"] == "-7"
    finally:
        resumed.close()


@pytest.mark.parametrize("scenario", ["placed_with_evidence", "timeout_with_evidence"])
def test_broker_history_wins_over_transport_result(mql_binary, tmp_path, scenario):
    config, command = config_and_command()
    bridge = FakeBridge(command)
    executor = MqlLabProcess(
        mql_binary, tmp_path, config, scenario=scenario, transport=httpx.MockTransport(bridge)
    )
    try:
        result = executor.cycle()
        assert result["operations"] == result["positions"] == 1 and result["unknown"] == 0
        assert [e["kind"] for e in bridge.events].count("FILL") == 1
        assert executor.cycle()["operations"] == 1
    finally:
        executor.close()


def test_crash_after_check_rejects_without_broker_submission(mql_binary, tmp_path):
    config, command = config_and_command()
    bridge = FakeBridge(command)
    executor = MqlLabProcess(
        mql_binary, tmp_path, config, crash="after_check", transport=httpx.MockTransport(bridge)
    )
    try:
        assert executor.cycle()["fault"] == "LAB_CRASH_AFTER_CHECK"
    finally:
        executor.close()
    resumed = MqlLabProcess(mql_binary, tmp_path, config, transport=httpx.MockTransport(bridge))
    try:
        assert resumed.cycle()["operations"] == resumed.cycle()["broker_replies"] == 0
        assert [e["kind"] for e in bridge.events] == ["RECEIVED", "REJECTED"]
    finally:
        resumed.close()


def test_simulation_build_has_no_native_broker_call_or_activation_escape():
    root = Path(__file__).resolve().parents[2] / "apps/mt5"
    import re

    def expand(path):
        return re.sub(
            r'^#include "([^"]+)"$',
            lambda m: expand(path.parent / m[1]),
            path.read_text(),
            flags=re.MULTILINE,
        )

    source = expand(root / "Experts/TrdLocalBridge.mq5")

    assert not re.search(
        r"\b(?:OrderSend|OrderSendAsync|OrderCheck|AccountInfo\w*|SymbolInfo\w*|HistorySelect)\s*\(",
        source,
    )
    assert "#import" not in source
