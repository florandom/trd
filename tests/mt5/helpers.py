from datetime import UTC, datetime
from uuid import uuid4

import httpx

from backend.domain.bridge import Envelope, PaperProfile, json_bytes, strict_json
from backend.domain.risk_contracts import SessionCalendar, SessionWindow
from infra.scripts.mt5_lab import lab_config
from tests.unit.test_paper_simulator import ORIGIN, REQUEST_KEY, RESPONSE_KEY, fixture


def config_and_command():
    p, snapshot, command = fixture()
    identity = p.account.model_copy(update={"login": "1"})
    p = PaperProfile.model_validate(
        {
            **p.model_dump(),
            "account": identity,
            "calendar": SessionCalendar(
                timezone="UTC",
                windows=tuple(
                    SessionWindow(weekday=d, start_minute=0, end_minute=1440) for d in range(7)
                ),
            ),
        }
    )
    snapshot = snapshot.model_copy(update={"account": identity})
    command = command.model_copy(update={"account": identity, "profile_hash": p.digest})
    config = lab_config(p, snapshot, REQUEST_KEY, RESPONSE_KEY, ORIGIN, uuid4())
    return config, command


class FakeBridge:
    def __init__(self, command=None, *, mutate=None, drop=False):
        self.command, self.mutate, self.drop = command, mutate, drop
        self.requests, self.events = [], []
        self.highwater = 0
        self.sent = False

    def __call__(self, request):
        if self.drop:
            raise httpx.ConnectError("synthetic contact loss")
        env = Envelope.verify(
            request.headers,
            REQUEST_KEY,
            request.content,
            request.url.path,
            now=int(datetime.now(UTC).timestamp()),
        )
        assert env.sequence > self.highwater
        self.highwater = env.sequence
        value = strict_json(request.content)
        self.requests.append((request.url.path, value))
        if request.url.path.endswith("events"):
            self.events.extend(value["events"])
            result = {"accepted": [e["event_id"] for e in value["events"]]}
        elif request.url.path.endswith("snapshot"):
            result = {"status": "RECONCILED"}
        elif self.command and not self.sent:
            from base64 import b64encode
            from hashlib import sha256

            payload = json_bytes(self.command)
            result = {
                "status": "DELIVERED",
                "command": b64encode(payload).decode(),
                "command_hash": sha256(payload).hexdigest(),
                "safety_epoch": 1,
            }
            self.sent = True
        else:
            result = {"status": "NO_COMMAND", "command": None}
        raw = json_bytes(result)
        headers = env.headers(RESPONSE_KEY, raw, request.url.path, direction="RESPONSE", status=200)
        if self.mutate:
            raw, headers = self.mutate(raw, headers)
        if headers.get("content-encoding") == "gzip":
            import gzip

            raw = gzip.compress(raw)
        return httpx.Response(200, stream=httpx.ByteStream(raw), headers=headers)
