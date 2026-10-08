# Autonomous trading orchestration platform

Phase 2 implements the domain/database foundation on top of the local infrastructure: explicit lifecycles, immutable configuration history, scoped repositories, the offline model registry, transactional audit/outbox and protected raw-data retention. The Italian dashboard reports real API/database readiness. Trading, external AI calls, Telegram collection and broker commands are disabled. Authentication and administrative controls arrive in Phase 3; keep this foundation on loopback.

## Local boot

Use Node **24.20.0**, pnpm **11.25.0**, uv **0.12.22**, and a running Linux Docker engine with Compose. uv installs the pinned Python **3.13.16** interpreter. Version files, lockfiles and container image digests are committed. Docker Desktop or Colima can supply the macOS engine. If your installation exposes Compose as `docker-compose`, substitute that executable for `docker compose` below.

This macOS workspace uses an isolated Colima profile without changing the default Docker context. To use it from a new terminal:

```sh
colima start --profile trd-phase1 --activate=false --ssh-config=false
export DOCKER_HOST="unix://$HOME/.colima/trd-phase1/docker.sock"
```

uv was installed locally at `.tools/uv/bin/uv` here; the workspace scripts detect it. A fresh clone needs uv0.12.22 in PATH. [uv installation](https://docs.astral.sh/uv/getting-started/installation/) describes supported installation methods.

From a fresh checkout:

```sh
uv sync --frozen
pnpm install --frozen-lockfile
pnpm setup
docker compose up --build -d
```

`pnpm setup` creates a private ignored `.env` with unique random database passwords, bootstrap password and purpose-specific keys. Running it again preserves existing values. The one-shot `initialize` container provisions restricted database roles, applies migrations and creates the administrator/default settings without resetting existing data. No manual SQL setup is required.

Open [the dashboard](http://localhost:3000). Its status should become **Connessione verificata** after initialization. [API readiness](http://127.0.0.1:8000/health/ready) returns 200 only when PostgreSQL and the expected migration revision are available; otherwise it returns 503. Bridge liveness is at port 8001. Ready describes this foundation, not a functioning trading pipeline.

```sh
docker compose ps
docker compose stop
```

Stopping preserves database volumes. Run `docker compose start` to resume. Avoid removing volumes if the local data is needed. Redis is available on loopback port 6379 but is optional and unused by foundation correctness.

## Host development

Start only PostgreSQL and optional Redis in containers, then run the cross-platform development supervisor:

```sh
docker compose stop
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
pnpm dev
```

This initializes the database, then starts the API, isolated bridge, AI placeholder, collector placeholder, maintenance heartbeat and dashboard as separate processes. Each receives a scoped environment and its own database role. Ctrl+C stops the children. This supervisor is for local development; production service management belongs to deployment work.

Standalone tasks are `pnpm db:provision`, `pnpm db:migrate` and `pnpm db:bootstrap`. Ports and the internal API origin are configured in `.env.example`; change them before `pnpm setup` when the defaults are occupied. After changing an existing database port, update its role URLs and `API_INTERNAL_URL` consistently.

## Checks

```sh
pnpm check
pnpm api:generate
git diff --exit-code -- packages/shared-types
```

`pnpm check` runs Python lint/unit tests and frontend typecheck, lint, tests and production build. PostgreSQL integration tests require an explicit `TEST_ADMIN_DATABASE_URL`; they create and drop only random `trd_test_*` databases. Never supply a production server. CI includes these integration tests and Windows foundation-script checks. See [Phase 2 validation evidence](docs/PHASE_2_VALIDATION.md) and the [earlier infrastructure validation](docs/PHASE_1_VALIDATION.md) for results and limits.

## Structure and documentation

| Location | Responsibility |
| --- | --- |
| `apps/dashboard` | Next.js/Astryx read-only foundation shell |
| `apps/api`, `apps/worker`, `apps/telegram`, `apps/simulator` | Separate Python composition/placeholder entrypoints |
| `backend` | Strict domain contracts, lifecycle rules, scoped persistence, versioning, audit and retention |
| `packages/shared-types` | Generated OpenAPI contracts and public types |
| `migrations` | Explicit Alembic schema and least-privilege grants |
| `infra` | Container packaging, operator tasks and Windows previews |
| `tests` | Configuration, security boundary and PostgreSQL verification |

- [Environment and secret scoping](docs/ENVIRONMENT.md)
- [Architecture](docs/ARCHITECTURE.md), [threat model](docs/THREAT_MODEL.md) and [decisions](docs/adr/README.md)
- [Domain/database contracts and permissions](docs/DOMAIN_DATABASE.md)
- [Windows deployment foundation](docs/DEPLOYMENT_WINDOWS.md)
- [Dashboard implementation notes](apps/dashboard/README.md)
- [Phase 0 approval record](docs/PHASE_0_APPROVAL.md)

The simulator entrypoint reports liveness only; it does not simulate execution yet. The deterministic risk engine, AI orchestration, MT5 EA and recovery pipeline remain later phases. Windows native services, MT5, TLS, real broker behavior and reboot recovery require tests on the target Windows host.
