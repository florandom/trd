# Domain and database contracts

The foundation below was implemented in Phase 2 on 8 October 2026. Phase 4 adds the
read-only Telegram collector and its fenced storage contract. Phase 5 adds offline
advisory analysis and spend accounting; risk evaluation,
external providers and trade execution remain unavailable. Historical foundation
[validation](PHASE_2_VALIDATION.md) and [current Telegram evidence](PHASE_4_VALIDATION.md)
record their separate acceptance scopes.

## Phase 5 additions

Revision `0005_analysis` adds append-only analysis receipts and protected provider
spend reservations, for 41 mapped tables. Role-authenticated functions bind attempts
and completion to current job generation, source/message/config versions and expiry.
Provider calls hold no transaction. Completion atomically persists the receipt,
optional advisory signal, legal transitions, audit/outbox and completed job.
No risk approval or broker command is generated. Safe API views include analysis,
signal attempts and unresolved budget holds. [Analysis contract](ANALYSIS.md).

## Phase 4 additions

Revision `0004_telegram` brings the schema to 39 tables, adding account leases and
source recovery state. It extends source configuration/resolution and immutable
message versions with event kind, semantic revision digest, publication date and
media metadata. The collector uses lease-fenced SQL functions; direct anchor/version
INSERT is revoked. Dashboard source changes use the existing confirmed ADMIN workflow.
Safe source and latest-message views expose status and bounded text previews while
withholding session credentials and peer access hashes. Disable/edit/delete invalidate
pending analysis and unsent proposals without rewriting delivered commands or
reservation evidence. [The Telegram contract](TELEGRAM.md) defines recovery bounds.

## Records and boundaries

The five foundation tables remain. Revision `0002_domain` adds 29 tables covering sessions, enrolled-account identities, Telegram anchors/versions, signals/versions, agents/configs/fallbacks/prompts, model manifests, runs/usage, risk rules/current pointers/events/approvals/reservations, commands/events, orders/positions/economic events, lifecycle history, health observations, jobs, outbox and compact trade memory.

Environment-scoped records use composite keys and references; financial chains also carry account identity through their foreign keys. A message version cannot be attached to a signal from another message or environment; a financial child cannot silently switch its account. These checks prevent accidental associations; service credentials belong to one deployment database. The database is not a multi-tenant security boundary, and arbitrary runtime roles are not isolated from other environment labels in that same database.

Money, prices, volume and estimated costs use `NUMERIC(28,10)` with nonnegative/positive bounds and NaN rejection. Python contracts reject floating-point values, booleans and nonfinite decimal inputs. JSON financial values are decimal strings. Broker logins/tickets remain text, including values larger than JavaScript's safe integer range. UTC-aware timestamps are mandatory at domain boundaries; observation time and database creation time are distinct.

Financial accounting bounds do not implement the Phase 6 risk engine. Account enrollment, fresh market/account snapshots, valuation, budget reservations, replay journals, broker-event authentication and reconciliation adapters arrive in their respective later phases.

## Lifecycles and transactions

Signals, transport commands and broker orders have separate explicit lifecycles. Receipt/acceptance does not mean execution. Completion/fill requires declared broker or reconciliation evidence. Unknown outcomes cannot return to delivery/submission or become expired; they enter reconciliation. The trusted risk role supplies validated broker evidence in later integration work; these storage functions do not authenticate external events themselves.

State changes use expected revisions and immutable event IDs. Repeating an identical event returns its original receipt; changing the payload under the same event ID is rejected. State, lifecycle history, audit and outbox commit in one transaction. Repositories share their caller's transaction and never commit inside an operation. A failed or interrupted transaction leaves no partial transition or event.

Message identities deduplicate concurrent deliveries. Later edits create versions; older deliveries do not overwrite a newer edit. Signal intents deduplicate concurrent creation. Appending a proposal version invalidates associated CREATED/READY commands, records those transitions and releases their HELD reservations. Submitted/unknown commands and their reservations remain unchanged. Editing a message creates no new approval or trade. Later risk validation must bind its approval to the current proposal version, policy and safety epoch before delivery.

`DomainTransaction` closes every connection and rolls back errors. Engine pools may be shared, but transactions must not cross threads or network waits. This follows [SQLAlchemy's transaction/session guidance](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).

## Configuration and registry

Bootstrap creates six disabled agents, conservative risk policy version 1 and only the deterministic zero-cost offline model `mock-v1`. The seed prompts explicitly treat incoming text and URLs as untrusted data and prohibit policy changes, secret requests and tool use. These are disabled placeholders, not implemented agent behavior.

Agent configuration references an existing prompt and registry entry. Publication validates enabled availability, matching output-schema capability, token ceilings and a unique fallback list limited to three total attempts. Risk-policy publication validates an explicit trusted server ceiling. Both preserve old versions, advance a current pointer under a lock, check expected versions, require an active administrator and record audit atomically.

Agent/risk/model publication currently requires the operator database role. The ordinary API cannot write those tables. Registry pricing/capability manifests are immutable; reviewed changes require a new registry ID. Operator availability toggles are audited, and bootstrap preserves them. No real provider model or pricing is seeded or fetched.

The API's narrowly scoped setting function permits retention periods, paper mode and disabling automation/live. It rejects enabling execution, live mode, unknown keys, malformed values, inactive users, VIEWER actors and stale versions. It is not exposed through HTTP in Phase 2; session/RBAC/CSRF routes belong to Phase 3.

## Database permissions

| Identity | Domain capability |
| --- | --- |
| Operator/migrator | Explicit schema/bootstrap; reviewed configuration and model publication |
| API | Sanitized read views; audited bounded setting function with active ADMIN actor |
| Collector | Read allowed sources and message history; append messages/versions; own job queue |
| AI | Read source/signal/registry/config data; append advisory versions/runs/usage; pre-risk signal transitions; own job queue |
| Risk | Read policies/proposals/accounts; append trusted execution/economic records; limited projection updates; protected lifecycle function; own job queue |
| Maintenance | Configured bounded raw-evidence cleanup and own job queue; no direct evidence deletion |

Runtime roles cannot become owner, rewrite configuration history/audit, create schema objects, read password hashes or use PUBLIC functions. The AI/API/collector/maintenance identities cannot create trade approval, release risk reservations or mutate command state. Risk cannot write risk-policy versions. Callable functions derive authority from `session_user`, fix their search path, qualify table names and have explicit execution grants. The risk signer, deployed code and database administrator remain trusted boundaries.

## Retention and durable work

`pnpm retention:run` uses only the scoped maintenance environment. Each invocation reads the current Telegram/AI retention settings, defaults to seven days and erases at most 100 raw bodies of each type. Identifiers, hashes, validated proposals/results, configuration versions, audit, trades and compact memory remain. Active signals, held/unknown reservations, outstanding commands/orders, open positions and unfinished/unknown AI outcomes preserve their raw evidence.

Cleanup and evidence-producing writes share an environment advisory transaction lock. This deliberately conservative fence prevents pruning while a protected association is being created. It serializes evidence mutations within an environment; finer-grained throughput work must retain the same safety property. Interrupted cleanup rolls back and the next invocation resumes safely. There is no periodic scheduler in this phase.

Jobs deduplicate by environment/service/key, reject conflicting payloads, claim with `FOR UPDATE SKIP LOCKED`, carry expiring leases and increasing generations, and reject completion by a stale worker/generation. Retry counts and backoff are bounded; exhausted leases enter DEAD. Queue ownership comes from the database login. Outbox records persist with business changes; no external dispatcher is active yet. These jobs do not authorize broker-send retries. Broker uncertainty still requires the separate reconciliation lifecycle. [PostgreSQL row locking](https://www.postgresql.org/docs/17/sql-select.html)

The Italian dashboard has authenticated operational and configuration pages, including
local analysis. Readiness confirms the current database migration with paper mode and
automation disabled; it does not certify Telegram, external AI or broker availability.
