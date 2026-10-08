import type {Overrides} from '@astryxdesign/core/i18n';

export const DASHBOARD_LOCALE = 'it-IT';

const dateTime = new Intl.DateTimeFormat(DASHBOARD_LOCALE, {
  timeZone: 'Europe/Rome',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  timeZoneName: 'short',
});

export function formatCheckedAt(timestamp: string): string {
  return dateTime.format(new Date(timestamp));
}

// Astryx 0.6.4 ships English only. Translate the controls used by this shell,
// including the mobile drawer and labels announced by assistive technology.
export const astryxItalianOverrides = {
  it: {
    '@astryx.appShell.mobileNavigation': 'Navigazione mobile',
    '@astryx.appShell.skipToContent': 'Vai al contenuto',
    '@astryx.sideNav.label': 'Menu principale',
    '@astryx.sideNav.resizeSidebar': 'Ridimensiona il menu laterale',
    '@astryx.sideNav.heading.openMenu': 'Apri il menu',
    '@astryx.sideNav.heading.dialogLabel': 'Menu di navigazione',
    '@astryx.sideNavCollapseButton.expandSidebar': 'Espandi il menu laterale',
    '@astryx.sideNavCollapseButton.collapseSidebar': 'Riduci il menu laterale',
    '@astryx.sideNavItem.expand': 'Espandi {label}',
    '@astryx.sideNavItem.collapse': 'Riduci {label}',
    '@astryx.sideNavItem.submenuLabel': 'Sottomenu di {label}',
    '@astryx.mobileNav.toggle.open': 'Apri il menu di navigazione',
    '@astryx.mobileNav.closeNavigation': 'Chiudi il menu di navigazione',
    '@astryx.mobileNav.navigation': 'Menu di navigazione',
    '@astryx.resizable.handle.label': 'Controllo di ridimensionamento',
    '@astryx.resizable.collapsed': 'Ridotto',
    '@astryx.banner.dismiss': 'Chiudi',
    '@astryx.banner.dismissTitled': '{dismiss}: {title}',
    '@astryx.banner.collapse': 'Riduci',
    '@astryx.banner.expand': 'Espandi',
    '@astryx.button.loading': 'Caricamento in corso',
    '@astryx.spinner.loading': 'Caricamento in corso',
    '@astryx.dialog.close': 'Chiudi',
    '@astryx.field.required': 'Obbligatorio',
    '@astryx.field.optional': 'Facoltativo',
    '@astryx.textInput.clearLabel': 'Cancella {label}',
    '@astryx.selector.placeholder': 'Scegli un’opzione',
    '@astryx.selector.searchPlaceholder': 'Cerca…',
    '@astryx.selector.empty': 'Nessuna opzione',
    '@astryx.selector.emptySearchResults': 'Nessun risultato',
    '@astryx.selector.searchOptions': 'Cerca opzioni',
    '@astryx.selector.clearLabel': 'Cancella {label}',
    '@astryx.selector.resultCount': '{count} risultati',
    '@astryx.table.label': 'Tabella',
    '@astryx.table.noData': 'Nessun dato disponibile',
  },
} satisfies Overrides;
