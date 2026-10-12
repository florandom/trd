-- Frozen phase 7 financial and enrollment contracts.
CREATE FUNCTION public.record_paper_audit(p_environment text,p_account uuid,
 p_action text,p_details jsonb) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE event uuid := gen_random_uuid();
BEGIN
 IF session_user<>'trd_risk' OR p_action NOT IN
 ('PAPER_BRIDGE_FAULT','PAPER_DAILY_LOSS_LATCHED','PAPER_COMMAND_RESERVED','PAPER_BROKER_FILL')
 OR jsonb_typeof(p_details) IS DISTINCT FROM 'object' OR octet_length(p_details::text)>2048
 OR NOT EXISTS(SELECT 1 FROM public.bridge_enrollments
 WHERE environment_id=p_environment AND account_id=p_account) THEN
 RAISE EXCEPTION 'paper audit identity required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.audit_events(id,environment_id,action,actor_service,target,details)
 VALUES(event,p_environment,p_action,'risk','paper-account:'||p_account,p_details);
 INSERT INTO public.outbox_events(environment_id,id,event_key,topic,payload)
 VALUES(p_environment,gen_random_uuid(),'paper-audit:'||event,'paper.evidence',
 jsonb_build_object('audit_id',event,'action',p_action,'account_id',p_account));
 RETURN event;
END; $fn$;
CREATE OR REPLACE FUNCTION public.apply_dashboard_change(p_environment text, p_session text, p_confirmation text, p_payload jsonb, p_idle integer)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
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
 IF EXISTS(SELECT 1 FROM public.trading_accounts a WHERE a.environment_id=p_environment
 AND (a.mode<>'paper' OR a.broker_server<>'TRD-PAPER-SIMULATOR'
 OR NOT EXISTS(SELECT 1 FROM public.bridge_enrollments b WHERE (b.environment_id,b.account_id)=(a.environment_id,a.id)))
 AND (EXISTS(SELECT 1 FROM public.execution_commands c WHERE (c.environment_id,c.account_id)=(a.environment_id,a.id) AND c.state NOT IN ('COMPLETED','REJECTED','EXPIRED','INVALIDATED'))
 OR EXISTS(SELECT 1 FROM public.positions p WHERE (p.environment_id,p.account_id)=(a.environment_id,a.id) AND p.status<>'CLOSED')
 OR EXISTS(SELECT 1 FROM public.risk_reservations r WHERE (r.environment_id,r.account_id)=(a.environment_id,a.id) AND r.status IN ('HELD','OUTCOME_UNKNOWN')))) THEN
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
 PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||p_environment,0));
 IF jsonb_typeof(value->'enabled') IS DISTINCT FROM 'boolean'
 OR ((value->>'enabled')::boolean AND NOT EXISTS(SELECT 1 FROM public.agents
 WHERE environment_id=p_environment AND id=agent AND name<>'POSITION_REVIEW_AGENT'))
 OR ((value->>'enabled')::boolean AND (value->>'prompt_version')::integer<>2)
 OR (value->>'timeout_seconds')::integer NOT BETWEEN 1 AND 120
 OR (value->>'max_output_tokens')::integer NOT BETWEEN 1 AND 4096
 OR value->>'max_cost_usd' IS NULL OR value->>'max_cost_usd' !~ '^[0-9]{1,18}(\.[0-9]{1,10})?$' OR ((value->>'max_cost_usd')::numeric<>0 AND NOT EXISTS(SELECT 1 FROM public.model_registry m WHERE m.provider='openrouter' AND (m.id=value->>'primary_model_id' OR value->'fallback_model_ids' ? m.id)))
 OR jsonb_typeof(value->'fallback_model_ids')<>'array'
 OR jsonb_array_length(value->'fallback_model_ids')>2
 OR NOT EXISTS(SELECT 1 FROM public.prompt_versions WHERE environment_id=p_environment
 AND agent_id=agent AND version=(value->>'prompt_version')::integer) THEN
 RAISE EXCEPTION 'unavailable agent capability' USING ERRCODE='22023'; END IF;
 FOR model IN SELECT value->>'primary_model_id' UNION ALL
 SELECT jsonb_array_elements_text(value->'fallback_model_ids') LOOP
 IF NOT EXISTS(SELECT 1 FROM public.model_registry m WHERE m.id=model AND m.enabled
 AND (m.provider='mock' OR (m.provider='openrouter' AND m.accepted_environment_id=p_environment AND m.input_token_limit BETWEEN 1 AND 1000000 AND m.provider_slug IS NOT NULL AND EXISTS(SELECT 1 FROM public.agents a WHERE a.environment_id=p_environment AND a.id=agent AND a.name IN ('MARKET_ANALYST','DECISION_AGENT','CRITIC')) AND (NOT (value->>'enabled')::boolean OR (m.accepted_until>clock_timestamp() AND (value->>'max_cost_usd')::numeric>0)))) AND m.schema_version=(value->>'required_schema_version')::integer
 AND m.max_output_tokens>=(value->>'max_output_tokens')::integer) THEN
 RAISE EXCEPTION 'incompatible model' USING ERRCODE='22023'; END IF;
 END LOOP;
 next_version:=current+1;
 INSERT INTO public.agent_configs(environment_id,agent_id,version,enabled,primary_model_id,
 prompt_version,timeout_seconds,max_output_tokens,max_cost_usd,required_schema_version,created_by)
 VALUES(p_environment,agent,next_version,(value->>'enabled')::boolean,value->>'primary_model_id',
 (value->>'prompt_version')::integer,(value->>'timeout_seconds')::integer,
 (value->>'max_output_tokens')::integer,(value->>'max_cost_usd')::numeric,(value->>'required_schema_version')::integer,actor);
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
END; $function$
;
CREATE OR REPLACE FUNCTION public.telegram_invalidate_message(p_environment text, p_message uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
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

 UPDATE public.risk_reservations r SET status='RELEASED'
 FROM public.execution_commands c WHERE (r.environment_id,r.id)=(c.environment_id,c.reservation_id)
 AND r.environment_id=p_environment AND r.status='HELD' AND c.state='INVALIDATED'
 AND EXISTS(SELECT 1 FROM public.paper_command_records p WHERE (p.environment_id,p.command_id,p.message_id)=(c.environment_id,c.id,p_message));
 FOR item IN SELECT o.* FROM public.orders o JOIN public.paper_command_records p
 ON (p.environment_id,p.command_id)=(o.environment_id,o.command_id)
 WHERE p.environment_id=p_environment AND p.message_id=p_message AND o.state IN ('PROPOSED','VALIDATED')
 AND EXISTS(SELECT 1 FROM public.execution_commands c WHERE (c.environment_id,c.id)=(o.environment_id,o.command_id) AND c.state='INVALIDATED') FOR UPDATE OF o LOOP
 UPDATE public.orders SET state='EXPIRED',revision=revision+1 WHERE environment_id=p_environment AND id=item.id;
 INSERT INTO public.lifecycle_events(environment_id,id,kind,entity_id,order_id,revision,"before","after",evidence,actor_service)
 VALUES(p_environment,gen_random_uuid(),'order',item.id,item.id,item.revision+1,item.state,'EXPIRED','OBSERVATION','risk');
 END LOOP;
 -- Delivered commands and their reservations are retained for future reconciliation.
END; $function$
;
CREATE OR REPLACE FUNCTION public.paper_account_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
    DECLARE item record;
    BEGIN
      IF NEW.safety_epoch < OLD.safety_epoch THEN RAISE EXCEPTION 'epoch cannot decrease' USING ERRCODE='22023'; END IF;
      PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||NEW.environment_id,0));
      IF NEW.status='PAUSED' OR NEW.safety_epoch<>OLD.safety_epoch THEN
        FOR item IN SELECT p.message_id FROM public.paper_command_records p
          JOIN public.execution_commands c ON (c.environment_id,c.id)=(p.environment_id,p.command_id)
          WHERE p.environment_id=NEW.environment_id AND p.account_id=NEW.id AND c.state IN ('CREATED','READY') LOOP
          PERFORM public.telegram_invalidate_message(NEW.environment_id,item.message_id);
        END LOOP;
      END IF;
      RETURN NEW;
    END; $function$
;
CREATE OR REPLACE FUNCTION public.paper_enrollment_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
    BEGIN
      IF NOT EXISTS(SELECT 1 FROM public.trading_accounts WHERE environment_id=NEW.environment_id AND id=NEW.account_id AND mode='paper' AND broker_server='TRD-PAPER-SIMULATOR') THEN
        RAISE EXCEPTION 'synthetic account required' USING ERRCODE='22023';
      END IF;
      IF TG_OP='UPDATE' AND (NEW.highwater<OLD.highwater
      OR (OLD.fault_latched AND NOT NEW.fault_latched)
      OR (OLD.journal_id IS NOT NULL AND NEW.journal_id IS DISTINCT FROM OLD.journal_id)) THEN
        RAISE EXCEPTION 'durable fence cannot decrease' USING ERRCODE='22023';
      END IF;
      RETURN NEW;
    END; $function$
;
CREATE OR REPLACE FUNCTION public.paper_baseline_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
    BEGIN
      IF OLD.loss_latched AND NOT NEW.loss_latched THEN RAISE EXCEPTION 'daily loss latch cannot clear' USING ERRCODE='22023'; END IF;
      RETURN NEW;
    END; $function$
;
