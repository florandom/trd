// Confirmed local-paper actions inside the existing table template.
'use client';
import {useEffect, useState} from 'react';
import {VStack, HStack} from '@astryxdesign/core/Stack';
import {Text} from '@astryxdesign/core/Text';
import {TextInput} from '@astryxdesign/core/TextInput';
import {Selector} from '@astryxdesign/core/Selector';
import {Button} from '@astryxdesign/core/Button';
import {Banner} from '@astryxdesign/core/Banner';
import {Dialog, DialogHeader} from '@astryxdesign/core/Dialog';
import {api, type Row, type Change, type Confirmation, type Snapshot} from '@/lib/dashboard-api';
import {useSession} from './trading-shell';

export function PaperAction({row, resume = false, onSaved}: {row: Row; resume?: boolean; onSaved: () => void}) {
  const user = useSession();
  const [open, setOpen] = useState(false);
  const [action, setAction] = useState('CLOSE');
  const [sl, setSl] = useState(String(row.stop_loss ?? ''));
  const [tp, setTp] = useState(String(row.take_profit ?? ''));
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  if (user.role !== 'ADMIN') return null;
  async function review() {
    setBusy(true); setError('');
    try {
      const change: Change = {kind: resume ? 'paper_resume' : 'paper_position', target: String(row.id),
        expected_version: Number(resume ? row.safety_epoch : row.revision),
        value: {action: resume ? 'RESUME' : action,
          stop_loss: action === 'MODIFY_STOPS' && !resume ? sl : null,
          take_profit: action === 'MODIFY_STOPS' && !resume ? tp : null}};
      setConfirmation(await api<Confirmation>('config/confirm', {body: change, csrf: user.csrf_token}));
    } catch (e) {setError(e instanceof Error ? e.message : 'Verifica non riuscita.');}
    finally {setBusy(false);}
  }
  async function send() {
    if (!confirmation) return;
    setBusy(true); setError('');
    try {
      await api('config/apply', {body: {change: confirmation.change, confirmation_token: confirmation.confirmation_token}, csrf: user.csrf_token});
      setConfirmation(null); setOpen(false); setSent(true); onSaved();
    } catch (e) {setConfirmation(null); setError(e instanceof Error ? e.message : 'Richiesta non registrata.');}
    finally {setBusy(false);}
  }
  return <VStack gap={2}>
    <Button label={resume ? 'Verifica ripresa' : 'Gestisci simulazione'} variant="secondary" size="sm"
      isDisabled={resume ? row.status === 'READY' : !row.can_manage}
      onClick={() => {setOpen(true); setSent(false); setError(''); setConfirmation(null); setSl(String(row.stop_loss ?? '')); setTp(String(row.take_profit ?? ''));}} />
    {sent && <Text type="supporting">Richiesta registrata; aggiorna per verificare l’esito.</Text>}
    <Dialog isOpen={open} onOpenChange={(value) => {if (!busy) setOpen(value);}} purpose="form" padding={6}>
      <DialogHeader title={resume ? 'Ripresa della simulazione' : 'Gestione della posizione simulata'} />
      <VStack gap={4}>
        <Text>Solo conto paper {String(row.account_id ?? row.id)}. {resume ? 'La verifica conserva la base giornaliera e gli esiti incerti.' : `Posizione ${String(row.broker_identifier)}, ${String(row.symbol)}, ${String(row.volume)} lotti.`}</Text>
        {resume ? <Text>La ripresa richiede dati aggiornati, riconciliazione completa e limiti rispettati. Un errore dei dati richiede un conto senza posizioni; il blocco per perdita giornaliera resta valido.</Text> : <>
          <Selector isDisabled={busy || !!confirmation} label="Operazione" value={action} onChange={(value) => {setAction(String(value)); setConfirmation(null);}}
            options={[{value: 'CLOSE', label: 'Chiudi interamente'}, {value: 'MODIFY_STOPS', label: 'Aggiorna stop e obiettivo'}]} />
          {action === 'MODIFY_STOPS' && <>
            <TextInput isReadOnly={busy || !!confirmation} label="Stop loss" value={sl} onChange={(value) => {setSl(value); setConfirmation(null);}} />
            <TextInput isReadOnly={busy || !!confirmation} label="Take profit" value={tp} onChange={(value) => {setTp(value); setConfirmation(null);}} />
            <Text>Il nuovo stop può solo ridurre il rischio. Non puoi rimuovere le protezioni.</Text>
          </>}
        </>}
        {error && <Banner status="error" title={error} />}
        {confirmation && <Banner status="warning" title="Conferma la richiesta simulata">
          <Text>{resume ? 'Richiedi la verifica di ripresa.' : action === 'CLOSE' ? 'Chiudi l’intera posizione indicata.' : `Nuovo stop ${sl}; nuovo obiettivo ${tp}.`} La registrazione non conferma l’esecuzione.</Text>
        </Banner>}
        <HStack gap={3}>
          <Button label="Annulla" isDisabled={busy} variant="secondary" onClick={() => setOpen(false)} />
          <Button label={confirmation ? 'Conferma richiesta' : 'Rivedi richiesta'} isLoading={busy} onClick={() => void (confirmation ? send() : review())} />
        </HStack>
      </VStack>
    </Dialog>
  </VStack>;
}

export function PaperAccounts({onSaved}: {onSaved: () => void}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {let current = true; api<Snapshot>('ops/paper-accounts').then((data) => {if (current) setRows(data.rows);}).catch((e) => {if (current) setError(e.message);}); return () => {current = false;};}, [onSaved]);
  return <VStack gap={3}>
    {error && <Banner status="warning" title={error} />}
    {rows.map((row) => <HStack key={String(row.id)} gap={3} wrap="wrap" vAlign="center">
      <Text>Conto simulato {String(row.login)} · {row.status === 'READY' ? 'Pronto' : row.status === 'PAUSED' ? 'Sospeso' : 'Da riconciliare'}{row.loss_latched ? ' · Limite giornaliero raggiunto' : ''}</Text>
      <PaperAction row={row} resume onSaved={onSaved} />
    </HStack>)}
  </VStack>;
}
