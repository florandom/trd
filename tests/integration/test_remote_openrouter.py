"""Actual scoped PostgreSQL roles, synthetic Access identity and offline provider wire."""

from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select

from backend.ai.acceptance import OpenRouterAcceptance
from backend.ai.openrouter import OpenRouterProvider, exact_json
from backend.api.factory import create_app
from backend.application.analysis import AnalysisWorker
from backend.application.bootstrap import bootstrap
from backend.domain.analysis import STAGES
from backend.domain.config import AiSettings, ApiSettings
from backend.infrastructure.domain_models import (
    AgentRun,
    AIBudgetReservation,
    AIUsage,
    ExecutionCommand,
)
from backend.infrastructure.models import User
from infra.scripts.openrouter_operator import import_models
from tests.access_fixtures import ORIGIN, PROXY_SECRET, assertion, keypair
from tests.access_fixtures import settings as remote_settings
from tests.integration.test_analysis import analysis as analysis
from tests.integration.test_analysis import enable, ingest, rows
from tests.integration.test_telegram import collection as collection
from tests.openrouter_fixtures import KEY, model, response
from tests.unit.test_access import verifier

pytestmark = pytest.mark.integration


def test_remote_sessions_bind_human_subject_email_and_original_environment(isolated_database):
    db = isolated_database
    bootstrap(db.settings())
    key = keypair()
    settings = remote_settings(environment_id="test", database_url=db.urls["trd_api"])
    engine = create_engine(db.urls["trd_api"])
    headers = {
        "X-TRD-Proxy-Key": PROXY_SECRET,
        "X-TRD-Environment": "test",
        "X-TRD-User-Assertion": assertion(key),
        "Origin": ORIGIN,
    }
    try:
        with TestClient(
            create_app(settings, lambda _: True, engine=engine, access_verifier=verifier(key)),
            base_url=ORIGIN,
            headers=headers,
        ) as client:
            csrf = client.get("/auth/csrf").json()["csrf_token"]
            login = client.post(
                "/auth/login",
                json={
                    "email": "admin@example.test",
                    "password": "test-only-password-please-change",
                },
                headers={"X-CSRF-Token": csrf},
            )
            assert login.status_code == 200
            cookie = client.cookies.get("trd_session")
            assert "Secure" in login.headers["set-cookie"]
            assert client.get("/auth/me").status_code == 200
            for claims in (
                {"sub": "other-user"},
                {"email": "other@example.test"},
                {"amr": ["pwd"]},
            ):
                assert (
                    client.get(
                        "/auth/me",
                        headers={"X-TRD-User-Assertion": assertion(key, overrides=claims)},
                    ).status_code
                    == 401
                )
            payload = {
                "kind": "settings",
                "target": "telegram_retention_days",
                "value": 14,
                "expected_version": 1,
            }
            user_csrf = client.get("/auth/me").json()["csrf_token"]
            denied = client.post(
                "/config/confirm",
                json=payload,
                headers={"X-CSRF-Token": user_csrf, "X-TRD-Environment": "staging-other"},
            )
            assert denied.status_code == 409
            assert client.get("/auth/me").status_code == 200
        local = ApiSettings(
            app_env="test",
            environment_id="test",
            database_url=db.urls["trd_api"],
            auth_cookie_secure=False,
        )
        with TestClient(create_app(local, lambda _: True, engine=engine)) as client:
            assert (
                client.get("/auth/me", headers={"Cookie": "trd_session=" + cookie}).status_code
                == 401
            )
    finally:
        engine.dispose()


def accepted(db, tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from hashlib import sha256

    profile = model(max_output_tokens=1024)
    receipt = OpenRouterAcceptance(
        schema_version=1,
        contract_version="openrouter-advisory-v1",
        environment_id="test",
        manifest_sha256="a" * 64,
        credential_sha256=sha256(("openrouter:" + KEY).encode()).hexdigest(),
        accepted_at=datetime.now(UTC),
        expires_at=profile.accepted_until,
        models=(profile,),
        checks="catalog-schema-routing-usage-cost-synthetic-wait",
    )
    monkeypatch.setenv("ENVIRONMENT_ID", "test")
    import_models(receipt, db.urls["trd_migrator"], "admin@example.test")
    import_models(receipt, db.urls["trd_migrator"], "admin@example.test")
    path = tmp_path / "acceptance.json"
    path.write_text(receipt.model_dump_json())
    return profile, AiSettings(
        app_env="test",
        environment_id="test",
        database_url=db.urls["trd_ai"],
        ai_provider_mode="openrouter",
        openrouter_api_key=KEY,
        openrouter_acceptance_path=path,
        ai_hard_daily_budget_usd="1",
        ai_hard_monthly_budget_usd="1",
        ai_hard_daily_budget_per_agent_usd="1",
        ai_hard_max_cost_per_request_usd="0.05",
    )


def test_approved_openrouter_spend_is_reserved_settled_and_never_authorizes_orders(
    analysis, tmp_path, monkeypatch
):
    db, _, _, _, store, _ = analysis
    profile, settings = accepted(db, tmp_path, monkeypatch)
    enable(db, names=STAGES[2:], model=profile.id, max_cost="0.05")
    calls = []
    provider = OpenRouterProvider(
        SecretStr(KEY),
        {profile.id: profile},
        transport=httpx.MockTransport(
            lambda call: calls.append(call) or httpx.Response(200, content=exact_json(response()))
        ),
    )
    worker = AnalysisWorker(settings, store, provider=provider)
    ingest(analysis)
    assert worker.process_one() and len(calls) == 2
    assert all(r["reported_cost_usd"] == Decimal("0.0000200000") for r in rows(db, AIUsage))
    assert all(
        r["charged_usd"] == Decimal("0.0000200000")
        and r["state"] == "SETTLED"
        and r["input_token_ceiling"] == profile.input_token_limit
        for r in rows(db, AIBudgetReservation)
    )
    assert all(r["result"]["provider_name"] == "Fixture" for r in rows(db, AgentRun))
    assert not rows(db, ExecutionCommand)


@pytest.mark.parametrize(
    "usage,cost",
    [
        (None, Decimal("0.006144")),
        (
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": "0.1"},
            Decimal("0.1"),
        ),
    ],
)
def test_unknown_or_excess_cost_holds_budget_and_stops_fallback(
    analysis, tmp_path, monkeypatch, usage, cost
):
    db, _, _, _, store, _ = analysis
    profile, settings = accepted(db, tmp_path, monkeypatch)
    enable(db, names=STAGES[2:], model=profile.id, max_cost="0.05", fallbacks=("mock-v1",))
    calls = []
    provider = OpenRouterProvider(
        SecretStr(KEY),
        {profile.id: profile},
        transport=httpx.MockTransport(
            lambda call: (
                calls.append(call) or httpx.Response(200, content=exact_json(response(usage=usage)))
            )
        ),
    )
    worker = AnalysisWorker(settings, store, provider=provider)
    ingest(analysis)
    assert worker.process_one() and len(calls) == 1
    (reservation,) = rows(db, AIBudgetReservation)
    assert reservation["state"] == "UNKNOWN" and reservation["reserved_usd"] == cost
    assert not rows(db, ExecutionCommand)


def test_registry_import_requires_environment_admin_and_preserves_immutable_profiles(
    analysis, tmp_path, monkeypatch
):
    db, *_ = analysis
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(User.role)) == "ADMIN"
    profile, _ = accepted(db, tmp_path, monkeypatch)
    from sqlalchemy import update

    from backend.infrastructure.domain_models import ModelRegistry

    with db.migration_engine.begin() as connection:
        connection.execute(
            update(ModelRegistry).where(ModelRegistry.id == profile.id).values(enabled=False)
        )
    # Re-import cannot silently change a reviewed/disabled profile.
    with pytest.raises(ValueError):
        accepted(db, tmp_path, monkeypatch)
