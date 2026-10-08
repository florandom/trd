"""Phase 3 authorization uses the actual PostgreSQL role and schema."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, text

from backend.api.factory import create_app
from backend.application.bootstrap import bootstrap
from backend.application.dashboard import HASHER, token_hash
from backend.domain.config import ApiSettings
from backend.infrastructure.database import create_database_engine
from backend.infrastructure.models import User

pytestmark = pytest.mark.integration
PASSWORD = "test-only-password-please-change"
ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture
def dashboard(isolated_database):
    db = isolated_database
    bootstrap(db.settings())
    engine = create_database_engine(db.urls["trd_api"])
    settings = ApiSettings(
        app_env="test",
        environment_id="test",
        database_url=db.urls["trd_api"],
        auth_cookie_secure=False,
    )
    with TestClient(create_app(settings, lambda _: True, engine=engine)) as client:
        yield client, db
    engine.dispose()


def login(client, email="admin@example.test", password=PASSWORD):
    challenge = client.get("/auth/csrf")
    csrf = challenge.json()["csrf_token"]
    return client.post(
        "/auth/login",
        json={"email": email, "password": password},
        headers={**ORIGIN, "X-CSRF-Token": csrf},
    )


def auth_headers(client):
    return {**ORIGIN, "X-CSRF-Token": client.get("/auth/me").json()["csrf_token"]}


def change(value=14, version=1):
    return {
        "kind": "settings",
        "target": "telegram_retention_days",
        "expected_version": version,
        "value": value,
    }


def test_login_cookie_hashed_session_reads_logout(dashboard):
    client, db = dashboard
    assert client.get("/ops/agents").status_code == 401
    response = login(client)
    assert response.status_code == 200
    assert response.json()["role"] == "ADMIN"
    assert (
        "HttpOnly" in response.headers["set-cookie"]
        and "SameSite=lax" in response.headers["set-cookie"]
    )
    token = client.cookies.get("trd_session")
    with db.migration_engine.connect() as connection:
        assert connection.scalar(text("SELECT token_hash FROM public.sessions")) == token_hash(
            token
        )
    for collection in (
        "agents",
        "risk",
        "settings",
        "models",
        "status",
        "audit",
        "positions",
        "signals",
        "orders",
        "sources",
        "costs",
    ):
        response = client.get("/ops/" + collection)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
    assert len(client.get("/ops/agents").json()["rows"]) == 6
    assert client.get("/ops/positions").json()["rows"] == []
    headers = auth_headers(client)
    assert client.post("/auth/logout", headers=headers).status_code == 204
    client.cookies.set("trd_session", token)
    assert client.get("/auth/me").status_code == 401


def test_login_csrf_origin_generic_errors(dashboard):
    client, _db = dashboard
    body = {"email": "admin@example.test", "password": PASSWORD}
    assert client.post("/auth/login", json=body, headers=ORIGIN).status_code == 403
    challenge = client.get("/auth/csrf").json()["csrf_token"]
    assert (
        client.post(
            "/auth/login",
            json=body,
            headers={"Origin": "https://evil.test", "X-CSRF-Token": challenge},
        ).status_code
        == 403
    )
    assert login(client, password="incorrect").json() == {"detail": "INVALID_CREDENTIALS"}
    assert login(client, email="absent@example.test").json() == {"detail": "INVALID_CREDENTIALS"}
    response = client.post("/auth/login", json={"email": "bad", "password": "password-canary"})
    assert response.status_code == 422 and "password-canary" not in response.text


def test_viewer_and_inactive_user_cannot_mutate(dashboard):
    client, db = dashboard
    with db.migration_engine.begin() as connection:
        connection.execute(
            insert(User).values(
                id=uuid4(),
                email="viewer@example.test",
                password_hash=HASHER.hash(PASSWORD),
                role="VIEWER",
            )
        )
    assert login(client, email="viewer@example.test").status_code == 200
    headers = auth_headers(client)
    assert client.get("/ops/settings").status_code == 200
    assert client.post("/config/confirm", json=change(), headers=headers).status_code == 403
    assert client.post("/trading/enable", headers=headers).status_code == 403
    with db.migration_engine.begin() as connection:
        connection.execute(text("UPDATE public.users SET active=false WHERE role='VIEWER'"))
    assert client.get("/auth/me").status_code == 401


@pytest.mark.parametrize("expired", ["absolute", "idle", "revoked"])
def test_session_expiry_fail_closed(dashboard, expired):
    client, db = dashboard
    assert login(client).status_code == 200
    sql = {
        "absolute": "expires_at=clock_timestamp()-interval '1 second',"
        "created_at=clock_timestamp()-interval '1 day'",
        "idle": "last_seen_at=clock_timestamp()-interval '31 minutes'",
        "revoked": "revoked_at=clock_timestamp()",
    }[expired]
    with db.migration_engine.begin() as connection:
        connection.execute(text("UPDATE public.sessions SET " + sql))
    assert client.get("/auth/me").status_code == 401


def test_confirmation_payload_session_expiry_replay_and_conflict(dashboard):
    client, db = dashboard
    assert login(client).status_code == 200
    headers = auth_headers(client)
    assert client.post("/config/confirm", json=change(), headers=ORIGIN).status_code == 403
    confirmation = client.post("/config/confirm", json=change(), headers=headers).json()
    body = {"change": change(15), "confirmation_token": confirmation["confirmation_token"]}
    assert client.post("/config/apply", json=body, headers=headers).status_code == 422
    body["change"] = change()
    assert client.post("/config/apply", json=body, headers=headers).json() == {"version": 2}
    assert client.post("/config/apply", json=body, headers=headers).status_code == 422
    stale = client.post("/config/confirm", json=change(16), headers=headers).json()
    assert (
        client.post(
            "/config/apply",
            json={"change": change(16), "confirmation_token": stale["confirmation_token"]},
            headers=headers,
        ).status_code
        == 409
    )
    expired = client.post("/config/confirm", json=change(17, 2), headers=headers).json()
    with db.migration_engine.begin() as connection:
        connection.execute(
            text("UPDATE public.dashboard_confirmations SET expires_at=now()-interval '1 second'")
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM public.audit_events WHERE action='SETTING_REVISED'")
            )
            == 1
        )
    assert (
        client.post(
            "/config/apply",
            json={"change": change(17, 2), "confirmation_token": expired["confirmation_token"]},
            headers=headers,
        ).status_code
        == 422
    )


def test_risk_agent_validation_and_atomic_publication(dashboard):
    client, _db = dashboard
    assert login(client).status_code == 200
    headers = auth_headers(client)
    row = client.get("/ops/risk").json()["rows"][0]
    payload = {
        "kind": "risk",
        "target": "baseline",
        "expected_version": row["current_version"],
        "value": row["policy"],
    }
    payload["value"]["max_risk_per_trade"] = "0.004"
    confirmation = client.post("/config/confirm", json=payload, headers=headers)
    assert confirmation.status_code == 200, confirmation.text
    result = client.post(
        "/config/apply",
        json={"change": payload, "confirmation_token": confirmation.json()["confirmation_token"]},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    payload["value"]["max_risk_per_trade"] = "0.005"
    assert client.post("/config/confirm", json=payload, headers=headers).status_code == 422
    row = client.get("/ops/agents").json()["rows"][0]
    value = {
        k: row[k]
        for k in (
            "enabled",
            "primary_model_id",
            "prompt_version",
            "timeout_seconds",
            "max_output_tokens",
            "max_cost_usd",
            "required_schema_version",
            "fallback_model_ids",
        )
    }
    value["timeout_seconds"] = 20
    payload = {
        "kind": "agent",
        "target": row["id"],
        "expected_version": row["current_version"],
        "value": value,
    }
    confirmation = client.post("/config/confirm", json=payload, headers=headers).json()
    result = client.post(
        "/config/apply",
        json={"change": payload, "confirmation_token": confirmation["confirmation_token"]},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    value["enabled"] = True
    assert client.post("/config/confirm", json=payload, headers=headers).status_code == 422
    assert client.post("/trading/enable", headers=headers).status_code == 409


def test_throttle_persists_across_app_instances(dashboard):
    client, _db = dashboard
    for _ in range(5):
        assert login(client, password="incorrect").status_code == 401
    response = login(client, password="incorrect")
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_confirmation_is_bound_to_session_and_expected_payload(dashboard):
    client, _db = dashboard
    assert login(client).status_code == 200
    first_headers = auth_headers(client)
    confirmation = client.post("/config/confirm", json=change(), headers=first_headers).json()
    with TestClient(client.app) as other:
        assert login(other).status_code == 200
        body = {"change": change(), "confirmation_token": confirmation["confirmation_token"]}
        assert (
            other.post("/config/apply", json=body, headers=auth_headers(other)).status_code == 422
        )
    assert client.post("/config/apply", json=body, headers=first_headers).status_code == 200


def test_secure_cookies_and_oversized_requests(dashboard):
    client, db = dashboard
    body = '{"password":"' + "x" * 17000 + '"}'
    response = client.post(
        "/auth/login", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413 and "xxx" not in response.text
    engine = create_database_engine(db.urls["trd_api"])
    settings = ApiSettings(
        app_env="test",
        environment_id="test",
        database_url=db.urls["trd_api"],
        app_url="https://localhost:3000",
        auth_cookie_secure=True,
    )
    try:
        with TestClient(
            create_app(settings, lambda _: True, engine=engine), base_url="https://localhost:3000"
        ) as secure_client:
            challenge = secure_client.get("/auth/csrf")
            assert "Secure" in challenge.headers["set-cookie"]
            response = secure_client.post(
                "/auth/login",
                json={"email": "admin@example.test", "password": PASSWORD},
                headers={
                    "Origin": "https://localhost:3000",
                    "X-CSRF-Token": challenge.json()["csrf_token"],
                },
            )
            assert response.status_code == 200 and "Secure" in response.headers["set-cookie"]
    finally:
        engine.dispose()


def test_operator_user_creation_never_overwrites_existing_user(dashboard):
    from backend.application.users import create_user

    client, db = dashboard
    settings = db.settings().model_copy(update={"admin_bootstrap_email": "reader@example.test"})
    create_user(settings, "VIEWER")
    with pytest.raises(ValueError):
        create_user(settings, "ADMIN")
    assert login(client, email="reader@example.test").json()["role"] == "VIEWER"


def test_api_role_cannot_create_trade_authority_or_change_risk_without_confirmation(dashboard):
    from sqlalchemy.exc import DBAPIError

    client, db = dashboard
    engine = create_database_engine(db.urls["trd_api"])
    try:
        for statement in (
            "SELECT * FROM public.risk_approvals",
            "SELECT * FROM public.users",
            "UPDATE public.risk_rule_heads SET current_version=2",
            "SELECT public.apply_dashboard_change('test','fake','fake','{}',1800)",
        ):
            with engine.begin() as connection, pytest.raises(DBAPIError) as error:
                connection.execute(text(statement))
            assert error.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()


def test_pagination_scope_does_not_expose_other_environment(dashboard):
    client, db = dashboard
    assert login(client).status_code == 200
    with db.migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO public.audit_events "
                "(id,environment_id,action,actor_service,target,details) "
                "VALUES(gen_random_uuid(),'other','PRIVATE_EVENT','operator','private','{}')"
            )
        )
    response = client.get("/ops/audit?limit=1")
    assert response.status_code == 200 and response.json()["has_more"]
    assert len(response.json()["rows"]) == 1 and "PRIVATE_EVENT" not in response.text
    assert "PRIVATE_EVENT" not in client.get("/ops/audit").text
    assert client.get("/ops/audit?limit=10000").status_code == 422


def test_risk_fingerprint_matches_domain_contract(dashboard):
    from backend.domain.contracts import RiskPolicy, fingerprint

    client, _db = dashboard
    assert login(client).status_code == 200
    headers = auth_headers(client)
    policy = client.get("/ops/risk").json()["rows"][0]["policy"]
    policy["max_risk_per_trade"] = "0.004"
    payload = {"kind": "risk", "target": "baseline", "expected_version": 1, "value": policy}
    confirmation = client.post("/config/confirm", json=payload, headers=headers).json()
    assert (
        client.post(
            "/config/apply",
            json={"change": payload, "confirmation_token": confirmation["confirmation_token"]},
            headers=headers,
        ).status_code
        == 200
    )
    row = client.get("/ops/risk").json()["rows"][0]
    assert row["fingerprint"] == fingerprint(RiskPolicy.model_validate(row["policy"]))


def test_auth_cleanup_is_bounded_and_preserves_active_sessions(dashboard):
    from backend.infrastructure.repositories import DomainTransaction

    client, db = dashboard
    assert login(client).status_code == 200
    client.get("/auth/csrf")
    with db.migration_engine.begin() as connection:
        connection.execute(
            text("UPDATE public.auth_challenges SET expires_at=now()-interval '2 days'")
        )
    engine = create_database_engine(db.urls["trd_maintenance"])
    try:
        with DomainTransaction(engine, "test") as uow:
            result = uow.retention.prune_auth(limit=1)
        assert result["challenge_count"] == 1 and result["session_count"] == 0
        assert client.get("/auth/me").status_code == 200
    finally:
        engine.dispose()


def test_shared_throttle_reservation_is_atomic(dashboard):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi import HTTPException

    from backend.application.dashboard import DashboardService

    _client, db = dashboard
    engine = create_database_engine(db.urls["trd_api"])
    settings = ApiSettings(app_env="test", environment_id="test", database_url=db.urls["trd_api"])
    services = [DashboardService(settings, engine), DashboardService(settings, engine)]

    def attempt(index):
        try:
            services[index % 2].throttle([("concurrency-account", 5)])
            return True
        except HTTPException as error:
            assert error.status_code == 429
            return False

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            assert sum(executor.map(attempt, range(12))) == 5
    finally:
        engine.dispose()


def test_risk_change_refuses_existing_exposure_without_consuming_confirmation(dashboard):
    from backend.infrastructure.domain_models import TelegramSource
    from tests.integration.test_domain_persistence import create_signal, raw_message, trading_chain

    client, db = dashboard
    source = uuid4()
    with db.migration_engine.begin() as connection:
        connection.execute(
            insert(TelegramSource).values(
                environment_id="test",
                id=source,
                collector_identity="fixture",
                peer_id="-123",
                name="Fixture source",
            )
        )
    signal = create_signal(db, raw_message(db, source))
    trading_chain(db, signal, open_position=True)
    assert login(client).status_code == 200
    headers = auth_headers(client)
    policy = client.get("/ops/risk").json()["rows"][0]["policy"]
    policy["max_risk_per_trade"] = "0.004"
    change = {"kind": "risk", "target": "baseline", "expected_version": 1, "value": policy}
    confirmation = client.post("/config/confirm", json=change, headers=headers).json()
    response = client.post(
        "/config/apply",
        json={"change": change, "confirmation_token": confirmation["confirmation_token"]},
        headers=headers,
    )
    assert response.status_code == 422
    with db.migration_engine.connect() as connection:
        assert connection.scalar(text("SELECT current_version FROM public.risk_rule_heads")) == 1
        assert (
            connection.scalar(text("SELECT consumed_at FROM public.dashboard_confirmations"))
            is None
        )


def test_password_verification_saturation_returns_bounded_retry(dashboard, monkeypatch):
    from backend.application import dashboard as application

    class Saturated:
        def acquire(self, timeout):
            assert timeout == 1
            return False

    client, _db = dashboard
    monkeypatch.setattr(application, "PASSWORD_SLOTS", Saturated())
    response = login(client)
    assert response.status_code == 429 and response.headers["Retry-After"] == "1"
    assert client.get("/auth/me").status_code == 401
