"""JSON logging with recursive redaction and bounded platform-native rotation."""

from __future__ import annotations

import json
import logging
import math
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any

from pydantic import SecretStr

from backend.domain.config import ServiceSettings

_PRIVATE_KEY = re.compile(
    r"password|passwd|secret|token|authorization|cookie|api.?key|session|dsn|database.?url|raw.?message|raw.?response",
    re.I,
)
_CREDENTIAL_URL = re.compile(
    r"\b(?:postgres(?:ql)?(?:\+psycopg)?|redis|rediss|https?)://[^\s/]+:[^\s/@]+@[^\s]+", re.I
)
_AUTH_HEADER = re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.I)
_ASSIGNMENT = re.compile(
    r"\b(password|passwd|secret|token|api[_-]?key|session(?:_id)?|cookie|authorization)"
    r"\s*[:=]\s*[^\s,;]+",
    re.I,
)
_STANDARD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class Redactor:
    def __init__(self, known_secrets: tuple[str, ...] = ()) -> None:
        self.known_secrets = sorted(
            {value for value in known_secrets if value}, key=len, reverse=True
        )

    def clean(self, value: Any) -> Any:
        if isinstance(value, SecretStr):
            return "[REDACTED]"
        if isinstance(value, Mapping):
            return {
                str(key): "[REDACTED]" if _PRIVATE_KEY.search(str(key)) else self.clean(item)
                for key, item in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [self.clean(item) for item in value]
        if isinstance(value, str):
            for secret in self.known_secrets:
                value = value.replace(secret, "[REDACTED]")
            value = _CREDENTIAL_URL.sub("[REDACTED_URL]", value)
            value = _AUTH_HEADER.sub("[REDACTED_AUTH]", value)
            return _ASSIGNMENT.sub(r"\1=[REDACTED]", value)
        if isinstance(value, float) and not math.isfinite(value):
            return "[NON_FINITE]"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        # Arbitrary object reprs can contain source bodies or credential fields.
        return f"<{type(value).__name__}>"


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str, known_secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.service_name = service_name
        self.redactor = Redactor(known_secrets)

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": self.redactor.clean(record.getMessage()),
        }
        payload["context"] = self.redactor.clean(
            {key: value for key, value in record.__dict__.items() if key not in _STANDARD_FIELDS}
        )
        if record.exc_info and record.exc_info[0]:
            # Exception messages and traceback source lines may carry raw secrets.
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def configure_logging(settings: ServiceSettings) -> logging.Logger:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter(settings.service_name, settings.logging_secrets())
    stream = logging.StreamHandler(sys.stdout)
    file_handler = RotatingFileHandler(
        settings.log_dir / f"{settings.service_name}.jsonl",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    for handler in (stream, file_handler):
        handler.setFormatter(formatter)
    # Uvicorn configures its loggers before importing the entrypoint. Replace
    # those handlers too, so framework failures cannot bypass redaction.
    for name in ("trd", "uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy"):
        logger = logging.getLogger(name)
        for previous in logger.handlers[:]:
            logger.removeHandler(previous)
            previous.close()
        logger.addHandler(stream)
        logger.addHandler(file_handler)
        logger.setLevel(settings.log_level)
        logger.propagate = False
    return logging.getLogger("trd")
