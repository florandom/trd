// Structured detail sections use the existing Astryx shell frame.
'use client';
import {useEffect, useState} from 'react';
import {VStack} from '@astryxdesign/core/Stack';
import {Heading, Text} from '@astryxdesign/core/Text';
import {Banner} from '@astryxdesign/core/Banner';
import {Table, proportional, type TableColumn} from '@astryxdesign/core/Table';
import {api, type Row} from '@/lib/dashboard-api';
import {STATUS} from '@/lib/configuration';
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
  useEffect(() => {
    let active = true;
    void api<{versions: Row[]; signal: Row}>(`ops/signals/${id}`)
      .then((value) => {
        if (active) {
          setVersions(value.versions);
          setState(STATUS[String(value.signal.state)] || 'Stato da verificare');
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
    </VStack>
  );
}
