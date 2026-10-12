-- Frozen Phase 2 schema. Reviewed migration input, not runtime create_all.
SET LOCAL search_path = public, pg_catalog;

CREATE TABLE agents (
	name VARCHAR(32) NOT NULL,
	current_version INTEGER,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	UNIQUE (environment_id, name),
	CHECK (name IN ('SIGNAL_CLASSIFIER','SIGNAL_PARSER','MARKET_ANALYST','DECISION_AGENT','CRITIC','POSITION_REVIEW_AGENT')),
	CONSTRAINT ck_agents_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE jobs (
	service VARCHAR(16) NOT NULL,
	dedupe_key VARCHAR(128) NOT NULL,
	payload JSONB NOT NULL,
	state VARCHAR(16) DEFAULT 'PENDING' NOT NULL,
	attempts INTEGER DEFAULT '0' NOT NULL,
	max_attempts INTEGER DEFAULT '3' NOT NULL,
	generation INTEGER DEFAULT '0' NOT NULL,
	available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	lease_owner VARCHAR(128),
	lease_until TIMESTAMP WITH TIME ZONE,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	UNIQUE (environment_id, service, dedupe_key),
	CHECK (service IN ('collector','ai','risk','maintenance')),
	CHECK (state IN ('PENDING','RUNNING','COMPLETED','DEAD')),
	CHECK (attempts >= 0 AND max_attempts BETWEEN 1 AND 10 AND generation >= 0),
	CHECK ((state = 'RUNNING') = (lease_owner IS NOT NULL AND lease_until IS NOT NULL)),
	CONSTRAINT ck_jobs_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE INDEX ix_jobs_claim ON jobs (environment_id, service, state, available_at);

CREATE TABLE model_registry (
	id VARCHAR(64) NOT NULL,
	provider VARCHAR(16) NOT NULL,
	model_name VARCHAR(128) NOT NULL,
	enabled BOOLEAN DEFAULT 'false' NOT NULL,
	schema_version INTEGER NOT NULL,
	max_output_tokens INTEGER NOT NULL,
	input_price_per_million NUMERIC(28, 10) NOT NULL,
	output_price_per_million NUMERIC(28, 10) NOT NULL,
	pricing_version VARCHAR(64) NOT NULL,
	currency VARCHAR(3) DEFAULT 'USD' NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (provider, model_name, pricing_version),
	CHECK (input_price_per_million >= 0 AND output_price_per_million >= 0),
	CHECK (schema_version >= 1 AND max_output_tokens > 0),
	CHECK (provider IN ('mock','openai','anthropic','google','moonshot','typesafe')),
	CHECK (currency = 'USD'),
	CONSTRAINT ck_model_registry_input_price_per_million_finite CHECK (input_price_per_million <> 'NaN'::numeric),
	CONSTRAINT ck_model_registry_output_price_per_million_finite CHECK (output_price_per_million <> 'NaN'::numeric)
);

CREATE TABLE outbox_events (
	event_key VARCHAR(128) NOT NULL,
	topic VARCHAR(64) NOT NULL,
	payload JSONB NOT NULL,
	delivered_at TIMESTAMP WITH TIME ZONE,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	UNIQUE (environment_id, event_key),
	CONSTRAINT ck_outbox_events_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE system_health (
	component VARCHAR(64) NOT NULL,
	status VARCHAR(16) NOT NULL,
	reason_codes JSONB NOT NULL,
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	CHECK (status IN ('HEALTHY','DEGRADED','UNAVAILABLE','UNKNOWN')),
	CONSTRAINT ck_system_health_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE telegram_sources (
	collector_identity VARCHAR(64) NOT NULL,
	peer_id VARCHAR(32) NOT NULL,
	name VARCHAR(160) NOT NULL,
	enabled BOOLEAN DEFAULT 'false' NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	UNIQUE (environment_id, collector_identity, peer_id),
	CONSTRAINT ck_telegram_sources_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE trading_accounts (
	broker_server VARCHAR(128) NOT NULL,
	login VARCHAR(32) NOT NULL,
	mode VARCHAR(8) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	status VARCHAR(16) DEFAULT 'PAUSED' NOT NULL,
	safety_epoch INTEGER DEFAULT '1' NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	UNIQUE (environment_id, broker_server, login, mode),
	CHECK (mode IN ('paper','demo','live')),
	CHECK (status IN ('PAUSED','RECONCILING','READY')),
	CHECK (login ~ '^[0-9]{1,32}$'),
	CHECK (safety_epoch >= 1),
	CONSTRAINT ck_trading_accounts_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE prompt_versions (
	environment_id VARCHAR(64) NOT NULL,
	agent_id UUID NOT NULL,
	version INTEGER NOT NULL,
	body TEXT NOT NULL,
	checksum VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, agent_id, version),
	FOREIGN KEY(environment_id, agent_id) REFERENCES agents (environment_id, id),
	CHECK (version >= 1),
	CHECK (checksum ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_prompt_versions_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE risk_rules (
	environment_id VARCHAR(64) NOT NULL,
	key VARCHAR(64) NOT NULL,
	version INTEGER NOT NULL,
	policy JSONB NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	created_by UUID,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, key, version),
	CHECK (version >= 1),
	CHECK (fingerprint ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(created_by) REFERENCES users (id),
	CONSTRAINT ck_risk_rules_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE sessions (
	user_id UUID NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	UNIQUE (token_hash),
	CHECK (token_hash ~ '^[a-f0-9]{64}$'),
	CHECK (expires_at > created_at),
	FOREIGN KEY(user_id) REFERENCES users (id),
	CONSTRAINT ck_sessions_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE telegram_messages (
	source_id UUID NOT NULL,
	message_id VARCHAR(32) NOT NULL,
	reply_message_id VARCHAR(32),
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, source_id) REFERENCES telegram_sources (environment_id, id),
	UNIQUE (environment_id, source_id, message_id),
	CHECK (message_id ~ '^[0-9]{1,32}$'),
	CONSTRAINT ck_telegram_messages_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE agent_configs (
	environment_id VARCHAR(64) NOT NULL,
	agent_id UUID NOT NULL,
	version INTEGER NOT NULL,
	enabled BOOLEAN DEFAULT 'false' NOT NULL,
	primary_model_id VARCHAR(64) NOT NULL,
	prompt_version INTEGER NOT NULL,
	timeout_seconds INTEGER NOT NULL,
	max_output_tokens INTEGER NOT NULL,
	max_cost_usd NUMERIC(28, 10) NOT NULL,
	required_schema_version INTEGER NOT NULL,
	created_by UUID,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, agent_id, version),
	FOREIGN KEY(environment_id, agent_id) REFERENCES agents (environment_id, id),
	FOREIGN KEY(environment_id, agent_id, prompt_version) REFERENCES prompt_versions (environment_id, agent_id, version),
	CHECK (version >= 1 AND timeout_seconds BETWEEN 1 AND 120),
	CHECK (max_output_tokens > 0 AND max_cost_usd >= 0),
	CHECK (required_schema_version >= 1),
	FOREIGN KEY(primary_model_id) REFERENCES model_registry (id),
	FOREIGN KEY(created_by) REFERENCES users (id),
	CONSTRAINT ck_agent_configs_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
	CONSTRAINT ck_agent_configs_max_cost_usd_finite CHECK (max_cost_usd <> 'NaN'::numeric)
);

CREATE TABLE risk_rule_heads (
	environment_id VARCHAR(64) NOT NULL,
	key VARCHAR(64) NOT NULL,
	current_version INTEGER NOT NULL,
	PRIMARY KEY (environment_id, key),
	FOREIGN KEY(environment_id, key, current_version) REFERENCES risk_rules (environment_id, key, version),
	CONSTRAINT ck_risk_rule_heads_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE signals (
	message_id UUID NOT NULL,
	intent_key VARCHAR(96) NOT NULL,
	trace_id UUID NOT NULL,
	state VARCHAR(32) DEFAULT 'RECEIVED' NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, message_id) REFERENCES telegram_messages (environment_id, id),
	UNIQUE (environment_id, id, message_id),
	UNIQUE (environment_id, message_id, intent_key),
	CHECK (state IN ('RECEIVED','CLASSIFIED','PARSED','ANALYZING','DECIDED','WAITING','ESCALATED','RISK_CHECK','APPROVED','EXECUTION_REQUESTED','RECONCILING','EXECUTED','IGNORED','REJECTED_AI','REJECTED_RISK','EXPIRED','FAILED')),
	CHECK (revision >= 1),
	CONSTRAINT ck_signals_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE INDEX ix_signals_state ON signals (environment_id, state);

CREATE TABLE telegram_message_versions (
	environment_id VARCHAR(64) NOT NULL,
	message_id UUID NOT NULL,
	version INTEGER NOT NULL,
	body_hash VARCHAR(64) NOT NULL,
	raw_body TEXT,
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, message_id, version),
	FOREIGN KEY(environment_id, message_id) REFERENCES telegram_messages (environment_id, id),
	CHECK (version >= 1),
	CHECK (body_hash ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_telegram_message_versions_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE INDEX ix_telegram_raw_retention ON telegram_message_versions (environment_id, created_at);

CREATE TABLE agent_fallbacks (
	environment_id VARCHAR(64) NOT NULL,
	agent_id UUID NOT NULL,
	config_version INTEGER NOT NULL,
	ordinal INTEGER NOT NULL,
	model_id VARCHAR(64) NOT NULL,
	PRIMARY KEY (environment_id, agent_id, config_version, ordinal),
	FOREIGN KEY(environment_id, agent_id, config_version) REFERENCES agent_configs (environment_id, agent_id, version),
	UNIQUE (environment_id, agent_id, config_version, model_id),
	CHECK (ordinal BETWEEN 1 AND 2),
	FOREIGN KEY(model_id) REFERENCES model_registry (id),
	CONSTRAINT ck_agent_fallbacks_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE agent_runs (
	agent_id UUID NOT NULL,
	config_version INTEGER NOT NULL,
	signal_id UUID,
	trace_id UUID NOT NULL,
	model_id VARCHAR(64) NOT NULL,
	attempt INTEGER NOT NULL,
	status VARCHAR(16) NOT NULL,
	result JSONB,
	raw_response TEXT,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, agent_id, config_version) REFERENCES agent_configs (environment_id, agent_id, version),
	FOREIGN KEY(environment_id, signal_id) REFERENCES signals (environment_id, id),
	CHECK (status IN ('STARTED','SUCCEEDED','REFUSED','FAILED','UNKNOWN')),
	CHECK (attempt BETWEEN 1 AND 3),
	FOREIGN KEY(model_id) REFERENCES model_registry (id),
	CONSTRAINT ck_agent_runs_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE INDEX ix_ai_raw_retention ON agent_runs (environment_id, created_at);

CREATE TABLE signal_versions (
	environment_id VARCHAR(64) NOT NULL,
	signal_id UUID NOT NULL,
	version INTEGER NOT NULL,
	message_id UUID NOT NULL,
	message_version INTEGER NOT NULL,
	proposal JSONB NOT NULL,
	proposal_hash VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, signal_id, version),
	FOREIGN KEY(environment_id, signal_id, message_id) REFERENCES signals (environment_id, id, message_id),
	FOREIGN KEY(environment_id, message_id, message_version) REFERENCES telegram_message_versions (environment_id, message_id, version),
	CHECK (version >= 1),
	CHECK (proposal_hash ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_signal_versions_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE ai_usage (
	run_id UUID NOT NULL,
	input_tokens INTEGER NOT NULL,
	output_tokens INTEGER NOT NULL,
	estimated_cost_usd NUMERIC(28, 10) NOT NULL,
	pricing_version VARCHAR(64) NOT NULL,
	usage_known BOOLEAN DEFAULT 'false' NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, run_id) REFERENCES agent_runs (environment_id, id),
	UNIQUE (environment_id, run_id),
	CHECK (input_tokens >= 0 AND output_tokens >= 0 AND estimated_cost_usd >= 0),
	CONSTRAINT ck_ai_usage_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
	CONSTRAINT ck_ai_usage_estimated_cost_usd_finite CHECK (estimated_cost_usd <> 'NaN'::numeric)
);

CREATE TABLE risk_events (
	signal_id UUID NOT NULL,
	signal_version INTEGER NOT NULL,
	rule_key VARCHAR(64) NOT NULL,
	rule_version INTEGER NOT NULL,
	result VARCHAR(16) NOT NULL,
	reason_codes JSONB NOT NULL,
	calculation JSONB NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, signal_id, signal_version) REFERENCES signal_versions (environment_id, signal_id, version),
	CHECK (result IN ('APPROVED','REJECTED','ERROR')),
	FOREIGN KEY(environment_id, rule_key, rule_version) REFERENCES risk_rules (environment_id, key, version),
	CONSTRAINT ck_risk_events_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE risk_approvals (
	account_id UUID NOT NULL,
	risk_event_id UUID NOT NULL,
	risk_amount NUMERIC(28, 10) NOT NULL,
	safety_epoch INTEGER NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id) REFERENCES trading_accounts (environment_id, id),
	FOREIGN KEY(environment_id, risk_event_id) REFERENCES risk_events (environment_id, id),
	UNIQUE (environment_id, account_id, id),
	CHECK (risk_amount > 0 AND safety_epoch >= 1),
	CHECK (expires_at > created_at),
	CONSTRAINT ck_risk_approvals_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
	CONSTRAINT ck_risk_approvals_risk_amount_finite CHECK (risk_amount <> 'NaN'::numeric)
);

CREATE TABLE risk_reservations (
	account_id UUID NOT NULL,
	approval_id UUID NOT NULL,
	risk_amount NUMERIC(28, 10) NOT NULL,
	slots INTEGER DEFAULT '1' NOT NULL,
	status VARCHAR(16) DEFAULT 'HELD' NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id, approval_id) REFERENCES risk_approvals (environment_id, account_id, id),
	UNIQUE (environment_id, approval_id),
	UNIQUE (environment_id, account_id, id),
	CHECK (status IN ('HELD','CONSUMED','RELEASED','OUTCOME_UNKNOWN')),
	CHECK (risk_amount > 0 AND slots > 0),
	CONSTRAINT ck_risk_reservations_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
	CONSTRAINT ck_risk_reservations_risk_amount_finite CHECK (risk_amount <> 'NaN'::numeric)
);

CREATE TABLE execution_commands (
	account_id UUID NOT NULL,
	reservation_id UUID NOT NULL,
	trace_id UUID NOT NULL,
	payload BYTEA NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	state VARCHAR(32) DEFAULT 'CREATED' NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id, reservation_id) REFERENCES risk_reservations (environment_id, account_id, id),
	UNIQUE (environment_id, reservation_id),
	UNIQUE (environment_id, account_id, id),
	CHECK (payload_hash ~ '^[a-f0-9]{64}$'),
	CHECK (revision >= 1),
	CHECK (expires_at > created_at),
	CHECK (state IN ('CREATED','READY','DELIVERED','ACKNOWLEDGED','OUTCOME_UNKNOWN','RECONCILING','COMPLETED','REJECTED','EXPIRED','INVALIDATED')),
	CONSTRAINT ck_execution_commands_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE execution_events (
	account_id UUID NOT NULL,
	command_id UUID NOT NULL,
	event_key VARCHAR(128) NOT NULL,
	event_type VARCHAR(32) NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	summary JSONB NOT NULL,
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id, command_id) REFERENCES execution_commands (environment_id, account_id, id),
	UNIQUE (environment_id, account_id, event_key),
	CHECK (payload_hash ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_execution_events_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE orders (
	account_id UUID NOT NULL,
	command_id UUID NOT NULL,
	broker_ticket VARCHAR(32),
	symbol VARCHAR(64) NOT NULL,
	side VARCHAR(4) NOT NULL,
	volume NUMERIC(28, 10) NOT NULL,
	filled_volume NUMERIC(28, 10) DEFAULT '0' NOT NULL,
	state VARCHAR(32) DEFAULT 'PROPOSED' NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id, command_id) REFERENCES execution_commands (environment_id, account_id, id),
	UNIQUE (environment_id, command_id),
	UNIQUE (environment_id, account_id, broker_ticket),
	UNIQUE (environment_id, account_id, id),
	CHECK (side IN ('BUY','SELL')),
	CHECK (revision >= 1),
	CHECK (volume > 0 AND filled_volume >= 0 AND filled_volume <= volume),
	CHECK (state IN ('PROPOSED','VALIDATED','REQUESTED','SENT','ACCEPTED','PARTIALLY_FILLED','FILLED','OUTCOME_UNKNOWN','RECONCILING','REJECTED','FAILED','EXPIRED','CANCELED')),
	CONSTRAINT ck_orders_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
	CONSTRAINT ck_orders_volume_finite CHECK (volume <> 'NaN'::numeric),
	CONSTRAINT ck_orders_filled_volume_finite CHECK (filled_volume <> 'NaN'::numeric)
);

CREATE TABLE lifecycle_events (
	kind VARCHAR(8) NOT NULL,
	entity_id UUID NOT NULL,
	signal_id UUID,
	order_id UUID,
	command_id UUID,
	revision INTEGER NOT NULL,
	before VARCHAR(32) NOT NULL,
	after VARCHAR(32) NOT NULL,
	evidence VARCHAR(32) NOT NULL,
	actor_service VARCHAR(16) NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, signal_id) REFERENCES signals (environment_id, id),
	FOREIGN KEY(environment_id, order_id) REFERENCES orders (environment_id, id),
	FOREIGN KEY(environment_id, command_id) REFERENCES execution_commands (environment_id, id),
	UNIQUE (environment_id, kind, entity_id, revision),
	CHECK (kind IN ('signal','order','command')),
	CHECK (revision >= 2),
	CHECK ((kind = 'signal' AND signal_id IS NOT NULL AND signal_id = entity_id AND order_id IS NULL AND command_id IS NULL) OR (kind = 'order' AND order_id IS NOT NULL AND order_id = entity_id AND signal_id IS NULL AND command_id IS NULL) OR (kind = 'command' AND command_id IS NOT NULL AND command_id = entity_id AND signal_id IS NULL AND order_id IS NULL)),
	CONSTRAINT ck_lifecycle_events_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE TABLE positions (
	account_id UUID NOT NULL,
	order_id UUID NOT NULL,
	broker_identifier VARCHAR(32) NOT NULL,
	symbol VARCHAR(64) NOT NULL,
	volume NUMERIC(28, 10) NOT NULL,
	entry_price NUMERIC(28, 10) NOT NULL,
	status VARCHAR(16) NOT NULL,
	opened_at TIMESTAMP WITH TIME ZONE NOT NULL,
	closed_at TIMESTAMP WITH TIME ZONE,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id, order_id) REFERENCES orders (environment_id, account_id, id),
	UNIQUE (environment_id, account_id, broker_identifier, opened_at),
	UNIQUE (environment_id, account_id, id),
	CHECK (volume >= 0 AND entry_price > 0),
	CHECK (status IN ('OPEN','CLOSING','CLOSED','OUTCOME_UNKNOWN')),
	CHECK ((status = 'CLOSED') = (closed_at IS NOT NULL)),
	CONSTRAINT ck_positions_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
	CONSTRAINT ck_positions_volume_finite CHECK (volume <> 'NaN'::numeric),
	CONSTRAINT ck_positions_entry_price_finite CHECK (entry_price <> 'NaN'::numeric)
);

CREATE TABLE compact_trade_memory (
	signal_id UUID NOT NULL,
	position_id UUID,
	context_summary JSONB NOT NULL,
	realized_pnl NUMERIC(28, 10),
	r_multiple NUMERIC(28, 10),
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, signal_id) REFERENCES signals (environment_id, id),
	FOREIGN KEY(environment_id, position_id) REFERENCES positions (environment_id, id),
	CONSTRAINT ck_compact_trade_memory_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
	CONSTRAINT ck_compact_trade_memory_realized_pnl_finite CHECK (realized_pnl <> 'NaN'::numeric),
	CONSTRAINT ck_compact_trade_memory_r_multiple_finite CHECK (r_multiple <> 'NaN'::numeric)
);

CREATE TABLE position_events (
	account_id UUID NOT NULL,
	position_id UUID NOT NULL,
	broker_deal_id VARCHAR(32) NOT NULL,
	event_type VARCHAR(32) NOT NULL,
	realized_pnl NUMERIC(28, 10) NOT NULL,
	summary JSONB NOT NULL,
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id, position_id) REFERENCES positions (environment_id, account_id, id),
	UNIQUE (environment_id, account_id, broker_deal_id),
	CONSTRAINT ck_position_events_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
	CONSTRAINT ck_position_events_realized_pnl_finite CHECK (realized_pnl <> 'NaN'::numeric)
);

ALTER TABLE agents ADD CONSTRAINT fk_agents_current_config FOREIGN KEY(environment_id, id, current_version) REFERENCES agent_configs (environment_id, agent_id, version);
