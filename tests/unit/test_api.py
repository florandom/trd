from uuid import UUID

from fastapi.testclient import TestClient

from backend.api.factory import create_app, create_bridge_app
from backend.domain.config import ApiSettings, BridgeSettings


def settings(identity="api"):
    cls = ApiSettings if identity == "api" else BridgeSettings
    return cls(
        app_env="test",
        environment_id="paper-test",
        database_url=f"postgresql+psycopg://trd_{identity}:hidden-canary@localhost:5432/trd",
    )


def test_liveness_is_independent_of_database_and_readiness_is_safe():
    def unavailable(_settings):
        raise RuntimeError("hidden-canary postgres host detail")

    app = create_app(settings(), unavailable)
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {
            "status": "alive",
            "service": "api",
            "phase": 1,
        }
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert set(response.json()) == {
        "status",
        "service",
        "phase",
        "mode",
        "automation_enabled",
        "checked_at",
    }
    assert "hidden-canary" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert UUID(response.headers["X-Trace-ID"])


def test_ready_dto_and_phase1_has_no_administrative_or_execution_routes():
    app = create_app(settings(), lambda _settings: True)
    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert response.json()["mode"] == "paper"
        assert response.json()["automation_enabled"] is False
        assert response.json()["checked_at"].endswith("Z")
        for route in ("/docs", "/openapi.json", "/admin", "/bridge/commands", "/orders"):
            assert client.get(route).status_code == 404
    assert set(app.openapi()["paths"]) == {"/health/live", "/health/ready"}


def test_bridge_has_separate_identity_and_liveness_only():
    app = create_bridge_app(settings("risk"), lambda _settings: True)
    with TestClient(app) as client:
        assert client.get("/health/live").json()["service"] == "risk"
        assert client.get("/health/ready").status_code == 404
        assert client.get("/commands").status_code == 404
    assert set(app.openapi()["paths"]) == {"/health/live"}


def test_lifespan_heartbeat_uses_only_its_identity():
    events = []

    def heartbeat(_settings, **event):
        events.append(event)

    app = create_app(settings(), lambda _settings: True, heartbeat)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
    assert events[0]["status"] == "STARTING"
    assert events[-1]["status"] == "STOPPED"
    assert all(event["service_name"] == "api" for event in events)


def test_unexpected_error_response_does_not_expose_driver_secrets():
    app = create_app(settings(), lambda _settings: True)

    @app.get("/test-failure")
    def failure():
        raise RuntimeError("postgresql+psycopg://trd_api:exception-canary@private-host:5432/trd")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test-failure", headers={"X-Trace-ID": "attacker-supplied"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal service error"}
    assert "exception-canary" not in response.text
    assert UUID(response.headers["X-Trace-ID"])
    assert response.headers["X-Trace-ID"] != "attacker-supplied"
