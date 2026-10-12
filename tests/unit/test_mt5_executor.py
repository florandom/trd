from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from backend.domain.bridge import PaperPositionCommand
from infra.scripts.mt5_lab import MqlLabProcess
from tests.mt5.helpers import FakeBridge, config_and_command


def test_ea_default_off_needs_no_config_or_network(mql_binary, tmp_path):
    host = MqlLabProcess(mql_binary, tmp_path, None, active=False)
    try:
        assert host.initial["status"] == "DISABLED"
        assert host.cycle()["sequence"] == 0
    finally:
        host.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("origin", "https://example.test"),
        ("environment", "production"),
        ("response_key_hex", "33" * 32),
        ("profile_hash", "bad"),
        ("utc_day", "2000-01-01"),
    ],
)
def test_ea_config_rejects_external_origin_production_and_bad_binding(
    mql_binary, tmp_path, field, value
):
    config, _ = config_and_command()
    config[field] = value
    host = MqlLabProcess(mql_binary, tmp_path, config)
    try:
        assert host.initial["initialized"] == 1
        assert host.initial["operations"] == host.cycle()["sequence"] == 0
    finally:
        host.close()


def test_ea_strategy_tester_cannot_enable_webrequest(mql_binary, tmp_path):
    config, _ = config_and_command()
    host = MqlLabProcess(mql_binary, tmp_path, config, tester=True)
    try:
        assert host.initial["initialized"] == 1
    finally:
        host.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("volume", "0.081"),
        ("volume", "1.01"),
        ("stop_loss", "1.1"),
        ("max_risk", "0.1"),
        ("symbol", "OTHER"),
        ("safety_epoch", 2),
        ("expires_at", datetime.now(UTC) - timedelta(seconds=1)),
    ],
)
def test_ea_preflight_rejects_changed_economics_without_send(mql_binary, tmp_path, field, value):
    config, command = config_and_command()
    command = type(command).model_validate({**command.model_dump(), field: value})
    bridge = FakeBridge(command)
    host = MqlLabProcess(mql_binary, tmp_path, config, transport=httpx.MockTransport(bridge))
    try:
        assert host.initial["initialized"] == 0
        stats = host.cycle()
        assert stats["operations"] == 0
        assert [e["kind"] for e in bridge.events] == ["RECEIVED", "REJECTED"]
    finally:
        host.close()


def test_ea_lost_contact_preserves_journal_and_reconnects(mql_binary, tmp_path):
    config, command = config_and_command()
    bridge = FakeBridge(command, drop=True)
    host = MqlLabProcess(mql_binary, tmp_path, config, transport=httpx.MockTransport(bridge))
    try:
        assert host.cycle()["status"] == "CONTACT_UNAVAILABLE"
        bridge.drop = False
        assert host.cycle()["operations"] == 1
    finally:
        host.close()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw, headers: (raw + b" ", headers),
        lambda raw, headers: (raw, {**headers, "x-trd-sequence": "1"}),
        lambda raw, headers: (raw, {**headers, "content-encoding": "gzip"}),
        lambda raw, headers: (raw, {**headers, "location": "https://example.test"}),
        lambda raw, headers: (raw, {**headers, "X-TRD-Sequence": headers["x-trd-sequence"]}),
        lambda raw, headers: (raw, {**headers, "Content-Type": "application/json"}),
        lambda raw, headers: (raw, {k: v for k, v in headers.items() if k != "x-trd-signature"}),
    ],
)
def test_ea_authentication_failure_never_executes(mql_binary, tmp_path, mutate):
    config, command = config_and_command()
    bridge = FakeBridge(command, mutate=mutate)
    host = MqlLabProcess(mql_binary, tmp_path, config, transport=httpx.MockTransport(bridge))
    try:
        # Sequence mismatch is injected after the first request.
        first = host.cycle()
        assert first["status"] == "FAULT"
        assert first["operations"] == 0
    finally:
        host.close()


@pytest.mark.parametrize(
    "crash,operations,unknown", [("after_intent", 0, 1), ("after_result", 1, 0)]
)
def test_ea_restart_reconciles_independent_ledger_never_resends(
    mql_binary, tmp_path, crash, operations, unknown
):
    config, command = config_and_command()
    bridge = FakeBridge(command)
    host = MqlLabProcess(
        mql_binary, tmp_path, config, crash=crash, transport=httpx.MockTransport(bridge)
    )
    try:
        assert host.cycle()["status"] == "FAULT"
    finally:
        host.close()
    resumed = MqlLabProcess(mql_binary, tmp_path, config, transport=httpx.MockTransport(bridge))
    try:
        assert resumed.initial["operations"] == operations
        assert resumed.initial["unknown"] == unknown
        assert resumed.cycle()["operations"] == operations
    finally:
        resumed.close()


def test_ea_exclusive_owner_and_corrupt_journal_fail_closed(mql_binary, tmp_path):
    config, command = config_and_command()
    bridge = FakeBridge(command)
    host = MqlLabProcess(mql_binary, tmp_path, config, transport=httpx.MockTransport(bridge))
    try:
        assert host.cycle()["operations"] == 1
        second = MqlLabProcess(mql_binary, tmp_path, None)
        try:
            assert second.initial["initialized"] == 1
        finally:
            second.close()
    finally:
        host.close()
    journal = next(tmp_path.rglob("journal.log"))
    journal.write_bytes(journal.read_bytes()[:-20])
    corrupt = MqlLabProcess(mql_binary, tmp_path, None)
    try:
        assert corrupt.initial["initialized"] == 1
        assert corrupt.initial["fault"] == "JOURNAL_CORRUPT_OR_REBOUND"
    finally:
        corrupt.close()


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_ea_exact_entry_value_protective_update_and_full_close(mql_binary, tmp_path, side):
    config, opening = config_and_command()
    if side == "SELL":
        opening = type(opening).model_validate(
            {**opening.model_dump(), "side": side, "stop_loss": "1.10500", "take_profit": "1.09000"}
        )
    bridge = FakeBridge(opening)
    host = MqlLabProcess(mql_binary, tmp_path, config, transport=httpx.MockTransport(bridge))
    try:
        assert host.cycle()["operations"] == 1
        entry = Decimal("1.10000" if side == "BUY" else "1.09990")
        current_sl = Decimal("1.09700" if side == "BUY" else "1.10300")
        common = dict(
            command_id=uuid4(),
            request_id=uuid4(),
            trace_id=opening.trace_id,
            account_id=opening.account_id,
            account=opening.account,
            bridge_id=opening.bridge_id,
            instance_id=opening.instance_id,
            generation=1,
            profile_hash=opening.profile_hash,
            safety_epoch=1,
            position_id=uuid4(),
            position_revision=1,
            opening_command_id=opening.command_id,
            position_identifier="1",
            symbol=opening.symbol,
            side=side,
            volume=opening.volume,
            entry_price=entry,
            entry_value=entry * opening.volume,
            previous_stop_loss=opening.stop_loss,
            previous_take_profit=opening.take_profit,
            stop_loss=current_sl,
            take_profit=opening.take_profit,
            price_band_low="1.09990",
            price_band_high="1.10010",
            max_spread_points="20",
            max_deviation_points="20",
            expires_at=datetime.now(UTC) + timedelta(seconds=30),
        )
        bridge.command = PaperPositionCommand(action="MODIFY_STOPS", **common)
        bridge.sent = False
        assert host.cycle()["operations"] == 2
        common.update(
            command_id=uuid4(),
            request_id=uuid4(),
            position_revision=2,
            previous_stop_loss=current_sl,
        )
        bridge.command = PaperPositionCommand(action="CLOSE", **common)
        bridge.sent = False
        result = host.cycle()
        assert result["positions"] == 0 and result["operations"] == 3
        assert Decimal(result["realized_pnl"]) == Decimal("-1.36")
    finally:
        host.close()


def test_ea_rolled_back_journal_cannot_adopt_unrecorded_broker_result(mql_binary, tmp_path):
    config, command = config_and_command()
    host = MqlLabProcess(
        mql_binary, tmp_path, config, transport=httpx.MockTransport(FakeBridge(command))
    )
    try:
        assert host.cycle()["operations"] == 1
    finally:
        host.close()
    journal = next(tmp_path.rglob("journal.log"))
    journal.write_bytes(journal.read_bytes().splitlines(keepends=True)[0])
    rolled_back = MqlLabProcess(mql_binary, tmp_path, None)
    try:
        assert rolled_back.initial["initialized"] == 1
        assert rolled_back.initial["fault"] == "LEDGER_WITHOUT_DURABLE_INTENT"
    finally:
        rolled_back.close()


@pytest.mark.parametrize(
    "change",
    [{"volume": 1}, {"generation": "1"}, {"partial_volume": "0.01"}, {"account_id": str(uuid4())}],
)
def test_ea_authenticated_command_still_requires_exact_schema(mql_binary, tmp_path, change):
    config, opening = config_and_command()
    command = {**opening.model_dump(mode="json"), **change}
    bridge = FakeBridge(command)
    host = MqlLabProcess(mql_binary, tmp_path, config, transport=httpx.MockTransport(bridge))
    try:
        assert host.cycle()["operations"] == 0
        assert [e["kind"] for e in bridge.events] == ["RECEIVED", "REJECTED"]
    finally:
        host.close()
