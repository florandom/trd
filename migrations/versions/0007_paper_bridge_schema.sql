-- Frozen phase 7 schema; independent of future runtime models.

CREATE TABLE bridge_enrollments (
	environment_id VARCHAR(64) NOT NULL, 
	account_id UUID NOT NULL, 
	bridge_id VARCHAR(64) NOT NULL, 
	instance_id VARCHAR(64) NOT NULL, 
	key_id VARCHAR(64) NOT NULL, 
	generation INTEGER NOT NULL, 
	profile_hash VARCHAR(64) NOT NULL, 
	request_key_hash VARCHAR(64) NOT NULL, 
	response_key_hash VARCHAR(64) NOT NULL, 
	highwater BIGINT DEFAULT '0' NOT NULL, 
	fault_latched BOOLEAN DEFAULT 'false' NOT NULL, 
	journal_id VARCHAR(64), 
	PRIMARY KEY (environment_id, account_id), 
	FOREIGN KEY(environment_id, account_id) REFERENCES trading_accounts (environment_id, id), 
	UNIQUE (environment_id, bridge_id, instance_id), 
	CHECK (generation >= 1 AND highwater >= 0), 
	CHECK (profile_hash ~ '^[a-f0-9]{64}$' AND request_key_hash ~ '^[a-f0-9]{64}$' AND response_key_hash ~ '^[a-f0-9]{64}$'), 
	CONSTRAINT ck_bridge_enrollments_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
)

;

CREATE TABLE bridge_snapshots (
	account_id UUID NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	payload JSONB NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	environment_id VARCHAR(64) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (environment_id, id), 
	FOREIGN KEY(environment_id, account_id) REFERENCES trading_accounts (environment_id, id), 
	UNIQUE (environment_id, account_id, id), 
	CHECK (payload_hash ~ '^[a-f0-9]{64}$'), 
	CONSTRAINT ck_bridge_snapshots_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
)

;

CREATE TABLE bridge_daily_baselines (
	environment_id VARCHAR(64) NOT NULL, 
	account_id UUID NOT NULL, 
	day DATE NOT NULL, 
	snapshot_id UUID NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	opening_equity NUMERIC(28, 10) NOT NULL, 
	net_cash_flow NUMERIC(28, 10) NOT NULL, 
	loss_latched BOOLEAN DEFAULT 'false' NOT NULL, 
	PRIMARY KEY (environment_id, account_id, day), 
	FOREIGN KEY(environment_id, account_id) REFERENCES trading_accounts (environment_id, id), 
	FOREIGN KEY(environment_id, account_id, snapshot_id) REFERENCES bridge_snapshots (environment_id, account_id, id), 
	CHECK (opening_equity > 0 AND opening_equity <> 'NaN'::numeric AND net_cash_flow <> 'NaN'::numeric), 
	CONSTRAINT ck_bridge_daily_baselines_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
)

;

CREATE TABLE bridge_requests (
	environment_id VARCHAR(64) NOT NULL, 
	account_id UUID NOT NULL, 
	sequence BIGINT NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	status INTEGER NOT NULL, 
	response BYTEA NOT NULL, 
	response_headers JSONB NOT NULL, 
	PRIMARY KEY (environment_id, account_id, sequence), 
	FOREIGN KEY(environment_id, account_id) REFERENCES bridge_enrollments (environment_id, account_id), 
	CHECK (sequence >= 1 AND request_hash ~ '^[a-f0-9]{64}$' AND status BETWEEN 200 AND 499), 
	CONSTRAINT ck_bridge_requests_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
)

;

CREATE TABLE paper_command_records (
	account_id UUID NOT NULL, 
	command_id UUID NOT NULL, 
	signal_id UUID NOT NULL, 
	message_id UUID NOT NULL, 
	proposal JSONB NOT NULL, 
	admission JSONB NOT NULL, 
	remaining_risk NUMERIC(28, 10) NOT NULL, 
	remaining_notional NUMERIC(28, 10) NOT NULL, 
	remaining_margin NUMERIC(28, 10) NOT NULL, 
	send_intent BOOLEAN DEFAULT 'false' NOT NULL, 
	environment_id VARCHAR(64) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (environment_id, id), 
	FOREIGN KEY(environment_id, account_id, command_id) REFERENCES execution_commands (environment_id, account_id, id), 
	FOREIGN KEY(environment_id, signal_id) REFERENCES signals (environment_id, id), 
	UNIQUE (environment_id, command_id), 
	UNIQUE (environment_id, signal_id), 
	UNIQUE (environment_id, message_id), 
	FOREIGN KEY(environment_id, message_id) REFERENCES telegram_messages (environment_id, id), 
	CHECK (remaining_risk >= 0 AND remaining_notional >= 0 AND remaining_margin >= 0 AND remaining_risk <> 'NaN'::numeric AND remaining_notional <> 'NaN'::numeric AND remaining_margin <> 'NaN'::numeric), 
	CONSTRAINT ck_paper_command_records_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
)

;

CREATE TABLE bridge_decisions (
	account_id UUID NOT NULL, 
	evaluation_hash VARCHAR(64) NOT NULL, 
	risk_event_id UUID NOT NULL, 
	environment_id VARCHAR(64) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (environment_id, id), 
	FOREIGN KEY(environment_id, account_id) REFERENCES trading_accounts (environment_id, id), 
	FOREIGN KEY(environment_id, risk_event_id) REFERENCES risk_events (environment_id, id), 
	UNIQUE (environment_id, account_id, evaluation_hash), 
	CHECK (evaluation_hash ~ '^[a-f0-9]{64}$'), 
	CONSTRAINT ck_bridge_decisions_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
)

;
