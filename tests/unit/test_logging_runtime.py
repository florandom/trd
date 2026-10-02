import json
import logging
import threading

from pydantic import SecretStr

from backend.application.runtime import HeartbeatRuntime
from backend.domain.config import ServiceSettings
from backend.infrastructure.logging import JsonFormatter, Redactor, configure_logging


def settings(tmp_path):
    return ServiceSettings(
        service_name="ai",
        app_env="test",
        environment_id="paper-test",
        database_url="postgresql+psycopg://trd_ai:log-secret-canary@localhost:5432/trd",
        log_dir=tmp_path,
        log_max_bytes=1024,
        log_backup_count=2,
    )


def test_recursive_redaction_and_exception_body_omission():
    formatter = JsonFormatter("ai", ("log-secret-canary",))
    record = logging.makeLogRecord(
        {
            "name": "trd.test",
            "levelname": "ERROR",
            "msg": "failure log-secret-canary Bearer abc123",
            "args": (),
            "nested": {
                "api_key": "foreign-secret",
                "items": [{"password": "deep-secret"}, SecretStr("wrapped")],
            },
            "exc_info": (RuntimeError, RuntimeError("exception-body-secret"), None),
        }
    )
    output = formatter.format(record)
    assert not any(
        value in output
        for value in (
            "log-secret-canary",
            "abc123",
            "foreign-secret",
            "deep-secret",
            "wrapped",
            "exception-body-secret",
        )
    )
    assert json.loads(output)["exception_type"] == "RuntimeError"
    assert Redactor().clean({"number": float("nan")}) == {"number": "[NON_FINITE]"}


def test_rotating_logs_bound_files_and_redact_known_password(tmp_path):
    logger = configure_logging(settings(tmp_path))
    try:
        for _ in range(30):
            logger.info("Foundation tick log-secret-canary %s", "x" * 120)
        for handler in logger.handlers:
            handler.flush()
        files = list(tmp_path.glob("ai.jsonl*"))
        assert 1 <= len(files) <= 3
        assert any(file.name.endswith(".1") for file in files)
        assert all("log-secret-canary" not in file.read_text() for file in files)
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()


def test_failed_database_tick_persists_degraded_and_recovers(tmp_path):
    events = []
    results = iter((False, True))
    runtime = HeartbeatRuntime(
        settings(tmp_path),
        lambda _settings: next(results),
        lambda _settings, **event: events.append(event),
    )
    assert runtime.tick() is False
    assert runtime.tick() is True
    assert [event["status"] for event in events] == ["DEGRADED", "HEALTHY"]


def test_heartbeat_failure_cannot_report_ready_and_pre_stopped_loop_exits(tmp_path):
    def failed(_settings, **_event):
        raise RuntimeError("secret-from-driver")

    runtime = HeartbeatRuntime(settings(tmp_path), lambda _settings: True, failed)
    assert runtime.tick() is False
    stop = threading.Event()
    stop.set()
    runtime.run(stop)
