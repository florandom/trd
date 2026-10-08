CREATE TABLE public.auth_attempts (
 environment_id varchar(64) NOT NULL, bucket_hash varchar(64) NOT NULL,
 window_started timestamptz NOT NULL DEFAULT clock_timestamp(), attempts integer NOT NULL,
 PRIMARY KEY(environment_id,bucket_hash), CHECK(attempts >= 1)
);
CREATE TABLE public.auth_challenges (
 environment_id varchar(64) NOT NULL, token_hash varchar(64) NOT NULL,
 expires_at timestamptz NOT NULL, PRIMARY KEY(environment_id,token_hash)
);
CREATE TABLE public.dashboard_confirmations (
 environment_id varchar(64) NOT NULL, token_hash varchar(64) NOT NULL,
 session_hash varchar(64) NOT NULL REFERENCES public.sessions(token_hash),
 payload jsonb NOT NULL, expires_at timestamptz NOT NULL,
 consumed_at timestamptz, PRIMARY KEY(environment_id,token_hash)
);
CREATE INDEX ix_sessions_expiry ON public.sessions(expires_at);
CREATE INDEX ix_auth_challenges_expiry ON public.auth_challenges(expires_at);
GRANT SELECT,INSERT,UPDATE,DELETE ON public.auth_attempts,public.auth_challenges,
 public.dashboard_confirmations TO trd_api;
GRANT SELECT,INSERT ON public.sessions TO trd_api;
GRANT UPDATE(last_seen_at,revoked_at) ON public.sessions TO trd_api;
CREATE FUNCTION public.lookup_login_user(p_email text)
RETURNS TABLE(id uuid,email varchar,role varchar,active boolean,password_hash text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog,public,pg_temp AS $fn$
BEGIN
 IF session_user <> 'trd_api' THEN
  RAISE EXCEPTION 'API identity required' USING ERRCODE='42501'; END IF;
 RETURN QUERY SELECT u.id,u.email,u.role,u.active,u.password_hash
 FROM public.users u WHERE u.email = p_email;
END; $fn$;
CREATE FUNCTION public.dashboard_auth_audit(p_environment text,p_actor uuid,p_action text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog,public,pg_temp AS $fn$
BEGIN
 IF session_user <> 'trd_api' OR p_environment IS NULL
 OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$'
 OR p_action NOT IN ('LOGIN_SUCCEEDED','LOGIN_FAILED','LOGOUT') THEN
 RAISE EXCEPTION 'invalid auth audit' USING ERRCODE='42501'; END IF;
 INSERT INTO public.audit_events(id,environment_id,action,actor_id,actor_service,target,details)
 VALUES(gen_random_uuid(),p_environment,p_action,p_actor,'api','authentication','{}');
END; $fn$;
CREATE VIEW public.dashboard_audit AS
 SELECT a.id,a.environment_id,a.action,a.actor_id,a.actor_service,a.target,a.created_at,
 u.email AS actor_email FROM public.audit_events a LEFT JOIN public.users u ON u.id=a.actor_id;
CREATE VIEW public.dashboard_agents AS
 SELECT a.environment_id,a.id,a.name,a.current_version,c.enabled,c.primary_model_id,
 c.prompt_version,c.timeout_seconds,c.max_output_tokens,c.max_cost_usd::text,
 c.required_schema_version,
 COALESCE((SELECT jsonb_agg(f.model_id ORDER BY f.ordinal) FROM public.agent_fallbacks f
 WHERE (f.environment_id,f.agent_id,f.config_version)=
 (a.environment_id,a.id,a.current_version)), '[]'::jsonb) AS fallback_model_ids
 FROM public.agents a JOIN public.agent_configs c ON
 (a.environment_id,a.id,a.current_version)=(c.environment_id,c.agent_id,c.version);
CREATE VIEW public.dashboard_risk AS
 SELECT h.environment_id,h.key,h.current_version,r.policy,r.fingerprint FROM public.risk_rule_heads h
 JOIN public.risk_rules r ON (h.environment_id,h.key,h.current_version)=
 (r.environment_id,r.key,r.version);
CREATE VIEW public.dashboard_sources AS
 SELECT environment_id,id,name,enabled FROM public.telegram_sources;
CREATE VIEW public.dashboard_costs AS
 SELECT environment_id,id,run_id,input_tokens,output_tokens,estimated_cost_usd::text,
 pricing_version,usage_known,created_at FROM public.ai_usage;
CREATE VIEW public.dashboard_signal_versions AS
 SELECT environment_id,signal_id,version,proposal,created_at FROM public.signal_versions;
GRANT SELECT ON public.dashboard_audit,public.dashboard_agents,public.dashboard_risk,public.dashboard_sources,
 public.dashboard_costs,public.dashboard_signal_versions TO trd_api;
CREATE FUNCTION public.apply_dashboard_change(
 p_environment text,p_session text,p_confirmation text,p_payload jsonb,p_idle integer)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,public,pg_temp AS $fn$
DECLARE actor uuid; current integer; next_version integer; old_policy jsonb; value jsonb;
 kind text; target text; expected integer; field text; agent uuid; model text; ordinal integer;
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
 IF expected IS NULL OR expected<1 OR value IS NULL THEN
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
REVOKE ALL ON FUNCTION public.lookup_login_user(text),public.dashboard_auth_audit(text,uuid,text),
 public.apply_dashboard_change(text,text,text,jsonb,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.lookup_login_user(text),public.dashboard_auth_audit(text,uuid,text),
 public.apply_dashboard_change(text,text,text,jsonb,integer) TO trd_api;

CREATE FUNCTION public.prune_dashboard_auth(p_environment text,p_limit integer)
RETURNS TABLE(challenge_count integer,attempt_count integer,confirmation_count integer,session_count integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
BEGIN
 IF session_user<>'trd_maintenance' THEN
 RAISE EXCEPTION 'maintenance identity required' USING ERRCODE='42501'; END IF;
 IF p_environment IS NULL OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$'
 OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 500 THEN
 RAISE EXCEPTION 'invalid cleanup request' USING ERRCODE='22023'; END IF;
 WITH candidates AS (SELECT token_hash FROM public.auth_challenges
 WHERE environment_id=p_environment AND expires_at<clock_timestamp()
 ORDER BY expires_at LIMIT p_limit FOR UPDATE SKIP LOCKED)
 DELETE FROM public.auth_challenges a USING candidates c
 WHERE a.environment_id=p_environment AND a.token_hash=c.token_hash;
 GET DIAGNOSTICS challenge_count=ROW_COUNT;
 WITH candidates AS (SELECT bucket_hash FROM public.auth_attempts
 WHERE environment_id=p_environment AND window_started<clock_timestamp()-interval '1 day'
 ORDER BY window_started LIMIT p_limit FOR UPDATE SKIP LOCKED)
 DELETE FROM public.auth_attempts a USING candidates c
 WHERE a.environment_id=p_environment AND a.bucket_hash=c.bucket_hash;
 GET DIAGNOSTICS attempt_count=ROW_COUNT;
 WITH candidates AS (SELECT token_hash FROM public.dashboard_confirmations
 WHERE environment_id=p_environment AND expires_at<clock_timestamp()-interval '1 day'
 ORDER BY expires_at LIMIT p_limit FOR UPDATE SKIP LOCKED)
 DELETE FROM public.dashboard_confirmations a USING candidates c
 WHERE a.environment_id=p_environment AND a.token_hash=c.token_hash;
 GET DIAGNOSTICS confirmation_count=ROW_COUNT;
 WITH candidates AS (SELECT token_hash FROM public.sessions s
 WHERE environment_id=p_environment AND (expires_at<clock_timestamp()-interval '1 day'
 OR revoked_at<clock_timestamp()-interval '1 day') AND NOT EXISTS(
 SELECT 1 FROM public.dashboard_confirmations c WHERE c.session_hash=s.token_hash)
 ORDER BY expires_at LIMIT p_limit FOR UPDATE SKIP LOCKED)
 DELETE FROM public.sessions a USING candidates c
 WHERE a.environment_id=p_environment AND a.token_hash=c.token_hash;
 GET DIAGNOSTICS session_count=ROW_COUNT;
 RETURN NEXT;
END; $fn$;
REVOKE ALL ON FUNCTION public.prune_dashboard_auth(text,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.prune_dashboard_auth(text,integer) TO trd_maintenance;
