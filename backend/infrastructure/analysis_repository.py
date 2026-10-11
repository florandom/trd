"""Analysis I/O uses short transactions. Provider calls never hold database locks."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.exc import DBAPIError

from backend.domain.analysis import AnalysisResult, CostLimits
from backend.domain.contracts import AgentConfiguration, ModelDefinition
from backend.infrastructure.domain_models import (
    Agent,
    AgentConfig,
    AgentFallback,
    AIBudgetReservation,
    PromptVersion,
)
from backend.infrastructure.repositories import JobLease, JobRepository, ScopedRepository


class BudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True, repr=False)
class AgentDefinition:
    id: UUID
    name: str
    version: int
    config: AgentConfiguration
    prompt: str
    prompt_checksum: str


class AnalysisStore:
    def __init__(self, engine: Engine, environment_id: str):
        self.engine, self.environment_id = engine, environment_id

    def claim(self, worker: str, seconds: int) -> JobLease | None:
        with self.engine.begin() as connection:
            return JobRepository(connection, self.environment_id).claim(
                worker, lease_seconds=seconds
            )

    def has_unresolved(self, job_id: UUID) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.scalar(
                    select(AIBudgetReservation.id)
                    .where(
                        AIBudgetReservation.environment_id == self.environment_id,
                        AIBudgetReservation.job_id == job_id,
                        AIBudgetReservation.state.in_(("RESERVED", "UNKNOWN")),
                    )
                    .limit(1)
                )
                is not None
            )

    def snapshot(self, lease: JobLease, worker: str) -> dict:
        with self.engine.begin() as connection:
            repo = ScopedRepository(connection, self.environment_id)
            result = repo.call(
                "SELECT public.analysis_assert_job(:environment,:job,:worker,:generation)",
                {"job": lease.job_id, "worker": worker, "generation": lease.generation},
            ).scalar_one()
            result["now"] = datetime.fromisoformat(result["now"])
            result["published_at"] = datetime.fromisoformat(result["published_at"])
            configs = (
                connection.execute(
                    select(
                        Agent.name,
                        Agent.id,
                        Agent.current_version,
                        AgentConfig,
                        PromptVersion.body,
                        PromptVersion.checksum,
                    )
                    .join(
                        AgentConfig,
                        (AgentConfig.environment_id == Agent.environment_id)
                        & (AgentConfig.agent_id == Agent.id)
                        & (AgentConfig.version == Agent.current_version),
                    )
                    .join(
                        PromptVersion,
                        (PromptVersion.environment_id == Agent.environment_id)
                        & (PromptVersion.agent_id == Agent.id)
                        & (PromptVersion.version == AgentConfig.prompt_version),
                    )
                    .where(Agent.environment_id == self.environment_id)
                )
                .mappings()
                .all()
            )
            agents = {}
            for row in configs:
                fallbacks = tuple(
                    connection.scalars(
                        select(AgentFallback.model_id)
                        .where(
                            AgentFallback.environment_id == self.environment_id,
                            AgentFallback.agent_id == row["id"],
                            AgentFallback.config_version == row["current_version"],
                        )
                        .order_by(AgentFallback.ordinal)
                    )
                )
                fields = {
                    name: row[name]
                    for name in AgentConfiguration.model_fields
                    if name != "fallback_model_ids"
                }
                config = AgentConfiguration(**fields, fallback_model_ids=fallbacks)
                agents[row["name"]] = AgentDefinition(
                    row["id"],
                    row["name"],
                    row["current_version"],
                    config,
                    row["body"],
                    row["checksum"],
                )
            from backend.infrastructure.domain_models import ModelRegistry

            models = {
                row["id"]: ModelDefinition.model_validate(dict(row))
                for row in connection.execute(select(ModelRegistry)).mappings()
            }
            result.update(agents=agents, models=models)
            return result

    def reserve(
        self,
        lease: JobLease,
        worker: str,
        agent: AgentDefinition,
        model: ModelDefinition,
        attempt: int,
        input_ceiling: int,
        output_ceiling: int,
        limits: CostLimits,
    ) -> UUID:
        try:
            with self.engine.begin() as connection:
                # Preserve SQLSTATE for this specific, non-sensitive policy failure.
                from sqlalchemy import bindparam, text
                from sqlalchemy.dialects.postgresql import JSONB

                statement = text(
                    "SELECT public.analysis_reserve_attempt(:environment,:job,:worker,"
                    ":generation,:agent,:config,:model,:attempt,:input,:output,:limits)"
                ).bindparams(bindparam("limits", type_=JSONB))
                return connection.scalar(
                    statement,
                    {
                        "environment": self.environment_id,
                        "job": lease.job_id,
                        "worker": worker,
                        "generation": lease.generation,
                        "agent": agent.id,
                        "config": agent.version,
                        "model": model.id,
                        "attempt": attempt,
                        "input": input_ceiling,
                        "output": output_ceiling,
                        "limits": limits.model_dump(mode="json"),
                    },
                )
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "P0001":
                raise BudgetExhausted("AI cost envelope exhausted") from None
            if getattr(error.orig, "sqlstate", None) == "40001":
                from backend.infrastructure.repositories import VersionConflict

                raise VersionConflict("analysis ownership or configuration changed") from None
            raise RuntimeError("analysis reservation rejected") from None

    def settle(self, reservation: UUID, worker: str, result: dict) -> None:
        with self.engine.begin() as connection:
            ScopedRepository(connection, self.environment_id).call(
                "SELECT public.analysis_settle_attempt(:environment,:reservation,:worker,:result)",
                {"reservation": reservation, "worker": worker, "result": result},
                "result",
            )

    def complete(self, lease: JobLease, worker: str, result: AnalysisResult) -> UUID:
        with self.engine.begin() as connection:
            return (
                ScopedRepository(connection, self.environment_id)
                .call(
                    "SELECT public.analysis_complete("
                    ":environment,:job,:worker,:generation,:result)",
                    {
                        "job": lease.job_id,
                        "worker": worker,
                        "generation": lease.generation,
                        "result": result.model_dump(mode="json"),
                    },
                    "result",
                )
                .scalar_one()
            )

    def fail(self, lease: JobLease, worker: str) -> None:
        with self.engine.begin() as connection:
            JobRepository(connection, self.environment_id).finish(
                lease, worker_id=worker, success=False
            )
