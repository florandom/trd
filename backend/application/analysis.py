"""Bounded offline analysis; every proposal still waits for the future risk gateway."""

import logging
from dataclasses import replace
from hashlib import sha256
from time import monotonic
from uuid import uuid4

from backend.ai.acceptance import configured_provider
from backend.ai.providers import AIProvider, ProviderRequest, ProviderResponse
from backend.domain.analysis import (
    STAGES,
    AgentResult,
    AnalysisJob,
    AnalysisResult,
    CostLimits,
    Reason,
    estimated_cost,
    parse_message,
)
from backend.domain.config import AiSettings
from backend.infrastructure.analysis_repository import AnalysisStore, BudgetExhausted
from backend.infrastructure.repositories import VersionConflict


class AnalysisWorker:
    def __init__(
        self, settings: AiSettings, store: AnalysisStore, provider: AIProvider | None = None
    ):
        self.settings, self.store = settings, store
        self.provider = provider or configured_provider(settings)
        self.worker_id = str(uuid4())
        self.logger = logging.getLogger("trd.analysis")

    def process_one(self) -> bool:
        lease = self.store.claim(self.worker_id, self.settings.ai_job_lease_seconds)
        if lease is None:
            return True
        try:
            self.process(lease)
            return True
        except VersionConflict:
            # Revisions and source disablement may have already killed the job.
            self.logger.info(
                "Analysis ownership or input changed", extra={"job_id": str(lease.job_id)}
            )
            try:
                self.store.fail(lease, self.worker_id)
            except VersionConflict:
                pass
            return False
        except Exception as error:
            self.logger.warning(
                "Analysis job failed",
                extra={"job_id": str(lease.job_id), "error_type": type(error).__name__},
            )
            try:
                self.store.fail(lease, self.worker_id)
            except VersionConflict:
                pass
            return False

    def process(self, lease):
        job = AnalysisJob.model_validate(lease.payload)
        snapshot = self.store.snapshot(lease, self.worker_id)
        parsed = parse_message(
            snapshot["body"],
            published_at=snapshot["published_at"],
            now=snapshot["now"],
            max_age_seconds=self.settings.ai_signal_max_age_seconds,
            review_only=job.review_only
            or job.message_version != 1
            or snapshot["event_kind"] != "NEW",
            reply=snapshot["reply_message_id"] is not None,
        )
        versions = {}
        trace = uuid4()
        outcome, reasons = parsed.outcome, list(parsed.reason_codes)
        if parsed.proposal is not None:
            agents, models = snapshot["agents"], snapshot["models"]
            critic = agents.get("CRITIC")
            stages = (
                (*STAGES, "CRITIC")
                if (
                    self.settings.enable_critic_agent
                    or (critic is not None and critic.config.enabled)
                )
                else STAGES
            )
            reason = None
            if self.store.has_unresolved(lease.job_id):
                reason = Reason.UNKNOWN_USAGE
            for stage in stages:
                if reason is not None:
                    break
                agent = agents.get(stage)
                if agent is None or not agent.config.enabled:
                    reason = Reason.AGENT_DISABLED
                    break
                versions[stage] = agent.version
                if (
                    agent.config.prompt_version != 2
                    or sha256(agent.prompt.encode("utf-8")).hexdigest() != agent.prompt_checksum
                ):
                    reason = Reason.PROMPT_UNAVAILABLE
                    break
                try:
                    agent.config.validate_models(models)
                except ValueError:
                    reason = Reason.MODEL_UNAVAILABLE
                    break
                selected = [
                    models[m]
                    for m in (agent.config.primary_model_id, *agent.config.fallback_model_ids)
                ]
                if any(
                    model.provider != "mock"
                    and (
                        stage in STAGES[:2]
                        or self.settings.ai_provider_mode != "openrouter"
                        or model.provider != "openrouter"
                        or model.accepted_environment_id != self.settings.environment_id
                        or model.accepted_until is None
                        or model.accepted_until <= snapshot["now"]
                        or model.input_token_limit > self.settings.ai_hard_max_input_tokens
                    )
                    for model in selected
                ):
                    reason = Reason.PROVIDER_DISABLED
                    break
            if reason is not None:
                outcome, reasons = "ESCALATED", [reason, Reason.RISK_NOT_IMPLEMENTED]
            else:
                # One application deadline covers every mandatory stage and fallback.
                deadline = monotonic() + self.settings.ai_hard_timeout_seconds
                reasons = [Reason.RISK_NOT_IMPLEMENTED]
                for stage in stages[2:]:
                    agent = agents[stage]
                    response = None
                    for attempt, model_id in enumerate(
                        (agent.config.primary_model_id, *agent.config.fallback_model_ids), 1
                    ):
                        current = self.store.snapshot(lease, self.worker_id)
                        if monotonic() >= deadline or parsed.proposal.expires_at <= current["now"]:
                            response = ProviderResponse(None, None, Reason.PROVIDER_TIMEOUT)
                            break
                        model = models[model_id]
                        output_ceiling = min(
                            agent.config.max_output_tokens, self.settings.ai_hard_max_output_tokens
                        )
                        input_ceiling = (
                            model.input_token_limit if model.provider == "openrouter" else 0
                        )
                        try:
                            reservation = self.store.reserve(
                                lease,
                                self.worker_id,
                                agent,
                                model,
                                attempt,
                                input_ceiling,
                                output_ceiling,
                                CostLimits(
                                    daily_usd=self.settings.ai_hard_daily_budget_usd,
                                    monthly_usd=self.settings.ai_hard_monthly_budget_usd,
                                    request_usd=self.settings.ai_hard_max_cost_per_request_usd,
                                    agent_daily_usd=self.settings.ai_hard_daily_budget_per_agent_usd,
                                ),
                            )
                        except BudgetExhausted:
                            response = ProviderResponse(None, None, Reason.BUDGET_EXHAUSTED)
                            break
                        started = monotonic()
                        request = ProviderRequest(
                            stage,
                            model,
                            agent.prompt,
                            parsed.proposal,
                            output_ceiling,
                            min(deadline, started + agent.config.timeout_seconds),
                        )
                        try:
                            response = self.provider.generate(request)
                            if monotonic() >= request.deadline:
                                response = replace(
                                    response, result=None, error=Reason.PROVIDER_TIMEOUT
                                )
                            if response.result is not None:
                                AgentResult.model_validate(response.result.model_dump())
                        except Exception:
                            response = ProviderResponse(None, None, Reason.PROVIDER_UNAVAILABLE)
                        usage = response.usage
                        valid_usage = (
                            usage is not None
                            and usage.input_tokens <= input_ceiling
                            and (usage.output_tokens <= output_ceiling)
                            and (model.provider != "openrouter" or usage.cost_usd is not None)
                            and (
                                usage.cost_usd is None
                                or usage.cost_usd
                                <= estimated_cost(
                                    input_ceiling,
                                    output_ceiling,
                                    model.input_price_per_million,
                                    model.output_price_per_million,
                                )
                            )
                        )
                        self.store.settle(
                            reservation,
                            self.worker_id,
                            {
                                "trace_id": str(trace),
                                "status": "SUCCEEDED"
                                if response.result
                                else (
                                    "REFUSED"
                                    if response.error == Reason.PROVIDER_REFUSAL
                                    else "FAILED"
                                ),
                                "input_tokens": usage.input_tokens if usage else 0,
                                "output_tokens": usage.output_tokens if usage else 0,
                                "usage_known": valid_usage,
                                "reported_cost_usd": format(usage.cost_usd, "f")
                                if usage and usage.cost_usd is not None
                                else None,
                                "generation_id": response.generation_id,
                                "provider_name": response.provider_name,
                                "latency_ms": int((monotonic() - started) * 1000),
                                "error_code": str(response.error) if response.error else None,
                                "advisory": response.result.model_dump(mode="json")
                                if response.result
                                else None,
                            },
                        )
                        if not valid_usage:
                            response = ProviderResponse(None, None, Reason.UNKNOWN_USAGE)
                        if response.result or response.error not in {
                            Reason.PROVIDER_UNAVAILABLE,
                            Reason.PROVIDER_RATE_LIMIT,
                        }:
                            break
                        # Retry-After is respected by refusing an immediate fallback.
                        # No sleeps or unbounded request retries inside a held job lease.
                        if response.retry_after_seconds:
                            break
                    if response is None or response.result is None:
                        outcome = "ESCALATED"
                        reasons.append(
                            response.error if response and response.error else Reason.INVALID_OUTPUT
                        )
                        break
                    reasons.extend(response.result.reason_codes)
                    if response.result.action in {"REJECT", "ESCALATE"}:
                        outcome = (
                            "REJECTED_AI" if response.result.action == "REJECT" else "ESCALATED"
                        )
                        break
        result = AnalysisResult(
            **parsed.model_dump(exclude={"outcome", "reason_codes"}),
            outcome=outcome,
            reason_codes=tuple(dict.fromkeys(reasons))[:12],
            input_hash=snapshot["body_hash"],
            trace_id=trace,
            config_versions=versions,
        )
        # Time is re-read at completion. Expired proposals lose authority rather than
        # being persisted as fresh after a slow provider result.
        latest = self.store.snapshot(lease, self.worker_id)
        if result.proposal is not None and result.proposal.expires_at <= latest["now"]:
            result = result.model_copy(
                update={
                    "proposal": None,
                    "outcome": "EXPIRED",
                    "reason_codes": (Reason.STALE_MESSAGE,),
                }
            )
        self.store.complete(lease, self.worker_id, result)
