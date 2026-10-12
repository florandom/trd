"""Public health schemas deliberately carry no infrastructure or secret values."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthLiveness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["alive"] = "alive"
    service: Literal["api", "risk", "simulator"]
    phase: Literal[1] = 1


class HealthReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "not_ready"]
    service: Literal["api"] = "api"
    phase: Literal[1] = 1
    mode: Literal["paper"] = "paper"
    automation_enabled: Literal[False] = False
    checked_at: datetime
