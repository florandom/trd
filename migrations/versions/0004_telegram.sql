-- Frozen schema and role-authenticated units of work. No network calls in transactions.
ALTER TABLE public.telegram_sources
 ADD COLUMN reference varchar(160), ADD COLUMN access_hash varchar(32),
 ADD COLUMN peer_kind varchar(8), ADD COLUMN version integer NOT NULL DEFAULT 1,
 ADD COLUMN resolution_state varchar(16) NOT NULL DEFAULT 'PENDING',
 ADD CONSTRAINT telegram_reference_unique UNIQUE(environment_id,collector_identity,reference),
 ADD CONSTRAINT telegram_source_version_check CHECK(version>=1),
 ADD CONSTRAINT telegram_source_resolution_check CHECK(resolution_state IN ('PENDING','RESOLVED','UNAVAILABLE'));
ALTER TABLE public.telegram_message_versions
 ADD COLUMN event_kind varchar(8) NOT NULL DEFAULT 'NEW', ADD COLUMN revision_hash varchar(64),
 ADD COLUMN published_at timestamptz, ADD COLUMN media_kind varchar(8) NOT NULL DEFAULT 'NONE',
 ADD CONSTRAINT telegram_revision_unique UNIQUE(environment_id,message_id,revision_hash),
 ADD CONSTRAINT telegram_event_kind_check CHECK(event_kind IN ('NEW','EDIT','DELETE'));
CREATE TABLE public.telegram_collector_leases (
 account_id varchar(20) PRIMARY KEY CHECK(account_id ~ '^[1-9][0-9]{0,19}$'),
 environment_id varchar(64) NOT NULL CONSTRAINT ck_telegram_collector_leases_environment CHECK(environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
 owner varchar(128) NOT NULL, generation integer NOT NULL CHECK(generation>=1), lease_until timestamptz NOT NULL,
 retry_after timestamptz
);
CREATE TABLE public.telegram_source_state (
 environment_id varchar(64) NOT NULL CONSTRAINT ck_telegram_source_state_environment CHECK(environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
 source_id uuid NOT NULL, last_message_id bigint NOT NULL DEFAULT 0,
 delete_cursor bigint NOT NULL DEFAULT 0,
 status varchar(16) NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','ACTIVE','BACKFILL','GAP','UNAVAILABLE','FLOOD_WAIT','DISABLED')),
 checked_at timestamptz, last_success_at timestamptz, gap_since timestamptz, error_code varchar(32),
 PRIMARY KEY(environment_id,source_id),
 FOREIGN KEY(environment_id,source_id) REFERENCES public.telegram_sources(environment_id,id),
 CHECK(last_message_id>=0 AND delete_cursor>=0)
);
GRANT SELECT ON public.telegram_source_state TO trd_collector;
-- The old foundation append interface remains for compatibility; the real collector uses
-- the fenced definer only. Runtime identity cannot bypass its lease or source allowlist.
REVOKE INSERT ON public.telegram_messages,public.telegram_message_versions FROM trd_collector;

CREATE FUNCTION public.telegram_acquire_lease(p_environment text,p_account text,p_owner text,p_seconds integer)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE result integer;
BEGIN
 IF session_user<>'trd_collector' THEN RAISE EXCEPTION 'collector required' USING ERRCODE='42501'; END IF;
 IF p_environment IS NULL OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$'
 OR p_account IS NULL OR p_account !~ '^[1-9][0-9]{0,19}$'
 OR p_owner IS NULL OR p_owner !~ '^[A-Za-z0-9_-]{1,128}$'
 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 30 AND 120 THEN
 RAISE EXCEPTION 'invalid lease' USING ERRCODE='22023'; END IF;
 INSERT INTO public.telegram_collector_leases(account_id,environment_id,owner,generation,lease_until)
 VALUES(p_account,p_environment,p_owner,1,clock_timestamp()+make_interval(secs=>p_seconds))
 ON CONFLICT(account_id) DO UPDATE SET environment_id=p_environment,owner=p_owner,
 generation=CASE WHEN telegram_collector_leases.owner=p_owner
 AND telegram_collector_leases.environment_id=p_environment
 AND telegram_collector_leases.lease_until>clock_timestamp()
 THEN telegram_collector_leases.generation ELSE telegram_collector_leases.generation+1 END,
 lease_until=clock_timestamp()+make_interval(secs=>p_seconds)
 WHERE (telegram_collector_leases.retry_after IS NULL OR telegram_collector_leases.retry_after<=clock_timestamp())
 AND (telegram_collector_leases.lease_until<=clock_timestamp()
 OR (telegram_collector_leases.owner=p_owner AND telegram_collector_leases.environment_id=p_environment))
 RETURNING generation INTO result;
 RETURN result;
END; $fn$;
CREATE FUNCTION public.telegram_assert_lease(p_environment text,p_account text,p_owner text,p_generation integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
BEGIN
 IF session_user<>'trd_collector' THEN RAISE EXCEPTION 'collector required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.telegram_collector_leases WHERE account_id=p_account
 AND environment_id=p_environment AND owner=p_owner AND generation=p_generation
 AND lease_until>clock_timestamp() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'collector lease lost' USING ERRCODE='40001'; END IF;
END; $fn$;
CREATE FUNCTION public.telegram_release_lease(p_environment text,p_account text,p_owner text,p_generation integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
BEGIN
 PERFORM public.telegram_assert_lease(p_environment,p_account,p_owner,p_generation);
 UPDATE public.telegram_collector_leases SET lease_until=clock_timestamp()
 WHERE account_id=p_account AND environment_id=p_environment AND owner=p_owner AND generation=p_generation;
END; $fn$;

CREATE FUNCTION public.telegram_invalidate_message(p_environment text,p_message uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE command record; item record;
BEGIN
 -- Only reachable from other authenticated definers. Never grant this financial helper.
 UPDATE public.jobs SET state='DEAD',lease_owner=NULL,lease_until=NULL,generation=generation+1
 WHERE environment_id=p_environment AND service='ai' AND state IN ('PENDING','RUNNING')
 AND payload->>'message_id'=p_message::text;
 FOR command IN SELECT c.* FROM public.execution_commands c
 JOIN public.risk_reservations r ON (r.environment_id,r.id)=(c.environment_id,c.reservation_id)
 JOIN public.risk_approvals a ON (a.environment_id,a.id)=(r.environment_id,r.approval_id)
 JOIN public.risk_events e ON (e.environment_id,e.id)=(a.environment_id,a.risk_event_id)
 JOIN public.signals s ON (s.environment_id,s.id)=(e.environment_id,e.signal_id)
 WHERE s.environment_id=p_environment AND s.message_id=p_message AND c.state IN ('CREATED','READY')
 FOR UPDATE OF c LOOP
 UPDATE public.execution_commands SET state='INVALIDATED',revision=revision+1
 WHERE environment_id=p_environment AND id=command.id;
 INSERT INTO public.lifecycle_events(environment_id,id,kind,entity_id,command_id,revision,"before","after",evidence,actor_service)
 VALUES(p_environment,gen_random_uuid(),'command',command.id,command.id,command.revision+1,command.state,'INVALIDATED','OBSERVATION','collector');
 END LOOP;
 FOR item IN SELECT * FROM public.signals WHERE environment_id=p_environment AND message_id=p_message
 AND state IN ('RECEIVED','CLASSIFIED','PARSED','ANALYZING','DECIDED','WAITING','ESCALATED','RISK_CHECK','APPROVED')
 FOR UPDATE LOOP
 UPDATE public.signals SET state='EXPIRED',revision=revision+1 WHERE environment_id=p_environment AND id=item.id;
 INSERT INTO public.lifecycle_events(environment_id,id,kind,entity_id,signal_id,revision,"before","after",evidence,actor_service)
 VALUES(p_environment,gen_random_uuid(),'signal',item.id,item.id,item.revision+1,item.state,'EXPIRED','OBSERVATION','collector');
 END LOOP;
 -- Delivered commands and their reservations are retained for future reconciliation.
END; $fn$;

CREATE FUNCTION public.telegram_source_observed(p_environment text,p_account text,p_owner text,p_generation integer,
 p_source uuid,p_version integer,p_data jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
BEGIN
 PERFORM public.telegram_assert_lease(p_environment,p_account,p_owner,p_generation);
 PERFORM 1 FROM public.telegram_sources WHERE environment_id=p_environment AND id=p_source
 AND version=p_version AND enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'source authority changed' USING ERRCODE='40001'; END IF;
 IF p_data->>'status' NOT IN ('ACTIVE','BACKFILL','GAP','UNAVAILABLE','FLOOD_WAIT')
 OR (p_data->>'delete_cursor')::bigint<0 THEN
 RAISE EXCEPTION 'invalid observation' USING ERRCODE='22023'; END IF;
 IF p_data ? 'peer_id' THEN
 IF p_data->>'peer_id' !~ '^-[1-9][0-9]{0,18}$'
 OR p_data->>'peer_kind' NOT IN ('CHANNEL','CHAT')
 OR (p_data->>'peer_kind'='CHANNEL' AND p_data->>'access_hash' !~ '^-?[0-9]{1,20}$') THEN
 RAISE EXCEPTION 'invalid peer' USING ERRCODE='22023'; END IF;
 BEGIN
 UPDATE public.telegram_sources SET peer_id=p_data->>'peer_id',peer_kind=p_data->>'peer_kind',
 access_hash=p_data->>'access_hash',resolution_state='RESOLVED'
 WHERE environment_id=p_environment AND id=p_source;
 EXCEPTION WHEN unique_violation THEN
 RAISE EXCEPTION 'source peer already enrolled' USING ERRCODE='22023';
 END;
 END IF;
 INSERT INTO public.telegram_source_state(environment_id,source_id,status,checked_at,gap_since,error_code,delete_cursor)
 VALUES(p_environment,p_source,p_data->>'status',clock_timestamp(),
 CASE WHEN p_data->>'status'='GAP' THEN clock_timestamp() END,p_data->>'error_code',COALESCE((p_data->>'delete_cursor')::bigint,0))
 ON CONFLICT(environment_id,source_id) DO UPDATE SET status=EXCLUDED.status,checked_at=EXCLUDED.checked_at,
 gap_since=CASE WHEN EXCLUDED.status='GAP' THEN COALESCE(telegram_source_state.gap_since,clock_timestamp()) ELSE telegram_source_state.gap_since END,
 error_code=EXCLUDED.error_code,delete_cursor=COALESCE((p_data->>'delete_cursor')::bigint,telegram_source_state.delete_cursor);
 IF p_data->'success'='true'::jsonb THEN
 UPDATE public.telegram_source_state SET last_success_at=clock_timestamp()
 WHERE environment_id=p_environment AND source_id=p_source;
 END IF;
 PERFORM public.telegram_assert_lease(p_environment,p_account,p_owner,p_generation);
END; $fn$;

CREATE FUNCTION public.telegram_ingest(p_environment text,p_account text,p_owner text,p_generation integer,
 p_source uuid,p_source_version integer,p_data jsonb,p_max_age integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE anchor uuid; previous record; next_version integer; event_kind text; event_time timestamptz;
 published timestamptz; message_key text; raw text; digest text; stale boolean; topic text;
BEGIN
 PERFORM public.telegram_assert_lease(p_environment,p_account,p_owner,p_generation);
 PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||p_environment,0));
 PERFORM 1 FROM public.telegram_sources WHERE environment_id=p_environment AND id=p_source
 AND version=p_source_version AND enabled AND resolution_state='RESOLVED' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'source authority changed' USING ERRCODE='40001'; END IF;
 message_key:=p_data->>'message_id'; event_kind:=p_data->>'kind'; raw:=p_data->>'body';
 event_time:=(p_data->>'observed_at')::timestamptz; published:=(p_data->>'published_at')::timestamptz;
 digest:=p_data->>'revision_hash';
 IF message_key IS NULL OR message_key !~ '^[1-9][0-9]{0,9}$' OR message_key::bigint>2147483647
 OR event_kind IS NULL OR event_kind NOT IN ('NEW','EDIT','DELETE') OR raw IS NULL OR octet_length(raw)>65536
 OR digest IS NULL OR digest !~ '^[a-f0-9]{64}$' OR p_data->>'body_hash' IS DISTINCT FROM encode(sha256(convert_to(raw,'UTF8')),'hex')
 OR published IS NULL OR event_time IS NULL OR event_time<published OR event_time>clock_timestamp()+interval '30 seconds'
 OR p_max_age IS NULL OR p_max_age NOT BETWEEN 30 AND 3600
 OR (event_kind='DELETE' AND raw<>'') THEN
 RAISE EXCEPTION 'invalid message observation' USING ERRCODE='22023'; END IF;
 INSERT INTO public.telegram_messages(environment_id,id,source_id,message_id,reply_message_id)
 VALUES(p_environment,gen_random_uuid(),p_source,message_key,p_data->>'reply_message_id')
 ON CONFLICT(environment_id,source_id,message_id) DO NOTHING;
 SELECT id INTO anchor FROM public.telegram_messages WHERE environment_id=p_environment
 AND source_id=p_source AND message_id=message_key FOR UPDATE;
 IF p_data->'advance_cursor'='true'::jsonb THEN
 INSERT INTO public.telegram_source_state(environment_id,source_id,last_message_id,status)
 VALUES(p_environment,p_source,message_key::bigint,'BACKFILL') ON CONFLICT(environment_id,source_id)
 DO UPDATE SET last_message_id=greatest(telegram_source_state.last_message_id,EXCLUDED.last_message_id);
 END IF;
 SELECT * INTO previous FROM public.telegram_message_versions WHERE environment_id=p_environment AND message_id=anchor
 ORDER BY version DESC LIMIT 1;
 next_version:=COALESCE(previous.version,0)+1;
 IF previous.version IS NOT NULL AND (previous.event_kind='DELETE' OR event_time<previous.observed_at
 OR digest=previous.revision_hash OR (event_time=previous.observed_at AND p_data->>'body_hash'=previous.body_hash
 AND event_kind<>'DELETE')) THEN
 PERFORM public.telegram_assert_lease(p_environment,p_account,p_owner,p_generation);
 RETURN jsonb_build_object('id',anchor,'version',previous.version,'created',false); END IF;
 IF previous.version IS NOT NULL AND event_time=previous.observed_at AND event_kind<>'DELETE' THEN
 RAISE EXCEPTION 'conflicting revision timestamp' USING ERRCODE='22023'; END IF;
 INSERT INTO public.telegram_message_versions(environment_id,message_id,version,body_hash,raw_body,observed_at,event_kind,revision_hash,published_at,media_kind)
 VALUES(p_environment,anchor,next_version,p_data->>'body_hash',CASE WHEN event_kind='DELETE' THEN NULL ELSE raw END,
 event_time,event_kind,digest,published,COALESCE(p_data->>'media_kind','NONE'));
 IF next_version>1 OR event_kind='DELETE' THEN PERFORM public.telegram_invalidate_message(p_environment,anchor); END IF;
 stale:=published<clock_timestamp()-make_interval(secs=>p_max_age);
 topic:=CASE WHEN event_kind='DELETE' THEN 'telegram.message.deleted'
 WHEN stale THEN 'telegram.message.expired' ELSE 'telegram.message.received' END;
 INSERT INTO public.outbox_events(environment_id,id,event_key,topic,payload)
 VALUES(p_environment,gen_random_uuid(),'telegram:'||anchor::text||':'||next_version,topic,
 jsonb_build_object('message_id',anchor,'source_id',p_source,'message_version',next_version,
 'source_version',p_source_version,'event_kind',event_kind,'stale',stale,'schema_version',1));
 IF (NOT stale AND raw<>'') OR next_version>1 OR event_kind='DELETE' THEN
 INSERT INTO public.jobs(environment_id,id,service,dedupe_key,payload)
 VALUES(p_environment,gen_random_uuid(),'ai','telegram:'||anchor::text||':'||next_version,
 jsonb_build_object('type','telegram_message','message_id',anchor,'message_version',next_version,
 'source_id',p_source,'source_version',p_source_version,'review_only',stale OR next_version>1 OR event_kind='DELETE','schema_version',1)); END IF;
 INSERT INTO public.audit_events(id,environment_id,action,actor_service,target,details)
 VALUES(gen_random_uuid(),p_environment,'TELEGRAM_MESSAGE_'||event_kind,'collector',anchor::text,
 jsonb_build_object('version',next_version,'source_id',p_source,'stale',stale));

 PERFORM public.telegram_assert_lease(p_environment,p_account,p_owner,p_generation);
 RETURN jsonb_build_object('id',anchor,'version',next_version,'created',true);
END; $fn$;

CREATE OR REPLACE VIEW public.dashboard_sources AS
 SELECT s.environment_id,s.id,s.name,s.enabled,s.reference,s.version,s.resolution_state,
 CASE WHEN NOT s.enabled THEN 'DISABLED' ELSE COALESCE(c.status,'PENDING') END AS status,
 c.checked_at,c.gap_since,c.error_code,c.last_message_id,c.last_success_at,
 (SELECT count(*) FROM public.telegram_messages m WHERE (m.environment_id,m.source_id)=(s.environment_id,s.id)) AS message_count
 FROM public.telegram_sources s LEFT JOIN public.telegram_source_state c
 ON (c.environment_id,c.source_id)=(s.environment_id,s.id);
CREATE VIEW public.dashboard_telegram_messages AS
 SELECT m.environment_id,m.id,m.source_id,s.name AS source_name,m.message_id,m.reply_message_id,
 v.version,v.event_kind,v.published_at,v.observed_at,v.media_kind,
 v.raw_body IS NOT NULL AS body_available,left(v.raw_body,240) AS preview
 FROM public.telegram_messages m JOIN public.telegram_sources s ON (s.environment_id,s.id)=(m.environment_id,m.source_id)
 JOIN LATERAL (SELECT * FROM public.telegram_message_versions mv
 WHERE (mv.environment_id,mv.message_id)=(m.environment_id,m.id) ORDER BY mv.version DESC LIMIT 1) v ON true;
GRANT SELECT ON public.dashboard_telegram_messages TO trd_api;
REVOKE ALL ON FUNCTION public.telegram_invalidate_message(text,uuid),
 public.telegram_acquire_lease(text,text,text,integer),public.telegram_assert_lease(text,text,text,integer),
 public.telegram_release_lease(text,text,text,integer),public.telegram_source_observed(text,text,text,integer,uuid,integer,jsonb),
 public.telegram_ingest(text,text,text,integer,uuid,integer,jsonb,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.telegram_acquire_lease(text,text,text,integer),
 public.telegram_assert_lease(text,text,text,integer),public.telegram_release_lease(text,text,text,integer),
 public.telegram_source_observed(text,text,text,integer,uuid,integer,jsonb),
 public.telegram_ingest(text,text,text,integer,uuid,integer,jsonb,integer) TO trd_collector;

CREATE OR REPLACE FUNCTION public.apply_dashboard_change(
 p_environment text,p_session text,p_confirmation text,p_payload jsonb,p_idle integer)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,public,pg_temp AS $fn$
DECLARE actor uuid; current integer; next_version integer; old_policy jsonb; value jsonb;
 kind text; target text; expected integer; field text; agent uuid; model text; ordinal integer; command_message uuid;
BEGIN
 IF session_user <> 'trd_api' OR p_idle IS NULL OR p_idle NOT BETWEEN 60 AND 1800 THEN
 RAISE EXCEPTION 'API identity required' USING ERRCODE='42501'; END IF;
 SELECT s.user_id INTO actor FROM public.sessions s JOIN public.users u ON u.id=s.user_id
 WHERE s.environment_id=p_environment AND s.token_hash=p_session AND s.revoked_at IS NULL
 AND s.expires_at>clock_timestamp() AND s.last_seen_at>clock_timestamp()-make_interval(secs=>p_idle)
 AND u.active AND u.role='ADMIN' FOR UPDATE OF s;
 IF actor IS NULL THEN RAISE EXCEPTION 'administrator session required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.dashboard_confirmations WHERE environment_id=p_environment
 AND token_hash=p_confirmation AND session_hash=p_session AND payload=p_payload
 AND expires_at>clock_timestamp() AND consumed_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'confirmation rejected' USING ERRCODE='22023'; END IF;
 kind:=p_payload->>'kind'; target:=p_payload->>'target';
 expected:=(p_payload->>'expected_version')::integer; value:=p_payload->'value';
 IF expected IS NULL OR expected<0 OR (kind<>'source' AND expected<1) OR value IS NULL THEN
 RAISE EXCEPTION 'invalid change' USING ERRCODE='22023'; END IF;
 IF kind='settings' THEN
 next_version:=public.revise_system_setting(p_environment,target,expected,value,actor);
 ELSIF kind='risk' AND target='baseline' THEN
 -- Phase 3 can only tighten the current reviewed envelope. Execution is still disabled.
 PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||p_environment,0));
 IF EXISTS(SELECT 1 FROM public.execution_commands WHERE environment_id=p_environment
 AND state NOT IN ('COMPLETED','REJECTED','EXPIRED','INVALIDATED'))
 OR EXISTS(SELECT 1 FROM public.positions WHERE environment_id=p_environment AND status<>'CLOSED')
 OR EXISTS(SELECT 1 FROM public.risk_reservations WHERE environment_id=p_environment
 AND status IN ('HELD','OUTCOME_UNKNOWN')) THEN
 RAISE EXCEPTION 'active exposure requires risk gateway' USING ERRCODE='22023'; END IF;
 SELECT h.current_version,r.policy INTO current,old_policy FROM public.risk_rule_heads h
 JOIN public.risk_rules r ON (h.environment_id,h.key,h.current_version)=
 (r.environment_id,r.key,r.version) WHERE h.environment_id=p_environment AND h.key=target
 FOR UPDATE OF h;
 IF current IS NULL OR current<>expected THEN
 RAISE EXCEPTION 'version conflict' USING ERRCODE='40001'; END IF;
 IF jsonb_typeof(value)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(value)) <> 8 THEN
 RAISE EXCEPTION 'invalid policy' USING ERRCODE='22023'; END IF;
 FOREACH field IN ARRAY ARRAY['max_risk_per_trade','max_daily_loss','max_total_open_risk',
 'max_open_positions','max_lots','max_effective_leverage'] LOOP
 IF value->>field IS NULL
 OR (field<>'max_open_positions' AND jsonb_typeof(value->field)<>'string')
 OR value->>field !~ '^[0-9]+(\.[0-9]+)?$'
 OR (value->>field)::numeric<=0 OR (value->>field)::numeric>(old_policy->>field)::numeric THEN
 RAISE EXCEPTION 'policy exceeds reviewed envelope' USING ERRCODE='22023'; END IF;
 END LOOP;
 IF value->'require_stop_loss' IS DISTINCT FROM 'true'::jsonb
 OR value->'require_take_profit' IS DISTINCT FROM 'true'::jsonb
 OR jsonb_typeof(value->'max_open_positions')<>'number'
 OR value->>'max_open_positions' !~ '^[0-9]+$' THEN
 RAISE EXCEPTION 'protective stops required' USING ERRCODE='22023'; END IF;
 next_version:=current+1;
 INSERT INTO public.risk_rules(environment_id,key,version,policy,fingerprint,created_by)
 VALUES(p_environment,target,next_version,value,
 encode(sha256(convert_to(format(
 '{"max_risk_per_trade":%s,"max_daily_loss":%s,"max_total_open_risk":%s,"max_open_positions":%s,"max_lots":%s,"max_effective_leverage":%s,"require_stop_loss":%s,"require_take_profit":%s}',
 value->'max_risk_per_trade',value->'max_daily_loss',value->'max_total_open_risk',
 value->'max_open_positions',value->'max_lots',value->'max_effective_leverage',
 value->'require_stop_loss',value->'require_take_profit'),'UTF8')),'hex'),actor);
 UPDATE public.risk_rule_heads SET current_version=next_version
 WHERE environment_id=p_environment AND key=target;
 UPDATE public.trading_accounts SET safety_epoch=safety_epoch+1,status='PAUSED'
 WHERE environment_id=p_environment;
 ELSIF kind='source' THEN
 agent:=target::uuid;
 PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||p_environment,0));
 IF jsonb_typeof(value)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(value))<>3
 OR jsonb_typeof(value->'enabled')<>'boolean' OR jsonb_typeof(value->'name')<>'string'
 OR length(value->>'name') NOT BETWEEN 1 AND 160
 OR value->>'reference' IS NULL OR value->>'reference' !~ '^(@[a-zA-Z][a-zA-Z0-9_]{4,31}|-[1-9][0-9]{0,18})$' THEN
 RAISE EXCEPTION 'invalid source configuration' USING ERRCODE='22023'; END IF;
 SELECT version INTO current FROM public.telegram_sources WHERE environment_id=p_environment AND id=agent FOR UPDATE;
 IF expected=0 THEN
 IF current IS NOT NULL OR (SELECT count(*) FROM public.telegram_sources WHERE environment_id=p_environment)>=32 THEN
 RAISE EXCEPTION 'source creation conflict or limit' USING ERRCODE='40001'; END IF;
 current:=0; next_version:=1;
 INSERT INTO public.telegram_sources(environment_id,id,collector_identity,peer_id,name,enabled,reference)
 VALUES(p_environment,agent,'primary','pending:'||left(replace(agent::text,'-',''),24),value->>'name',(value->>'enabled')::boolean,value->>'reference');
 ELSE
 IF current IS NULL OR current<>expected THEN RAISE EXCEPTION 'source version conflict' USING ERRCODE='40001'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.telegram_sources WHERE environment_id=p_environment AND id=agent
 AND reference=value->>'reference' AND collector_identity='primary') THEN
 RAISE EXCEPTION 'source reference is immutable' USING ERRCODE='22023'; END IF;
 next_version:=current+1;
 UPDATE public.telegram_sources SET version=next_version,name=value->>'name',enabled=(value->>'enabled')::boolean
 WHERE environment_id=p_environment AND id=agent;
 IF NOT (value->>'enabled')::boolean THEN
 FOR command_message IN SELECT id FROM public.telegram_messages WHERE environment_id=p_environment AND source_id=agent LOOP
 PERFORM public.telegram_invalidate_message(p_environment,command_message); END LOOP;
 UPDATE public.telegram_source_state SET status='DISABLED' WHERE environment_id=p_environment AND source_id=agent;
 END IF;
 END IF;
 ELSIF kind='agent' THEN
 agent:=target::uuid;
 SELECT current_version INTO current FROM public.agents
 WHERE environment_id=p_environment AND id=agent FOR UPDATE;
 IF current IS NULL OR current<>expected THEN
 RAISE EXCEPTION 'version conflict' USING ERRCODE='40001'; END IF;
 IF value->'enabled' IS DISTINCT FROM 'false'::jsonb
 OR (value->>'timeout_seconds')::integer NOT BETWEEN 1 AND 120
 OR (value->>'max_output_tokens')::integer NOT BETWEEN 1 AND 4096
 OR (value->>'max_cost_usd')::numeric<>0
 OR jsonb_typeof(value->'fallback_model_ids')<>'array'
 OR jsonb_array_length(value->'fallback_model_ids')>2
 OR NOT EXISTS(SELECT 1 FROM public.prompt_versions WHERE environment_id=p_environment
 AND agent_id=agent AND version=(value->>'prompt_version')::integer) THEN
 RAISE EXCEPTION 'unavailable agent capability' USING ERRCODE='22023'; END IF;
 FOR model IN SELECT value->>'primary_model_id' UNION ALL
 SELECT jsonb_array_elements_text(value->'fallback_model_ids') LOOP
 IF NOT EXISTS(SELECT 1 FROM public.model_registry m WHERE m.id=model AND m.enabled
 AND m.provider='mock' AND m.schema_version=(value->>'required_schema_version')::integer
 AND m.max_output_tokens>=(value->>'max_output_tokens')::integer) THEN
 RAISE EXCEPTION 'incompatible model' USING ERRCODE='22023'; END IF;
 END LOOP;
 next_version:=current+1;
 INSERT INTO public.agent_configs(environment_id,agent_id,version,enabled,primary_model_id,
 prompt_version,timeout_seconds,max_output_tokens,max_cost_usd,required_schema_version,created_by)
 VALUES(p_environment,agent,next_version,false,value->>'primary_model_id',
 (value->>'prompt_version')::integer,(value->>'timeout_seconds')::integer,
 (value->>'max_output_tokens')::integer,0,(value->>'required_schema_version')::integer,actor);
 ordinal:=0;
 FOR model IN SELECT jsonb_array_elements_text(value->'fallback_model_ids') LOOP
 ordinal:=ordinal+1;
 INSERT INTO public.agent_fallbacks(environment_id,agent_id,config_version,ordinal,model_id)
 VALUES(p_environment,agent,next_version,ordinal,model);
 END LOOP;
 UPDATE public.agents SET current_version=next_version WHERE environment_id=p_environment AND id=agent;
 ELSE RAISE EXCEPTION 'unsupported change' USING ERRCODE='22023'; END IF;
 UPDATE public.dashboard_confirmations SET consumed_at=clock_timestamp()
 WHERE environment_id=p_environment AND token_hash=p_confirmation;
 IF kind<>'settings' THEN
 INSERT INTO public.audit_events(id,environment_id,action,actor_id,actor_service,target,details)
 VALUES(gen_random_uuid(),p_environment,upper(kind)||'_CONFIG_REVISED',actor,'api',target,
 jsonb_build_object('previous_version',current,'version',next_version)); END IF;
 RETURN next_version;
END; $fn$;

CREATE FUNCTION public.telegram_account_backoff(p_environment text,p_account text,p_owner text,p_generation integer,p_seconds integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
BEGIN
 PERFORM public.telegram_assert_lease(p_environment,p_account,p_owner,p_generation);
 IF p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 604800 THEN
 RAISE EXCEPTION 'invalid Telegram retry time' USING ERRCODE='22023'; END IF;
 UPDATE public.telegram_collector_leases SET retry_after=clock_timestamp()+make_interval(secs=>p_seconds)
 WHERE account_id=p_account;
END; $fn$;
REVOKE ALL ON FUNCTION public.telegram_account_backoff(text,text,text,integer,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.telegram_account_backoff(text,text,text,integer,integer) TO trd_collector;
