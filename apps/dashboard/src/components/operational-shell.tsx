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
  loading: {label: 'Checking connection', variant: 'neutral', detail: 'Waiting for the first readiness check.'},
  ready: {label: 'Foundation ready', variant: 'success', detail: 'The API can reach its database and the schema is current.'},
  not_ready: {label: 'Foundation not ready', variant: 'warning', detail: 'The API reports that database or migration checks need attention.'},
  stale: {label: 'Status is stale', variant: 'warning', detail: 'The last check is too old or its clock is out of sync. Current readiness is unknown.'},
  offline: {label: 'Status unavailable', variant: 'error', detail: 'The dashboard cannot confirm API readiness. No connection is assumed.'},
};

interface ServiceRow extends Record<string, unknown> {
  name: string;
  state: string;
  detail: string;
  variant: StatusDotVariant;
}

const serviceColumns: TableColumn<ServiceRow>[] = [
  {key: 'name', header: 'Service', width: proportional(2), renderCell: row => <Text weight="semibold">{row.name}</Text>},
  {key: 'state', header: 'State', width: proportional(2), renderCell: row => (
    <HStack gap={2} vAlign="center">
      <StatusDot variant={row.variant} label={row.state} />
      <Text>{row.state}</Text>
    </HStack>
  )},
  {key: 'detail', header: 'What this means', width: proportional(4), renderCell: row => <Text color="secondary">{row.detail}</Text>},
];

export default function OperationalShell() {
  const {data, state, isRefreshing, refresh} = useReadiness();
  const connection = CONNECTION[state];
  const services: ServiceRow[] = [
    {name: 'API / database', state: connection.label, detail: 'Database reachability and migration revision only.', variant: connection.variant},
    {name: 'Telegram', state: 'Not connected', detail: 'Signal ingestion will be added in a later phase.', variant: 'neutral'},
    {name: 'AI agents', state: 'Not configured', detail: 'No provider requests or decisions are running.', variant: 'neutral'},
    {name: 'Risk / execution', state: 'Not active', detail: 'Deterministic risk controls and the execution bridge are not implemented yet.', variant: 'neutral'},
    {name: 'MT5 / EA', state: 'Not connected', detail: 'No terminal or broker account is connected.', variant: 'neutral'},
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
          header={<SideNavHeading heading="TRD" superheading="CONTROL CENTER" headingHref="/" />}
          footer={
            <Section variant="transparent" padding={4}>
              <VStack gap={2}>
                <HStack gap={2} vAlign="center">
                  <StatusDot variant="neutral" label="Automation disabled" />
                  <Text type="supporting">Automation disabled</Text>
                </HStack>
                <Text type="supporting" color="secondary">Foundation · Phase 1</Text>
              </VStack>
            </Section>
          }>
          <SideNavSection title="Workspace">
            <SideNavItem label="Overview" icon={Squares2X2Icon} href="/" as={Link} isSelected />
            <SideNavItem label="System status" icon={SignalIcon} href="#service-health" />
          </SideNavSection>
          <Divider />
          <SideNavSection title="Coming in later phases">
            <SideNavItem label="Positions" icon={ChartBarIcon} isDisabled />
            <SideNavItem label="Signals" icon={SignalIcon} isDisabled />
            <SideNavItem label="Agents" icon={CommandLineIcon} isDisabled />
            <SideNavItem label="Risk controls" icon={ShieldCheckIcon} isDisabled />
            <SideNavItem label="Audit log" icon={DocumentTextIcon} isDisabled />
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
                <Token label="PAPER" color="blue" size="sm" description="Paper mode only. No broker execution." />
                <Token label="AUTOMATION DISABLED" color="gray" size="sm" />
                <Text type="supporting" color="secondary">FOUNDATION</Text>
              </HStack>

              <Section variant="transparent" padding={6}>
                <VStack gap={2}>
                  <Text type="supporting" color="secondary">OPERATIONAL OVERVIEW</Text>
                  <Heading level={1}>System overview</Heading>
                  <Text color="secondary">A read-only view of the local foundation. Trading services are not active.</Text>
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
                      label="Refresh status" size="sm" variant="secondary"
                      icon={<Icon icon={ArrowPathIcon} />}
                      isLoading={isRefreshing} onClick={() => void refresh()}
                    />
                  </HStack>
                  <Text>{connection.detail}</Text>
                  <Text type="supporting" color="secondary" xstyle={styles.meta}>
                    {data ? `Last received check: ${data.checked_at.replace('T', ' ').replace(/(?:Z|\+00:00)$/, ' UTC')}` : 'No readiness check received yet.'}
                    {' '}Refreshes every 10 seconds.
                  </Text>
                </VStack>
              </Section>

              {(state === 'offline' || state === 'not_ready' || state === 'stale') && (
                <Banner
                  status={state === 'offline' ? 'error' : 'warning'}
                  title={state === 'not_ready' ? 'Infrastructure needs attention' : 'Current health is unknown'}
                  description={state === 'not_ready'
                    ? 'Check the API, database and migrations in your local setup. This view does not expose internal error details.'
                    : 'The last observation is not a current health guarantee. Check the local services, then refresh.'}
                />
              )}

              <Section id="service-health" variant="transparent" padding={0}>
                <VStack gap={3}>
                  <HStack gap={3} hAlign="between" vAlign="center" wrap="wrap" paddingInline={6}>
                    <Heading level={2}>Service readiness</Heading>
                    <Text type="supporting" color="secondary">Observed status, no simulated metrics</Text>
                  </HStack>
                  <Table data={services} columns={serviceColumns} idKey="name" density="balanced" textOverflow="wrap" aria-label="Service readiness" />
                </VStack>
              </Section>

              <Card padding={4}>
                <HStack gap={4} vAlign="start">
                  <Icon icon={ShieldCheckIcon} color="secondary" />
                  <VStack gap={1}>
                    <Text weight="semibold">Execution remains locked</Text>
                    <Text color="secondary">No trades can be submitted from this foundation. Risk validation, authentication and broker execution arrive in later phases.</Text>
                  </VStack>
                </HStack>
              </Card>

              <Section variant="transparent" padding={0}>
                <EmptyState
                  isCompact headingLevel={2} title="Trading activity is not available yet"
                  description="Positions, signals, agent decisions and financial results will appear when their services are implemented and connected."
                />
              </Section>
            </VStack>
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            <Text type="supporting" color="secondary">Local foundation · Paper only · Read-only status</Text>
          </LayoutFooter>
        }
      />
    </AppShell>
  );
}
