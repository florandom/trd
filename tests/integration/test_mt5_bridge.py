from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.api.factory import create_bridge_app
from backend.infrastructure.bridge_models import PaperCommandRecord
from backend.infrastructure.domain_models import (
    ExecutionCommand,
    Position,
    RiskReservation,
    TradingAccount,
)
from backend.infrastructure.position_models import PaperOperation
from infra.scripts.mt5_lab import MqlLabProcess, lab_config
from infra.scripts.paper_scenarios import LocalPaperScenario

pytestmark = pytest.mark.integration


@pytest.fixture
def native(isolated_database, tmp_path):
    scenario = LocalPaperScenario(isolated_database.urls, tmp_path)
    with TestClient(
        create_bridge_app(scenario.settings, lambda _: True, engine=scenario.engines["trd_risk"])
    ) as client:
        scenario.client = client
        yield scenario
    scenario.close()


def host(binary, platform, directory, config, **options):
    def relay(request):
        response = platform.client.post(
            request.url.path, content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(
            response.status_code,
            stream=httpx.ByteStream(response.content),
            headers=dict(response.headers),
        )

    return MqlLabProcess(binary, directory, config, transport=httpx.MockTransport(relay), **options)


def configuration(scenario):
    return lab_config(
        scenario.profile,
        scenario.snapshot(),
        scenario.request_key,
        scenario.response_key,
        "http://127.0.0.1:12345",
        uuid4(),
    )


@pytest.mark.parametrize("action", ["OPEN", "MODIFY_STOPS", "CLOSE"])
@pytest.mark.parametrize("crash", ["after_intent", "after_result"])
def test_native_ea_restart_retains_unknown_or_reconciles_real_gateway(
    mql_binary, native, tmp_path, action, crash
):
    config = configuration(native)
    directory = tmp_path / "terminal"
    if action != "OPEN":
        original = host(mql_binary, native, directory, config)
        try:
            native.emit_signal()
            assert original.cycle()["operations"] == 1
        finally:
            original.close()
        with native.operator.connect() as c:
            position = c.scalar(select(Position.id))
        extra = (
            {"stop_loss": "1.09700", "take_profit": "1.11000"} if action == "MODIFY_STOPS" else {}
        )
        native.operator_request(action, position, **extra)
    else:
        native.emit_signal()
    executor = host(mql_binary, native, directory, config, crash=crash)
    try:
        assert executor.cycle()["status"] == "FAULT"
    finally:
        executor.close()
    resumed = host(mql_binary, native, directory, config)
    try:
        result = resumed.cycle()
        baseline = 0 if action == "OPEN" else 1
        assert result["operations"] == baseline + (crash == "after_result")
        assert result["unknown"] == (crash == "after_intent")
        with native.operator.connect() as c:
            states = c.scalars(select(ExecutionCommand.state)).all()
            account = c.scalar(select(TradingAccount.status))
            if crash == "after_intent":
                assert "RECONCILING" in states and account == "RECONCILING"
                if action != "OPEN":
                    assert c.scalar(select(Position.volume)) > 0
            else:
                assert set(states) == {"COMPLETED"}
                assert account == "READY"
        assert resumed.cycle()["operations"] == result["operations"]
    finally:
        resumed.close()


def test_native_ea_same_second_restart_waits_without_stale_snapshot(mql_binary, native, tmp_path):
    config = configuration(native)
    first = host(mql_binary, native, tmp_path / "terminal", config)
    try:
        native.emit_signal()
        assert first.cycle()["operations"] == 1
    finally:
        first.close()
    second = host(mql_binary, native, tmp_path / "terminal", config)
    try:
        assert second.cycle()["status"] == "NO_COMMAND"
        with native.operator.connect() as c:
            assert c.scalar(select(TradingAccount.status)) == "READY"
    finally:
        second.close()


@pytest.mark.parametrize("scenario", ["check_false", "check_rejected", "quote_changed_after_check"])
def test_broker_adapter_pre_send_rejection_releases_only_unsent_risk(
    mql_binary, native, tmp_path, scenario
):
    executor = host(
        mql_binary, native, tmp_path / "terminal", configuration(native), scenario=scenario
    )
    try:
        native.emit_signal()
        assert executor.cycle()["operations"] == 0
        with native.operator.connect() as c:
            assert c.scalar(select(ExecutionCommand.state)) == "REJECTED"
            assert c.scalar(select(RiskReservation.status)) == "RELEASED"
            assert c.scalar(select(Position.id)) is None
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
def test_broker_adapter_unknown_reply_retains_gateway_reservation_across_restart(
    mql_binary, native, tmp_path, scenario
):
    config = configuration(native)
    directory = tmp_path / "terminal"
    executor = host(mql_binary, native, directory, config, scenario=scenario)
    try:
        native.emit_signal()
        result = executor.cycle()
        assert result["unknown"] == 1 and result["operations"] == 0
        with native.operator.connect() as c:
            assert c.scalar(select(ExecutionCommand.state)) == "RECONCILING"
            assert c.scalar(select(RiskReservation.status)) == "OUTCOME_UNKNOWN"
            assert c.scalar(select(PaperCommandRecord.remaining_risk)) > 0
            assert c.scalar(select(TradingAccount.status)) == "RECONCILING"
            assert c.scalar(select(Position.id)) is None
    finally:
        executor.close()
    resumed = host(mql_binary, native, directory, config)
    try:
        assert resumed.cycle()["status"] == "RECONCILING"
        assert resumed.cycle()["broker_replies"] == 1
        with native.operator.connect() as c:
            assert c.scalar(select(RiskReservation.status)) == "OUTCOME_UNKNOWN"
    finally:
        resumed.close()


@pytest.mark.parametrize("action", ["MODIFY_STOPS", "CLOSE"])
def test_broker_adapter_position_timeout_keeps_original_position(
    mql_binary, native, tmp_path, action
):
    config = configuration(native)
    directory = tmp_path / "terminal"
    initial = host(mql_binary, native, directory, config)
    try:
        native.emit_signal()
        assert initial.cycle()["operations"] == 1
    finally:
        initial.close()
    with native.operator.connect() as c:
        position = c.scalar(select(Position.id))
        volume = c.scalar(select(Position.volume))
    extra = {"stop_loss": "1.09700", "take_profit": "1.11000"} if action == "MODIFY_STOPS" else {}
    native.operator_request(action, position, **extra)
    uncertain = host(mql_binary, native, directory, config, scenario="timeout")
    try:
        result = uncertain.cycle()
        assert result["operations"] == 1 and result["unknown"] == 1
        with native.operator.connect() as c:
            assert c.scalar(select(Position.volume)) == volume
            assert c.scalar(select(Position.status)) == "OUTCOME_UNKNOWN"
            assert c.scalar(select(PaperOperation.state)) == "UNKNOWN"
    finally:
        uncertain.close()


@pytest.mark.parametrize("scenario", ["timeout_with_evidence", "placed_with_evidence"])
def test_broker_adapter_durable_history_confirms_fill_despite_reply(
    mql_binary, native, tmp_path, scenario
):
    executor = host(
        mql_binary, native, tmp_path / "terminal", configuration(native), scenario=scenario
    )
    try:
        native.emit_signal()
        assert executor.cycle()["operations"] == 1
        assert executor.cycle()["operations"] == 1
        with native.operator.connect() as c:
            assert c.scalar(select(ExecutionCommand.state)) == "COMPLETED"
            assert c.scalar(select(RiskReservation.status)) == "CONSUMED"
            assert c.scalar(select(Position.volume)) > 0
    finally:
        executor.close()
