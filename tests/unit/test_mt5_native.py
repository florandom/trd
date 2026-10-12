import json
import re
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from infra.scripts.mt5_native import prepare
from tests.mt5.native_helpers import NativeMqlProcess


def test_native_connection_default_off_touches_no_terminal_or_files(native_binary, tmp_path):
    with NativeMqlProcess(
        native_binary, tmp_path, active=False, login="", server="", symbol=""
    ) as host:
        assert host.initial["initialized"] == 0
        result = host.command("TICK")
        assert result["status"] == "DISABLED" and result["native_calls"] == 0
        assert not list(tmp_path.rglob("*.log"))


@pytest.mark.parametrize(
    "options",
    [
        {"tester": True},
        {"login": ""},
        {"server": ""},
        {"symbol": ""},
        {"journal": "bad"},
        {"history": 59},
        {"history": 86401},
    ],
)
def test_native_inputs_fail_before_terminal_calls(native_binary, tmp_path, options):
    with NativeMqlProcess(native_binary, tmp_path, **options) as host:
        assert host.initial["initialized"] == 1
        assert host.initial["native_calls"] == 0


@pytest.mark.parametrize(
    "options",
    [
        {"login": "8"},
        {"server": "OTHER"},
        {"case": "real"},
        {"case": "contest"},
    ],
)
def test_native_identity_requires_explicit_pinned_demo(native_binary, tmp_path, options):
    with NativeMqlProcess(native_binary, tmp_path, **options) as host:
        assert host.initial["initialized"] == 1
        assert host.initial["fault"] == "NATIVE_ACCOUNT_MISMATCH"
        assert host.command("TICK")["broker_calls"] == 0
        assert not list(tmp_path.rglob("*.log"))


def test_native_observes_entire_account_and_preserves_server_time_and_cashflows(
    native_binary, tmp_path
):
    with NativeMqlProcess(native_binary, tmp_path) as host:
        assert host.initial["initialized"] == 0
        result = host.command("TICK")
        assert result["status"] == "NATIVE_READONLY_OBSERVED"
        data = result["snapshot"]
        assert data["scope"] == "native-readonly"
        assert not data["execution_authority"] and not data["send_enabled"]
        assert not data["full_reconciliation"]
        assert data["account"]["mode"] == "demo"
        assert not data["account"]["trade_permission_observed"]
        assert Decimal(data["account"]["equity"]) == Decimal("10249.5")
        assert data["positions"][0]["ticket"] == "10000000000000001"
        assert data["positions"][0]["identifier"] == "10000000000000002"
        assert (
            data["positions"][0]["magic"] == "0" and not data["positions"][0]["ownership_verified"]
        )
        assert Decimal(data["positions"][0]["sl"]) == 0
        assert len(data["orders"]) == 1 and len(data["history_orders"]) == 1
        assert len(data["deals"]) == 2 and data["deals"][1]["symbol"] == ""
        assert Decimal(data["deals"][1]["profit"]) == 250
        assert Decimal(data["deals"][0]["commission"]) == Decimal("-1.25")
        assert Decimal(data["deals"][0]["swap"]) == Decimal("-0.5")
        assert Decimal(data["deals"][0]["fee"]) == Decimal("-0.1")
        assert result["history_to"] - result["history_from"] == 3600
        assert data["history_window_observed"] and data["history_from_server"] == str(
            result["history_from"]
        )
        assert 0 <= result["history_to"] - int(data["market"]["tick_server_time_msc"]) // 1000 <= 10
        assert result["broker_calls"] == 0


@pytest.mark.parametrize(
    "case,reason",
    [
        ("disconnected", "NATIVE_DISCONNECTED"),
        ("history_failed", "NATIVE_HISTORY_UNAVAILABLE"),
        ("symbol_failed", "NATIVE_SYMBOL_READ_FAILED"),
        ("missing_metadata", "NATIVE_SYMBOL_READ_FAILED"),
        ("missing_account", "NATIVE_ACCOUNT_READ_FAILED"),
        ("nan_equity", "NATIVE_ACCOUNT_READ_FAILED"),
        ("inf_contract", "NATIVE_SYMBOL_INVALID_OR_STALE"),
        ("negative_step", "NATIVE_SYMBOL_INVALID_OR_STALE"),
        ("tiny_point", "NATIVE_SYMBOL_INVALID_OR_STALE"),
        ("stale_tick", "NATIVE_SYMBOL_INVALID_OR_STALE"),
        ("future_tick", "NATIVE_SYMBOL_INVALID_OR_STALE"),
        ("missing_position", "NATIVE_POSITION_READ_FAILED"),
        ("missing_order", "NATIVE_ORDER_READ_FAILED"),
        ("missing_deal", "NATIVE_HISTORY_READ_FAILED"),
        ("position_race", "NATIVE_OBSERVATION_CHANGED"),
        ("position_capacity", "NATIVE_POSITION_CAPACITY"),
        ("order_capacity", "NATIVE_ORDER_CAPACITY"),
        ("history_capacity", "NATIVE_HISTORY_CAPACITY"),
        ("unicode", "NATIVE_ACCOUNT_READ_FAILED"),
        ("ticket_overflow", "NATIVE_POSITION_READ_FAILED"),
        ("duplicate_position", "NATIVE_POSITION_READ_FAILED"),
        ("duplicate_order", "NATIVE_ORDER_READ_FAILED"),
        ("duplicate_deal", "NATIVE_HISTORY_READ_FAILED"),
        ("record_capacity", "NATIVE_OBSERVATION_CAPACITY_OR_ENCODING"),
    ],
)
def test_native_missing_stale_or_racing_data_never_publishes_snapshot(
    native_binary, tmp_path, case, reason
):
    with NativeMqlProcess(native_binary, tmp_path, case=case) as host:
        result = host.command("TICK")
        assert result["status"] == reason
        assert (
            result["snapshot"] is None and result["sequence"] == 0 and result["broker_calls"] == 0
        )


def test_native_contact_loss_clears_previous_observation_and_recovers(native_binary, tmp_path):
    with NativeMqlProcess(native_binary, tmp_path) as host:
        assert host.command("TICK")["snapshot"] is not None
        host.command("CASE disconnected")
        assert host.command("TICK")["snapshot"] is None
        host.command("CASE reconnected")
        assert host.command("TICK")["sequence"] == 2


@pytest.mark.parametrize("case", ["account_changed", "server_changed", "real"])
def test_native_account_switch_latches_and_keeps_journal_bound(native_binary, tmp_path, case):
    with NativeMqlProcess(native_binary, tmp_path) as host:
        assert host.command("TICK")["sequence"] == 1
        host.command("CASE " + case)
        result = host.command("TICK")
        assert result["fault"] == "NATIVE_ACCOUNT_MISMATCH"
        assert result["snapshot"] is None and result["sequence"] == 1


@pytest.mark.parametrize(
    "case", ["permissions_on", "netting", "magic_candidate", "negative_equity"]
)
def test_native_diagnostic_data_never_gains_execution_authority(native_binary, tmp_path, case):
    with NativeMqlProcess(native_binary, tmp_path, case=case) as host:
        result = host.command("TICK")
        assert result["snapshot"] is not None
        assert not result["snapshot"]["execution_authority"]
        assert not result["snapshot"]["positions"][0]["ownership_verified"]
        for command in ("SEND", "SEND CLOSE", "SEND STOPS"):
            blocked = host.command(command)
            assert blocked["status"] == "BROKER_SEND_DISABLED"
            assert not blocked["send_ok"] and blocked["send_retcode"] == 10027
        assert host.command("TICK")["broker_calls"] == 0


def test_native_resolves_current_ticket_from_lifetime_identifier(native_binary, tmp_path):
    with NativeMqlProcess(native_binary, tmp_path) as host:
        result = host.command("RESOLVE 10000000000000002")
        assert result["resolved"] and result["resolved_ticket"] == "10000000000000001"
        assert not host.command("RESOLVE 10000000000000001")["resolved"]
        assert not host.command("RESOLVE 001")["resolved"]
        assert host.command("TICK")["broker_calls"] == 0


def test_native_target_resolution_refuses_disconnected_terminal_cache(native_binary, tmp_path):
    with NativeMqlProcess(native_binary, tmp_path) as host:
        assert host.command("RESOLVE 10000000000000002")["resolved"]
        host.command("CASE disconnected")
        result = host.command("RESOLVE 10000000000000002")
        assert not result["resolved"] and result["resolved_ticket"] == "0"
        assert result["status"] == "NATIVE_DISCONNECTED" and result["broker_calls"] == 0


def test_native_transaction_handler_buffers_without_io_and_ignores_undefined_result(
    native_binary, tmp_path
):
    with NativeMqlProcess(native_binary, tmp_path) as host:
        initial = host.initial
        for hint in ("request", "deal", "deal"):
            buffered = host.command("HINT " + hint)
            assert buffered["native_calls"] == initial["native_calls"] and buffered["sequence"] == 0
        assert buffered["hints"] == 3
        result = host.command("TICK")
        assert result["hints"] == 0 and len(result["snapshot"]["deals"]) == 2
    records = [
        json.loads(line[65:])
        for line in next(tmp_path.rglob("observations.log")).read_text().splitlines()
    ]
    hints = records[1]["transactions"]
    assert hints[0]["request_id"] == "99" and hints[0]["retcode_external"] == "-7"
    assert hints[0]["symbol"] == "" and hints[0]["deal"] == hints[0]["order"] == "0"
    assert hints[1]["request_id"] == hints[1]["retcode"] == "0"


def test_native_transaction_overflow_latches_without_reporting_complete_data(
    native_binary, tmp_path
):
    with NativeMqlProcess(native_binary, tmp_path) as host:
        for _ in range(129):
            result = host.command("HINT deal")
        assert result["fault"] == "NATIVE_TRANSACTION_OVERFLOW"
        assert host.command("TICK")["snapshot"] is None


def test_native_restart_replays_sequence_without_adopting_old_snapshot(native_binary, tmp_path):
    journal = uuid4()
    with NativeMqlProcess(native_binary, tmp_path, journal=journal) as host:
        assert host.command("TICK")["sequence"] == 1
    with NativeMqlProcess(native_binary, tmp_path, journal=journal) as host:
        assert host.initial["sequence"] == 1 and host.initial["snapshot"] is None
        assert host.command("TICK")["sequence"] == 2


def test_native_exclusive_lock_and_corrupt_or_rebound_journal_fail_closed(native_binary, tmp_path):
    journal = uuid4()
    with NativeMqlProcess(native_binary, tmp_path, journal=journal) as first:
        assert first.command("TICK")["sequence"] == 1
        with NativeMqlProcess(native_binary, tmp_path, journal=journal) as other:
            assert other.initial["fault"] == "NATIVE_ACCOUNT_OWNED_OR_DISK_FAILED"
    with NativeMqlProcess(native_binary, tmp_path, journal=uuid4()) as changed:
        assert changed.initial["fault"] == "NATIVE_JOURNAL_REBOUND"
    path = next(tmp_path.rglob("observations.log"))
    path.write_bytes(path.read_bytes()[:-20])
    with NativeMqlProcess(native_binary, tmp_path, journal=journal) as corrupt:
        assert corrupt.initial["fault"] == "NATIVE_JOURNAL_CORRUPT"


def test_native_flush_failure_preserves_buffer_and_stops_observations(native_binary, tmp_path):
    with NativeMqlProcess(native_binary, tmp_path) as host:
        host.command("HINT deal")
        host.command("CASE disk_failed")
        result = host.command("TICK")
        assert result["fault"] == "NATIVE_JOURNAL_FLUSH_FAILED"
        assert result["snapshot"] is None and result["hints"] == 1 and result["sequence"] == 0
        assert host.command("TICK")["broker_calls"] == 0


def test_native_prepare_contains_only_readonly_source_and_no_credentials(tmp_path):
    target = tmp_path / "private"
    assert prepare(target) == 0
    files = {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}
    assert files == {
        "LEGGIMI.txt",
        "TRD/Experts/TrdNativeReadOnly.mq5",
        "TRD/Include/TrdNative.mqh",
        "TRD/Include/TrdCore.mqh",
    }
    source = (target / "TRD/Experts/TrdNativeReadOnly.mq5").read_text()
    assert "input bool ActivateNativeReadOnly=false;" in source
    assert 'input string NativeExpectedLogin="";' in source
    assert 'input string NativeExpectedServer="";' in source
    assert 'input string NativeSymbol="";' in source
    journal = re.search(r'input string NativeJournal="([^"]+)";', source)[1]
    assert str(UUID(journal)) == journal
    with pytest.raises(FileExistsError):
        prepare(target)
    assert (target / "TRD/Experts/TrdNativeReadOnly.mq5").read_text() == source


def test_native_build_excludes_submission_libraries_and_network():
    root = Path(__file__).resolve().parents[2] / "apps/mt5"
    source = "\n".join(p.read_text() for p in root.rglob("*") if p.suffix in {".mq5", ".mqh"})
    assert not re.search(r"\b(?:OrderSend|OrderSendAsync|CTrade|OrderCheck)\s*\(", source)
    assert "#import" not in source
    native = (root / "Include/TrdNative.mqh").read_text() + (
        root / "Experts/TrdNativeReadOnly.mq5"
    ).read_text()
    assert "WebRequest(" not in native and "TrdAccept(" not in native
