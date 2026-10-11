// Structured detail sections use the existing Astryx shell frame.
'use client';
import {useEffect, useState} from 'react';
import {VStack} from '@astryxdesign/core/Stack';
import {Heading, Text} from '@astryxdesign/core/Text';
import {Banner} from '@astryxdesign/core/Banner';
import {Table, proportional, type TableColumn} from '@astryxdesign/core/Table';
import {api, type Row} from '@/lib/dashboard-api';
import {STATUS, AGENT_LABELS, analysisReasons} from '@/lib/configuration';
import {formatCheckedAt} from '@/lib/locale';
function proposal(row: Row): Record<string, unknown> {
  return row.proposal &&
    typeof row.proposal === 'object' &&
    !Array.isArray(row.proposal)
    ? (row.proposal as Record<string, unknown>)
    : {};
}
const columns: TableColumn<Row>[] = [
  {key: 'version', header: 'Versione', width: proportional(1)},
  {
    key: 'created_at',
    header: 'Data',
    width: proportional(2),
    renderCell: (r) => <Text>{formatCheckedAt(String(r.created_at))}</Text>,
  },
  ...[
    ['symbol', 'Strumento'],
    ['side', 'Direzione'],
    ['entry', 'Ingresso'],
    ['stop_loss', 'Stop loss'],
    ['take_profit', 'Take profit'],
  ].map(([key, header]) => ({
    key: key!,
    header: header!,
    width: proportional(1),
    renderCell: (r: Row) => (
      <Text>
        {key === 'side'
          ? proposal(r)[key] === 'BUY'
            ? 'Acquisto'
            : proposal(r)[key] === 'SELL'
              ? 'Vendita'
              : 'Non disponibile'
          : String(proposal(r)[key!] ?? '—')}
      </Text>
    ),
  })),
];
export default function SignalDetail({id}: {id: string}) {
  const [state, setState] = useState('');
  const [versions, setVersions] = useState<Row[] | null>(null);
  const [error, setError] = useState('');
  const [analysis, setAnalysis] = useState<Row | null>(null);
  const [runs, setRuns] = useState<Row[]>([]);
  useEffect(() => {
    let active = true;
    void api<{versions: Row[]; signal: Row; analysis: Row | null; runs: Row[]}>(`ops/signals/${id}`)
      .then((value) => {
        if (active) {
          setVersions(value.versions);
          setState(STATUS[String(value.signal.state)] || 'Stato da verificare');
          setAnalysis(value.analysis);
          setRuns(value.runs);
        }
      })
      .catch((e) => {
        if (active)
          setError(e instanceof Error ? e.message : 'Segnale non disponibile.');
      });
    return () => {
      active = false;
    };
  }, [id]);
  return (
    <VStack gap={5}>
      <Heading level={1}>Dettaglio del segnale</Heading>
      {state && <Text>Stato: {state}</Text>}
      <Text color="secondary">
        Identificativo: {id}. Ultime 20 versioni della proposta. Le proposte non
        confermano l’esecuzione di un ordine.
      </Text>
      {error && <Banner status="error" title={error} />}
      {analysis && <Banner status="info" title="Esito dell’analisi consultiva"
        description={analysisReasons(analysis.reason_codes)} />}
      {versions ? (
        <Table
          data={versions}
          columns={columns}
          idKey="version"
          aria-label="Versioni del segnale"
          textOverflow="wrap"
        />
      ) : (
        !error && <Text role="status">Caricamento del segnale…</Text>
      )}
      {!!runs.length && <>
        <Heading level={2}>Valutazioni degli agenti</Heading>
        <Text color="secondary">Tentativi registrati con versione della configurazione e del modello.
          Il consumo del simulatore è zero; nessuna richiesta è stata inviata a un fornitore esterno.</Text>
        <Table data={runs} idKey="id" aria-label="Valutazioni consultive degli agenti" textOverflow="wrap"
          columns={[
            {key: 'agent_name', header: 'Agente', width: proportional(2), renderCell: (r) => <Text>{AGENT_LABELS[String(r.agent_name)] ?? 'Agente da verificare'}</Text>},
            {key: 'status', header: 'Esito', width: proportional(2), renderCell: (r) => <Text>{STATUS[String(r.status)] ?? 'Da verificare'}</Text>},
            {key: 'model_id', header: 'Modello', width: proportional(1)},
            {key: 'config_version', header: 'Versione', width: proportional(1)},
            {key: 'attempt', header: 'Tentativo', width: proportional(1)},
          ]} />
      </>}
    </VStack>
  );
}
