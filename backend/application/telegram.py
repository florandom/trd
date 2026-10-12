"""Bounded read-only reconciliation. PostgreSQL owns checkpoints and account fencing."""

import asyncio
import logging
import random
import signal
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.application.runtime import HeartbeatRuntime
from backend.domain.config import CollectorSettings
from backend.domain.telegram import TelegramObservation
from backend.infrastructure.database import create_database_engine, database_probe, record_heartbeat
from backend.infrastructure.repositories import IdentityConflict, VersionConflict
from backend.infrastructure.telegram_repository import TelegramStore
from backend.integrations.telegram.client import Peer, ReadOnlyTelegramClient, TelegramUnavailable
from backend.integrations.telegram.session import load_session


class Collector:
    def __init__(
        self,
        settings: CollectorSettings,
        store: TelegramStore,
        client_factory=ReadOnlyTelegramClient,
    ):
        self.settings = settings
        self.store = store
        self.client_factory = client_factory
        self.owner = uuid4().hex
        self.ownership = None
        self.logger = logging.getLogger("trd.telegram")

    async def renew(self):
        current = await asyncio.to_thread(self.store.acquire, self.ownership.account_id, self.owner)
        if current is None or current.generation != self.ownership.generation:
            raise VersionConflict("collector ownership changed")

    async def network(self, operation, *args, **kwargs):
        await self.renew()
        return await operation(*args, **kwargs)

    async def scan_source(self, client, source: dict):
        now = datetime.now(UTC)
        since = now - timedelta(seconds=self.settings.telegram_backfill_max_age_seconds)
        gap = bool(source.get("gap_since")) or (
            source.get("last_success_at") is not None and source["last_success_at"] < since
        )
        if source["resolution_state"] != "RESOLVED":
            peer = await self.network(client.resolve, source["reference"])
            await asyncio.to_thread(
                self.store.observe,
                self.ownership,
                source,
                status="BACKFILL",
                peer_id=peer.id,
                peer_kind=peer.kind,
                access_hash=peer.access_hash,
            )
        else:
            peer = Peer(source["peer_id"], source["peer_kind"], source["access_hash"])
        batch = self.settings.telegram_history_batch_size
        after = source.get("last_message_id") or 0
        if after and (
            source.get("cursor_published_at") is None or source["cursor_published_at"] < since
        ):
            # A cursor before the bounded recovery window must restart by date.
            # Telegram gives an ID offset precedence over a date offset.
            after = 0
        history = await self.network(client.history, peer, after=after, since=since, limit=batch)
        for event in history:
            await asyncio.to_thread(
                self.store.ingest,
                self.ownership,
                source,
                event,
                self.settings.telegram_signal_max_age_seconds,
            )
        # A latest-window read cannot advance the sequential history high-water mark.
        overlap = await self.network(
            client.history, peer, after=0, since=since, limit=batch, newest=True
        )
        for event in overlap:
            if event.published_at >= since:
                await asyncio.to_thread(
                    self.store.ingest,
                    self.ownership,
                    source,
                    event,
                    self.settings.telegram_signal_max_age_seconds,
                    advance_cursor=False,
                )
        candidates = await asyncio.to_thread(
            self.store.deletion_candidates,
            source["id"],
            source.get("delete_cursor") or 0,
            since,
            batch,
        )
        deletion_cursor = 0
        if candidates:
            observed = await self.network(
                client.check_ids, peer, [int(item["message_id"]) for item in candidates]
            )
            for item in candidates:
                key = int(item["message_id"])
                if key not in observed:
                    raise TelegramUnavailable("INCOMPLETE_RESPONSE")
                event = observed[key]
                if event is None:
                    event = TelegramObservation(
                        message_id=key,
                        kind="DELETE",
                        published_at=item["published_at"],
                        observed_at=now,
                    )
                await asyncio.to_thread(
                    self.store.ingest,
                    self.ownership,
                    source,
                    event,
                    self.settings.telegram_signal_max_age_seconds,
                    advance_cursor=False,
                )
            deletion_cursor = int(candidates[-1]["message_id"])
        await asyncio.to_thread(
            self.store.observe,
            self.ownership,
            source,
            status="GAP" if gap else "BACKFILL" if len(history) == batch else "ACTIVE",
            error_code="HISTORY_WINDOW_EXCEEDED" if gap else None,
            success=len(history) < batch,
            delete_cursor=deletion_cursor,
        )
        return not gap and len(history) < batch

    async def run(self, stop: asyncio.Event):
        heartbeat = HeartbeatRuntime(self.settings, database_probe, record_heartbeat)
        heartbeat.instance_id = self.owner
        heartbeat.emit("STARTING")
        failures = 0
        blocked_session = False
        try:
            while not stop.is_set():
                client = None
                connected = False
                healthy = False
                delay = self.settings.telegram_poll_seconds
                try:
                    if not self.settings.telegram_enabled:
                        heartbeat.emit("STOPPED")
                        await wait_stop(stop, self.settings.heartbeat_interval_seconds)
                        continue
                    if blocked_session:
                        heartbeat.emit("DEGRADED")
                        await wait_stop(stop, self.settings.heartbeat_interval_seconds)
                        continue
                    stored = load_session(self.settings)
                    self.ownership = await asyncio.to_thread(
                        self.store.acquire, stored.account_id, self.owner
                    )
                    if self.ownership is None:
                        heartbeat.emit("DEGRADED")
                        await wait_stop(stop, self.settings.heartbeat_interval_seconds)
                        continue
                    client = self.client_factory(self.settings, stored)
                    await self.network(client.connect)
                    connected = True
                    await self.renew()
                    await asyncio.to_thread(client.persist_session)
                    sources = await asyncio.to_thread(
                        self.store.sources, self.settings.telegram_collector_identity
                    )
                    healthy = bool(sources)
                    for source in sources:
                        if stop.is_set():
                            break
                        try:
                            healthy = await self.scan_source(client, source) and healthy
                        except IdentityConflict:
                            healthy = False
                            await asyncio.to_thread(
                                self.store.observe,
                                self.ownership,
                                source,
                                status="UNAVAILABLE",
                                error_code="SOURCE_DATA_CONFLICT",
                            )
                        except TelegramUnavailable as error:
                            await asyncio.to_thread(
                                self.store.observe,
                                self.ownership,
                                source,
                                status="FLOOD_WAIT"
                                if error.code == "FLOOD_WAIT"
                                else "UNAVAILABLE",
                                error_code=error.code,
                            )
                            healthy = False
                            if error.code != "SOURCE_UNAVAILABLE":
                                raise
                    failures = 0
                except TelegramUnavailable as error:
                    healthy = False
                    failures += 1
                    blocked_session = error.code in {"SESSION_REVOKED", "ACCOUNT_MISMATCH"}
                    if error.code == "FLOOD_WAIT" and self.ownership:
                        await asyncio.to_thread(
                            self.store.backoff, self.ownership, min(error.retry_after, 604800)
                        )
                        delay = max(self.settings.heartbeat_interval_seconds, error.retry_after)
                    else:
                        delay = min(300, 5 * 2 ** min(failures, 6)) + random.uniform(0, 2)
                    self.logger.warning(
                        "Telegram collection unavailable", extra={"reason_code": error.code}
                    )
                except Exception as error:
                    healthy = False
                    failures += 1
                    delay = min(300, 5 * 2 ** min(failures, 6)) + random.uniform(0, 2)
                    self.logger.warning(
                        "Telegram collection suspended", extra={"error_type": type(error).__name__}
                    )
                finally:
                    if client is not None:
                        if connected and self.ownership is not None:
                            try:
                                await self.renew()
                                await asyncio.to_thread(client.persist_session)
                            except Exception:
                                healthy = False
                                self.logger.warning("Telegram session persistence unavailable")
                        try:
                            await asyncio.wait_for(client.disconnect(), 5)
                        except Exception:
                            self.logger.warning("Telegram disconnect failed")
                    if self.ownership is not None:
                        try:
                            await asyncio.to_thread(self.store.release, self.ownership)
                        except Exception:
                            pass
                        self.ownership = None
                heartbeat.emit("HEALTHY" if healthy else "DEGRADED")
                # Keep service observations fresh during flood waits and backoff.
                remaining = delay
                while remaining > 0 and not stop.is_set():
                    step = min(remaining, self.settings.heartbeat_interval_seconds)
                    await wait_stop(stop, step)
                    remaining -= step
                    heartbeat.emit("HEALTHY" if healthy else "DEGRADED")
        finally:
            heartbeat.emit("STOPPED")


async def wait_stop(stop: asyncio.Event, seconds: float):
    try:
        await asyncio.wait_for(stop.wait(), seconds)
    except TimeoutError:
        pass


def run_collector(settings: CollectorSettings):
    async def execute():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        previous = {}
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            number = getattr(signal, name, None)
            if number is not None:
                previous[number] = signal.signal(
                    number, lambda _n, _f: loop.call_soon_threadsafe(stop.set)
                )
        engine = create_database_engine(settings.database_url.get_secret_value())
        try:
            await Collector(settings, TelegramStore(engine, settings.environment_id)).run(stop)
        finally:
            engine.dispose()
            for number, handler in previous.items():
                signal.signal(number, handler)

    asyncio.run(execute())
