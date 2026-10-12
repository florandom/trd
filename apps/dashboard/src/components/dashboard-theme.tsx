'use client';

import {createContext, useContext, useState, type ReactNode} from 'react';
import {Button} from '@astryxdesign/core/Button';
import {Icon} from '@astryxdesign/core/Icon';
import {MoonIcon, SunIcon} from '@heroicons/react/24/outline';
import {Theme} from '@astryxdesign/core/theme';
import {InternationalizationProvider} from '@astryxdesign/core/i18n';
import {neutralTheme} from '@astryxdesign/theme-neutral/built';
import {astryxItalianOverrides, DASHBOARD_LOCALE} from '@/lib/locale';
import {DASHBOARD_THEME_COOKIE, type DashboardThemeMode} from '@/lib/theme';

const DashboardThemeContext = createContext<{
  mode: DashboardThemeMode;
  toggle: () => void;
} | null>(null);

export function DashboardTheme({children, initialMode}: {
  children: ReactNode;
  initialMode: DashboardThemeMode;
}) {
  const [mode, setMode] = useState(initialMode);
  function toggle() {
    const nextMode = mode === 'dark' ? 'light' : 'dark';
    setMode(nextMode);
    // This cookie contains only the display preference, shared with SSR.
    document.cookie = `${DASHBOARD_THEME_COOKIE}=${nextMode}; Path=/; Max-Age=31536000; SameSite=Lax${window.location.protocol === 'https:' ? '; Secure' : ''}`;
  }
  return (
    <InternationalizationProvider locale={DASHBOARD_LOCALE} overrides={astryxItalianOverrides}>
      <DashboardThemeContext value={{mode, toggle}}>
        <Theme theme={neutralTheme} mode={mode}>{children}</Theme>
      </DashboardThemeContext>
    </InternationalizationProvider>
  );
}

export function DashboardThemeToggle() {
  const theme = useContext(DashboardThemeContext);
  if (!theme) throw new Error('Tema della dashboard non disponibile');
  return (
    <Button
      label={theme.mode === 'dark' ? 'Passa al tema chiaro' : 'Passa al tema scuro'}
      icon={<Icon icon={theme.mode === 'dark' ? SunIcon : MoonIcon} />}
      variant="secondary"
      size="sm"
      onClick={theme.toggle}
    />
  );
}
