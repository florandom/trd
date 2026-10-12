"""Repeatable local HTTP paper run, using temporary keys and PostgreSQL only."""

import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from backend.api.factory import create_bridge_app
from backend.infrastructure.domain_models import ExecutionCommand, Order, RiskReservation
from backend.trading.simulator import PaperSimulator, SimulatedCrash
from infra.scripts.paper_database import disposable_database
from infra.scripts.paper_scenarios import LocalPaperScenario

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def loopback_bridge(scenario):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    app = create_bridge_app(scenario.settings, lambda _: True, engine=scenario.engines["trd_risk"])
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=listener.getsockname()[1],
            log_level="error",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("Local paper bridge did not start")
            time.sleep(0.02)
        else:
            raise RuntimeError("Local paper bridge startup timed out")
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("Local paper bridge did not stop")


def run_acceptance():
    old_migration = os.environ.get("MIGRATION_DATABASE_URL")
    try:
        with disposable_database() as values, TemporaryDirectory(prefix="trd-paper-") as temporary:
            os.environ["MIGRATION_DATABASE_URL"] = values["MIGRATION_DATABASE_URL"]
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
            urls = {
                "trd_migrator": values["MIGRATION_DATABASE_URL"],
                **{
                    f"trd_{role}": values[f"{role.upper()}_DATABASE_URL"]
                    for role in ("api", "collector", "ai", "risk", "maintenance")
                },
            }
            scenario = LocalPaperScenario(urls, Path(temporary))
            try:
                with loopback_bridge(scenario) as origin:
                    directory = Path(temporary) / "executor"
                    sim = PaperSimulator(
                        scenario.profile,
                        scenario.request_key,
                        scenario.response_key,
                        directory,
                        origin,
                    )
                    try:
                        scenario.emit_signal()
                        assert sim.cycle(scenario.snapshot()) == "DELIVERED"
                        assert sim.cycle(scenario.snapshot()) == "NO_COMMAND"
                        assert (
                            sim.broker.db.execute("SELECT count(*) FROM broker_orders").fetchone()[
                                0
                            ]
                            == 1
                        )
                        scenario.emit_signal()
                        try:
                            sim.cycle(scenario.snapshot(), crash="after_fill")
                        except SimulatedCrash:
                            pass
                        else:
                            raise RuntimeError("Restart scenario did not interrupt")
                    finally:
                        sim.close()
                    resumed = PaperSimulator(
                        scenario.profile,
                        scenario.request_key,
                        scenario.response_key,
                        directory,
                        origin,
                    )
                    try:
                        assert resumed.cycle(scenario.snapshot()) == "NO_COMMAND"
                        assert (
                            resumed.broker.db.execute(
                                "SELECT count(*) FROM broker_orders"
                            ).fetchone()[0]
                            == 2
                        )
                        with scenario.operator.connect() as c:
                            commands = c.scalars(select(ExecutionCommand.state)).all()
                            orders = c.scalars(select(Order.state)).all()
                            reservations = c.scalars(select(RiskReservation.status)).all()
                            assert commands == ["COMPLETED", "COMPLETED"]
                            assert orders == ["FILLED", "FILLED"]
                            assert reservations == ["CONSUMED", "CONSUMED"]
                        report = {
                            "mode": "paper",
                            "external_connections": False,
                            "real_orders": 0,
                            "simulated_orders": 2,
                            "duplicate_orders": 0,
                            "restart_reconciled": True,
                            "database_and_keys": "temporary",
                        }
                    finally:
                        resumed.close()
            finally:
                scenario.close()
        return report
    finally:
        if old_migration is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = old_migration


def main():
    try:
        print(json.dumps(run_acceptance(), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(f"Prova paper locale non completata ({type(error).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
