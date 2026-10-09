"""Bounded Telegram inputs are evidence, never trading instructions."""

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    name: str = Field(min_length=1, max_length=160)
    reference: str = Field(pattern=r"^(@[A-Za-z][A-Za-z0-9_]{4,31}|-[1-9][0-9]{0,18})$")
    enabled: bool

    @field_validator("name", "reference", mode="before")
    @classmethod
    def normalize(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if any(ord(character) < 32 for character in value):
                raise ValueError("control characters are unavailable")
        return value

    @field_validator("reference", mode="before")
    @classmethod
    def public_link(cls, value):
        if isinstance(value, str):
            match = re.fullmatch(
                r"(?:https://)?t\.me/([A-Za-z][A-Za-z0-9_]{4,31})/?", value.strip()
            )
            if match:
                return "@" + match.group(1)
        return value

    @field_validator("reference")
    @classmethod
    def canonical_reference(cls, value: str) -> str:
        return value.lower() if value.startswith("@") else value


class TelegramObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    message_id: int = Field(ge=1, le=2_147_483_647)
    kind: Literal["NEW", "EDIT", "DELETE"]
    body: str = ""
    published_at: datetime
    observed_at: datetime
    reply_message_id: int | None = Field(default=None, ge=1, le=2_147_483_647)
    media_kind: Literal["NONE", "PHOTO", "DOCUMENT", "OTHER"] = "NONE"

    @field_validator("published_at", "observed_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Telegram dates must have a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded(self):
        if "\x00" in self.body or len(self.body.encode("utf-8")) > 65_536:
            raise ValueError("raw message storage boundary exceeded")
        if self.observed_at < self.published_at:
            raise ValueError("revision predates message")
        if self.kind == "DELETE" and (self.body or self.media_kind != "NONE"):
            raise ValueError("a tombstone has no raw body or media")
        return self

    def payload(self) -> dict:
        result = self.model_dump(mode="json")
        result["body_hash"] = sha256(self.body.encode("utf-8")).hexdigest()
        result["revision_hash"] = sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return result


def valid_account(value: str) -> bool:
    return bool(re.fullmatch(r"[1-9][0-9]{0,19}", value))
