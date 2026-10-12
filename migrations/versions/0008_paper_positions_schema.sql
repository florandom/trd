-- Frozen local paper position schema.

CREATE TABLE paper_position_state (
	position_id UUID NOT NULL,
	account_id UUID NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	stop_loss NUMERIC(28, 10) NOT NULL,
	take_profit NUMERIC(28, 10) NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id, position_id) REFERENCES positions (environment_id, account_id, id),
	CHECK (revision >= 1 AND stop_loss > 0 AND take_profit > 0 AND stop_loss <> 'NaN'::numeric AND take_profit <> 'NaN'::numeric),
	CONSTRAINT ck_paper_position_state_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
)

;
CREATE UNIQUE INDEX uq_paper_position_state ON paper_position_state (environment_id, position_id);

CREATE TABLE paper_operations (
	account_id UUID NOT NULL,
	position_id UUID,
	command_id UUID,
	actor_id UUID NOT NULL,
	action VARCHAR(16) NOT NULL,
	expected_revision INTEGER NOT NULL,
	safety_epoch INTEGER NOT NULL,
	value JSONB NOT NULL,
	state VARCHAR(16) DEFAULT 'PENDING' NOT NULL,
	reason VARCHAR(64),
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id) REFERENCES trading_accounts (environment_id, id),
	FOREIGN KEY(environment_id, account_id, position_id) REFERENCES positions (environment_id, account_id, id),
	FOREIGN KEY(environment_id, account_id, command_id) REFERENCES execution_commands (environment_id, account_id, id),
	CHECK (action IN ('CLOSE','MODIFY_STOPS','RESUME') AND state IN ('PENDING','DISPATCHED','UNKNOWN','COMPLETED','REJECTED')),
	CHECK (expected_revision >= 1 AND safety_epoch >= 1),
	CHECK ((action='RESUME') = (position_id IS NULL)),
	FOREIGN KEY(actor_id) REFERENCES users (id),
	CONSTRAINT ck_paper_operations_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
)

;
CREATE UNIQUE INDEX uq_paper_operation_command ON paper_operations (environment_id, command_id);
CREATE UNIQUE INDEX uq_paper_pending_position ON paper_operations (environment_id, position_id) WHERE state IN ('PENDING','DISPATCHED','UNKNOWN');
CREATE UNIQUE INDEX uq_paper_pending_resume ON paper_operations (environment_id, account_id) WHERE action='RESUME' AND state='PENDING';

CREATE TABLE paper_operation_results (
	account_id UUID NOT NULL,
	request_id UUID NOT NULL,
	operation_id VARCHAR(32) NOT NULL,
	outcome JSONB NOT NULL,
	environment_id VARCHAR(64) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (environment_id, id),
	FOREIGN KEY(environment_id, account_id) REFERENCES trading_accounts (environment_id, id),
	FOREIGN KEY(environment_id, request_id) REFERENCES paper_operations (environment_id, id),
	CONSTRAINT ck_paper_operation_results_environment CHECK (environment_id ~ '^[a-z][a-z0-9_-]{0,63}$')
)

;
CREATE UNIQUE INDEX uq_paper_operation_identity ON paper_operation_results (environment_id, account_id, operation_id);
CREATE UNIQUE INDEX uq_paper_operation_result ON paper_operation_results (environment_id, request_id);
