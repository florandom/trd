from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.application.domain_bootstrap import MOCK_MODEL
from backend.domain.contracts import AgentConfiguration, Proposal, RiskPolicy
from backend.domain.lifecycle import Evidence, InvalidTransition, validate_transition


def test_transport_acknowledgement_is_not_a_fill():
    validate_transition("command", "DELIVERED", "ACKNOWLEDGED")
    for kind, before, after in (
        ("command", "ACKNOWLEDGED", "COMPLETED"),
        ("order", "SENT", "FILLED"),
        ("signal", "EXECUTION_REQUESTED", "EXECUTED"),
    ):
        with pytest.raises(InvalidTransition, match="evidence"):
            validate_transition(kind, before, after)
        validate_transition(kind, before, after, Evidence.BROKER_FILL)


def test_unknown_outcomes_require_reconciliation_and_cannot_be_retried():
    for kind in ("order", "command"):
        validate_transition(kind, "OUTCOME_UNKNOWN", "RECONCILING")
        for after in ("SENT", "READY", "EXPIRED", "FAILED"):
            with pytest.raises(InvalidTransition):
                validate_transition(kind, "OUTCOME_UNKNOWN", after)
        with pytest.raises(InvalidTransition):
            validate_transition(kind, "RECONCILING", "REJECTED")
        validate_transition(kind, "RECONCILING", "REJECTED", Evidence.RECONCILED_ABSENT)


def test_terminal_states_cannot_restart_a_trade_or_approve_escalation():
    for kind, before, after in (
        ("signal", "EXECUTED", "APPROVED"),
        ("signal", "ESCALATED", "APPROVED"),
        ("order", "FILLED", "SENT"),
        ("command", "COMPLETED", "READY"),
    ):
        with pytest.raises(InvalidTransition):
            validate_transition(kind, before, after)


@pytest.mark.parametrize("value", [0.01, True, "NaN", "Infinity", "0", "-0.01", "1.01"])
def test_financial_values_reject_inexact_nonfinite_and_invalid_fractions(value):
    with pytest.raises(ValidationError):
        RiskPolicy(max_risk_per_trade=value)


def test_later_configuration_can_only_tighten_the_safety_envelope():
    ceiling = RiskPolicy(max_risk_per_trade="0.01", max_open_positions=3)
    RiskPolicy(max_risk_per_trade="0.01", max_open_positions=3).within(ceiling)
    RiskPolicy().within(ceiling)
    with pytest.raises(ValueError, match="safety envelope"):
        RiskPolicy(max_risk_per_trade="0.0100000001").within(ceiling)
    assert RiskPolicy().model_dump(mode="json")["max_risk_per_trade"] == "0.005"
    assert isinstance(RiskPolicy().max_risk_per_trade, Decimal)


def test_proposals_require_aware_time_and_protective_prices():
    values = dict(
        symbol="EURUSD",
        side="BUY",
        entry="1.1",
        stop_loss="1.09",
        take_profit="1.12",
        expires_at="2026-10-08T15:00:00+02:00",
    )
    assert Proposal(**values).expires_at == datetime(2026, 10, 8, 13, tzinfo=UTC)
    for change in (
        {"expires_at": "2026-10-08T13:00:00"},
        {"stop_loss": "1.11"},
        {"side": "SELL"},
        {"entry": 1.1},
        {"unexpected": "ignored?"},
    ):
        with pytest.raises(ValidationError):
            Proposal(**(values | change))


def test_agent_configs_use_only_compatible_registry_entries_and_bounded_fallbacks():
    config = AgentConfiguration(primary_model_id="mock-v1", prompt_version=1)
    config.validate_models({"mock-v1": MOCK_MODEL})
    for models in (
        {},
        {"mock-v1": MOCK_MODEL.model_copy(update={"enabled": False})},
        {"mock-v1": MOCK_MODEL.model_copy(update={"schema_version": 2})},
        {"mock-v1": MOCK_MODEL.model_copy(update={"max_output_tokens": 1})},
    ):
        with pytest.raises(ValueError, match="incompatible"):
            config.validate_models(models)
    with pytest.raises(ValidationError):
        AgentConfiguration(
            primary_model_id="mock-v1", prompt_version=1, fallback_model_ids=("mock-v1",)
        )
    with pytest.raises(ValidationError):
        AgentConfiguration(
            primary_model_id="mock-v1", prompt_version=1, fallback_model_ids=("a", "b", "c")
        )
