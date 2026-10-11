export type DashboardThemeMode = 'light' | 'dark';

export const DASHBOARD_THEME_COOKIE = 'trd-dashboard-theme';

export function parseDashboardTheme(value: string | undefined): DashboardThemeMode {
  return value === 'light' ? 'light' : 'dark';
}
