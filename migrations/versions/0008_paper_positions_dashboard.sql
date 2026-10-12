CREATE OR REPLACE FUNCTION public.apply_dashboard_change(p_environment text, p_session text, p_confirmation text, p_payload jsonb, p_idle integer)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE actor uuid; current integer; next_version integer; old_policy jsonb; value jsonb;
 kind text; target text; expected integer; field text; agent uuid; model text; ordinal integer; command_message uuid; paper_account uuid; paper_epoch integer;
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
 ELSIF kind IN ('paper_position','paper_resume') THEN
 PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||p_environment,0));
 IF NOT EXISTS(SELECT 1 FROM public.dashboard_confirmations
 WHERE environment_id=p_environment AND token_hash=p_confirmation AND session_hash=p_session
 AND payload=p_payload AND consumed_at IS NULL AND expires_at>clock_timestamp())
 OR NOT EXISTS(SELECT 1 FROM public.sessions s JOIN public.users u ON u.id=s.user_id
 WHERE s.environment_id=p_environment AND s.token_hash=p_session AND s.revoked_at IS NULL
 AND s.expires_at>clock_timestamp() AND s.last_seen_at>clock_timestamp()-make_interval(secs=>p_idle)
 AND u.active AND u.role='ADMIN') THEN
 RAISE EXCEPTION 'confirmation expired during lock contention' USING ERRCODE='42501'; END IF;

 agent:=target::uuid;
 IF jsonb_typeof(value)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(value))<>3
 OR value->>'action' NOT IN ('CLOSE','MODIFY_STOPS','RESUME')
 OR (kind='paper_resume') IS DISTINCT FROM (value->>'action'='RESUME') THEN
 RAISE EXCEPTION 'invalid paper action' USING ERRCODE='22023'; END IF;
 IF kind='paper_position' THEN
 SELECT p.account_id INTO paper_account FROM public.positions p
 WHERE p.environment_id=p_environment AND p.id=agent;
 ELSE paper_account:=agent; END IF;
 SELECT a.safety_epoch INTO paper_epoch FROM public.trading_accounts a
 JOIN public.bridge_enrollments b ON (b.environment_id,b.account_id)=(a.environment_id,a.id)
 WHERE a.environment_id=p_environment AND a.id=paper_account
 AND a.mode='paper' AND a.broker_server='TRD-PAPER-SIMULATOR' FOR UPDATE OF a;
 IF paper_epoch IS NULL THEN RAISE EXCEPTION 'enrolled paper account required' USING ERRCODE='22023'; END IF;
 IF kind='paper_position' THEN
 SELECT ps.revision INTO current FROM public.positions p
 JOIN public.paper_position_state ps ON (ps.environment_id,ps.position_id)=(p.environment_id,p.id)
 JOIN public.orders o ON (o.environment_id,o.id)=(p.environment_id,p.order_id)
 WHERE p.environment_id=p_environment AND p.id=agent AND p.status='OPEN' AND o.state='FILLED'
 FOR UPDATE OF p,ps;
 ELSE current:=paper_epoch; END IF;
 IF current IS NULL OR current<>expected OR EXISTS(SELECT 1 FROM public.paper_operations
 WHERE environment_id=p_environment AND account_id=paper_account AND state IN ('PENDING','DISPATCHED','UNKNOWN')
 AND (kind='paper_resume' OR position_id=agent)) THEN
 RAISE EXCEPTION 'paper version or operation conflict' USING ERRCODE='40001'; END IF;
 IF value->>'action'='MODIFY_STOPS' THEN
 FOREACH field IN ARRAY ARRAY['stop_loss','take_profit'] LOOP
 IF jsonb_typeof(value->field)<>'string' OR value->>field !~ '^[0-9]{1,18}(\.[0-9]{1,10})?$'
 OR (value->>field)::numeric<=0 THEN RAISE EXCEPTION 'invalid protection' USING ERRCODE='22023'; END IF;
 END LOOP;
 ELSIF value->'stop_loss' IS DISTINCT FROM 'null'::jsonb OR value->'take_profit' IS DISTINCT FROM 'null'::jsonb THEN
 RAISE EXCEPTION 'unexpected protection' USING ERRCODE='22023'; END IF;
 INSERT INTO public.paper_operations(environment_id,id,account_id,position_id,actor_id,action,
 expected_revision,safety_epoch,value,expires_at)
 VALUES(p_environment,gen_random_uuid(),paper_account,CASE WHEN kind='paper_position' THEN agent END,
 actor,value->>'action',current,paper_epoch,value,clock_timestamp()+interval '2 minutes');
 next_version:=current;
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
