"""Short, fenced PostgreSQL transactions around network-independent observations."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, String, cast, func, select, text

from backend.domain.telegram import TelegramObservation
from backend.infrastructure.domain_models import (
    CollectorSourceState,
    TelegramMessage,
    TelegramMessageVersion,
    TelegramSource,
)
from backend.infrastructure.repositories import ScopedRepository


@dataclass(frozen=True)
class CollectorOwnership:
    account_id: str
    owner: str
    generation: int


class TelegramStore:
    def __init__(self, engine: Engine, environment_id: str):
        self.engine = engine
        self.environment_id = environment_id

    def acquire(self, account_id: str, owner: str, seconds: int = 90) -> CollectorOwnership | None:
        with self.engine.begin() as connection:
            generation = (
                ScopedRepository(connection, self.environment_id)
                .call(
                    "SELECT public.telegram_acquire_lease(:environment,:account,:owner,:seconds)",
                    {"account": account_id, "owner": owner, "seconds": seconds},
                )
                .scalar_one()
            )
        return CollectorOwnership(account_id, owner, generation) if generation else None

    def _parameters(self, ownership: CollectorOwnership):
        return {
            "account": ownership.account_id,
            "owner": ownership.owner,
            "generation": ownership.generation,
        }

    def release(self, ownership: CollectorOwnership):
        with self.engine.begin() as connection:
            ScopedRepository(connection, self.environment_id).call(
                "SELECT public.telegram_release_lease(:environment,:account,:owner,:generation)",
                self._parameters(ownership),
            )

    def backoff(self, ownership: CollectorOwnership, seconds: int):
        with self.engine.begin() as connection:
            ScopedRepository(connection, self.environment_id).call(
                "SELECT public.telegram_account_backoff"
                "(:environment,:account,:owner,:generation,:seconds)",
                self._parameters(ownership) | {"seconds": seconds},
            )

    def sources(self, collector_identity: str) -> list[dict]:
        cursor_date = (
            select(
                func.coalesce(
                    TelegramMessageVersion.published_at, TelegramMessageVersion.observed_at
                )
            )
            .join(
                TelegramMessage,
                (TelegramMessageVersion.environment_id == TelegramMessage.environment_id)
                & (TelegramMessageVersion.message_id == TelegramMessage.id),
            )
            .where(
                TelegramMessage.environment_id == TelegramSource.environment_id,
                TelegramMessage.source_id == TelegramSource.id,
                TelegramMessage.message_id == cast(CollectorSourceState.last_message_id, String),
            )
            .order_by(TelegramMessageVersion.version)
            .limit(1)
            .correlate(TelegramSource, CollectorSourceState)
            .scalar_subquery()
        )
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(
                        TelegramSource,
                        CollectorSourceState.last_message_id,
                        CollectorSourceState.delete_cursor,
                        CollectorSourceState.checked_at,
                        CollectorSourceState.gap_since,
                        CollectorSourceState.last_success_at,
                        cursor_date.label("cursor_published_at"),
                    )
                    .outerjoin(
                        CollectorSourceState,
                        (CollectorSourceState.environment_id == TelegramSource.environment_id)
                        & (CollectorSourceState.source_id == TelegramSource.id),
                    )
                    .where(
                        TelegramSource.environment_id == self.environment_id,
                        TelegramSource.collector_identity == collector_identity,
                        TelegramSource.enabled.is_(True),
                        TelegramSource.reference.is_not(None),
                    )
                    .order_by(TelegramSource.id)
                    .limit(32)
                ).mappings()
            ]

    def observe(self, ownership: CollectorOwnership, source: dict, **data):
        with self.engine.begin() as connection:
            ScopedRepository(connection, self.environment_id).call(
                "SELECT public.telegram_source_observed(:environment,:account,:owner,:generation,"
                ":source,:version,:data)",
                self._parameters(ownership)
                | {"source": source["id"], "version": source["version"], "data": data},
                "data",
            )

    def ingest(
        self,
        ownership: CollectorOwnership,
        source: dict,
        event: TelegramObservation,
        max_age: int = 900,
        *,
        advance_cursor: bool = True,
    ) -> dict:
        with self.engine.begin() as connection:
            return (
                ScopedRepository(connection, self.environment_id)
                .call(
                    "SELECT public.telegram_ingest(:environment,:account,:owner,:generation,"
                    ":source,:version,:data,:max_age)",
                    self._parameters(ownership)
                    | {
                        "source": source["id"],
                        "version": source["version"],
                        "data": event.payload() | {"advance_cursor": advance_cursor},
                        "max_age": max_age,
                    },
                    "data",
                )
                .scalar_one()
            )

    def deletion_candidates(
        self, source_id: UUID, after: int, since: datetime, limit: int = 100
    ) -> list[dict]:
        # Rotate across recently stored anchors. Raw bodies are not needed for deletion checks.
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    text("""
                SELECT m.message_id, min(coalesce(v.published_at,v.observed_at)) AS published_at
                FROM public.telegram_messages m JOIN public.telegram_message_versions v
                ON (v.environment_id,v.message_id)=(m.environment_id,m.id)
                WHERE m.environment_id=:environment AND m.source_id=:source
                AND m.message_id::bigint>:after
                AND NOT EXISTS (SELECT 1 FROM public.telegram_message_versions d
                WHERE (d.environment_id,d.message_id)=(m.environment_id,m.id)
                AND d.event_kind='DELETE')
                GROUP BY m.message_id HAVING min(coalesce(v.published_at,v.observed_at))>=:since
                ORDER BY m.message_id::bigint LIMIT :limit
            """),
                    {
                        "environment": self.environment_id,
                        "source": source_id,
                        "after": after,
                        "since": since,
                        "limit": limit,
                    },
                ).mappings()
            ]
