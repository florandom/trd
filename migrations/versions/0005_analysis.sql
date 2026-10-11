-- Jobs, source revisions, message revisions and config versions fence advisory work.
CREATE TABLE public.analysis_records (
 environment_id varchar(64) NOT NULL, id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 job_id uuid NOT NULL, message_id uuid NOT NULL, message_version integer NOT NULL,
 source_version integer NOT NULL CHECK(source_version>=1), signal_id uuid, trace_id uuid NOT NULL,
 classification varchar(16) NOT NULL CHECK(classification IN ('NOISE','STRUCTURED','AMBIGUOUS','REVIEW')),
 outcome varchar(16) NOT NULL CHECK(outcome IN ('IGNORED','ESCALATED','EXPIRED','WAITING','REJECTED_AI')),
 reason_codes jsonb NOT NULL, route_version varchar(64) NOT NULL,
 input_hash varchar(64) NOT NULL CHECK(input_hash ~ '^[a-f0-9]{64}$'), config_versions jsonb NOT NULL,
 PRIMARY KEY(environment_id,id), UNIQUE(environment_id,job_id),
 UNIQUE(environment_id,message_id,message_version),
 FOREIGN KEY(environment_id,job_id) REFERENCES public.jobs(environment_id,id),
 FOREIGN KEY(environment_id,signal_id) REFERENCES public.signals(environment_id,id),
 FOREIGN KEY(environment_id,message_id,message_version)
 REFERENCES public.telegram_message_versions(environment_id,message_id,version)
);
CREATE TRIGGER protect_analysis_records BEFORE UPDATE OR DELETE ON public.analysis_records
 FOR EACH ROW EXECUTE FUNCTION public.protect_domain_record('');

CREATE TABLE public.ai_budget_reservations (
 environment_id varchar(64) NOT NULL, id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 job_id uuid NOT NULL, generation integer NOT NULL, agent_id uuid NOT NULL,
 config_version integer NOT NULL, model_id varchar(64) NOT NULL REFERENCES public.model_registry(id),
 attempt integer NOT NULL, reserved_usd numeric(28,10) NOT NULL CHECK(reserved_usd>=0),
 charged_usd numeric(28,10) CHECK(charged_usd>=0),
 input_token_ceiling integer NOT NULL CHECK(input_token_ceiling>=0),
 output_token_ceiling integer NOT NULL CHECK(output_token_ceiling>0),
 state varchar(16) NOT NULL DEFAULT 'RESERVED' CHECK(state IN ('RESERVED','SETTLED','UNKNOWN')),
 snapshot jsonb NOT NULL, settled_at timestamptz,
 CHECK(attempt BETWEEN 1 AND 3 AND generation>=1),
 CHECK((state='SETTLED')=(charged_usd IS NOT NULL)),
 PRIMARY KEY(environment_id,id), UNIQUE(environment_id,job_id,generation,agent_id,attempt),
 FOREIGN KEY(environment_id,job_id) REFERENCES public.jobs(environment_id,id),
 FOREIGN KEY(environment_id,agent_id,config_version)
 REFERENCES public.agent_configs(environment_id,agent_id,version)
);
CREATE INDEX ix_ai_budget_period ON public.ai_budget_reservations(environment_id,created_at);
CREATE TRIGGER identity_ai_budget BEFORE UPDATE ON public.ai_budget_reservations
 FOR EACH ROW EXECUTE FUNCTION public.protect_domain_identity('state,charged_usd,settled_at');

CREATE FUNCTION public.analysis_assert_job(p_environment text,p_job uuid,p_worker text,p_generation integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE item public.jobs; source public.telegram_sources; message public.telegram_message_versions;
BEGIN
 IF session_user<>'trd_ai' THEN RAISE EXCEPTION 'analysis identity required' USING ERRCODE='42501'; END IF;
 IF p_environment IS NULL OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$' OR p_job IS NULL
 OR p_worker IS NULL OR p_generation IS NULL THEN
 RAISE EXCEPTION 'invalid analysis identity' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||p_environment,0));
 SELECT * INTO item FROM public.jobs WHERE environment_id=p_environment AND id=p_job FOR UPDATE;
 IF item.service IS DISTINCT FROM 'ai' OR item.state IS DISTINCT FROM 'RUNNING'
 OR item.lease_owner IS DISTINCT FROM p_worker OR item.generation IS DISTINCT FROM p_generation
 OR item.lease_until<=clock_timestamp() THEN
 RAISE EXCEPTION 'analysis ownership lost' USING ERRCODE='40001'; END IF;
 IF item.payload->>'type' IS DISTINCT FROM 'telegram_message'
 OR item.payload->'schema_version' IS DISTINCT FROM '1'::jsonb THEN
 RAISE EXCEPTION 'unsupported analysis job' USING ERRCODE='22023'; END IF;
 SELECT s.* INTO source FROM public.telegram_sources s
 JOIN public.telegram_messages m ON (m.environment_id,m.source_id)=(s.environment_id,s.id)
 WHERE m.environment_id=p_environment AND m.id=(item.payload->>'message_id')::uuid
 AND s.id=(item.payload->>'source_id')::uuid;
 SELECT * INTO message FROM public.telegram_message_versions
 WHERE environment_id=p_environment AND message_id=(item.payload->>'message_id')::uuid
 ORDER BY version DESC LIMIT 1;
 IF source.enabled IS DISTINCT FROM true OR source.version IS DISTINCT FROM
 (item.payload->>'source_version')::integer OR message.version IS DISTINCT FROM
 (item.payload->>'message_version')::integer THEN
 RAISE EXCEPTION 'analysis input changed' USING ERRCODE='40001'; END IF;
 RETURN jsonb_build_object('body',message.raw_body,'body_hash',message.body_hash,
 'published_at',COALESCE(message.published_at,message.observed_at),
 'event_kind',message.event_kind,'reply_message_id',(SELECT reply_message_id FROM public.telegram_messages
 WHERE environment_id=p_environment AND id=(item.payload->>'message_id')::uuid),
 'now',clock_timestamp(),'payload',item.payload);
END; $fn$;

CREATE FUNCTION public.analysis_reserve_attempt(p_environment text,p_job uuid,p_worker text,
 p_generation integer,p_agent uuid,p_config integer,p_model text,p_attempt integer,
 p_input integer,p_output integer,p_limits jsonb)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE input jsonb; config public.agent_configs; model public.model_registry; agent public.agents;
 prompt public.prompt_versions; previous public.ai_budget_reservations; cost numeric; spent numeric;
 reservation uuid; day_start timestamptz; month_start timestamptz; snapshot jsonb;
BEGIN
 input:=public.analysis_assert_job(p_environment,p_job,p_worker,p_generation);
 IF p_attempt IS NULL OR p_attempt NOT BETWEEN 1 AND 3 OR p_input IS NULL
 OR p_input NOT BETWEEN 0 AND 32768 OR p_output IS NULL OR p_output NOT BETWEEN 1 AND 4096
 OR p_limits IS NULL OR jsonb_typeof(p_limits)<>'object' THEN
 RAISE EXCEPTION 'invalid attempt bounds' USING ERRCODE='22023'; END IF;
 IF NOT (p_limits ?& ARRAY['daily_usd','monthly_usd','request_usd','agent_daily_usd'])
 OR EXISTS(SELECT 1 FROM jsonb_each_text(p_limits) x WHERE x.value !~ '^[0-9]+(\.[0-9]+)?$') THEN
 RAISE EXCEPTION 'invalid cost limits' USING ERRCODE='22023'; END IF;
 SELECT * INTO agent FROM public.agents WHERE environment_id=p_environment AND id=p_agent;
 SELECT * INTO config FROM public.agent_configs WHERE environment_id=p_environment
 AND agent_id=p_agent AND version=p_config;
 SELECT * INTO model FROM public.model_registry WHERE id=p_model;
 SELECT * INTO prompt FROM public.prompt_versions WHERE environment_id=p_environment
 AND agent_id=p_agent AND version=config.prompt_version;
 IF agent.current_version IS DISTINCT FROM p_config OR config.enabled IS DISTINCT FROM true
 OR agent.name NOT IN ('MARKET_ANALYST','DECISION_AGENT','CRITIC')
 OR model.enabled IS DISTINCT FROM true OR model.schema_version IS DISTINCT FROM config.required_schema_version
 OR p_output>LEAST(model.max_output_tokens,config.max_output_tokens) OR prompt.body IS NULL
 OR prompt.checksum<>encode(sha256(convert_to(prompt.body,'UTF8')),'hex')
 OR (p_attempt=1 AND config.primary_model_id IS DISTINCT FROM p_model)
 OR (p_attempt>1 AND NOT EXISTS(SELECT 1 FROM public.agent_fallbacks
 WHERE environment_id=p_environment AND agent_id=p_agent AND config_version=p_config
 AND ordinal=p_attempt-1 AND model_id=p_model)) THEN
 RAISE EXCEPTION 'agent configuration changed or unavailable' USING ERRCODE='40001'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('trd-ai-budget:'||p_environment,0));
 SELECT * INTO previous FROM public.ai_budget_reservations WHERE environment_id=p_environment
 AND job_id=p_job AND generation=p_generation AND agent_id=p_agent AND attempt=p_attempt;
 IF FOUND THEN
 IF previous.config_version<>p_config OR previous.model_id<>p_model
 OR previous.input_token_ceiling<>p_input OR previous.output_token_ceiling<>p_output THEN
 RAISE EXCEPTION 'attempt identity conflict' USING ERRCODE='22023'; END IF;
 RETURN previous.id; END IF;
 IF (SELECT count(*) FROM public.ai_budget_reservations WHERE environment_id=p_environment
 AND job_id=p_job AND agent_id=p_agent)>=3 THEN
 RAISE EXCEPTION 'provider attempt limit reached' USING ERRCODE='22023'; END IF;
 -- Unresolved earlier generations are never blindly resubmitted after a restart.
 IF EXISTS(SELECT 1 FROM public.ai_budget_reservations WHERE environment_id=p_environment
 AND job_id=p_job AND state IN ('RESERVED','UNKNOWN')) THEN
 RAISE EXCEPTION 'unresolved provider attempt' USING ERRCODE='22023'; END IF;
 cost:=ceil((p_input*model.input_price_per_million+p_output*model.output_price_per_million)
 /1000000*10000000000)/10000000000;
 IF model.provider='mock' AND cost<>0 THEN
 RAISE EXCEPTION 'invalid mock pricing' USING ERRCODE='22023'; END IF;
 IF cost>LEAST((p_limits->>'request_usd')::numeric,config.max_cost_usd) THEN
 RAISE EXCEPTION 'budget exhausted' USING ERRCODE='P0001'; END IF;
 day_start:=date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
 month_start:=date_trunc('month',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
 SELECT COALESCE(sum(COALESCE(charged_usd,reserved_usd)),0) INTO spent FROM public.ai_budget_reservations
 WHERE environment_id=p_environment AND (created_at>=day_start OR settled_at>=day_start OR state<>'SETTLED');
 IF spent+cost>(p_limits->>'daily_usd')::numeric THEN
 RAISE EXCEPTION 'budget exhausted' USING ERRCODE='P0001'; END IF;
 SELECT COALESCE(sum(COALESCE(charged_usd,reserved_usd)),0) INTO spent FROM public.ai_budget_reservations
 WHERE environment_id=p_environment AND (created_at>=month_start OR settled_at>=month_start OR state<>'SETTLED');
 IF spent+cost>(p_limits->>'monthly_usd')::numeric THEN
 RAISE EXCEPTION 'budget exhausted' USING ERRCODE='P0001'; END IF;
 SELECT COALESCE(sum(COALESCE(charged_usd,reserved_usd)),0) INTO spent FROM public.ai_budget_reservations
 WHERE environment_id=p_environment AND agent_id=p_agent
 AND (created_at>=day_start OR settled_at>=day_start OR state<>'SETTLED');
 IF spent+cost>(p_limits->>'agent_daily_usd')::numeric THEN
 RAISE EXCEPTION 'budget exhausted' USING ERRCODE='P0001'; END IF;
 reservation:=gen_random_uuid();
 snapshot:=jsonb_build_object('worker',p_worker,'input_hash',input->>'body_hash',
 'prompt_version',prompt.version,'prompt_checksum',prompt.checksum,'stage',agent.name,
 'pricing_version',model.pricing_version,'input_price',model.input_price_per_million::text,
 'output_price',model.output_price_per_million::text,'schema_version',model.schema_version,
 'route_version','structured-fx-v1');
 INSERT INTO public.ai_budget_reservations(environment_id,id,job_id,generation,agent_id,config_version,
 model_id,attempt,reserved_usd,input_token_ceiling,output_token_ceiling,snapshot)
 VALUES(p_environment,reservation,p_job,p_generation,p_agent,p_config,p_model,p_attempt,cost,p_input,p_output,snapshot);
 RETURN reservation;
END; $fn$;

CREATE FUNCTION public.analysis_settle_attempt(p_environment text,p_reservation uuid,p_worker text,p_result jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE item public.ai_budget_reservations; cost numeric; known boolean; status text; trace uuid;
BEGIN
 IF session_user<>'trd_ai' THEN RAISE EXCEPTION 'analysis identity required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||p_environment,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('trd-ai-budget:'||p_environment,0));
 SELECT * INTO item FROM public.ai_budget_reservations WHERE environment_id=p_environment AND id=p_reservation FOR UPDATE;
 IF NOT FOUND OR item.snapshot->>'worker' IS DISTINCT FROM p_worker THEN
 RAISE EXCEPTION 'attempt ownership lost' USING ERRCODE='40001'; END IF;
 IF item.state<>'RESERVED' THEN RAISE EXCEPTION 'attempt already settled' USING ERRCODE='40001'; END IF;
 IF p_result IS NULL OR octet_length(p_result::text)>8192 OR p_result->>'status' IS NULL
 OR p_result->>'status' NOT IN ('SUCCEEDED','REFUSED','FAILED','UNKNOWN')
 OR jsonb_typeof(p_result->'usage_known') IS DISTINCT FROM 'boolean'
 OR p_result->>'input_tokens' !~ '^[0-9]{1,7}$' OR p_result->>'output_tokens' !~ '^[0-9]{1,7}$'
 OR p_result->>'trace_id' IS NULL THEN
 RAISE EXCEPTION 'invalid attempt result' USING ERRCODE='22023'; END IF;
 trace:=(p_result->>'trace_id')::uuid;
 known:=(p_result->>'usage_known')::boolean;
 cost:=ceil(((p_result->>'input_tokens')::integer*(item.snapshot->>'input_price')::numeric
 +(p_result->>'output_tokens')::integer*(item.snapshot->>'output_price')::numeric)
 /1000000*10000000000)/10000000000;
 IF (p_result->>'input_tokens')::integer>item.input_token_ceiling
 OR (p_result->>'output_tokens')::integer>item.output_token_ceiling OR cost>item.reserved_usd THEN known:=false; END IF;
 status:=CASE WHEN known THEN p_result->>'status' ELSE 'UNKNOWN' END;
 UPDATE public.ai_budget_reservations SET state=CASE WHEN known THEN 'SETTLED' ELSE 'UNKNOWN' END,
 charged_usd=CASE WHEN known THEN cost END,settled_at=clock_timestamp()
 WHERE environment_id=p_environment AND id=p_reservation;
 INSERT INTO public.agent_runs(environment_id,id,agent_id,config_version,trace_id,model_id,attempt,status,result)
 VALUES(p_environment,item.id,item.agent_id,item.config_version,trace,item.model_id,item.attempt,status,
 item.snapshot || (p_result - ARRAY['trace_id','input_tokens','output_tokens','usage_known']));
 INSERT INTO public.ai_usage(environment_id,id,run_id,input_tokens,output_tokens,estimated_cost_usd,pricing_version,usage_known)
 VALUES(p_environment,gen_random_uuid(),item.id,(p_result->>'input_tokens')::integer,
 (p_result->>'output_tokens')::integer,CASE WHEN known THEN cost ELSE GREATEST(cost,item.reserved_usd) END,
 item.snapshot->>'pricing_version',known);
END; $fn$;

CREATE FUNCTION public.analysis_complete(p_environment text,p_job uuid,p_worker text,p_generation integer,p_result jsonb)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE input jsonb; proposal jsonb; signal uuid; record_id uuid; stage record; revision integer; state text;
BEGIN
 input:=public.analysis_assert_job(p_environment,p_job,p_worker,p_generation);
 IF p_result IS NULL OR octet_length(p_result::text)>16384
 OR p_result->>'input_hash' IS DISTINCT FROM input->>'body_hash'
 OR p_result->>'route_version' IS DISTINCT FROM 'structured-fx-v1'
 OR p_result->>'outcome' IS NULL OR p_result->>'outcome' NOT IN ('IGNORED','ESCALATED','EXPIRED','WAITING','REJECTED_AI')
 OR p_result->>'classification' IS NULL OR p_result->>'classification' NOT IN ('NOISE','STRUCTURED','AMBIGUOUS','REVIEW')
 OR jsonb_typeof(p_result->'reason_codes') IS DISTINCT FROM 'array'
 OR jsonb_array_length(p_result->'reason_codes') NOT BETWEEN 1 AND 12
 OR jsonb_typeof(p_result->'config_versions') IS DISTINCT FROM 'object' THEN
 RAISE EXCEPTION 'invalid analysis record' USING ERRCODE='22023'; END IF;
 FOR stage IN SELECT * FROM jsonb_each_text(p_result->'config_versions') LOOP
 IF stage.value !~ '^[1-9][0-9]*$' OR NOT EXISTS(SELECT 1 FROM public.agents
 WHERE environment_id=p_environment AND name=stage.key AND current_version=stage.value::integer) THEN
 RAISE EXCEPTION 'analysis configuration changed' USING ERRCODE='40001'; END IF; END LOOP;
 proposal:=p_result->'proposal';
 IF proposal IS NOT NULL AND proposal<>'null'::jsonb THEN
 IF (input->'payload'->>'review_only')::boolean OR input->>'event_kind'<>'NEW'
 OR (input->'payload'->>'message_version')::integer<>1 OR input->>'reply_message_id' IS NOT NULL
 OR p_result->>'classification'<>'STRUCTURED' OR jsonb_typeof(proposal)<>'object'
 OR (SELECT count(*) FROM jsonb_object_keys(proposal))<>6
 OR proposal->>'side' IS NULL OR proposal->>'side' NOT IN ('BUY','SELL')
 OR proposal->>'symbol' IS NULL OR proposal->>'symbol' NOT IN ('EURUSD','GBPUSD','USDJPY','USDCHF','AUDUSD','USDCAD','NZDUSD')
 OR proposal->>'entry' IS NULL OR proposal->>'entry' !~ '^[0-9]+(\.[0-9]+)?$'
 OR proposal->>'stop_loss' IS NULL OR proposal->>'stop_loss' !~ '^[0-9]+(\.[0-9]+)?$'
 OR proposal->>'take_profit' IS NULL OR proposal->>'take_profit' !~ '^[0-9]+(\.[0-9]+)?$'
 OR (proposal->>'entry')::numeric<=0 OR (proposal->>'stop_loss')::numeric<=0 OR (proposal->>'take_profit')::numeric<=0
 OR proposal->>'expires_at' IS NULL OR (proposal->>'expires_at')::timestamptz<=clock_timestamp()
 OR (input->>'published_at')::timestamptz>clock_timestamp()+interval '5 seconds'
 OR NOT ((proposal->>'side'='BUY' AND (proposal->>'stop_loss')::numeric<(proposal->>'entry')::numeric
 AND (proposal->>'entry')::numeric<(proposal->>'take_profit')::numeric)
 OR (proposal->>'side'='SELL' AND (proposal->>'take_profit')::numeric<(proposal->>'entry')::numeric
 AND (proposal->>'entry')::numeric<(proposal->>'stop_loss')::numeric)) THEN
 RAISE EXCEPTION 'invalid or expired advisory proposal' USING ERRCODE='22023'; END IF;
 signal:=gen_random_uuid();
 INSERT INTO public.signals(environment_id,id,message_id,intent_key,trace_id,expires_at)
 VALUES(p_environment,signal,(input->'payload'->>'message_id')::uuid,'initial-analysis',
 (p_result->>'trace_id')::uuid,(proposal->>'expires_at')::timestamptz);
 PERFORM public.append_signal_version(p_environment,signal,0,1,proposal,
 encode(sha256(convert_to(format(
 '{"symbol":%s,"side":%s,"entry":%s,"stop_loss":%s,"take_profit":%s,"expires_at":%s}',
 proposal->'symbol',proposal->'side',proposal->'entry',proposal->'stop_loss',
 proposal->'take_profit',proposal->'expires_at'),'UTF8')),'hex'));
 revision:=1;
 FOREACH state IN ARRAY ARRAY['CLASSIFIED','PARSED','ANALYZING','DECIDED',
 CASE WHEN p_result->>'outcome'='WAITING' THEN 'WAITING'
 WHEN p_result->>'outcome'='REJECTED_AI' THEN 'REJECTED_AI' ELSE 'ESCALATED' END] LOOP
 revision:=public.transition_domain_entity(p_environment,'signal',signal,revision,state,'OBSERVATION',gen_random_uuid());
 END LOOP;
 END IF;
 record_id:=gen_random_uuid();
 INSERT INTO public.analysis_records(environment_id,id,job_id,message_id,message_version,source_version,
 signal_id,trace_id,classification,outcome,reason_codes,route_version,input_hash,config_versions)
 VALUES(p_environment,record_id,p_job,(input->'payload'->>'message_id')::uuid,
 (input->'payload'->>'message_version')::integer,(input->'payload'->>'source_version')::integer,signal,
 (p_result->>'trace_id')::uuid,p_result->>'classification',p_result->>'outcome',p_result->'reason_codes',
 p_result->>'route_version',p_result->>'input_hash',p_result->'config_versions');
 INSERT INTO public.audit_events(id,environment_id,action,actor_service,target,details)
 VALUES(gen_random_uuid(),p_environment,'MESSAGE_ANALYSIS_COMPLETED','ai',record_id::text,
 jsonb_build_object('outcome',p_result->>'outcome','message_version',input->'payload'->'message_version'));
 INSERT INTO public.outbox_events(environment_id,id,event_key,topic,payload)
 VALUES(p_environment,gen_random_uuid(),'analysis:'||p_job::text,'analysis.completed',
 jsonb_build_object('analysis_id',record_id,'signal_id',signal,'outcome',p_result->>'outcome'));
 PERFORM public.finish_domain_job(p_environment,p_job,p_worker,p_generation,true);
 RETURN record_id;
END; $fn$;

CREATE VIEW public.dashboard_analyses AS SELECT r.*,s.name AS source_name
 FROM public.analysis_records r JOIN public.telegram_messages m
 ON (m.environment_id,m.id)=(r.environment_id,r.message_id)
 JOIN public.telegram_sources s ON (s.environment_id,s.id)=(m.environment_id,m.source_id);
CREATE VIEW public.dashboard_agent_runs AS SELECT r.environment_id,r.id,r.trace_id,r.status,
 r.model_id,r.config_version,r.attempt,r.result,r.created_at,a.name AS agent_name,
 b.job_id,b.state AS budget_state,b.reserved_usd::text,b.charged_usd::text
 FROM public.agent_runs r JOIN public.agents a ON (a.environment_id,a.id)=(r.environment_id,r.agent_id)
 JOIN public.ai_budget_reservations b ON (b.environment_id,b.id)=(r.environment_id,r.id);
GRANT SELECT ON public.dashboard_analyses,public.dashboard_agent_runs TO trd_api;
GRANT SELECT ON public.analysis_records,public.ai_budget_reservations TO trd_ai;
-- Include requests interrupted before a usage row could be committed.
DROP VIEW public.dashboard_costs;
CREATE VIEW public.dashboard_costs AS
 SELECT u.environment_id,u.id,u.run_id,u.input_tokens,u.output_tokens,u.estimated_cost_usd::text,
 u.pricing_version,u.usage_known,u.created_at,COALESCE(b.state,'SETTLED')::varchar(16) AS budget_state,
 b.reserved_usd::text,b.charged_usd::text
 FROM public.ai_usage u LEFT JOIN public.ai_budget_reservations b
 ON (b.environment_id,b.id)=(u.environment_id,u.run_id)
 UNION ALL SELECT b.environment_id,b.id,b.id,0,0,b.reserved_usd::text,
 b.snapshot->>'pricing_version',false,b.created_at,b.state,b.reserved_usd::text,NULL::text
 FROM public.ai_budget_reservations b WHERE NOT EXISTS(SELECT 1 FROM public.ai_usage u
 WHERE (u.environment_id,u.run_id)=(b.environment_id,b.id));
GRANT SELECT ON public.dashboard_costs TO trd_api;
REVOKE ALL ON FUNCTION public.analysis_assert_job(text,uuid,text,integer),
 public.analysis_reserve_attempt(text,uuid,text,integer,uuid,integer,text,integer,integer,integer,jsonb),
 public.analysis_settle_attempt(text,uuid,text,jsonb),public.analysis_complete(text,uuid,text,integer,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.analysis_assert_job(text,uuid,text,integer),
 public.analysis_reserve_attempt(text,uuid,text,integer,uuid,integer,text,integer,integer,integer,jsonb),
 public.analysis_settle_attempt(text,uuid,text,jsonb),public.analysis_complete(text,uuid,text,integer,jsonb) TO trd_ai;
