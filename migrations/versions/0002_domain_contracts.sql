-- All callable mutation functions authenticate the database role as well as input.
CREATE FUNCTION public.domain_evidence_fence() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $fn$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:' || NEW.environment_id, 0));
  IF TG_TABLE_NAME = 'signal_versions' THEN
    IF NOT EXISTS (
    SELECT 1 FROM public.telegram_message_versions v
    WHERE (v.environment_id, v.message_id, v.version) =
      (NEW.environment_id, NEW.message_id, NEW.message_version) AND v.raw_body IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'message evidence has expired' USING ERRCODE = '22023';
    END IF;
  END IF;
  RETURN NEW;
END; $fn$;

CREATE FUNCTION public.protect_domain_record() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE raw_column text := TG_ARGV[0];
BEGIN
  IF TG_OP = 'DELETE' OR raw_column = '' THEN
    RAISE EXCEPTION 'append-only record' USING ERRCODE = '42501';
  END IF;
  IF (to_jsonb(NEW) - raw_column) IS DISTINCT FROM (to_jsonb(OLD) - raw_column)
     OR (to_jsonb(NEW) -> raw_column) IS DISTINCT FROM 'null'::jsonb THEN
    RAISE EXCEPTION 'only raw evidence erasure is allowed' USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END; $fn$;

CREATE FUNCTION public.require_initial_lifecycle() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $fn$
BEGIN
  IF NEW.revision <> 1 OR NEW.state <> TG_ARGV[0] THEN
    RAISE EXCEPTION 'invalid initial lifecycle state' USING ERRCODE = '22023';
  END IF;
  RETURN NEW;
END; $fn$;

CREATE FUNCTION public.revise_system_setting(
  p_environment text, p_key text, p_expected integer, p_value jsonb, p_actor uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE current integer; previous jsonb; next_version integer;
BEGIN
  IF session_user <> 'trd_api' OR NOT EXISTS (
    SELECT 1 FROM public.users WHERE id = p_actor AND active AND role = 'ADMIN'
  ) THEN RAISE EXCEPTION 'administrator required' USING ERRCODE = '42501'; END IF;
  IF p_environment IS NULL OR p_key IS NULL OR p_value IS NULL OR p_expected IS NULL
     OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$' OR p_expected < 1 THEN
    RAISE EXCEPTION 'invalid configuration request' USING ERRCODE = '22023';
  END IF;
  IF NOT (
    (p_key IN ('automation_enabled','live_trading_enabled') AND p_value = 'false'::jsonb)
    OR (p_key = 'trading_mode' AND p_value = '"paper"'::jsonb)
    OR (p_key IN ('raw_log_retention_days','ai_response_retention_days','telegram_retention_days')
        AND jsonb_typeof(p_value) = 'number' AND p_value::text ~ '^[0-9]{1,3}$'
        AND (p_value::text)::integer BETWEEN 1 AND 365)
  ) THEN RAISE EXCEPTION 'unsupported or unsafe setting' USING ERRCODE = '22023'; END IF;
  SELECT s.current_version, v.value INTO current, previous
    FROM public.system_settings s JOIN public.setting_versions v
      ON (s.environment_id,s.key,s.current_version) = (v.environment_id,v.key,v.version)
    WHERE s.environment_id = p_environment AND s.key = p_key FOR UPDATE OF s;
  IF current IS NULL OR current <> p_expected THEN
    RAISE EXCEPTION 'configuration version conflict' USING ERRCODE = '40001';
  END IF;
  IF previous = p_value THEN RETURN current; END IF;
  next_version := current + 1;
  INSERT INTO public.setting_versions(environment_id,key,version,value,created_by)
    VALUES(p_environment,p_key,next_version,p_value,p_actor);
  UPDATE public.system_settings SET current_version = next_version
    WHERE environment_id = p_environment AND key = p_key;
  INSERT INTO public.audit_events(id,environment_id,action,actor_id,actor_service,target,details)
    VALUES(gen_random_uuid(),p_environment,'SETTING_REVISED',p_actor,'api',p_key,
      jsonb_build_object('previous_version',current,'version',next_version));
  RETURN next_version;
END; $fn$;

CREATE FUNCTION public.signal_evidence_protected(p_environment text, p_signal uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
  SELECT EXISTS(SELECT 1 FROM public.signals s
    WHERE s.environment_id = p_environment AND s.id = p_signal
      AND s.state NOT IN ('EXECUTED','IGNORED','REJECTED_AI','REJECTED_RISK','EXPIRED','FAILED'))
  OR EXISTS(SELECT 1 FROM public.risk_events e
    JOIN public.risk_approvals a ON (a.environment_id,a.risk_event_id) = (e.environment_id,e.id)
    JOIN public.risk_reservations r ON (r.environment_id,r.approval_id) = (a.environment_id,a.id)
    LEFT JOIN public.execution_commands c ON (c.environment_id,c.reservation_id) =
      (r.environment_id,r.id)
    LEFT JOIN public.orders o ON (o.environment_id,o.command_id) = (c.environment_id,c.id)
    LEFT JOIN public.positions p ON (p.environment_id,p.order_id) = (o.environment_id,o.id)
    WHERE e.environment_id = p_environment AND e.signal_id = p_signal AND (
      r.status IN ('HELD','OUTCOME_UNKNOWN')
      OR c.state NOT IN ('COMPLETED','REJECTED','EXPIRED','INVALIDATED')
      OR o.state IN ('REQUESTED','SENT','ACCEPTED','PARTIALLY_FILLED','OUTCOME_UNKNOWN','RECONCILING')
      OR p.status <> 'CLOSED'));
$fn$;

CREATE FUNCTION public.prune_raw_evidence(
  p_environment text, p_telegram_days integer, p_ai_days integer, p_limit integer)
RETURNS TABLE(telegram_count integer, ai_count integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
BEGIN
  IF session_user <> 'trd_maintenance' THEN
    RAISE EXCEPTION 'maintenance identity required' USING ERRCODE = '42501'; END IF;
  IF p_environment IS NULL OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$'
     OR p_telegram_days IS NULL OR p_telegram_days NOT BETWEEN 1 AND 365
     OR p_ai_days IS NULL OR p_ai_days NOT BETWEEN 1 AND 365
     OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 500 THEN
    RAISE EXCEPTION 'invalid retention policy' USING ERRCODE = '22023'; END IF;
  -- Serialize with evidence-producing writes; inspect again after obtaining the fence.
  PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:' || p_environment, 0));
  WITH candidates AS (
    SELECT v.environment_id, v.message_id, v.version FROM public.telegram_message_versions v
    WHERE v.environment_id = p_environment AND v.raw_body IS NOT NULL
      AND v.created_at < clock_timestamp() - make_interval(days => p_telegram_days)
      AND NOT EXISTS(SELECT 1 FROM public.signals s
        WHERE s.environment_id = v.environment_id AND s.message_id = v.message_id
          AND public.signal_evidence_protected(s.environment_id,s.id))
    ORDER BY v.created_at,v.message_id,v.version LIMIT p_limit FOR UPDATE OF v SKIP LOCKED
  ) UPDATE public.telegram_message_versions v SET raw_body = NULL FROM candidates x
    WHERE (v.environment_id,v.message_id,v.version) = (x.environment_id,x.message_id,x.version);
  GET DIAGNOSTICS telegram_count = ROW_COUNT;
  WITH candidates AS (
    SELECT a.environment_id, a.id FROM public.agent_runs a
    WHERE a.environment_id = p_environment AND a.raw_response IS NOT NULL
      AND a.status NOT IN ('STARTED','UNKNOWN')
      AND a.created_at < clock_timestamp() - make_interval(days => p_ai_days)
      AND (a.signal_id IS NULL OR NOT public.signal_evidence_protected(a.environment_id,a.signal_id))
    ORDER BY a.created_at,a.id LIMIT p_limit FOR UPDATE OF a SKIP LOCKED
  ) UPDATE public.agent_runs a SET raw_response = NULL FROM candidates x
    WHERE (a.environment_id,a.id) = (x.environment_id,x.id);
  GET DIAGNOSTICS ai_count = ROW_COUNT;
  IF telegram_count + ai_count > 0 THEN
    INSERT INTO public.audit_events(id,environment_id,action,actor_service,target,details)
      VALUES(gen_random_uuid(),p_environment,'RAW_EVIDENCE_PRUNED','maintenance','raw_evidence',
        jsonb_build_object('telegram_count',telegram_count,'ai_count',ai_count));
  END IF;
  RETURN NEXT;
END; $fn$;

CREATE FUNCTION public.enqueue_domain_job(p_environment text, p_key text, p_payload jsonb)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE service_name text; job_id uuid; existing jsonb;
BEGIN
  service_name := CASE session_user WHEN 'trd_collector' THEN 'collector' WHEN 'trd_ai' THEN 'ai'
    WHEN 'trd_risk' THEN 'risk' WHEN 'trd_maintenance' THEN 'maintenance' END;
  IF service_name IS NULL THEN RAISE EXCEPTION 'worker required' USING ERRCODE = '42501'; END IF;
  IF p_environment IS NULL OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$'
     OR p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 128 OR p_payload IS NULL
     OR jsonb_typeof(p_payload) <> 'object' OR octet_length(p_payload::text) > 16384 THEN
    RAISE EXCEPTION 'invalid job' USING ERRCODE = '22023'; END IF;
  INSERT INTO public.jobs(environment_id,id,service,dedupe_key,payload)
    VALUES(p_environment,gen_random_uuid(),service_name,p_key,p_payload)
    ON CONFLICT(environment_id,service,dedupe_key) DO NOTHING;
  SELECT id,payload INTO job_id,existing FROM public.jobs
    WHERE environment_id = p_environment AND jobs.service = service_name AND dedupe_key = p_key;
  IF existing IS DISTINCT FROM p_payload THEN
    RAISE EXCEPTION 'job identity conflict' USING ERRCODE = '22023'; END IF;
  RETURN job_id;
END; $fn$;

CREATE FUNCTION public.claim_domain_job(p_environment text, p_worker text, p_seconds integer)
RETURNS TABLE(job_id uuid, generation integer, payload jsonb, lease_until timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE service_name text;
BEGIN
  service_name := CASE session_user WHEN 'trd_collector' THEN 'collector' WHEN 'trd_ai' THEN 'ai'
    WHEN 'trd_risk' THEN 'risk' WHEN 'trd_maintenance' THEN 'maintenance' END;
  IF service_name IS NULL THEN RAISE EXCEPTION 'worker required' USING ERRCODE = '42501'; END IF;
  IF p_environment IS NULL OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$'
     OR p_worker IS NULL OR p_worker !~ '^[A-Za-z0-9_-]{1,128}$'
     OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 300 THEN
    RAISE EXCEPTION 'invalid lease' USING ERRCODE = '22023'; END IF;
  UPDATE public.jobs j SET state = 'DEAD',lease_owner = NULL,lease_until = NULL
    WHERE j.environment_id = p_environment AND j.service = service_name
      AND j.attempts >= j.max_attempts AND (j.state = 'PENDING'
        OR (j.state = 'RUNNING' AND j.lease_until < clock_timestamp()));
  RETURN QUERY WITH candidate AS (
    SELECT j.environment_id,j.id FROM public.jobs j
    WHERE j.environment_id = p_environment AND j.service = service_name
      AND j.attempts < j.max_attempts AND j.available_at <= clock_timestamp()
      AND (j.state = 'PENDING' OR (j.state = 'RUNNING' AND j.lease_until < clock_timestamp()))
    ORDER BY j.available_at,j.created_at,j.id LIMIT 1 FOR UPDATE OF j SKIP LOCKED
  ) UPDATE public.jobs j SET state = 'RUNNING',lease_owner = p_worker,
      lease_until = clock_timestamp() + make_interval(secs => p_seconds),
      attempts = j.attempts + 1,generation = j.generation + 1
    FROM candidate x WHERE (j.environment_id,j.id) = (x.environment_id,x.id)
    RETURNING j.id,j.generation,j.payload,j.lease_until;
END; $fn$;

CREATE FUNCTION public.finish_domain_job(
  p_environment text,p_job uuid,p_worker text,p_generation integer,p_success boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE service_name text; changed integer;
BEGIN
  service_name := CASE session_user WHEN 'trd_collector' THEN 'collector' WHEN 'trd_ai' THEN 'ai'
    WHEN 'trd_risk' THEN 'risk' WHEN 'trd_maintenance' THEN 'maintenance' END;
  IF service_name IS NULL THEN RAISE EXCEPTION 'worker required' USING ERRCODE = '42501'; END IF;
  IF p_success IS NULL THEN RAISE EXCEPTION 'invalid outcome' USING ERRCODE = '22023'; END IF;
  UPDATE public.jobs j SET
    state = CASE WHEN p_success THEN 'COMPLETED' WHEN attempts >= max_attempts THEN 'DEAD'
      ELSE 'PENDING' END, lease_owner = NULL,lease_until = NULL,
    available_at = clock_timestamp() + make_interval(secs => LEAST(60, attempts * 5))
    WHERE j.environment_id = p_environment AND j.service = service_name AND j.id = p_job
      AND j.state = 'RUNNING' AND j.lease_owner = p_worker AND j.generation = p_generation
      AND j.lease_until > clock_timestamp();
  GET DIAGNOSTICS changed = ROW_COUNT;
  IF changed <> 1 THEN RAISE EXCEPTION 'lease ownership lost' USING ERRCODE = '40001'; END IF;
END; $fn$;

CREATE FUNCTION public.transition_domain_entity(
  p_environment text,p_kind text,p_entity uuid,p_expected integer,p_after text,
  p_evidence text,p_event uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE
  rules jsonb := '{"command": {"ACKNOWLEDGED": ["COMPLETED", "OUTCOME_UNKNOWN", "REJECTED"], "CREATED": ["EXPIRED", "INVALIDATED", "READY"], "DELIVERED": ["ACKNOWLEDGED", "COMPLETED", "OUTCOME_UNKNOWN", "REJECTED"], "OUTCOME_UNKNOWN": ["RECONCILING"], "READY": ["DELIVERED", "EXPIRED", "INVALIDATED"], "RECONCILING": ["COMPLETED", "REJECTED"]}, "order": {"ACCEPTED": ["CANCELED", "FILLED", "OUTCOME_UNKNOWN", "PARTIALLY_FILLED"], "OUTCOME_UNKNOWN": ["RECONCILING"], "PARTIALLY_FILLED": ["CANCELED", "FILLED", "OUTCOME_UNKNOWN"], "PROPOSED": ["EXPIRED", "FAILED", "REJECTED", "VALIDATED"], "RECONCILING": ["CANCELED", "FILLED", "PARTIALLY_FILLED", "REJECTED"], "REQUESTED": ["OUTCOME_UNKNOWN", "SENT"], "SENT": ["ACCEPTED", "FILLED", "OUTCOME_UNKNOWN", "PARTIALLY_FILLED", "REJECTED"], "VALIDATED": ["EXPIRED", "FAILED", "REJECTED", "REQUESTED"]}, "signal": {"ANALYZING": ["DECIDED", "EXPIRED", "FAILED"], "APPROVED": ["EXECUTION_REQUESTED", "EXPIRED", "FAILED"], "CLASSIFIED": ["EXPIRED", "FAILED", "IGNORED", "PARSED"], "DECIDED": ["ESCALATED", "EXPIRED", "FAILED", "REJECTED_AI", "RISK_CHECK", "WAITING"], "ESCALATED": ["EXPIRED", "FAILED"], "EXECUTION_REQUESTED": ["EXECUTED", "RECONCILING"], "PARSED": ["ANALYZING", "DECIDED", "EXPIRED", "FAILED"], "RECEIVED": ["CLASSIFIED", "EXPIRED", "FAILED"], "RECONCILING": ["EXECUTED", "FAILED"], "RISK_CHECK": ["APPROVED", "EXPIRED", "FAILED", "REJECTED_RISK"], "WAITING": ["DECIDED", "EXPIRED", "FAILED"]}}'::jsonb;
  table_name text; before_state text; current_revision integer; expires timestamptz;
  previous public.lifecycle_events; service_name text; next_revision integer;
BEGIN
  service_name := CASE session_user WHEN 'trd_ai' THEN 'ai' WHEN 'trd_risk' THEN 'risk' END;
  IF service_name IS NULL OR (service_name = 'ai' AND p_kind IS DISTINCT FROM 'signal') THEN
    RAISE EXCEPTION 'lifecycle authority required' USING ERRCODE = '42501'; END IF;
  table_name := CASE p_kind WHEN 'signal' THEN 'signals' WHEN 'order' THEN 'orders'
    WHEN 'command' THEN 'execution_commands' END;
  IF table_name IS NULL OR p_environment IS NULL OR p_entity IS NULL OR p_event IS NULL
    OR p_expected IS NULL OR p_expected < 1 OR p_after IS NULL OR p_evidence IS NULL
    OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$'
    OR p_evidence NOT IN ('OBSERVATION','BROKER_ACCEPTANCE','BROKER_FILL','BROKER_PARTIAL_FILL',
      'BROKER_REJECTION','BROKER_CANCEL','RECONCILED_FILL','RECONCILED_ABSENT') THEN
    RAISE EXCEPTION 'invalid lifecycle request' USING ERRCODE = '22023'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:' || p_environment, 0));
  SELECT * INTO previous FROM public.lifecycle_events
    WHERE environment_id = p_environment AND id = p_event;
  IF FOUND THEN
    IF previous.kind <> p_kind OR previous.entity_id <> p_entity
      OR previous.revision <> p_expected + 1 OR previous.after <> p_after
      OR previous.evidence <> p_evidence OR previous.actor_service <> service_name THEN
      RAISE EXCEPTION 'event identity conflict' USING ERRCODE = '22023'; END IF;
    RETURN previous.revision;
  END IF;
  EXECUTE format('SELECT state,revision,(to_jsonb(t)->>''expires_at'')::timestamptz '
    'FROM public.%I t WHERE environment_id=$1 AND id=$2 FOR UPDATE',table_name)
    INTO before_state,current_revision,expires USING p_environment,p_entity;
  IF current_revision IS NULL OR current_revision <> p_expected THEN
    RAISE EXCEPTION 'lifecycle version conflict' USING ERRCODE = '40001'; END IF;
  IF service_name = 'ai' AND (before_state NOT IN
      ('RECEIVED','CLASSIFIED','PARSED','ANALYZING','DECIDED','WAITING','ESCALATED')
    OR p_after NOT IN ('CLASSIFIED','PARSED','ANALYZING','DECIDED','WAITING','ESCALATED',
      'RISK_CHECK','IGNORED','REJECTED_AI','EXPIRED','FAILED')) THEN
    RAISE EXCEPTION 'risk authority required' USING ERRCODE = '42501'; END IF;
  IF NOT COALESCE((rules -> p_kind -> before_state) ? p_after,false) THEN
    RAISE EXCEPTION 'invalid lifecycle transition' USING ERRCODE = '22023'; END IF;
  IF p_after IN ('EXECUTED','FILLED','COMPLETED')
      AND p_evidence NOT IN ('BROKER_FILL','RECONCILED_FILL')
    OR (p_kind = 'order' AND p_after = 'PARTIALLY_FILLED' AND p_evidence <> 'BROKER_PARTIAL_FILL')
    OR (p_kind = 'order' AND p_after = 'ACCEPTED' AND p_evidence <> 'BROKER_ACCEPTANCE')
    OR (p_after = 'CANCELED' AND p_evidence <> 'BROKER_CANCEL')
    OR (p_after IN ('REJECTED','FAILED') AND before_state IN
      ('SENT','DELIVERED','ACKNOWLEDGED','RECONCILING')
      AND p_evidence NOT IN ('BROKER_REJECTION','RECONCILED_ABSENT')) THEN
    RAISE EXCEPTION 'broker evidence required' USING ERRCODE = '22023'; END IF;
  IF expires <= clock_timestamp() AND p_after IN ('APPROVED','EXECUTION_REQUESTED','READY','DELIVERED')
    THEN RAISE EXCEPTION 'expired authority' USING ERRCODE = '22023'; END IF;
  next_revision := current_revision + 1;
  EXECUTE format('UPDATE public.%I SET state=$1,revision=$2 WHERE environment_id=$3 AND id=$4',
    table_name) USING p_after,next_revision,p_environment,p_entity;
  INSERT INTO public.lifecycle_events(environment_id,id,kind,entity_id,signal_id,order_id,
    command_id,revision,before,after,evidence,actor_service)
    VALUES(p_environment,p_event,p_kind,p_entity,
      CASE WHEN p_kind='signal' THEN p_entity END,CASE WHEN p_kind='order' THEN p_entity END,
      CASE WHEN p_kind='command' THEN p_entity END,next_revision,before_state,p_after,
      p_evidence,service_name);
  INSERT INTO public.audit_events(id,environment_id,action,actor_service,target,details)
    VALUES(gen_random_uuid(),p_environment,'LIFECYCLE_TRANSITION',service_name,
      p_kind || ':' || p_entity::text,jsonb_build_object('before',before_state,'after',p_after,
        'revision',next_revision,'event_id',p_event));
  INSERT INTO public.outbox_events(environment_id,id,event_key,topic,payload)
    VALUES(p_environment,gen_random_uuid(),p_event::text,'lifecycle.changed',
      jsonb_build_object('kind',p_kind,'entity_id',p_entity,'state',p_after,'revision',next_revision));
  RETURN next_revision;
END; $fn$;

CREATE FUNCTION public.append_signal_version(
  p_environment text,p_signal uuid,p_expected integer,p_message_version integer,
  p_proposal jsonb,p_hash text)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE s public.signals; current_version integer; new_version integer;
BEGIN
  IF session_user <> 'trd_ai' THEN
    RAISE EXCEPTION 'proposal authority required' USING ERRCODE = '42501'; END IF;
  IF p_environment IS NULL OR p_environment !~ '^[a-z][a-z0-9_-]{0,63}$'
    OR p_signal IS NULL OR p_expected IS NULL OR p_expected < 0 OR p_message_version IS NULL
    OR p_message_version < 1 OR p_proposal IS NULL OR jsonb_typeof(p_proposal) <> 'object'
    OR p_hash IS NULL OR p_hash !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'invalid proposal version' USING ERRCODE = '22023'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:' || p_environment,0));
  SELECT * INTO s FROM public.signals
    WHERE environment_id=p_environment AND id=p_signal FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'signal not found' USING ERRCODE = '22023'; END IF;
  SELECT COALESCE(max(version),0) INTO current_version FROM public.signal_versions
    WHERE environment_id=p_environment AND signal_id=p_signal;
  IF current_version <> p_expected THEN
    RAISE EXCEPTION 'proposal version conflict' USING ERRCODE = '40001'; END IF;
  new_version := current_version + 1;
  INSERT INTO public.signal_versions(environment_id,signal_id,version,message_id,message_version,
    proposal,proposal_hash) VALUES(p_environment,p_signal,new_version,s.message_id,p_message_version,
      p_proposal,p_hash);
  IF current_version > 0 THEN
    -- Edits preserve submitted/unknown outcomes and never create a new approval or trade.
    WITH targets AS (
      SELECT c.environment_id,c.id,c.reservation_id,c.state AS old_state
      FROM public.execution_commands c JOIN public.risk_reservations r
        ON (r.environment_id,r.id) = (c.environment_id,c.reservation_id)
      JOIN public.risk_approvals a ON (a.environment_id,a.id) = (r.environment_id,r.approval_id)
      JOIN public.risk_events e ON (e.environment_id,e.id) = (a.environment_id,a.risk_event_id)
      WHERE e.environment_id=p_environment AND e.signal_id=p_signal AND c.state IN ('CREATED','READY')
      FOR UPDATE OF c
    ), invalidated AS (
      UPDATE public.execution_commands c SET state='INVALIDATED',revision=revision+1
      FROM targets t WHERE (c.environment_id,c.id) = (t.environment_id,t.id)
      RETURNING c.environment_id,c.id,c.reservation_id,c.revision,t.old_state
    ), written_events AS (
      INSERT INTO public.lifecycle_events(environment_id,id,kind,entity_id,command_id,revision,
        before,after,evidence,actor_service)
      SELECT environment_id,gen_random_uuid(),'command',id,id,revision,old_state,'INVALIDATED',
        'OBSERVATION','ai' FROM invalidated RETURNING id
    ), written_audits AS (
      INSERT INTO public.audit_events(id,environment_id,action,actor_service,target,details)
      SELECT gen_random_uuid(),environment_id,'LIFECYCLE_TRANSITION','ai','command:'||id,
        jsonb_build_object('before',old_state,'after','INVALIDATED','revision',revision,
          'reason','MESSAGE_EDIT') FROM invalidated RETURNING id
    ), written_outbox AS (
      INSERT INTO public.outbox_events(environment_id,id,event_key,topic,payload)
      SELECT environment_id,gen_random_uuid(),'command-invalidated:'||id||':'||revision,
        'lifecycle.changed',jsonb_build_object('kind','command','entity_id',id,'state','INVALIDATED',
          'revision',revision) FROM invalidated RETURNING id
    ) UPDATE public.risk_reservations r SET status='RELEASED' FROM invalidated x
      WHERE (r.environment_id,r.id) = (x.environment_id,x.reservation_id) AND r.status='HELD';
    UPDATE public.signals SET revision=revision+1 WHERE environment_id=p_environment AND id=p_signal;
    INSERT INTO public.audit_events(id,environment_id,action,actor_service,target,details)
      VALUES(gen_random_uuid(),p_environment,'SIGNAL_VERSION_APPENDED','ai','signal:'||p_signal,
        jsonb_build_object('version',new_version,'message_version',p_message_version));
    INSERT INTO public.outbox_events(environment_id,id,event_key,topic,payload)
      VALUES(p_environment,gen_random_uuid(),'signal-version:'||p_signal||':'||new_version,
        'signal.versioned',jsonb_build_object('signal_id',p_signal,'version',new_version));
  END IF;
  RETURN new_version;
END; $fn$;

CREATE FUNCTION public.prune_configured_evidence(p_environment text,p_limit integer)
RETURNS TABLE(telegram_count integer,ai_count integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE telegram_days integer; ai_days integer;
BEGIN
  IF session_user <> 'trd_maintenance' THEN
    RAISE EXCEPTION 'maintenance identity required' USING ERRCODE = '42501'; END IF;
  SELECT CASE WHEN v.value::text ~ '^[0-9]{1,3}$' THEN (v.value::text)::integer END
    INTO telegram_days FROM public.system_settings s JOIN public.setting_versions v
    ON (s.environment_id,s.key,s.current_version) = (v.environment_id,v.key,v.version)
    WHERE s.environment_id=p_environment AND s.key='telegram_retention_days';
  SELECT CASE WHEN v.value::text ~ '^[0-9]{1,3}$' THEN (v.value::text)::integer END
    INTO ai_days FROM public.system_settings s JOIN public.setting_versions v
    ON (s.environment_id,s.key,s.current_version) = (v.environment_id,v.key,v.version)
    WHERE s.environment_id=p_environment AND s.key='ai_response_retention_days';
  RETURN QUERY SELECT * FROM public.prune_raw_evidence(p_environment,telegram_days,ai_days,p_limit);
END; $fn$;

CREATE FUNCTION public.protect_domain_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $fn$
BEGIN
  IF (to_jsonb(NEW) - string_to_array(TG_ARGV[0],',')) IS DISTINCT FROM
     (to_jsonb(OLD) - string_to_array(TG_ARGV[0],',')) THEN
    RAISE EXCEPTION 'immutable record identity or payload' USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END; $fn$;
