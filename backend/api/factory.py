"""HTTP composition for the authenticated dashboard and isolated bridge foundation."""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hmac import compare_digest
from uuid import uuid4

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from backend.api.body_limit import BodyLimit
from backend.api.dashboard import dashboard_router
from backend.api.schemas import HealthLiveness, HealthReadiness
from backend.application.dashboard import DashboardService
from backend.application.runtime import HeartbeatHook, HeartbeatRuntime, Probe
from backend.domain.config import ApiSettings, BridgeSettings
from backend.infrastructure.access import AccessRejected, AccessVerifier


def _lifespan(
    settings: ApiSettings | BridgeSettings, probe: Probe, heartbeat: HeartbeatHook | None
):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        stop = threading.Event()
        runtime = HeartbeatRuntime(settings, probe, heartbeat) if heartbeat else None
        task = asyncio.create_task(asyncio.to_thread(runtime.run, stop)) if runtime else None
        try:
            yield
        finally:
            stop.set()
            if task:
                await task

    return lifespan


def create_app(
    settings: ApiSettings,
    probe: Probe,
    heartbeat: HeartbeatHook | None = None,
    *,
    engine: Engine | None = None,
    access_verifier: AccessVerifier | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Trading orchestration foundation",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan(settings, probe, heartbeat),
    )

    app.add_middleware(BodyLimit)
    app.include_router(dashboard_router(DashboardService(settings, engine)))
    verifier = access_verifier or AccessVerifier(settings)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_request, _error):
        # Never echo submitted passwords, tokens or configuration source data.
        return JSONResponse(status_code=422, content={"detail": "INVALID_REQUEST"})

    @app.middleware("http")
    async def security_headers(request, call_next):
        # Generate our own ID. Untrusted headers cannot inject log fields or
        # impersonate a trace belonging to another request.
        request.state.trace_id = str(uuid4())
        if settings.remote_access_mode == "cloudflare" and request.url.path != "/health/live":
            supplied = request.headers.get("X-TRD-Proxy-Key", "")
            expected = settings.dashboard_proxy_secret.get_secret_value()
            if not compare_digest(supplied.encode(), expected.encode()):
                response = JSONResponse(
                    status_code=401, content={"detail": "REMOTE_ACCESS_REQUIRED"}
                )
            elif request.headers.get("X-TRD-Environment") != settings.environment_id:
                response = JSONResponse(status_code=409, content={"detail": "ENVIRONMENT_MISMATCH"})
            else:
                try:
                    request.state.access_identity = await asyncio.to_thread(
                        verifier.verify, request.headers.get("X-TRD-User-Assertion")
                    )
                except AccessRejected:
                    response = JSONResponse(
                        status_code=401, content={"detail": "REMOTE_ACCESS_REQUIRED"}
                    )
                else:
                    response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Trace-ID"] = request.state.trace_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-TRD-Environment"] = settings.environment_id
        return response

    @app.get("/health/live", response_model=HealthLiveness, operation_id="health_live")
    def live() -> HealthLiveness:
        return HealthLiveness(service="api")

    @app.get(
        "/health/ready",
        response_model=HealthReadiness,
        operation_id="health_ready",
        responses={503: {"model": HealthReadiness}},
    )
    def ready(response: Response) -> HealthReadiness:
        try:
            is_ready = probe(settings)
        except Exception as exc:
            is_ready = False
            logging.getLogger("trd.api").warning(
                "Database readiness unavailable", extra={"error_type": type(exc).__name__}
            )
        if not is_ready:
            response.status_code = 503
        return HealthReadiness(
            status="ready" if is_ready else "not_ready", checked_at=datetime.now(UTC)
        )

    @app.exception_handler(Exception)
    async def safe_error(request, exc: Exception):
        trace_id = getattr(request.state, "trace_id", str(uuid4()))
        logging.getLogger("trd.api").error(
            "HTTP request failed", extra={"error_type": type(exc).__name__, "trace_id": trace_id}
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal service error"},
            headers={"Cache-Control": "no-store", "X-Trace-ID": trace_id},
        )

    return app


def create_bridge_app(
    settings: BridgeSettings, probe: Probe, heartbeat: HeartbeatHook | None = None
) -> FastAPI:
    app = FastAPI(
        title="Isolated bridge foundation",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan(settings, probe, heartbeat),
    )

    @app.get("/health/live", response_model=HealthLiveness, operation_id="bridge_health_live")
    def live(response: Response) -> HealthLiveness:
        response.headers["Cache-Control"] = "no-store"
        return HealthLiveness(service="risk")

    return app
