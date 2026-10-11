# Phase 5 local advisory analysis

Implemented 11 October 2026. Acceptance is offline paper analysis with synthetic
Telegram observations and PostgreSQL 17. External AI, trading, account valuation,
MT5 and position review remain disabled. Local analysis requires configured sources
and explicitly enabled mock agents; installation does not enable them.

## Route and authority

`structured-fx-v1` classifies noise and parses a complete ASCII message:
`BUY EURUSD ENTRY 1.10000 SL 1.09500 TP 1.11000`, or SELL with consistent stop/target
relationships. Whitespace may separate fields; case, labels and symbol identities
are exact. Parser symbols are EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD and NZDUSD.
This is a grammar boundary, not broker mapping or financial permission. Missing
fields, ranges, multiple targets, suffixes and additional instructions escalate
without inference or provider calls. All prices use Decimal.

Only initial non-reply, fresh NEW messages form advisory proposals. Edits, deletions
and replies are review-only; Telegram revisions invalidate the prior unsent signal
rather than creating another opening. Freshness uses publication time and the AI
worker's independent 900-second default, checked again at completion. Future
timestamps beyond five seconds are rejected. Collector history recovery does not
extend proposal freshness.

Required classifier/parser configs gate proposals, followed by MARKET_ANALYST and
DECISION_AGENT. All required configs/models must be enabled and schema-compatible.
CRITIC runs when enabled or required by `ENABLE_CRITIC_AGENT`; an unavailable required
critic stops the route. Required stages never become optional for cost/availability.
POSITION_REVIEW_AGENT and adaptive memory remain unavailable.

The mock reports WAIT, MOCK_ONLY and NO_MARKET_CONTEXT, with zero consumption. Even
a schema-valid PROPOSE stays WAITING with RISK_NOT_IMPLEMENTED. Rejection/escalation
stop the route. Analysis creates no risk approval, exposure reservation, execution
command or broker action. The future gateway must check source/instrument permissions,
market/account freshness and every financial gate; parsing satisfies none of those
execution acceptance requirements.

## Persistence and spend

`0005_analysis` adds append-only analysis receipts and protected spend reservations,
bringing schema/ORM parity to 41 tables. Role-authenticated functions revalidate job
owner/generation/expiry, source/version, latest message revision and config versions.
No transaction spans a provider call. Completion atomically writes receipt, optional
proposal/version, legal lifecycle transitions, metadata-only audit/outbox and completed
job. Late workers cannot overwrite current evidence.

Receipts retain reasons, classification, outcome, source/message/config versions,
route version, body hash and trace. Runs retain model, prompt checksum/version,
schema/pricing version, attempt, latency, consumption certainty and bounded advisory
enums. No raw source body, private reasoning or credentials enter these records.
Existing bounded raw-evidence retention preserves financial recovery evidence.

Before each attempt PostgreSQL serializes worst-case priced input/output reservations
against global daily/monthly, per-agent daily and per-request limits; the agent's
request cap also applies. Decimal cost rounds upward to NUMERIC(28,10). Usage
breakdowns are subsets of total tokens and are not counted twice. UTC defines the
periods; dashboard times use Europe/Rome.

Known usage settles estimated cost. Missing/invalid/excessive usage retains an
UNKNOWN reservation. RESERVED/UNKNOWN amounts survive period rollover and restart;
the worker does not blindly repeat them. Costi IA shows attempts interrupted before
a usage row exists. Releasing unknown spend requires future provider reconciliation;
there is no dashboard release control. Each agent has at most three attempts per
job across fallbacks/restarts, with one total deadline and tighter stage timeouts.
Retry-After blocks immediate fallback. Quota, refusal, incomplete/invalid output and
unknown consumption stop the route. Exhausted unexpected job failures become DEAD.

The AI process is trusted to enforce its deployed spend envelope. Database functions
authenticate its role and serialize legitimate concurrent workers; they do not defend
that process's budget arguments against hostile code holding its own credentials.
Risk/execution authority remains separate.

## OpenAI and remaining gates

The Responses adapter accepts only `httpx.MockTransport`; no runtime setting or key
enables network calls. Existing httpx is used directly, without an SDK or hidden SDK
retries. Offline tests cover fixed origin, strict schema, `store=false`, no tools or
redirects, deadline, refusal/incomplete/errors and usage. Duplicate JSON keys, extra
commands, unknown enums, malformed usage and tool output fail validation. Private
reasoning items are discarded. `store=false` does not establish zero provider retention.
[Official structured-output contract](https://developers.openai.com/api/docs/guides/structured-outputs),
[Responses storage behavior](https://developers.openai.com/api/docs/guides/migrate-to-responses).

Real transport requires verified account/model access, reviewed current capabilities
and prices, defensible input-token/charge ceilings, real billing/timeout tests and
quality evaluation on approved fixtures. No real model availability, price, network
acceptance or decision calibration is claimed. Real Telegram, native Windows, EA/demo
broker and external MFA acceptance remain separate gates.

## Dashboard and operation

Analisi messaggi shows outcomes, Italian reasons and proposal links. Signal detail
shows immutable prices and agent attempts. ADMIN enables offline agents using the
existing session/payload/version-bound confirmation; the reviewed prompt version 2
is explicitly shown. Bootstrap appends those prompts and preserves prior configs.
VIEWER remains read-only; sources remain dashboard-managed. Cost rows distinguish
consumption certainty and reservation state. No schedule or notification is added.

Defaults, setup and evidence are in the maintained
[team guide](team/GUIDA_PREPARAZIONE.md), [customer guide](cliente/GUIDA_CLIENTE.md)
and [Phase 5 validation](PHASE_5_VALIDATION.md).
