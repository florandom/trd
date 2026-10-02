import type {Metadata} from 'next';
import type {ReactNode} from 'react';
import '@stylexswc/webpack-plugin/stylex.css';
import './globals.css';
import {DashboardTheme} from '@/components/dashboard-theme';

export const metadata: Metadata = {
  title: 'TRD · Operational foundation',
  description: 'Read-only system readiness. Paper mode. Automation disabled.',
  robots: {index: false, follow: false},
};

export default function RootLayout({children}: {children: ReactNode}) {
  return <html lang="en"><body><DashboardTheme>{children}</DashboardTheme></body></html>;
}
