CREATE FUNCTION public.paper_operation_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
 IF OLD.command_id IS NOT NULL AND NEW.command_id IS DISTINCT FROM OLD.command_id
 OR (NEW.state<>OLD.state AND NOT (
 (OLD.state='PENDING' AND NEW.state IN ('DISPATCHED','COMPLETED','REJECTED'))
 OR (OLD.state='DISPATCHED' AND NEW.state IN ('UNKNOWN','COMPLETED','REJECTED'))
 OR (OLD.state='UNKNOWN' AND NEW.state='COMPLETED'))) THEN
 RAISE EXCEPTION 'position operation cannot rewind' USING ERRCODE='22023'; END IF;
 IF OLD.command_id IS NULL AND NEW.command_id IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM public.execution_commands c WHERE c.environment_id=NEW.environment_id
 AND c.account_id=NEW.account_id AND c.id=NEW.command_id AND c.reservation_id IS NULL
 AND convert_from(c.payload,'UTF8')::jsonb->>'request_id'=NEW.id::text
 AND convert_from(c.payload,'UTF8')::jsonb->>'action'=NEW.action
 AND convert_from(c.payload,'UTF8')::jsonb->>'position_id'=NEW.position_id::text) THEN
 RAISE EXCEPTION 'position command identity mismatch' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END; $fn$;
REVOKE ALL ON FUNCTION public.paper_operation_guard() FROM PUBLIC;
CREATE TRIGGER paper_operation_guard BEFORE UPDATE ON public.paper_operations FOR EACH ROW EXECUTE FUNCTION public.paper_operation_guard();

CREATE OR REPLACE FUNCTION public.paper_enrollment_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $fn$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.trading_accounts WHERE environment_id=NEW.environment_id AND id=NEW.account_id AND mode='paper' AND broker_server='TRD-PAPER-SIMULATOR') THEN
 RAISE EXCEPTION 'synthetic account required' USING ERRCODE='22023'; END IF;
 IF TG_OP='UPDATE' AND (NEW.highwater<OLD.highwater
 OR (OLD.journal_id IS NOT NULL AND NEW.journal_id IS DISTINCT FROM OLD.journal_id)) THEN
 RAISE EXCEPTION 'durable fence cannot decrease' USING ERRCODE='22023'; END IF;
 IF TG_OP='UPDATE' AND OLD.fault_latched AND NOT NEW.fault_latched AND (
 session_user<>'trd_risk' OR NOT EXISTS(SELECT 1 FROM public.paper_operations r
 JOIN public.trading_accounts a ON (a.environment_id,a.id)=(r.environment_id,r.account_id)
 WHERE r.environment_id=NEW.environment_id AND r.account_id=NEW.account_id AND r.action='RESUME'
 AND r.state='PENDING' AND r.safety_epoch=a.safety_epoch AND r.expires_at>clock_timestamp())
 OR EXISTS(SELECT 1 FROM public.positions WHERE environment_id=NEW.environment_id AND account_id=NEW.account_id AND status<>'CLOSED')
 OR EXISTS(SELECT 1 FROM public.execution_commands WHERE environment_id=NEW.environment_id AND account_id=NEW.account_id AND state NOT IN ('COMPLETED','EXPIRED','INVALIDATED','REJECTED'))
 OR EXISTS(SELECT 1 FROM public.risk_reservations WHERE environment_id=NEW.environment_id AND account_id=NEW.account_id AND status IN ('HELD','OUTCOME_UNKNOWN'))
 ) THEN RAISE EXCEPTION 'confirmed reconciled flat account required' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END; $fn$;

DROP VIEW public.api_positions;
CREATE VIEW public.api_positions AS SELECT p.environment_id,p.id,p.account_id,p.order_id,
p.broker_identifier,p.symbol,p.volume::text AS volume,p.entry_price::text AS entry_price,p.status,p.opened_at,p.closed_at,
s.revision,s.stop_loss::text AS stop_loss,s.take_profit::text AS take_profit,a.mode,a.broker_server,
COALESCE((SELECT sum(e.realized_pnl) FROM public.position_events e WHERE e.environment_id=p.environment_id AND e.position_id=p.id),0)::text AS realized_pnl,
(p.status='OPEN' AND o.state='FILLED' AND b.account_id IS NOT NULL AND NOT EXISTS(
SELECT 1 FROM public.paper_operations r WHERE r.environment_id=p.environment_id AND r.position_id=p.id AND r.state IN ('PENDING','DISPATCHED','UNKNOWN'))) AS can_manage
FROM public.positions p JOIN public.trading_accounts a ON (a.environment_id,a.id)=(p.environment_id,p.account_id)
JOIN public.orders o ON (o.environment_id,o.id)=(p.environment_id,p.order_id)
LEFT JOIN public.paper_position_state s ON (s.environment_id,s.position_id)=(p.environment_id,p.id)
LEFT JOIN public.bridge_enrollments b ON (b.environment_id,b.account_id)=(p.environment_id,p.account_id);
CREATE VIEW public.api_paper_accounts AS SELECT a.environment_id,a.id,a.broker_server,a.login,a.mode,a.status,a.safety_epoch,b.fault_latched,
(SELECT max(observed_at) FROM public.bridge_snapshots s WHERE s.environment_id=a.environment_id AND s.account_id=a.id) AS observed_at,
COALESCE((SELECT loss_latched FROM public.bridge_daily_baselines d WHERE d.environment_id=a.environment_id AND d.account_id=a.id AND d.day=(clock_timestamp() AT TIME ZONE 'UTC')::date),false) AS loss_latched
FROM public.trading_accounts a JOIN public.bridge_enrollments b ON (b.environment_id,b.account_id)=(a.environment_id,a.id);
CREATE VIEW public.api_paper_operations AS SELECT environment_id,id,account_id,position_id,command_id,action,state,reason,created_at,expires_at FROM public.paper_operations;
GRANT SELECT ON public.api_positions,public.api_paper_accounts,public.api_paper_operations TO trd_api;
CREATE OR REPLACE FUNCTION public.record_paper_audit(p_environment text,p_account uuid,
 p_action text,p_details jsonb) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE event uuid := gen_random_uuid();
BEGIN
 IF session_user<>'trd_risk' OR p_action NOT IN
 ('PAPER_BRIDGE_FAULT','PAPER_DAILY_LOSS_LATCHED','PAPER_COMMAND_RESERVED','PAPER_BROKER_FILL','PAPER_OPERATION_REJECTED','PAPER_POSITION_CLOSED','PAPER_STOPS_CHANGED','PAPER_ACCOUNT_RESUMED')
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

CREATE FUNCTION public.paper_command_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $fn$
DECLARE payload jsonb;
BEGIN
 IF NEW.reservation_id IS NULL THEN
 payload:=convert_from(NEW.payload,'UTF8')::jsonb;
 IF session_user<>'trd_risk' OR NOT EXISTS(
 SELECT 1 FROM public.paper_operations r JOIN public.positions p
 ON (p.environment_id,p.id)=(r.environment_id,r.position_id)
 JOIN public.orders o ON (o.environment_id,o.id)=(p.environment_id,p.order_id)
 WHERE r.environment_id=NEW.environment_id AND r.account_id=NEW.account_id
 AND r.id=(payload->>'request_id')::uuid AND r.state='PENDING'
 AND r.action IN ('CLOSE','MODIFY_STOPS') AND r.action=payload->>'action'
 AND r.safety_epoch=(payload->>'safety_epoch')::integer
 AND r.position_id=(payload->>'position_id')::uuid
 AND o.command_id=(payload->>'opening_command_id')::uuid
 AND NEW.id=(payload->>'command_id')::uuid AND NEW.expires_at<=r.expires_at
 AND r.expires_at>clock_timestamp() AND p.status='OPEN' AND o.state='FILLED') THEN
 RAISE EXCEPTION 'confirmed position request required' USING ERRCODE='42501'; END IF;
 END IF;
 RETURN NEW;
END; $fn$;
REVOKE ALL ON FUNCTION public.paper_command_guard() FROM PUBLIC;
CREATE TRIGGER paper_command_guard BEFORE INSERT ON public.execution_commands FOR EACH ROW EXECUTE FUNCTION public.paper_command_guard();
