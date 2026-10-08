// Adapted from Astryx 0.6.4 shell-side-nav: AppShell > SideNav + Layout.
'use client';

import Link from 'next/link';
import * as stylex from '@stylexjs/stylex';
import {AppShell} from '@astryxdesign/core/AppShell';
import {Banner} from '@astryxdesign/core/Banner';
import {Button} from '@astryxdesign/core/Button';
import {Card} from '@astryxdesign/core/Card';
import {Divider} from '@astryxdesign/core/Divider';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Icon} from '@astryxdesign/core/Icon';
import {Layout, LayoutContent, LayoutFooter} from '@astryxdesign/core/Layout';
import {Section} from '@astryxdesign/core/Section';
import {SideNav, SideNavHeading, SideNavItem, SideNavSection} from '@astryxdesign/core/SideNav';
import {HStack, VStack} from '@astryxdesign/core/Stack';
import {StatusDot} from '@astryxdesign/core/StatusDot';
import type {StatusDotVariant} from '@astryxdesign/core/StatusDot';
import {Table, proportional} from '@astryxdesign/core/Table';
import type {TableColumn} from '@astryxdesign/core/Table';
import {Heading, Text} from '@astryxdesign/core/Text';
import {Token} from '@astryxdesign/core/Token';
import {
  ArrowPathIcon, ChartBarIcon, CommandLineIcon, DocumentTextIcon,
  ShieldCheckIcon, SignalIcon, Squares2X2Icon,
} from '@heroicons/react/24/outline';
import {useReadiness} from '@/hooks/use-readiness';
import {formatCheckedAt} from '@/lib/locale';
import type {ConnectionState} from '@/lib/readiness';

const styles = stylex.create({
  hero: {
    backgroundColor: 'var(--color-background-surface)',
    backgroundImage: 'radial-gradient(ellipse at top right, var(--color-accent-muted), transparent)',
    borderRadius: 'var(--radius-container)',
  },
  meta: {fontVariantNumeric: 'tabular-nums'},
});

const CONNECTION: Record<ConnectionState, {label: string; variant: StatusDotVariant; detail: string}> = {
  loading: {label: 'Verifica della connessione', variant: 'neutral', detail: 'In attesa del primo aggiornamento sullo stato dei servizi.'},
  ready: {label: 'Connessione verificata', variant: 'success', detail: 'I servizi di base comunicano correttamente con il database, che è aggiornato.'},
  not_ready: {label: 'Connessione da verificare', variant: 'warning', detail: 'Il database non è disponibile oppure richiede un aggiornamento.'},
  stale: {label: 'Stato non aggiornato', variant: 'warning', detail: 'L’ultimo controllo è troppo vecchio oppure l’orario non è sincronizzato. Lo stato attuale non è confermato.'},
  offline: {label: 'Stato non disponibile', variant: 'error', detail: 'Non è possibile verificare la connessione ai servizi di base.'},
};

interface ServiceRow extends Record<string, unknown> {
  name: string;
  state: string;
  detail: string;
  variant: StatusDotVariant;
}

const serviceColumns: TableColumn<ServiceRow>[] = [
  {key: 'name', header: 'Servizio', width: proportional(2), renderCell: row => <Text weight="semibold">{row.name}</Text>},
  {key: 'state', header: 'Stato', width: proportional(2), renderCell: row => (
    <HStack gap={2} vAlign="center">
      <StatusDot variant={row.variant} label={row.state} />
      <Text>{row.state}</Text>
    </HStack>
  )},
  {key: 'detail', header: 'Dettagli', width: proportional(4), renderCell: row => <Text color="secondary">{row.detail}</Text>},
];

export default function OperationalShell() {
  const {data, state, isRefreshing, refresh} = useReadiness();
  const connection = CONNECTION[state];
  const services: ServiceRow[] = [
    {name: 'Servizi di base', state: connection.label, detail: 'Verifica della connessione al database e del suo aggiornamento.', variant: connection.variant},
    {name: 'Telegram', state: 'Non collegato', detail: 'La ricezione dei segnali sarà disponibile in seguito.', variant: 'neutral'},
    {name: 'Agenti IA', state: 'Non attivi', detail: 'Nessuna analisi o decisione automatica in corso.', variant: 'neutral'},
    {name: 'Rischio e ordini', state: 'Non attivi', detail: 'I controlli del rischio e l’invio degli ordini saranno disponibili in seguito.', variant: 'neutral'},
    {name: 'MetaTrader 5', state: 'Non collegato', detail: 'Nessun terminale o conto di trading collegato.', variant: 'neutral'},
  ];

  // The original template frame is retained. Mixed operational rows use a 960px
  // content budget; the navigation swaps to AppShell's drawer below md.
  return (
    <AppShell
      contentPadding={0}
      variant="section"
      mobileNav={{breakpoint: 'md'}}
      sideNav={
        <SideNav
          collapsible
          resizable={{defaultWidth: 260, minWidth: 220, maxWidth: 420}}
          header={<SideNavHeading heading="TRD" superheading="CENTRO DI CONTROLLO" headingHref="/" />}
          footer={
            <Section variant="transparent" padding={4}>
              <VStack gap={2}>
                <HStack gap={2} vAlign="center">
                  <StatusDot variant="neutral" label="Automazione disattivata" />
                  <Text type="supporting">Automazione disattivata</Text>
                </HStack>
                <Text type="supporting" color="secondary">Ambiente locale</Text>
              </VStack>
            </Section>
          }>
          <SideNavSection title="Area di lavoro">
            <SideNavItem label="Panoramica" icon={Squares2X2Icon} href="/" as={Link} isSelected />
            <SideNavItem label="Stato dei servizi" icon={SignalIcon} href="#service-health" />
          </SideNavSection>
          <Divider />
          <SideNavSection title="Prossime funzionalità">
            <SideNavItem label="Posizioni" icon={ChartBarIcon} isDisabled />
            <SideNavItem label="Segnali" icon={SignalIcon} isDisabled />
            <SideNavItem label="Agenti IA" icon={CommandLineIcon} isDisabled />
            <SideNavItem label="Controlli del rischio" icon={ShieldCheckIcon} isDisabled />
            <SideNavItem label="Registro attività" icon={DocumentTextIcon} isDisabled />
          </SideNavSection>
        </SideNav>
      }>
      <Layout
        height="fill"
        contentWidth={960}
        content={
          <LayoutContent padding={6}>
            <VStack gap={5}>
              <HStack gap={2} wrap="wrap" vAlign="center">
                <Token label="SIMULAZIONE" color="blue" size="sm" description="Modalità simulazione. Nessun ordine viene inviato al broker." />
                <Token label="AUTOMAZIONE DISATTIVATA" color="gray" size="sm" />
                <Text type="supporting" color="secondary">AMBIENTE LOCALE</Text>
              </HStack>

              <Section variant="transparent" padding={6}>
                <VStack gap={2}>
                  <Text type="supporting" color="secondary">STATO DEL SISTEMA</Text>
                  <Heading level={1}>Panoramica</Heading>
                  <Text color="secondary">Consulta lo stato dei servizi. Le funzioni di trading non sono ancora attive.</Text>
                </VStack>
              </Section>

              <Section variant="transparent" padding={0}>
                <VStack gap={3} padding={6} xstyle={styles.hero}>
                  <HStack gap={3} hAlign="between" vAlign="center" wrap="wrap">
                    <HStack gap={3} vAlign="center" role="status" aria-live="polite" aria-atomic="true">
                      <StatusDot variant={connection.variant} label={connection.label} />
                      <Heading level={2}>{connection.label}</Heading>
                    </HStack>
                    <Button
                      label="Aggiorna stato" size="sm" variant="secondary"
                      icon={<Icon icon={ArrowPathIcon} />}
                      isLoading={isRefreshing} onClick={() => void refresh()}
                    />
                  </HStack>
                  <Text>{connection.detail}</Text>
                  <Text type="supporting" color="secondary" xstyle={styles.meta}>
                    {data ? `Ultimo aggiornamento: ${formatCheckedAt(data.checked_at)}` : 'Nessun aggiornamento ricevuto.'}
                    {' '}Aggiornamento automatico ogni 10 secondi.
                  </Text>
                </VStack>
              </Section>

              {(state === 'offline' || state === 'not_ready' || state === 'stale') && (
                <Banner
                  status={state === 'offline' ? 'error' : 'warning'}
                  title={state === 'not_ready' ? 'I servizi richiedono attenzione' : 'Stato attuale non confermato'}
                  description={state === 'not_ready'
                    ? 'La connessione al database o il suo aggiornamento richiedono una verifica. Contatta l’amministratore del sistema.'
                    : 'I dati disponibili non confermano lo stato attuale. Aggiorna lo stato; se il problema persiste, contatta l’amministratore del sistema.'}
                />
              )}

              <Section id="service-health" variant="transparent" padding={0}>
                <VStack gap={3}>
                  <HStack gap={3} hAlign="between" vAlign="center" wrap="wrap" paddingInline={6}>
                    <Heading level={2}>Stato dei servizi</Heading>
                    <Text type="supporting" color="secondary">Stato rilevato dai servizi</Text>
                  </HStack>
                  <Table data={services} columns={serviceColumns} idKey="name" density="balanced" textOverflow="wrap" aria-label="Stato dei servizi" />
                </VStack>
              </Section>

              <Card padding={4}>
                <HStack gap={4} vAlign="start">
                  <Icon icon={ShieldCheckIcon} color="secondary" />
                  <VStack gap={1}>
                    <Text weight="semibold">Invio degli ordini disattivato</Text>
                    <Text color="secondary">Al momento non è possibile inviare ordini. Le funzioni di trading saranno disponibili dopo l’attivazione dei controlli del rischio, dell’accesso protetto e del collegamento al broker.</Text>
                  </VStack>
                </HStack>
              </Card>

              <Section variant="transparent" padding={0}>
                <EmptyState
                  isCompact headingLevel={2} title="Attività di trading non ancora disponibile"
                  description="Posizioni, segnali, decisioni degli agenti e risultati saranno visibili dopo l’attivazione dei relativi servizi."
                />
              </Section>
            </VStack>
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            <Text type="supporting" color="secondary">Ambiente locale · Simulazione · Sola consultazione</Text>
          </LayoutFooter>
        }
      />
    </AppShell>
  );
}
