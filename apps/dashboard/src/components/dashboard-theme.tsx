'use client';

import type {ReactNode} from 'react';
import {Theme} from '@astryxdesign/core/theme';
import {InternationalizationProvider} from '@astryxdesign/core/i18n';
import {neutralTheme} from '@astryxdesign/theme-neutral/built';
import {astryxItalianOverrides, DASHBOARD_LOCALE} from '@/lib/locale';

export function DashboardTheme({children}: {children: ReactNode}) {
  return (
    <InternationalizationProvider locale={DASHBOARD_LOCALE} overrides={astryxItalianOverrides}>
      <Theme theme={neutralTheme} mode="dark">{children}</Theme>
    </InternationalizationProvider>
  );
}
