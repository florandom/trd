import type {Metadata} from 'next';
import type {ReactNode} from 'react';
import {cookies} from 'next/headers';
import '@stylexswc/webpack-plugin/stylex.css';
import './globals.css';
import {DashboardTheme} from '@/components/dashboard-theme';
import {DASHBOARD_LOCALE} from '@/lib/locale';
import {DASHBOARD_THEME_COOKIE, parseDashboardTheme} from '@/lib/theme';

export const metadata: Metadata = {
  title: 'TRD · Centro di controllo',
  description: 'Stato dei servizi e panoramica del sistema. Modalità simulazione, automazione disattivata.',
  robots: {index: false, follow: false},
};

export default async function RootLayout({children}: {children: ReactNode}) {
  const mode = parseDashboardTheme((await cookies()).get(DASHBOARD_THEME_COOKIE)?.value);
  return <html lang={DASHBOARD_LOCALE} data-theme={mode} data-astryx-theme="neutral"><body><DashboardTheme initialMode={mode}>{children}</DashboardTheme></body></html>;
}
