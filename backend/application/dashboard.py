"""Cookie sessions and dashboard use cases. No trading or provider authority."""

from __future__ import annotations

import json
import secrets
from datetime import timedelta
from functools import cached_property
from hashlib import sha256
from hmac import compare_digest
from threading import BoundedSemaphore
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError
from fastapi import HTTPException
from sqlalchemy import Engine, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError

from backend.domain.config import ApiSettings
from backend.domain.contracts import AgentConfiguration, RiskPolicy
from backend.domain.telegram import SourceConfiguration
from backend.infrastructure.database import create_database_engine

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)
PASSWORD_SLOTS = BoundedSemaphore(2)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
COOKIE = "trd_session"
LOGIN_COOKIE = "trd_login"


def token_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def csrf_token(token: str) -> str:
    return token_hash("csrf:" + token)


def valid_token(token: str | None) -> bool:
    return bool(token and len(token) == 43 and all(c.isalnum() or c in "-_" for c in token))


class DashboardService:
    def __init__(self, settings: ApiSettings, engine: Engine | None = None):
        self.settings = settings
        self._engine = engine
        self.environment = settings.environment_id

    @cached_property
    def engine(self) -> Engine:
        return self._engine or create_database_engine(self.settings.database_url.get_secret_value())

    def parameters(self, **kwargs):
        return {"environment": self.environment, **kwargs}

    def origin(self, origin: str | None) -> None:
        if origin != self.settings.app_url.rstrip("/"):
            raise HTTPException(403, "ORIGIN_REJECTED")

    def csrf(self, token: str | None, supplied: str | None) -> None:
        if (
            not valid_token(token)
            or not supplied
            or not compare_digest(csrf_token(token), supplied)
        ):
            raise HTTPException(403, "CSRF_REJECTED")

    def throttle(self, buckets: list[tuple[str, int]]) -> None:
        # Reserve an attempt before password verification; concurrent workers share this state.
        denied = False
        with self.engine.begin() as connection:
            for bucket, limit in buckets:
                row = (
                    connection.execute(
                        text("""
                    INSERT INTO public.auth_attempts(environment_id,bucket_hash,attempts)
                    VALUES(:environment,:bucket,1) ON CONFLICT(environment_id,bucket_hash)
                    DO UPDATE SET attempts=CASE WHEN auth_attempts.window_started<
                      clock_timestamp()-interval '5 minutes' THEN 1
                      ELSE auth_attempts.attempts+1 END,
                      window_started=CASE WHEN auth_attempts.window_started<
                      clock_timestamp()-interval '5 minutes' THEN clock_timestamp()
                      ELSE auth_attempts.window_started END
                    RETURNING attempts,extract(epoch FROM
                      (window_started+interval '5 minutes'-clock_timestamp())) AS retry
                """),
                        self.parameters(bucket=token_hash(bucket)),
                    )
                    .mappings()
                    .one()
                )
                if row["attempts"] > limit:
                    denied = True
                    retry = max(1, min(300, int(row["retry"]) + 1))
                    break
        if denied:
            raise HTTPException(429, "LOGIN_THROTTLED", headers={"Retry-After": str(retry)})

    def challenge(self, peer: str, previous: str | None) -> dict[str, str]:
        self.throttle([("challenge-ip:" + peer, 60)])
        token = secrets.token_urlsafe(32)
        with self.engine.begin() as connection:
            connection.execute(
                text("""DELETE FROM public.auth_challenges
                WHERE environment_id=:environment AND (token_hash=:previous OR token_hash IN (
                SELECT token_hash FROM public.auth_challenges WHERE environment_id=:environment
                AND expires_at<clock_timestamp() ORDER BY expires_at LIMIT 100))"""),
                self.parameters(previous=token_hash(previous or "")),
            )
            connection.execute(
                text("""INSERT INTO public.auth_challenges
                VALUES(:environment,:token,clock_timestamp()+interval '5 minutes')"""),
                self.parameters(token=token_hash(token)),
            )
        return {"token": token, "csrf_token": csrf_token(token)}

    def login(
        self,
        *,
        email: str,
        password: str,
        token: str | None,
        csrf: str | None,
        origin: str | None,
        peer: str,
        previous: str | None,
    ) -> tuple[str, dict]:
        self.origin(origin)
        self.csrf(token, csrf)
        self.throttle([("login-ip:" + peer, 30), ("login-account:" + email, 5)])
        with self.engine.begin() as connection:
            accepted = connection.execute(
                text("""DELETE FROM public.auth_challenges
                WHERE environment_id=:environment AND token_hash=:token
                AND expires_at>clock_timestamp() RETURNING token_hash"""),
                self.parameters(token=token_hash(token)),
            ).first()
        if not accepted:
            raise HTTPException(403, "CSRF_REJECTED")
        with self.engine.begin() as connection:
            user = (
                connection.execute(
                    text("SELECT * FROM public.lookup_login_user(:email)"), {"email": email}
                )
                .mappings()
                .first()
            )
        if not PASSWORD_SLOTS.acquire(timeout=1):
            raise HTTPException(429, "LOGIN_THROTTLED", headers={"Retry-After": "1"})
        try:
            verified = HASHER.verify(user["password_hash"] if user else DUMMY_HASH, password)
        except VerificationError:
            verified = False
        finally:
            PASSWORD_SLOTS.release()
        valid = bool(verified and user and user["active"])
        raw = secrets.token_urlsafe(32)
        with self.engine.begin() as connection:
            connection.execute(
                text("SELECT public.dashboard_auth_audit(:environment,:actor,:action)"),
                self.parameters(
                    actor=user["id"] if valid else None,
                    action="LOGIN_SUCCEEDED" if valid else "LOGIN_FAILED",
                ),
            )
            if valid:
                if valid_token(previous):
                    connection.execute(
                        text("""UPDATE public.sessions SET revoked_at=clock_timestamp()
                        WHERE environment_id=:environment AND token_hash=:token"""),
                        self.parameters(token=token_hash(previous)),
                    )
                connection.execute(
                    text("""INSERT INTO public.sessions
                    (environment_id,id,user_id,token_hash,expires_at,last_seen_at)
                    VALUES(:environment,gen_random_uuid(),:user,:token,
                     clock_timestamp()+make_interval(secs=>:ttl),clock_timestamp())"""),
                    self.parameters(
                        user=user["id"],
                        token=token_hash(raw),
                        ttl=self.settings.auth_session_ttl_seconds,
                    ),
                )
        if not valid:
            raise HTTPException(401, "INVALID_CREDENTIALS")
        return raw, {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "csrf_token": csrf_token(raw),
        }

    def authenticate(self, raw: str | None) -> dict:
        if not valid_token(raw):
            raise HTTPException(401, "AUTH_REQUIRED")
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("""UPDATE public.sessions s
                SET last_seen_at=clock_timestamp() FROM public.api_users u
                WHERE s.user_id=u.id AND u.active AND s.environment_id=:environment
                 AND s.token_hash=:token AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp()
                 AND s.last_seen_at>clock_timestamp()-make_interval(secs=>:idle)
                RETURNING u.id,u.email,u.role,s.expires_at,s.last_seen_at"""),
                    self.parameters(
                        token=token_hash(raw), idle=self.settings.auth_idle_ttl_seconds
                    ),
                )
                .mappings()
                .first()
            )
        if not row:
            raise HTTPException(401, "AUTH_REQUIRED")
        return {
            **row,
            "csrf_token": csrf_token(raw),
            "idle_expires_at": row["last_seen_at"]
            + timedelta(seconds=self.settings.auth_idle_ttl_seconds),
        }

    def admin(self, raw: str | None, csrf: str | None, origin: str | None) -> dict:
        self.origin(origin)
        self.csrf(raw, csrf)
        user = self.authenticate(raw)
        if user["role"] != "ADMIN":
            raise HTTPException(403, "ADMIN_REQUIRED")
        return user

    def logout(self, raw: str, csrf: str | None, origin: str | None) -> None:
        self.origin(origin)
        self.csrf(raw, csrf)
        user = self.authenticate(raw)
        with self.engine.begin() as connection:
            connection.execute(
                text("""UPDATE public.sessions SET revoked_at=clock_timestamp()
                WHERE environment_id=:environment AND token_hash=:token"""),
                self.parameters(token=token_hash(raw)),
            )
            connection.execute(
                text("SELECT public.dashboard_auth_audit(:environment,:actor,'LOGOUT')"),
                self.parameters(actor=user["id"]),
            )

    def rows(self, collection: str, offset: int = 0, limit: int = 50) -> dict:
        views = {
            "settings": ("api_settings", "key"),
            "agents": ("dashboard_agents", "name"),
            "risk": ("dashboard_risk", "key"),
            "models": ("api_models", "id"),
            "audit": ("dashboard_audit", "created_at DESC,id"),
            "status": ("api_heartbeats", "service_name,instance_id"),
            "positions": ("api_positions", "opened_at DESC,id"),
            "orders": ("api_orders", "created_at DESC,id"),
            "signals": ("api_signals", "created_at DESC,id"),
            "sources": ("dashboard_sources", "name,id"),
            "telegram-messages": ("dashboard_telegram_messages", "observed_at DESC,id"),
            "costs": ("dashboard_costs", "created_at DESC,id"),
        }
        if collection not in views:
            raise HTTPException(404, "NOT_FOUND")
        view, order = views[collection]
        where = "" if collection == "models" else "WHERE environment_id=:environment"
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    text(
                        f"SELECT * FROM public.{view} {where} "
                        f"ORDER BY {order} LIMIT :limit OFFSET :offset"
                    ),
                    self.parameters(limit=limit + 1, offset=offset),
                )
                .mappings()
                .all()
            )
            now = connection.scalar(text("SELECT clock_timestamp()"))
        return {
            "rows": [dict(row) for row in rows[:limit]],
            "has_more": len(rows) > limit,
            "offset": offset,
            "checked_at": now,
            "environment_id": self.environment,
        }

    def signal_detail(self, identifier) -> dict:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("""SELECT * FROM public.api_signals
                WHERE environment_id=:environment AND id=:id"""),
                    self.parameters(id=identifier),
                )
                .mappings()
                .first()
            )
            if not row:
                raise HTTPException(404, "NOT_FOUND")
            versions = (
                connection.execute(
                    text("""SELECT version,proposal,created_at
                FROM public.dashboard_signal_versions WHERE environment_id=:environment
                AND signal_id=:id ORDER BY version DESC LIMIT 20"""),
                    self.parameters(id=identifier),
                )
                .mappings()
                .all()
            )
        return {"signal": dict(row), "versions": [dict(v) for v in versions]}

    def validate_change(self, payload: dict[str, Any]) -> dict:
        kind, target, value = payload["kind"], payload["target"], payload["value"]
        try:
            if kind != "source" and payload["expected_version"] < 1:
                raise ValueError("configuration version required")
            if kind == "settings":
                allowed = {
                    "raw_log_retention_days",
                    "ai_response_retention_days",
                    "telegram_retention_days",
                }
                if target not in allowed or type(value) is not int or not 1 <= value <= 365:
                    raise ValueError("unsupported setting")
            elif kind == "risk":
                if target != "baseline":
                    raise ValueError("unknown risk policy")
                policy = RiskPolicy.model_validate(value)
                rows = self.rows("risk")["rows"]
                current = next(r for r in rows if r["key"] == target)
                policy.within(RiskPolicy.model_validate(current["policy"]))
                payload["value"] = policy.model_dump(mode="json")
            elif kind == "source":
                UUID(target)
                payload["value"] = SourceConfiguration.model_validate(value).model_dump(mode="json")
            elif kind == "agent":
                config = AgentConfiguration.model_validate(value)
                if config.enabled or config.max_cost_usd != 0 or config.max_output_tokens > 4096:
                    raise ValueError("capability unavailable")
                models = self.rows("models")["rows"]
                for identifier in (config.primary_model_id, *config.fallback_model_ids):
                    if not any(
                        m["id"] == identifier
                        and m["provider"] == "mock"
                        and m["enabled"]
                        and m["schema_version"] == config.required_schema_version
                        and m["max_output_tokens"] >= config.max_output_tokens
                        for m in models
                    ):
                        raise ValueError("model unavailable")
                payload["value"] = config.model_dump(mode="json")
            else:
                raise ValueError("unsupported change")
        except (ValueError, StopIteration, TypeError):
            raise HTTPException(422, "INVALID_CONFIGURATION") from None
        return payload

    def confirm(self, raw: str, payload: dict) -> dict:
        payload = self.validate_change(payload)
        token = secrets.token_urlsafe(32)
        with self.engine.begin() as connection:
            statement = text("""INSERT INTO public.dashboard_confirmations
                (environment_id,token_hash,session_hash,payload,expires_at)
                VALUES(:environment,:token,:session,:payload,clock_timestamp()+interval '2 minutes')
                RETURNING expires_at""").bindparams(bindparam("payload", type_=JSONB))
            expiry = connection.scalar(
                statement,
                self.parameters(token=token_hash(token), session=token_hash(raw), payload=payload),
            )
        return {
            "confirmation_token": token,
            "expires_at": expiry,
            "change": payload,
            "digest": token_hash(json.dumps(payload, sort_keys=True, separators=(",", ":"))),
        }

    def apply(self, raw: str, confirmation: str, payload: dict) -> int:
        payload = self.validate_change(payload)
        try:
            with self.engine.begin() as connection:
                statement = text("""SELECT public.apply_dashboard_change
                    (:environment,:session,:confirmation,:payload,:idle)""").bindparams(
                    bindparam("payload", type_=JSONB)
                )
                return connection.scalar(
                    statement,
                    self.parameters(
                        session=token_hash(raw),
                        confirmation=token_hash(confirmation),
                        payload=payload,
                        idle=self.settings.auth_idle_ttl_seconds,
                    ),
                )
        except DBAPIError as error:
            code = getattr(error.orig, "sqlstate", None)
            if code == "40001":
                raise HTTPException(409, "VERSION_CONFLICT") from None
            if code == "42501":
                raise HTTPException(403, "ADMIN_REQUIRED") from None
            if code in {"22023", "23505", "23503", "23514", "22P02"}:
                raise HTTPException(422, "INVALID_CONFIGURATION") from None
            raise
