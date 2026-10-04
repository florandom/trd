import type {Metadata} from 'next';
import type {ReactNode} from 'react';
import '@stylexswc/webpack-plugin/stylex.css';
import './globals.css';
import {DashboardTheme} from '@/components/dashboard-theme';
import {DASHBOARD_LOCALE} from '@/lib/locale';

export const metadata: Metadata = {
  title: 'TRD · Centro di controllo',
  description: 'Stato dei servizi e panoramica del sistema. Modalità simulazione, automazione disattivata.',
  robots: {index: false, follow: false},
};

export default function RootLayout({children}: {children: ReactNode}) {
  return <html lang={DASHBOARD_LOCALE}><body><DashboardTheme>{children}</DashboardTheme></body></html>;
}
