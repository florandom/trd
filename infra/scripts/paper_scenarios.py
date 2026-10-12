"""Explicit synthetic fixtures for a disposable local database only."""

import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import make_url

from backend.ai.providers import ProviderResponse
from backend.application.analysis import AnalysisWorker
from backend.application.bootstrap import BootstrapSettings, bootstrap
from backend.domain.analysis import STAGES, AgentResult, ProviderUsage, Reason
from backend.domain.bridge import PaperProfile, PaperSnapshot, json_bytes
from backend.domain.config import AiSettings, BridgeSettings
from backend.domain.contracts import AccountIdentity, AgentConfiguration
from backend.domain.risk_contracts import (
    FxInstrument,
    Quote,
    SessionCalendar,
    SessionWindow,
    SymbolMapping,
)
from backend.domain.telegram import TelegramObservation
from backend.infrastructure.analysis_repository import AnalysisStore
from backend.infrastructure.bridge_models import BridgeEnrollment
from backend.infrastructure.domain_models import Agent, AgentConfig, TelegramSource, TradingAccount
from backend.infrastructure.models import User
from backend.infrastructure.telegram_repository import TelegramStore


class SyntheticProposalProvider:
    """Acceptance fixture only. General-purpose mock still returns WAIT."""

    def generate(self, request):
        if request.model.provider != "mock":
            raise ValueError("synthetic provider cannot use external models")
        return ProviderResponse(
            AgentResult(schema_version=1, action="PROPOSE", reason_codes=(Reason.MOCK_ONLY,)),
            ProviderUsage(input_tokens=0, output_tokens=0),
        )


class LocalPaperScenario:
    def __init__(self, urls: dict, directory: Path, *, environment="test"):
        if not make_url(urls["trd_migrator"]).database.startswith(("paper_", "trd_test_")):
            raise ValueError("synthetic setup requires a disposable database")
        self.env, self.urls = environment, urls
        self.engines = {role: create_engine(url) for role, url in urls.items()}
        self.operator = self.engines["trd_migrator"]
        try:
            self._initialize(urls, directory, environment)
        except Exception:
            self.close()
            raise

    def _initialize(self, urls, directory, environment):
        self.operator_password = secrets.token_urlsafe(32)
        bootstrap(
            BootstrapSettings(
                migration_database_url=urls["trd_migrator"],
                environment_id=environment,
                admin_bootstrap_email="paper-operator@example.test",
                admin_bootstrap_password=self.operator_password,
            )
        )
        self.source_id, self.account_id = uuid4(), uuid4()
        self.identity = AccountIdentity(
            environment_id=environment, broker_server="TRD-PAPER-SIMULATOR", login="1", mode="paper"
        )
        reference = datetime(2026, 10, 12, tzinfo=UTC)
        instrument = FxInstrument(
            snapshot_id=uuid4(),
            observed_at=reference,
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
        self.profile = PaperProfile(
            account_id=self.account_id,
            account=self.identity,
            bridge_id="paper-local",
            instance_id="paper-executor",
            source_ids=(self.source_id,),
            instruments=(instrument,),
            mappings=(SymbolMapping(symbol="EURUSD", broker_symbol="EURUSD.paper"),),
            calendar=SessionCalendar(
                timezone="UTC",
                windows=tuple(
                    SessionWindow(weekday=d, start_minute=0, end_minute=1440) for d in range(7)
                ),
            ),
        )
        self.request_key, self.response_key = secrets.token_bytes(32), secrets.token_bytes(32)
        directory.mkdir(parents=True, exist_ok=True)
        self.profile_path = directory / "paper-profile.json"
        self.profile_path.write_bytes(json_bytes(self.profile))
        self.profile_path.chmod(0o600)
        with self.operator.begin() as connection:
            connection.execute(
                insert(TelegramSource).values(
                    environment_id=environment,
                    id=self.source_id,
                    name="SIMULAZIONE LOCALE",
                    collector_identity="paper-fixture",
                    peer_id="-1001",
                    reference="@paper_fixture",
                    enabled=True,
                    resolution_state="RESOLVED",
                    peer_kind="CHANNEL",
                    access_hash="1",
                )
            )
            connection.execute(
                insert(TradingAccount).values(
                    environment_id=environment,
                    id=self.account_id,
                    broker_server=self.identity.broker_server,
                    login="1",
                    mode="paper",
                    currency="USD",
                    status="RECONCILING",
                )
            )
            actor = connection.scalar(
                select(User.id).where(User.email == "paper-operator@example.test")
            )
            for agent in connection.execute(
                select(Agent).where(Agent.environment_id == environment, Agent.name.in_(STAGES))
            ).mappings():
                config = AgentConfiguration(
                    enabled=True, primary_model_id="mock-v1", prompt_version=2
                )
                connection.execute(
                    insert(AgentConfig).values(
                        environment_id=environment,
                        agent_id=agent["id"],
                        version=agent["current_version"] + 1,
                        created_by=actor,
                        **config.model_dump(exclude={"fallback_model_ids"}),
                    )
                )
                connection.execute(
                    update(Agent)
                    .where(Agent.environment_id == environment, Agent.id == agent["id"])
                    .values(current_version=agent["current_version"] + 1)
                )
            connection.execute(
                insert(BridgeEnrollment).values(
                    environment_id=environment,
                    account_id=self.account_id,
                    bridge_id=self.profile.bridge_id,
                    instance_id=self.profile.instance_id,
                    key_id=self.profile.key_id,
                    generation=1,
                    profile_hash=self.profile.digest,
                    request_key_hash=sha256(self.request_key).hexdigest(),
                    response_key_hash=sha256(self.response_key).hexdigest(),
                )
            )
        self.settings = BridgeSettings(
            app_env="test",
            environment_id=environment,
            database_url=urls["trd_risk"],
            paper_bridge_enabled=True,
            paper_profile_path=self.profile_path,
            paper_request_key=self.request_key.hex(),
            paper_response_key=self.response_key.hex(),
        )
        self.telegram = TelegramStore(self.engines["trd_collector"], environment)
        self.owner = self.telegram.acquire("1", "paper-synthetic-input")
        self.source = self.telegram.sources("paper-fixture")[0]
        self.worker = AnalysisWorker(
            AiSettings(app_env="test", environment_id=environment, database_url=urls["trd_ai"]),
            AnalysisStore(self.engines["trd_ai"], environment),
            SyntheticProposalProvider(),
        )
        self.message_sequence = 0

    def emit_signal(self):
        self.message_sequence += 1
        published = datetime.now(UTC) - timedelta(seconds=1)
        receipt = self.telegram.ingest(
            self.owner,
            self.source,
            TelegramObservation(
                message_id=self.message_sequence,
                kind="NEW",
                body="BUY EURUSD ENTRY 1.10000 SL 1.09500 TP 1.11000",
                published_at=published,
                observed_at=published,
            ),
        )
        if not self.worker.process_one():
            raise RuntimeError("synthetic analysis did not complete")
        return receipt

    def snapshot(self, *, equity="10000", bid="1.09990", ask="1.10000", positions=(), **updates):
        now = datetime.now(UTC)
        return PaperSnapshot(
            snapshot_id=uuid4(),
            account=self.identity,
            observed_at=now,
            currency="USD",
            equity=equity,
            free_margin="10000",
            broker_leverage="100",
            position_mode="hedging",
            history_complete=True,
            portfolio_complete=True,
            opening_equity="10000",
            net_cash_flow="0",
            positions=positions,
            quotes=(
                Quote(
                    snapshot_id=uuid4(),
                    observed_at=now,
                    symbol="EURUSD.paper",
                    bid=bid,
                    ask=ask,
                    market_open=True,
                ),
            ),
            instruments=tuple(
                i.model_copy(update={"snapshot_id": uuid4(), "observed_at": now})
                for i in self.profile.instruments
            ),
            **updates,
        )

    def close(self):
        if hasattr(self, "admin_client"):
            self.admin_client.close()
        for engine in self.engines.values():
            engine.dispose()

    def operator_request(self, action, position_id=None, **levels):
        """Use real session/CSRF/confirmation routes; never direct execution writes."""
        from fastapi.testclient import TestClient

        from backend.api.factory import create_app
        from backend.domain.config import ApiSettings
        from backend.infrastructure.position_models import PaperPositionState

        if not hasattr(self, "admin_client"):
            self.admin_client = TestClient(
                create_app(
                    ApiSettings(
                        app_env="test",
                        environment_id=self.env,
                        database_url=self.urls["trd_api"],
                        auth_cookie_secure=False,
                    ),
                    lambda _: True,
                    engine=self.engines["trd_api"],
                )
            )
            csrf = self.admin_client.get("/auth/csrf").json()["csrf_token"]
            response = self.admin_client.post(
                "/auth/login",
                json={"email": "paper-operator@example.test", "password": self.operator_password},
                headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
            )
            if response.status_code != 200:
                raise RuntimeError("local operator login failed")
        with self.operator.connect() as c:
            version = (
                c.scalar(
                    select(TradingAccount.safety_epoch).where(TradingAccount.id == self.account_id)
                )
                if action == "RESUME"
                else c.scalar(
                    select(PaperPositionState.revision).where(
                        PaperPositionState.position_id == position_id
                    )
                )
            )
        value = {
            "action": action,
            "stop_loss": levels.get("stop_loss"),
            "take_profit": levels.get("take_profit"),
        }
        change = {
            "kind": "paper_resume" if action == "RESUME" else "paper_position",
            "target": str(self.account_id if action == "RESUME" else position_id),
            "expected_version": version,
            "value": value,
        }
        headers = {
            "Origin": "http://localhost:3000",
            "X-CSRF-Token": self.admin_client.get("/auth/me").json()["csrf_token"],
        }
        response = self.admin_client.post("/config/confirm", json=change, headers=headers)
        if response.status_code != 200:
            raise RuntimeError("local operator confirmation failed")
        response = self.admin_client.post(
            "/config/apply",
            json={
                "change": response.json()["change"],
                "confirmation_token": response.json()["confirmation_token"],
            },
            headers=headers,
        )
        if response.status_code != 200:
            raise RuntimeError("local operator request failed")
        return response
