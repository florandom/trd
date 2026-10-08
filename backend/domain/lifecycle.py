"""Pure lifecycle rules. Transport acknowledgements are never broker fills."""

from enum import StrEnum


class SignalState(StrEnum):
    RECEIVED = "RECEIVED"
    CLASSIFIED = "CLASSIFIED"
    PARSED = "PARSED"
    ANALYZING = "ANALYZING"
    DECIDED = "DECIDED"
    WAITING = "WAITING"
    ESCALATED = "ESCALATED"
    RISK_CHECK = "RISK_CHECK"
    APPROVED = "APPROVED"
    EXECUTION_REQUESTED = "EXECUTION_REQUESTED"
    RECONCILING = "RECONCILING"
    EXECUTED = "EXECUTED"
    IGNORED = "IGNORED"
    REJECTED_AI = "REJECTED_AI"
    REJECTED_RISK = "REJECTED_RISK"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class OrderState(StrEnum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    REQUESTED = "REQUESTED"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECONCILING = "RECONCILING"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELED = "CANCELED"


class CommandState(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECONCILING = "RECONCILING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class Evidence(StrEnum):
    OBSERVATION = "OBSERVATION"
    BROKER_ACCEPTANCE = "BROKER_ACCEPTANCE"
    BROKER_FILL = "BROKER_FILL"
    BROKER_PARTIAL_FILL = "BROKER_PARTIAL_FILL"
    BROKER_REJECTION = "BROKER_REJECTION"
    BROKER_CANCEL = "BROKER_CANCEL"
    RECONCILED_FILL = "RECONCILED_FILL"
    RECONCILED_ABSENT = "RECONCILED_ABSENT"


SIGNAL_TRANSITIONS = {
    "RECEIVED": {"CLASSIFIED", "EXPIRED", "FAILED"},
    "CLASSIFIED": {"PARSED", "IGNORED", "EXPIRED", "FAILED"},
    "PARSED": {"ANALYZING", "DECIDED", "EXPIRED", "FAILED"},
    "ANALYZING": {"DECIDED", "EXPIRED", "FAILED"},
    "DECIDED": {"WAITING", "ESCALATED", "REJECTED_AI", "RISK_CHECK", "EXPIRED", "FAILED"},
    "WAITING": {"DECIDED", "EXPIRED", "FAILED"},
    "ESCALATED": {"EXPIRED", "FAILED"},
    "RISK_CHECK": {"APPROVED", "REJECTED_RISK", "EXPIRED", "FAILED"},
    "APPROVED": {"EXECUTION_REQUESTED", "EXPIRED", "FAILED"},
    "EXECUTION_REQUESTED": {"EXECUTED", "RECONCILING"},
    "RECONCILING": {"EXECUTED", "FAILED"},
}
ORDER_TRANSITIONS = {
    "PROPOSED": {"VALIDATED", "REJECTED", "EXPIRED", "FAILED"},
    "VALIDATED": {"REQUESTED", "REJECTED", "EXPIRED", "FAILED"},
    "REQUESTED": {"SENT", "OUTCOME_UNKNOWN"},
    "SENT": {"ACCEPTED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "OUTCOME_UNKNOWN"},
    "ACCEPTED": {"PARTIALLY_FILLED", "FILLED", "CANCELED", "OUTCOME_UNKNOWN"},
    "PARTIALLY_FILLED": {"FILLED", "CANCELED", "OUTCOME_UNKNOWN"},
    "OUTCOME_UNKNOWN": {"RECONCILING"},
    "RECONCILING": {"PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELED"},
}
COMMAND_TRANSITIONS = {
    "CREATED": {"READY", "EXPIRED", "INVALIDATED"},
    "READY": {"DELIVERED", "EXPIRED", "INVALIDATED"},
    "DELIVERED": {"ACKNOWLEDGED", "OUTCOME_UNKNOWN", "COMPLETED", "REJECTED"},
    "ACKNOWLEDGED": {"COMPLETED", "REJECTED", "OUTCOME_UNKNOWN"},
    "OUTCOME_UNKNOWN": {"RECONCILING"},
    "RECONCILING": {"COMPLETED", "REJECTED"},
}
TRANSITIONS = {
    "signal": SIGNAL_TRANSITIONS,
    "order": ORDER_TRANSITIONS,
    "command": COMMAND_TRANSITIONS,
}
STATES = {"signal": SignalState, "order": OrderState, "command": CommandState}


class InvalidTransition(ValueError):
    pass


def validate_transition(
    kind: str, before: str, after: str, evidence: Evidence = Evidence.OBSERVATION
) -> None:
    if kind not in TRANSITIONS or after not in TRANSITIONS[kind].get(before, set()):
        raise InvalidTransition("lifecycle transition is not allowed")
    required: set[Evidence] | None = None
    if after in {"EXECUTED", "FILLED", "COMPLETED"}:
        required = {Evidence.BROKER_FILL, Evidence.RECONCILED_FILL}
    elif kind == "order" and after == "PARTIALLY_FILLED":
        required = {Evidence.BROKER_PARTIAL_FILL}
    elif kind == "order" and after == "ACCEPTED":
        required = {Evidence.BROKER_ACCEPTANCE}
    elif after == "CANCELED":
        required = {Evidence.BROKER_CANCEL}
    elif after in {"REJECTED", "FAILED"} and before in {
        "SENT",
        "DELIVERED",
        "ACKNOWLEDGED",
        "RECONCILING",
    }:
        required = {Evidence.BROKER_REJECTION, Evidence.RECONCILED_ABSENT}
    if required is not None and evidence not in required:
        raise InvalidTransition("broker or reconciliation evidence is required")
