// Settings template sections: responsive two-column Grid minWidth320/gap10, VStack gap4.
'use client';
import {useState} from 'react';
import {Grid} from '@astryxdesign/core/Grid';
import {VStack, HStack} from '@astryxdesign/core/Stack';
import {Text, Heading} from '@astryxdesign/core/Text';
import {TextInput} from '@astryxdesign/core/TextInput';
import {Selector} from '@astryxdesign/core/Selector';
import {Button} from '@astryxdesign/core/Button';
import {Banner} from '@astryxdesign/core/Banner';
import {Dialog, DialogHeader} from '@astryxdesign/core/Dialog';
import {Table, proportional, type TableColumn} from '@astryxdesign/core/Table';
import {Section} from '@astryxdesign/core/Section';
import {Token} from '@astryxdesign/core/Token';
import {
  api,
  type Change,
  type Confirmation,
  type Row,
} from '@/lib/dashboard-api';
import {
  AGENT_LABELS,
  SETTING_LABELS,
  RISK_FIELDS,
  shiftDecimal,
} from '@/lib/configuration';
import {formatCheckedAt} from '@/lib/locale';
import {useSession} from './trading-shell';

type Kind = 'settings' | 'risk' | 'agent' | 'source';
type Diff = {name: string; before: string; after: string} & Record<
  string,
  unknown
>;
const columns: TableColumn<Diff>[] = [
  {key: 'name', header: 'Impostazione', width: proportional(2)},
  {key: 'before', header: 'Attuale', width: proportional(1)},
  {key: 'after', header: 'Proposta', width: proportional(1)},
];

export default function ConfigurationEditor({
  kind,
  row,
  models = [],
  onSaved,
}: {
  kind: Kind;
  row: Row;
  models?: Row[];
  onSaved: () => void;
}) {
  const user = useSession();
  const canEdit = user.role === 'ADMIN';
  const original = (
    kind === 'risk'
      ? row.policy
      : kind === 'agent' || kind === 'source'
        ? row
        : {value: row.value}
  ) as Record<string, unknown>;
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(original).map(([key, value]) => [
        key,
        kind === 'risk' &&
        RISK_FIELDS.some(([k, , percent]) => k === key && percent)
          ? shiftDecimal(String(value), 2)
          : Array.isArray(value)
            ? value.join(', ')
            : String(value),
      ])
    )
  );
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [diff, setDiff] = useState<Diff[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const title =
    kind === 'settings'
      ? (SETTING_LABELS[String(row.key)] ?? 'Conservazione dei dati')
      : kind === 'risk'
        ? 'Limiti di rischio'
        : kind === 'source'
          ? row.id
            ? String(row.name)
            : 'Nuova fonte Telegram'
          : (AGENT_LABELS[String(row.name)] ?? 'Agente IA');
  const version = Number(kind === 'source' ? row.version : row.current_version);
  function field(key: string, label: string, readOnly = false) {
    return (
      <TextInput
        key={key}
        label={label}
        value={values[key] ?? ''}
        onChange={(value) =>
          setValues((previous) => ({...previous, [key]: value}))
        }
        isReadOnly={!canEdit || readOnly || busy}
      />
    );
  }
  async function review() {
    setError('');
    setBusy(true);
    try {
      let value: Change['value'];
      let changes: Diff[];
      if (kind === 'settings') {
        if (
          !/^\d{1,3}$/.test(values.value ?? '') ||
          Number(values.value ?? '') < 1 ||
          Number(values.value ?? '') > 365
        )
          throw new Error('Inserisci un numero di giorni tra 1 e 365.');
        value = Number(values.value ?? '');
        changes = [
          {
            name: title,
            before: `${row.value} giorni`,
            after: `${value} giorni`,
          },
        ];
      } else if (kind === 'risk') {
        const policy: Record<string, string | number | boolean> = {
          require_stop_loss: true,
          require_take_profit: true,
        };
        changes = RISK_FIELDS.map(([key, label, percent]) => {
          const input = values[key] ?? '';
          policy[key] = percent
            ? shiftDecimal(input, -2)
            : key === 'max_open_positions'
              ? Number(input)
              : shiftDecimal(input, 0);
          if (key === 'max_open_positions' && !/^\d+$/.test(input))
            throw new Error('Il numero di posizioni deve essere intero.');
          return {
            name: label,
            before: percent
              ? shiftDecimal(String(original[key]), 2)
              : String(original[key]),
            after: input,
          };
        });
        value = policy;
      } else if (kind === 'source') {
        value = {
          name: values.name ?? '',
          reference: values.reference ?? '',
          enabled: values.enabled === 'true',
        };
        changes = [
          {
            name: 'Nome',
            before: String(row.name || 'Nuova fonte'),
            after: values.name ?? '',
          },
          {
            name: 'Canale o gruppo',
            before: String(row.reference || 'Da verificare'),
            after: values.reference ?? '',
          },
          {
            name: 'Lettura dei messaggi',
            before: row.id
              ? row.enabled
                ? 'Autorizzata'
                : 'Disattivata'
              : 'Non configurata',
            after: values.enabled === 'true' ? 'Autorizzata' : 'Disattivata',
          },
        ];
      } else {
        if (
          !/^\d+$/.test(values.timeout_seconds ?? '') ||
          !/^\d+$/.test(values.max_output_tokens ?? '')
        )
          throw new Error('Durata e numero di token devono essere interi.');
        value = {
          enabled: false,
          primary_model_id: values.primary_model_id ?? '',
          fallback_model_ids: (values.fallback_model_ids ?? '').trim()
            ? (values.fallback_model_ids ?? '').split(',').map((v) => v.trim())
            : [],
          prompt_version: Number(row.prompt_version),
          timeout_seconds: Number(values.timeout_seconds ?? ''),
          max_output_tokens: Number(values.max_output_tokens ?? ''),
          max_cost_usd: '0',
          required_schema_version: Number(row.required_schema_version),
        };
        changes = [
          {
            name: 'Modello principale',
            before: String(row.primary_model_id),
            after: values.primary_model_id ?? '',
          },
          {
            name: 'Modelli alternativi',
            before: Array.isArray(row.fallback_model_ids)
              ? row.fallback_model_ids.join(', ') || 'Nessuno'
              : 'Nessuno',
            after: (values.fallback_model_ids ?? '') || 'Nessuno',
          },
          {
            name: 'Durata massima (secondi)',
            before: String(row.timeout_seconds),
            after: values.timeout_seconds ?? '',
          },
          {
            name: 'Token massimi in uscita',
            before: String(row.max_output_tokens),
            after: values.max_output_tokens ?? '',
          },
        ];
      }
      if (changes.every((item) => item.before === item.after))
        throw new Error('Nessuna modifica da salvare.');
      const change: Change = {
        kind,
        target: String(
          kind === 'source'
            ? row.id || crypto.randomUUID()
            : kind === 'agent'
              ? row.id
              : row.key
        ),
        expected_version: version,
        value,
      };
      const reviewed = await api<Confirmation>('config/confirm', {
        body: change,
        csrf: user.csrf_token,
      });
      setDiff(changes);
      setConfirmation(reviewed);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Verifica non riuscita.');
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!confirmation || busy) return;
    setBusy(true);
    setError('');
    try {
      await api('config/apply', {
        body: {
          change: confirmation.change,
          confirmation_token: confirmation.confirmation_token,
        },
        csrf: user.csrf_token,
      });
      setConfirmation(null);
      onSaved();
    } catch (e) {
      setConfirmation(null);
      setError(e instanceof Error ? e.message : 'Salvataggio non riuscito.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <Section variant="transparent" padding={4}>
      <VStack gap={4}>
        <Grid columns={{minWidth: 320}} gap={10}>
          <VStack gap={1}>
            <Heading level={2}>{title}</Heading>
            <Text color="secondary">
              Versione {version}.{' '}
              {kind === 'risk'
                ? 'Puoi ridurre i limiti attuali. Stop loss e take profit rimangono obbligatori.'
                : kind === 'agent'
                  ? 'Prepara la configurazione. L’agente resterà disattivato.'
                  : kind === 'source'
                    ? 'Autorizza la lettura di un canale o gruppo accessibile all’account collegato. La verifica avviene dopo il salvataggio.'
                    : 'Imposta il periodo di conservazione. Le evidenze necessarie alle operazioni restano protette.'}
            </Text>
            {!canEdit && (
              <Text color="secondary">
                Il tuo ruolo consente la sola consultazione.
              </Text>
            )}
          </VStack>
          <VStack gap={4}>
            {kind === 'settings' ? (
              field('value', 'Giorni di conservazione')
            ) : kind === 'risk' ? (
              <>
                {RISK_FIELDS.map(([key, label]) => field(key, label))}
                <HStack gap={2} wrap="wrap">
                  <Token label="STOP LOSS OBBLIGATORIO" color="gray" />
                  <Token label="TAKE PROFIT OBBLIGATORIO" color="gray" />
                </HStack>
              </>
            ) : kind === 'source' ? (
              <>
                {field('name', 'Nome della fonte')}
                {field(
                  'reference',
                  'Canale o gruppo (@nome, link pubblico t.me o ID negativo)',
                  !!row.id
                )}
                <Selector
                  label="Lettura dei messaggi"
                  value={values.enabled ?? 'false'}
                  options={[
                    {value: 'true', label: 'Autorizzata'},
                    {value: 'false', label: 'Disattivata'},
                  ]}
                  onChange={(value) =>
                    setValues((previous) => ({...previous, enabled: value}))
                  }
                  isReadOnly={!canEdit || busy}
                />
                <Text color="secondary">
                  Gli inviti privati richiedono l’accesso dell’account al
                  gruppo; inserisci poi il suo ID. Il sistema non accetta inviti
                  né si iscrive automaticamente.
                </Text>
              </>
            ) : (
              <>
                <Selector
                  label="Modello principale"
                  value={values.primary_model_id ?? ''}
                  onChange={(value) =>
                    setValues((previous) => ({
                      ...previous,
                      primary_model_id: value,
                    }))
                  }
                  options={models
                    .filter(
                      (model) => model.enabled && model.provider === 'mock'
                    )
                    .map((model) => ({
                      value: String(model.id),
                      label: 'Simulatore locale',
                      description: String(model.id),
                    }))}
                  isReadOnly={!canEdit || busy}
                  emptyText="Nessun modello disponibile"
                />
                {field(
                  'fallback_model_ids',
                  'Modelli alternativi (identificativi separati da virgola)'
                )}
                {field(
                  'timeout_seconds',
                  'Durata massima della richiesta (secondi)'
                )}
                {field('max_output_tokens', 'Token massimi in uscita')}
                {field(
                  'max_cost_usd',
                  'Costo massimo della richiesta (USD)',
                  true
                )}
                {field('prompt_version', 'Versione delle istruzioni', true)}
                <Token label="AGENTE DISATTIVATO" color="gray" />
              </>
            )}
            {error && <Banner status="error" title={error} />}
            {canEdit && (
              <Button
                label="Rivedi modifica"
                variant="secondary"
                isLoading={busy}
                onClick={() => void review()}
              />
            )}
          </VStack>
        </Grid>
        <Dialog
          isOpen={!!confirmation}
          onOpenChange={(open) => {
            if (!open && !busy) setConfirmation(null);
          }}
          purpose="form"
          width={640}
        >
          <DialogHeader
            title="Conferma la modifica"
            onOpenChange={(open) => {
              if (!open && !busy) setConfirmation(null);
            }}
          />
          <VStack gap={4} padding={4}>
            <Text>
              {title} · Simulazione · Versione {version} → {version + 1}
            </Text>
            <Table
              data={diff}
              columns={columns}
              idKey="name"
              textOverflow="wrap"
              aria-label="Riepilogo delle modifiche"
            />
            <Text color="secondary">
              La modifica viene salvata nello storico.{' '}
              {confirmation &&
                `Conferma valida fino alle ${formatCheckedAt(confirmation.expires_at)}.`}
            </Text>
            <HStack gap={2} hAlign="end">
              <Button
                label="Annulla"
                variant="secondary"
                isDisabled={busy}
                onClick={() => setConfirmation(null)}
              />
              <Button
                label="Conferma e salva"
                isLoading={busy}
                onClick={() => void save()}
              />
            </HStack>
          </VStack>
        </Dialog>
      </VStack>
    </Section>
  );
}
