"""Small cross-platform heartbeat runtime; no trading or provider side effects."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable
from uuid import uuid4

from backend.domain.config import ServiceSettings

Probe = Callable[[ServiceSettings], bool]
HeartbeatHook = Callable[..., None]


class HeartbeatRuntime:
    def __init__(self, settings: ServiceSettings, probe: Probe, heartbeat: HeartbeatHook) -> None:
        self.settings = settings
        self.probe = probe
        self.heartbeat = heartbeat
        self.instance_id = str(uuid4())
        self.logger = logging.getLogger("trd.runtime")

    def emit(self, status: str) -> bool:
        try:
            self.heartbeat(
                self.settings,
                service_name=self.settings.service_name,
                instance_id=self.instance_id,
                status=status,
            )
            return True
        except Exception as exc:
            self.logger.warning(
                "Heartbeat persistence failed", extra={"error_type": type(exc).__name__}
            )
            return False

    def tick(self) -> bool:
        try:
            ready = self.probe(self.settings)
        except Exception as exc:
            ready = False
            self.logger.warning(
                "Foundation readiness check failed", extra={"error_type": type(exc).__name__}
            )
        persisted = self.emit("HEALTHY" if ready else "DEGRADED")
        return ready and persisted

    def run(self, stop: threading.Event) -> None:
        self.emit("STARTING")
        try:
            while not stop.is_set():
                self.tick()
                stop.wait(self.settings.heartbeat_interval_seconds)
        finally:
            self.emit("STOPPED")


def run_service(settings: ServiceSettings, probe: Probe, heartbeat: HeartbeatHook) -> None:
    stop = threading.Event()
    previous = {}

    def request_stop(_number: int, _frame: object) -> None:
        stop.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is not None:
            previous[number] = signal.signal(number, request_stop)
    try:
        HeartbeatRuntime(settings, probe, heartbeat).run(stop)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
