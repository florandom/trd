CREATE OR REPLACE FUNCTION public.transition_domain_entity(
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
      'BROKER_REJECTION','BROKER_CANCEL','RECONCILED_FILL','RECONCILED_ABSENT','BROKER_POSITION_UPDATE') THEN
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
      AND NOT (p_kind='command' AND p_evidence='BROKER_POSITION_UPDATE' AND EXISTS(SELECT 1 FROM public.paper_operations WHERE environment_id=p_environment AND command_id=p_entity))
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
