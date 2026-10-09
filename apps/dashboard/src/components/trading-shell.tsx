// Astryx shell-side-nav frame retained from the Phase 1 operational shell.
'use client';
import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from 'react';
import Link from 'next/link';
import {usePathname, useRouter} from 'next/navigation';
import {AppShell} from '@astryxdesign/core/AppShell';
import {Button} from '@astryxdesign/core/Button';
import {Banner} from '@astryxdesign/core/Banner';
import {Layout, LayoutContent, LayoutFooter} from '@astryxdesign/core/Layout';
import {Section} from '@astryxdesign/core/Section';
import {
  SideNav,
  SideNavHeading,
  SideNavItem,
  SideNavSection,
} from '@astryxdesign/core/SideNav';
import {HStack, VStack} from '@astryxdesign/core/Stack';
import {StatusDot} from '@astryxdesign/core/StatusDot';
import {Text} from '@astryxdesign/core/Text';
import {Token} from '@astryxdesign/core/Token';
import {
  ChartBarIcon,
  CommandLineIcon,
  DocumentTextIcon,
  ShieldCheckIcon,
  SignalIcon,
  Squares2X2Icon,
  Cog6ToothIcon,
  CpuChipIcon,
  CurrencyDollarIcon,
  ChatBubbleLeftRightIcon,
} from '@heroicons/react/24/outline';
import {api, type SessionUser} from '@/lib/dashboard-api';
const UserContext = createContext<SessionUser | null>(null);
export function useSession() {
  const user = useContext(UserContext);
  if (!user) throw new Error('Accesso richiesto');
  return user;
}
const NAV = [
  ['/', 'Panoramica', Squares2X2Icon],
  ['/signals', 'Segnali', SignalIcon],
  ['/positions', 'Posizioni', ChartBarIcon],
  ['/sources', 'Fonti Telegram', ChatBubbleLeftRightIcon],
  ['/telegram-messages', 'Messaggi Telegram', ChatBubbleLeftRightIcon],
  ['/agents', 'Agenti IA', CommandLineIcon],
  ['/models', 'Registro modelli', CpuChipIcon],
  ['/risk', 'Controlli del rischio', ShieldCheckIcon],
  ['/costs', 'Costi IA', CurrencyDollarIcon],
  ['/status', 'Stato dei servizi', SignalIcon],
  ['/settings', 'Impostazioni', Cog6ToothIcon],
  ['/audit', 'Registro attività', DocumentTextIcon],
] as const;
export default function TradingShell({
  user,
  children,
}: {
  user: SessionUser;
  children: ReactNode;
}) {
  const router = useRouter();
  const [session, setSession] = useState(user);
  useEffect(() => {
    const expired = () => {
      router.replace('/login');
      router.refresh();
    };
    window.addEventListener('trd-session-expired', expired);
    let lastCheck = Date.now();
    let checking = false;
    const activity = () => {
      if (
        checking ||
        Date.now() - lastCheck < 60_000 ||
        document.visibilityState !== 'visible'
      )
        return;
      checking = true;
      lastCheck = Date.now();
      void api<SessionUser>('auth/me')
        .then(setSession)
        .catch(() => {})
        .finally(() => {
          checking = false;
        });
    };
    const expiry = Math.min(
      Date.parse(session.expires_at || ''),
      Date.parse(session.idle_expires_at || '')
    );
    const timer = Number.isFinite(expiry)
      ? setTimeout(expired, Math.max(0, expiry - Date.now()))
      : undefined;
    window.addEventListener('pointerdown', activity);
    window.addEventListener('keydown', activity);
    document.addEventListener('visibilitychange', activity);
    return () => {
      if (timer !== undefined) clearTimeout(timer);
      window.removeEventListener('trd-session-expired', expired);
      window.removeEventListener('pointerdown', activity);
      window.removeEventListener('keydown', activity);
      document.removeEventListener('visibilitychange', activity);
    };
  }, [router, session.expires_at, session.idle_expires_at]);
  const pathname = usePathname();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function logout() {
    setBusy(true);
    try {
      await api('auth/logout', {body: {}, csrf: session.csrf_token});
      router.replace('/login');
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Uscita non disponibile.');
      setBusy(false);
    }
  }
  return (
    <UserContext value={session}>
      <AppShell
        contentPadding={0}
        variant="section"
        mobileNav={{breakpoint: 'md'}}
        sideNav={
          <SideNav
            collapsible
            resizable={{defaultWidth: 260, minWidth: 220, maxWidth: 420}}
            header={
              <SideNavHeading
                heading="TRD"
                superheading="CENTRO DI CONTROLLO"
                headingHref="/"
              />
            }
            footer={
              <Section variant="transparent" padding={4}>
                <VStack gap={2}>
                  <HStack gap={2} vAlign="center">
                    <StatusDot
                      variant="neutral"
                      label="Automazione disattivata"
                    />
                    <Text type="supporting">Automazione disattivata</Text>
                  </HStack>
                  <Text type="supporting">
                    {session.role === 'ADMIN' ? 'Amministratore' : 'Lettore'}
                  </Text>
                  <Text type="supporting" color="secondary">
                    {session.email}
                  </Text>
                  <Button
                    label="Esci"
                    variant="secondary"
                    size="sm"
                    isLoading={busy}
                    onClick={() => void logout()}
                  />
                </VStack>
              </Section>
            }
          >
            <SideNavSection title="Area di lavoro">
              {NAV.map(([href, label, icon]) => (
                <SideNavItem
                  key={href}
                  href={href}
                  as={Link}
                  label={label}
                  icon={icon}
                  isSelected={
                    href === '/' ? pathname === '/' : pathname.startsWith(href)
                  }
                />
              ))}
            </SideNavSection>
          </SideNav>
        }
      >
        <Layout
          height="fill"
          contentWidth={960}
          content={
            <LayoutContent padding={6}>
              <VStack gap={5}>
                <HStack gap={2} vAlign="center" wrap="wrap">
                  <Token label="SIMULAZIONE" color="blue" size="sm" />
                  <Token
                    label="AUTOMAZIONE DISATTIVATA"
                    color="gray"
                    size="sm"
                  />
                  <Text type="supporting" color="secondary">
                    AMBIENTE LOCALE
                  </Text>
                </HStack>
                {error && <Banner status="error" title={error} />}
                {children}
              </VStack>
            </LayoutContent>
          }
          footer={
            <LayoutFooter hasDivider>
              <Text type="supporting" color="secondary">
                Ambiente locale · Simulazione ·{' '}
                {session.role === 'ADMIN'
                  ? 'Configurazioni protette'
                  : 'Sola consultazione'}
              </Text>
            </LayoutFooter>
          }
        />
      </AppShell>
    </UserContext>
  );
}
