"""Native EA source in a portable platform harness against the real local gateway."""

import json
import os
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import select, update

from backend.infrastructure.domain_models import (
    ExecutionCommand,
    Position,
    PositionEvent,
    TradingAccount,
)
from infra.scripts.mt5_lab import MqlLabProcess, compile_lab, lab_config
from infra.scripts.paper_acceptance import loopback_bridge
from infra.scripts.paper_database import disposable_database
from infra.scripts.paper_scenarios import LocalPaperScenario

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def native_lab():
    previous = os.environ.get("MIGRATION_DATABASE_URL")
    try:
        with disposable_database() as values, TemporaryDirectory(prefix="trd-mt5-") as temporary:
            os.environ["MIGRATION_DATABASE_URL"] = values["MIGRATION_DATABASE_URL"]
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
            urls = {
                "trd_migrator": values["MIGRATION_DATABASE_URL"],
                **{
                    f"trd_{role}": values[f"{role.upper()}_DATABASE_URL"]
                    for role in ("api", "collector", "ai", "risk", "maintenance")
                },
            }
            scenario = LocalPaperScenario(
                urls, Path(temporary), environment="test-mt5-" + uuid4().hex[:8]
            )
            try:
                with loopback_bridge(scenario) as origin:
                    config = lab_config(
                        scenario.profile,
                        scenario.snapshot(),
                        scenario.request_key,
                        scenario.response_key,
                        origin,
                        uuid4(),
                    )
                    yield scenario, config, Path(temporary)
            finally:
                scenario.close()
    finally:
        if previous is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = previous


def run_acceptance():
    with native_lab() as (scenario, config, temporary):
        binary = compile_lab(temporary / "build")
        directory = temporary / "terminal"
        host = MqlLabProcess(binary, directory, config)
        try:
            assert host.initial["initialized"] == 0
            scenario.emit_signal()
            assert host.cycle()["operations"] == 1
            assert host.cycle()["operations"] == 1
        finally:
            host.close()
        crashed = MqlLabProcess(binary, directory, config, crash="after_result")
        try:
            scenario.emit_signal()
            assert crashed.cycle()["fault"] == "LAB_CRASH_AFTER_RESULT"
        finally:
            crashed.close()
        resumed = MqlLabProcess(binary, directory, config)
        try:
            assert resumed.cycle()["operations"] == 2
            with scenario.operator.connect() as connection:
                assert connection.scalars(select(ExecutionCommand.state)).all() == [
                    "COMPLETED",
                    "COMPLETED",
                ]
                positions = connection.scalars(
                    select(Position.id).order_by(Position.opened_at)
                ).all()
            scenario.operator_request(
                "MODIFY_STOPS", positions[0], stop_loss="1.09700", take_profit="1.11000"
            )
            assert resumed.cycle()["operations"] == 3
            scenario.operator_request("CLOSE", positions[0])
            assert resumed.cycle()["operations"] == 4
            with scenario.operator.begin() as connection:
                connection.execute(update(TradingAccount).values(status="PAUSED"))
            scenario.operator_request("CLOSE", positions[1])
            result = resumed.cycle()
            assert result["operations"] == 5 and result["positions"] == 0
            scenario.operator_request("RESUME")
            assert resumed.cycle()["status"] == "RESUMED"
            with scenario.operator.connect() as connection:
                net = sum(connection.scalars(select(PositionEvent.realized_pnl)).all())
                assert net == Decimal(result["realized_pnl"])
            return {
                "mode": "paper",
                "executor": "MQL5 source with portable platform shim",
                "external_connections": False,
                "real_orders": 0,
                "simulated_openings": 2,
                "stop_updates": 1,
                "full_closes": 2,
                "duplicate_operations": 0,
                "restart_reconciled": True,
                "close_while_paused": True,
                "controlled_resume": True,
                "realized_pnl_usd": str(net),
                "native_metaeditor_compilation": "still required",
                "database_and_keys": "temporary",
            }
        finally:
            resumed.close()


def main():
    try:
        print(json.dumps(run_acceptance(), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(f"Prova bridge MT5 locale non completata ({type(error).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
