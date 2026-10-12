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
 -- Delivered commands and their reservations are retained for future reconciliation.
END; $function$
