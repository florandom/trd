// Page sections live inside the existing Astryx shell-side-nav frame.
'use client';
import {useCallback, useEffect, useState} from 'react';
import Link from 'next/link';
import {VStack, HStack} from '@astryxdesign/core/Stack';
import {Text, Heading} from '@astryxdesign/core/Text';
import {Table, proportional, type TableColumn} from '@astryxdesign/core/Table';
import {Section} from '@astryxdesign/core/Section';
import {Button} from '@astryxdesign/core/Button';
import {Banner} from '@astryxdesign/core/Banner';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {StatusDot} from '@astryxdesign/core/StatusDot';
import {api, type Row, type Snapshot} from '@/lib/dashboard-api';
import {
  AGENT_LABELS,
  STATUS,
  SETTING_LABELS,
  displaySetting,
  analysisReasons,
} from '@/lib/configuration';
import {formatCheckedAt} from '@/lib/locale';
import ConfigurationEditor from './configuration-page';
import {useSession} from './trading-shell';
export const PAGES: Record<string, {title: string; description: string}> = {
  settings: {
    title: 'Impostazioni',
    description:
      'Gestisci la conservazione dei dati. Automazione e trading reale restano disattivati.',
  },
  risk: {
    title: 'Controlli del rischio',
    description:
      'Rischio ed esecuzione verificati nel laboratorio locale con ordini simulati. I limiti non abilitano il trading reale; MT5 e conto broker richiedono ancora collaudo.',
  },
  agents: {
    title: 'Agenti IA',
    description:
      'Configura il simulatore locale o i modelli OpenRouter approvati dal team. La revisione delle posizioni non è ancora disponibile.',
  },
  models: {
    title: 'Registro modelli',
    description:
      'Modelli e prezzi del registro verificato. I manifesti vengono gestiti dall’amministratore del server.',
  },
  audit: {
    title: 'Registro attività',
    description:
      'Accessi e modifiche registrati dal sistema, in ordine dal più recente.',
  },
  status: {
    title: 'Stato dei servizi',
    description:
      'Presenza dei processi nel database. Un processo attivo non conferma il collegamento a Telegram, IA o broker.',
  },
  positions: {
    title: 'Posizioni',
    description:
      'Posizioni registrate dal sistema. Nessun conto di trading è attualmente collegato.',
  },
  signals: {
    title: 'Segnali',
    description:
      'Proposte strutturate con esito e versioni verificabili. La valutazione consultiva non autorizza ordini.',
  },
  sources: {
    title: 'Fonti Telegram',
    description:
      'Aggiungi i canali e gruppi da leggere. La fonte viene verificata quando il team collega l’account Telegram. Nessun messaggio può avviare un ordine.',
  },
  'telegram-messages': {
    title: 'Messaggi Telegram',
    description:
      'Messaggi ricevuti, revisioni e cancellazioni. Consulta gli esiti nella pagina Analisi messaggi.',
  },
  analyses: {
    title: 'Analisi messaggi',
    description: 'Esiti della classificazione locale, motivi di arresto e proposte. Il simulatore non osserva il mercato e non autorizza ordini.',
  },
  costs: {
    title: 'Costi IA',
    description:
      'Consumi registrati per richiesta. I costi stimati restano distinti dagli utilizzi confermati.',
  },
};
const ACTION: Record<string, string> = {
  USER_CREATED: 'Utente creato',
  LOGIN_SUCCEEDED: 'Accesso riuscito',
  LOGIN_FAILED: 'Accesso non riuscito',
  LOGOUT: 'Uscita',
  SETTING_REVISED: 'Impostazione modificata',
  RISK_CONFIG_REVISED: 'Limiti di rischio modificati',
  AGENT_CONFIG_REVISED: 'Configurazione agente modificata',
  SOURCE_CONFIG_REVISED: 'Fonte Telegram modificata',
  TELEGRAM_MESSAGE_NEW: 'Messaggio Telegram registrato',
  TELEGRAM_MESSAGE_EDIT: 'Messaggio Telegram modificato',
  TELEGRAM_MESSAGE_DELETE: 'Cancellazione Telegram registrata',
  MESSAGE_ANALYSIS_COMPLETED: 'Analisi del messaggio registrata',
  PAPER_BRIDGE_FAULT: 'Simulazione fermata: dati da verificare',
  PAPER_DAILY_LOSS_LATCHED: 'Simulazione fermata al limite di perdita giornaliera',
  PAPER_COMMAND_RESERVED: 'Rischio prenotato per un ordine simulato',
  PAPER_BROKER_FILL: 'Esecuzione simulata confermata',
  BOOTSTRAP_DOMAIN_DEFAULTS_CREATED: 'Configurazioni iniziali create',
  BOOTSTRAP_ADMIN_CREATED: 'Amministratore iniziale creato',
  BOOTSTRAP_DEFAULTS_CREATED: 'Impostazioni iniziali create',
};
const SOURCE_STATUS: Record<string, string> = {
  PENDING: 'In attesa del collegamento',
  ACTIVE: 'Lettura verificata',
  BACKFILL: 'Recupero in corso',
  GAP: 'Interruzione da verificare',
  UNAVAILABLE: 'Fonte non accessibile',
  FLOOD_WAIT: 'Attesa richiesta da Telegram',
  DISABLED: 'Disattivata',
};
const MESSAGE_EVENTS: Record<string, string> = {
  NEW: 'Ricevuto',
  EDIT: 'Modificato',
  DELETE: 'Cancellato',
};
const SERVICES: Record<string, string> = {
  api: 'Accesso e dashboard',
  collector: 'Ricezione Telegram',
  ai: 'Agenti IA',
  risk: 'Rischio e ordini',
  maintenance: 'Manutenzione',
};
function translated(value: unknown): string {
  return STATUS[String(value)] || 'Stato da verificare';
}
function status(
  label: string,
  variant: 'neutral' | 'success' | 'warning' = 'neutral'
) {
  return (
    <HStack gap={2} vAlign="center">
      <StatusDot variant={variant} label={label} />
      <Text>{label}</Text>
    </HStack>
  );
}
function column(
  key: string,
  header: string,
  render?: (row: Row) => React.ReactNode
): TableColumn<Row> {
  return {
    key,
    header,
    width: proportional(1),
    renderCell: (row) =>
      render ? render(row) : <Text>{String(row[key] ?? '—')}</Text>,
  };
}
export default function OperationalPage({section}: {section: string}) {
  const user = useSession();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(timer);
  }, []);
  const [data, setData] = useState<Snapshot | null>(null);
  const [models, setModels] = useState<Row[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const load = useCallback(() => {
    setBusy(true);
    setError('');
    setData(null);
    setRefreshKey((value) => value + 1);
  }, []);
  useEffect(() => {
    let active = true;
    const requests = Promise.all([
      api<Snapshot>(`ops/${section}?offset=${offset}`),
      section === 'agents'
        ? api<Snapshot>('ops/models')
        : Promise.resolve(null),
    ]);
    void requests
      .then(([snapshot, registry]) => {
        if (active) {
          setData(snapshot);
          if (registry) setModels(registry.rows);
        }
      })
      .catch((e) => {
        if (active)
          setError(e instanceof Error ? e.message : 'Dati non disponibili.');
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [section, offset, refreshKey]);
  const page = PAGES[section] ?? {
    title: 'Pagina non disponibile',
    description: '',
  };
  let columns: TableColumn<Row>[] = [];
  if (section === 'agents')
    columns = [
      column('name', 'Agente', (r) => (
        <Text weight="semibold">{AGENT_LABELS[String(r.name)]}</Text>
      )),
      column('enabled', 'Stato', (r) =>
        status(
          r.enabled ? 'Agente attivo' : 'Disattivato'
        )
      ),
      column('primary_model_id', 'Modello'),
      column('current_version', 'Versione'),
      column('id', 'Configurazione', (r) => (
        <Button
          label="Apri configurazione"
          size="sm"
          variant="secondary"
          onClick={() => setSelected(String(r.id))}
        />
      )),
    ];
  if (section === 'analyses')
    columns = [
      column('created_at', 'Data', (r) => <Text>{formatCheckedAt(String(r.created_at))}</Text>),
      column('source_name', 'Fonte'),
      column('message_version', 'Revisione'),
      column('outcome', 'Esito', (r) => status(translated(r.outcome))),
      column('reason_codes', 'Motivi', (r) => <Text>{analysisReasons(r.reason_codes)}</Text>),
      column('signal_id', 'Proposta', (r) => r.signal_id
        ? <Link href={`/signals/${String(r.signal_id)}`}>Apri dettaglio</Link>
        : <Text>Nessuna proposta</Text>),
    ];
  if (section === 'models')
    columns = [
      column('id', 'Identificativo'),
      column('provider', 'Fornitore', (r) => (
        <Text>
          {r.provider === 'mock' ? 'Simulatore locale' : String(r.provider)}
        </Text>
      )),
      column('enabled', 'Disponibilità', (r) =>
        status(
          r.enabled ? 'Disponibile' : 'Disattivato',
          r.enabled ? 'success' : 'neutral'
        )
      ),
      column('max_output_tokens', 'Token massimi'),
      column('input_price_per_million', 'Costo input (USD/milione)'),
      column('output_price_per_million', 'Costo output (USD/milione)'),
      column('pricing_version', 'Versione prezzi'),
      column('budget_state', 'Prenotazione', (r) => <Text>{
        r.budget_state === 'SETTLED' ? 'Consumo registrato' : 'Conservata per verifica'
      }</Text>),
      column('reserved_usd', 'Importo prenotato (USD)'),
    ];
  if (section === 'settings')
    columns = [
      column('key', 'Impostazione', (r) => (
        <Text>{SETTING_LABELS[String(r.key)]}</Text>
      )),
      column('value', 'Valore', (r) => (
        <Text>{displaySetting(String(r.key), r.value)}</Text>
      )),
      column('current_version', 'Versione'),
    ];
  if (section === 'audit')
    columns = [
      column('created_at', 'Data', (r) => (
        <Text>{formatCheckedAt(String(r.created_at))}</Text>
      )),
      column('action', 'Attività', (r) => (
        <Text>{ACTION[String(r.action)] || 'Evento operativo registrato'}</Text>
      )),
      column('actor_email', 'Utente', (r) => (
        <Text>{String(r.actor_email || 'Amministrazione del sistema')}</Text>
      )),
      column('actor_service', 'Origine', (r) => (
        <Text>
          {SERVICES[String(r.actor_service)] || 'Amministrazione del sistema'}
        </Text>
      )),
      column('target', 'Oggetto', (r) => (
        <Text>
          {SETTING_LABELS[String(r.target)] ||
            (r.target === 'system_settings'
              ? 'Impostazioni iniziali'
              : r.target === 'authentication'
                ? 'Accesso'
                : r.target === 'domain_defaults'
                  ? 'Configurazioni iniziali'
                  : r.target === 'baseline'
                    ? 'Limiti di rischio'
                    : String(r.target))}
        </Text>
      )),
    ];
  if (section === 'status')
    columns = [
      column('service_name', 'Servizio', (r) => (
        <Text>{SERVICES[String(r.service_name)]}</Text>
      )),
      column('status', 'Stato', (r) => {
        const age = data ? now - Date.parse(String(r.observed_at)) : Infinity;
        const fresh = age >= -5000 && age < 30_000;
        const ok = fresh && r.status === 'HEALTHY';
        const label = fresh ? translated(r.status) : 'Non aggiornato';
        return (
          <HStack gap={2} vAlign="center">
            <StatusDot variant={ok ? 'success' : 'warning'} label={label} />
            <Text>{label}</Text>
          </HStack>
        );
      }),
      column('observed_at', 'Ultima presenza', (r) => (
        <Text>{formatCheckedAt(String(r.observed_at))}</Text>
      )),
    ];
  if (section === 'positions')
    columns = [
      column('symbol', 'Strumento'),
      column('volume', 'Volume (lotti)'),
      column('entry_price', 'Prezzo di ingresso'),
      column('status', 'Stato', (r) => status(translated(r.status))),
      column('broker_identifier', 'Identificativo broker'),
    ];
  if (section === 'signals')
    columns = [
      column('id', 'Segnale', (r) => (
        <Button
          as={Link}
          href={`/signals/${r.id}`}
          label="Apri segnale"
          size="sm"
          variant="secondary"
        />
      )),
      column('state', 'Stato', (r) => status(translated(r.state))),
      column('revision', 'Versione'),
      column('created_at', 'Ricevuto', (r) => (
        <Text>{formatCheckedAt(String(r.created_at))}</Text>
      )),
    ];
  if (section === 'sources')
    columns = [
      column('name', 'Fonte'),
      column('reference', 'Canale o gruppo'),
      column('status', 'Lettura', (r) =>
        status(
          !r.enabled
            ? 'Disattivata'
            : r.status === 'ACTIVE' &&
                r.last_success_at &&
                now - Date.parse(String(r.last_success_at)) > 120_000
              ? 'Da verificare'
              : SOURCE_STATUS[String(r.status)] || 'Da verificare',
          r.status === 'ACTIVE' &&
            r.last_success_at &&
            now - Date.parse(String(r.last_success_at)) <= 120_000
            ? 'success'
            : 'neutral'
        )
      ),
      column('message_count', 'Messaggi'),
      column('last_success_at', 'Ultima verifica', (r) => (
        <Text>
          {r.last_success_at
            ? formatCheckedAt(String(r.last_success_at))
            : 'Non ancora verificata'}
        </Text>
      )),
      column('id', 'Configurazione', (r) => (
        <Button
          label="Apri fonte"
          size="sm"
          variant="secondary"
          onClick={() => setSelected(String(r.id))}
        />
      )),
    ];
  if (section === 'telegram-messages')
    columns = [
      column('source_name', 'Fonte'),
      column('message_id', 'Messaggio'),
      column('event_kind', 'Evento', (r) =>
        status(MESSAGE_EVENTS[String(r.event_kind)] || 'Da verificare')
      ),
      column('version', 'Versione'),
      column('preview', 'Contenuto', (r) => (
        <Text>
          {r.event_kind === 'DELETE'
            ? 'Messaggio cancellato'
            : r.preview ? String(r.preview) :
              (r.body_available
                ? 'Messaggio senza testo'
                : 'Contenuto non più conservato')}
        </Text>
      )),
      column('observed_at', 'Data', (r) => (
        <Text>{formatCheckedAt(String(r.observed_at))}</Text>
      )),
    ];
  if (section === 'costs')
    columns = [
      column('created_at', 'Data', (r) => (
        <Text>{formatCheckedAt(String(r.created_at))}</Text>
      )),
      column('input_tokens', 'Token', (r) => (
        <VStack gap={1}>
          <Text>{String(r.input_tokens)} in ingresso</Text>
          <Text>{String(r.output_tokens)} in uscita</Text>
        </VStack>
      )),
      {key: 'estimated_cost_usd', header: 'Costo (USD)', width: proportional(1),
        renderCell: (r: Row) => <VStack gap={1}>
          <Text>Budget: {String(r.estimated_cost_usd)}</Text>
          <Text color="secondary">Fornitore: {r.reported_cost_usd == null ? 'Non confermato' : String(r.reported_cost_usd)}</Text>
        </VStack>},
      column('reserved_usd', 'Prenotato (USD)'),
      column('usage_known', 'Consumo', (r) => (
        <VStack gap={1}>
          <Text>{r.usage_known ? 'Confermato' : 'Non confermato'}</Text>
          <Text color="secondary">{r.budget_state === 'SETTLED' ? 'Consumo registrato' : 'Prenotazione conservata'}</Text>
        </VStack>
      )),
      column('pricing_version', 'Versione prezzi'),
    ];
  return (
    <VStack gap={5}>
      <Section variant="transparent" padding={6}>
        <VStack gap={2}>
          <HStack hAlign="between" vAlign="center" gap={3} wrap="wrap">
            <Heading level={1}>{page.title}</Heading>
            <Button
              label="Aggiorna dati"
              variant="secondary"
              size="sm"
              isLoading={busy}
              onClick={() => {
                setSaved(false);
                void load();
              }}
            />
          </HStack>
          <Text color="secondary">{page.description}</Text>
          {data && (
            <Text type="supporting" color="secondary">
              Ultimo aggiornamento: {formatCheckedAt(data.checked_at)}
            </Text>
          )}
        </VStack>
      </Section>
      {error && (
        <Banner
          status="error"
          title="Dati non disponibili"
          description={error}
        />
      )}
      {data && now - Date.parse(data.checked_at) > 30_000 && (
        <Banner
          status="warning"
          title="Dati non aggiornati"
          description="L’ultimo caricamento risale a più di 30 secondi fa. Aggiorna i dati per verificare lo stato attuale."
        />
      )}
      {saved && (
        <Banner
          status="success"
          title="Configurazione salvata"
          description="La nuova versione è registrata nello storico."
        />
      )}
      {busy && <Text role="status">Caricamento dei dati…</Text>}
      {section === 'sources' && user.role === 'ADMIN' && (
        <Button
          label="Aggiungi fonte"
          variant="secondary"
          onClick={() => setSelected('__new')}
        />
      )}
      {data && section === 'sources' && selected && (
        <ConfigurationEditor
          key={
            selected === '__new'
              ? 'new-source'
              : `${selected}:${data.rows.find((r) => r.id === selected)?.version}`
          }
          kind="source"
          row={
            selected === '__new'
              ? {version: 0, name: '', reference: '', enabled: true}
              : data.rows.find((r) => r.id === selected) || {
                  version: 0,
                  name: '',
                  reference: '',
                  enabled: true,
                }
          }
          onSaved={() => {
            setSelected(null);
            setSaved(true);
            void load();
          }}
        />
      )}
      {data &&
        section !== 'risk' &&
        (data.rows.length ? (
          <Table
            data={data.rows}
            columns={columns}
            idKey={
              section === 'settings'
                ? 'key'
                : section === 'status'
                  ? 'instance_id'
                  : 'id'
            }
            textOverflow="wrap"
            aria-label={page.title}
          />
        ) : (
          <EmptyState
            title="Nessun dato registrato"
            description="Qui compariranno le attività quando il relativo servizio sarà collegato e attivato."
            isCompact
          />
        ))}
      {data && (data.has_more || offset > 0) && (
        <HStack gap={2} hAlign="end">
          <Button
            label="Precedenti"
            variant="secondary"
            isDisabled={offset === 0 || busy}
            onClick={() => {
              setBusy(true);
              setData(null);
              setOffset((value) => Math.max(0, value - 50));
            }}
          />
          <Button
            label="Successivi"
            variant="secondary"
            isDisabled={!data.has_more || busy}
            onClick={() => {
              setBusy(true);
              setData(null);
              setOffset((value) => value + 50);
            }}
          />
        </HStack>
      )}
      {data &&
        (section === 'settings' ||
          section === 'risk' ||
          section === 'agents') &&
        data.rows
          .filter((row) =>
            section === 'settings'
              ? String(row.key).endsWith('_retention_days')
              : section === 'risk'
                ? true
                : String(row.id) === selected
          )
          .map((row) => (
            <ConfigurationEditor
              key={`${row.id || row.key}:${row.current_version}`}
              kind={
                section === 'agents'
                  ? 'agent'
                  : section === 'risk'
                    ? 'risk'
                    : 'settings'
              }
              row={row}
              models={models}
              onSaved={() => {
                setSaved(true);
                void load();
              }}
            />
          ))}
    </VStack>
  );
}
