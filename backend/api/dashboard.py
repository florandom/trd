"""Dashboard routes: all data requires a live session; mutations require ADMIN and CSRF."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, field_validator

from backend.application.dashboard import COOKIE, LOGIN_COOKIE, DashboardService


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LoginInput(Input):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s\x00]+@[^\s\x00]+$")
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("email", mode="before")
    @classmethod
    def normalized(cls, value):
        return value.strip().casefold() if isinstance(value, str) else value


class SessionUser(BaseModel):
    id: UUID
    email: str
    role: Literal["ADMIN", "VIEWER"]
    csrf_token: str
    expires_at: datetime | None = None
    idle_expires_at: datetime | None = None


class Challenge(BaseModel):
    csrf_token: str


class OperationalRows(BaseModel):
    rows: list[dict[str, JsonValue | datetime | UUID]]
    has_more: bool
    offset: int
    checked_at: datetime
    environment_id: str


class Change(Input):
    kind: Literal["settings", "risk", "agent"]
    target: str = Field(min_length=1, max_length=96)
    expected_version: int = Field(strict=True, ge=1)
    value: JsonValue


class Confirmation(BaseModel):
    confirmation_token: str
    expires_at: datetime
    change: Change
    digest: str


class Apply(Input):
    change: Change
    confirmation_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class Applied(BaseModel):
    version: int


def dashboard_router(service: DashboardService) -> APIRouter:
    router = APIRouter()

    def raw(request: Request):
        return request.cookies.get(COOKIE)

    def authenticated(request: Request) -> dict:
        return service.authenticate(raw(request))

    def administrator(request: Request) -> dict:
        return service.admin(
            raw(request), request.headers.get("X-CSRF-Token"), request.headers.get("Origin")
        )

    def peer(request: Request) -> str:
        # Forwarded IP headers are untrusted. Behind Next this conservatively limits the shared hop.
        return request.client.host if request.client else "unknown"

    def cookie(response: Response, name: str, value: str, ttl: int):
        response.set_cookie(
            name,
            value,
            max_age=ttl,
            httponly=True,
            secure=service.settings.auth_cookie_secure,
            samesite="lax",
            path="/",
        )

    @router.get("/auth/csrf", response_model=Challenge, operation_id="auth_challenge")
    def challenge(request: Request, response: Response):
        result = service.challenge(peer(request), request.cookies.get(LOGIN_COOKIE))
        cookie(response, LOGIN_COOKIE, result["token"], 300)
        return {"csrf_token": result["csrf_token"]}

    @router.post("/auth/login", response_model=SessionUser, operation_id="auth_login")
    def login(body: LoginInput, request: Request, response: Response):
        token, user = service.login(
            email=body.email,
            password=body.password.get_secret_value(),
            token=request.cookies.get(LOGIN_COOKIE),
            csrf=request.headers.get("X-CSRF-Token"),
            origin=request.headers.get("Origin"),
            peer=peer(request),
            previous=raw(request),
        )
        cookie(response, COOKIE, token, service.settings.auth_session_ttl_seconds)
        cookie(response, LOGIN_COOKIE, "", 0)
        return user

    @router.get("/auth/me", response_model=SessionUser, operation_id="auth_me")
    def me(user: Annotated[dict, Depends(authenticated)]):
        return user

    @router.post("/auth/logout", status_code=204, operation_id="auth_logout")
    def logout(request: Request, response: Response):
        service.logout(
            raw(request), request.headers.get("X-CSRF-Token"), request.headers.get("Origin")
        )
        cookie(response, COOKIE, "", 0)

    @router.get("/ops/signals/{identifier}", operation_id="signal_detail")
    def signal(identifier: UUID, _user: Annotated[dict, Depends(authenticated)]):
        return service.signal_detail(identifier)

    @router.get(
        "/ops/{collection}", response_model=OperationalRows, operation_id="operational_rows"
    )
    def rows(
        collection: str,
        _user: Annotated[dict, Depends(authenticated)],
        offset: int = Query(default=0, ge=0, le=100_000),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        return service.rows(collection, offset, limit)

    @router.post(
        "/config/confirm", response_model=Confirmation, operation_id="confirm_config_change"
    )
    def confirm(body: Change, request: Request, _user: Annotated[dict, Depends(administrator)]):
        return service.confirm(raw(request), body.model_dump())

    @router.post("/config/apply", response_model=Applied, operation_id="apply_config_change")
    def apply(body: Apply, request: Request, _user: Annotated[dict, Depends(administrator)]):
        return {
            "version": service.apply(
                raw(request), body.confirmation_token, body.change.model_dump()
            )
        }

    @router.post("/trading/{action}", operation_id="trading_unavailable")
    def unavailable(action: str, _user: Annotated[dict, Depends(administrator)]):
        raise HTTPException(409, "TRADING_UNAVAILABLE")

    return router
