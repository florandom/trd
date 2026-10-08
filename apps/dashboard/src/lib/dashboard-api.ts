import type {components} from '@trd/shared-types';

export type SessionUser = components['schemas']['SessionUser'];
export type Change = components['schemas']['Change'];
export type Confirmation = components['schemas']['Confirmation'];
export type Snapshot = components['schemas']['OperationalRows'];
export type Row = Snapshot['rows'][number];

const ERRORS: Record<string, string> = {
  INVALID_CREDENTIALS: 'Email o password non corretti.',
  LOGIN_THROTTLED: 'Troppi tentativi. Attendi qualche minuto e riprova.',
  AUTH_REQUIRED: 'La sessione è terminata. Accedi di nuovo.',
  ADMIN_REQUIRED: 'Questa modifica richiede un amministratore.',
  CSRF_REJECTED: 'La conferma è scaduta. Aggiorna la pagina e riprova.',
  ORIGIN_REJECTED:
    'L’indirizzo di accesso non corrisponde a quello configurato.',
  VERSION_CONFLICT:
    'La configurazione è stata modificata. Aggiorna i dati prima di riprovare.',
  INVALID_CONFIGURATION:
    'Valori non consentiti o conferma scaduta. Verifica i limiti e aggiorna i dati.',
  INVALID_REQUEST: 'Controlla i dati inseriti.',
  TRADING_UNAVAILABLE: 'Le funzioni di trading non sono ancora disponibili.',
};

export async function api<T>(
  path: string,
  options: {body?: unknown; csrf?: string} = {}
): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    method: options.body === undefined ? 'GET' : 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      ...(options.csrf ? {'X-CSRF-Token': options.csrf} : {}),
    },
    ...(options.body === undefined ? {} : {body: JSON.stringify(options.body)}),
    signal: AbortSignal.timeout(10_000),
  }).catch(() => {
    throw new Error('Servizio non disponibile. Riprova tra poco.');
  });
  if (!response.ok) {
    if (response.status === 401 && !['auth/login', 'auth/csrf'].includes(path))
      window.dispatchEvent(new Event('trd-session-expired'));
    const value = await response.json().catch(() => ({}));
    throw new Error(
      ERRORS[value.detail] || 'Servizio non disponibile. Riprova tra poco.'
    );
  }
  return response.status === 204
    ? (undefined as T)
    : response.json().catch(() => {
        throw new Error('Risposta non disponibile. Aggiorna la pagina.');
      });
}
