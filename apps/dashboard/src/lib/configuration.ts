// Move the decimal point without binary floating-point arithmetic.
export function shiftDecimal(value: string, shift: number): string {
  if (!/^\d+(\.\d+)?$/.test(value.trim()))
    throw new Error(
      'Inserisci un numero positivo, usando il punto per i decimali.'
    );
  const [integer = '', fraction = ''] = value.trim().split('.');
  const digits = integer + fraction;
  const point = integer.length + shift;
  const moved =
    point <= 0
      ? `0.${'0'.repeat(-point)}${digits}`
      : point >= digits.length
        ? digits + '0'.repeat(point - digits.length)
        : `${digits.slice(0, point)}.${digits.slice(point)}`;
  const [whole = '', decimal = ''] = moved.split('.');
  return (
    (whole.replace(/^0+(?=\d)/, '') || '0') +
    (decimal.replace(/0+$/, '') ? `.${decimal.replace(/0+$/, '')}` : '')
  );
}
export const SETTING_LABELS: Record<string, string> = {
  automation_enabled: 'Automazione',
  live_trading_enabled: 'Trading reale',
  trading_mode: 'Modalità operativa',
  raw_log_retention_days: 'Conservazione dei log grezzi',
  ai_response_retention_days: 'Conservazione delle risposte IA',
  telegram_retention_days: 'Conservazione dei messaggi Telegram',
};
export const AGENT_LABELS: Record<string, string> = {
  SIGNAL_CLASSIFIER: 'Classificazione dei segnali',
  SIGNAL_PARSER: 'Interpretazione dei segnali',
  MARKET_ANALYST: 'Analisi di mercato',
  DECISION_AGENT: 'Valutazione delle decisioni',
  CRITIC: 'Verifica critica',
  POSITION_REVIEW_AGENT: 'Revisione delle posizioni',
};
export const RISK_FIELDS = [
  ['max_risk_per_trade', 'Rischio massimo per operazione (%)', true],
  ['max_daily_loss', 'Perdita giornaliera massima (%)', true],
  ['max_total_open_risk', 'Rischio aperto massimo (%)', true],
  ['max_open_positions', 'Numero massimo di posizioni', false],
  ['max_lots', 'Volume massimo (lotti)', false],
  ['max_effective_leverage', 'Leva effettiva massima', false],
] as const;
export function displaySetting(key: string, value: unknown): string {
  if (key === 'trading_mode')
    return value === 'paper' ? 'Simulazione' : 'Non disponibile';
  if (typeof value === 'boolean') return value ? 'Attivata' : 'Disattivata';
  return `${value} giorni`;
}

export const STATUS: Record<string, string> = {
  RECEIVED: 'Ricevuto',
  CLASSIFIED: 'Classificato',
  PARSED: 'Interpretato',
  ANALYZING: 'In analisi',
  DECIDED: 'Valutato',
  WAITING: 'In attesa',
  ESCALATED: 'Richiede revisione',
  RISK_CHECK: 'Verifica del rischio',
  APPROVED: 'Approvato',
  EXECUTION_REQUESTED: 'Esecuzione richiesta',
  EXECUTED: 'Eseguito',
  IGNORED: 'Ignorato',
  REJECTED_AI: 'Respinto dagli agenti',
  REJECTED_RISK: 'Respinto dal rischio',
  EXPIRED: 'Scaduto',
  FAILED: 'Non riuscito',
  RECONCILING: 'In verifica',
  OUTCOME_UNKNOWN: 'Esito non confermato',
  OPEN: 'Aperta',
  CLOSING: 'In chiusura',
  CLOSED: 'Chiusa',
  UNKNOWN: 'Non confermata',
  HEALTHY: 'Processo presente',
  STARTING: 'In avvio',
  DEGRADED: 'Richiede attenzione',
  STOPPED: 'Arrestato',
  BUY: 'Acquisto',
  SELL: 'Vendita',
  SUCCEEDED: 'Valutazione registrata',
  REFUSED: 'Richiesta rifiutata',
};

export const ANALYSIS_REASONS: Record<string, string> = {
  NO_SIGNAL: 'Nessun segnale riconosciuto',
  UNSUPPORTED_FORMAT: 'Formato non supportato o ambiguo',
  UNSUPPORTED_SYMBOL: 'Strumento non supportato',
  INVALID_PRICES: 'Prezzi o protezioni incoerenti',
  REVIEW_ONLY: 'Risposta, modifica o cancellazione da rivedere',
  STALE_MESSAGE: 'Messaggio troppo vecchio',
  FUTURE_MESSAGE: 'Data del messaggio da verificare',
  EVIDENCE_UNAVAILABLE: 'Contenuto originale non disponibile',
  AGENT_DISABLED: 'Agente richiesto disattivato',
  MODEL_UNAVAILABLE: 'Modello non disponibile o incompatibile',
  PROMPT_UNAVAILABLE: 'Istruzioni non disponibili o non verificate',
  CONFIG_CHANGED: 'Configurazione modificata durante l’analisi',
  BUDGET_EXHAUSTED: 'Limite di spesa raggiunto',
  PROVIDER_DISABLED: 'Fornitore esterno disabilitato',
  PROVIDER_REFUSAL: 'Richiesta rifiutata dal fornitore',
  PROVIDER_TIMEOUT: 'Tempo massimo della richiesta superato',
  PROVIDER_UNAVAILABLE: 'Fornitore non disponibile',
  PROVIDER_RATE_LIMIT: 'Attesa richiesta dal fornitore',
  PROVIDER_QUOTA: 'Credito o quota del fornitore esauriti',
  PROVIDER_INCOMPLETE: 'Risposta incompleta',
  INVALID_OUTPUT: 'Risposta non valida',
  UNKNOWN_USAGE: 'Consumo non confermato e prenotazione conservata',
  MOCK_ONLY: 'Valutazione del simulatore locale',
  NO_MARKET_CONTEXT: 'Dati di mercato verificati non disponibili',
  RISK_NOT_IMPLEMENTED: 'Verifica del rischio ancora da implementare',
  RISK_GATEWAY_UNAVAILABLE: 'Rischio verificato in locale; collegamento all’esecuzione non disponibile',
};
export function analysisReasons(value: unknown): string {
  return Array.isArray(value)
    ? value.map((code) => ANALYSIS_REASONS[String(code)] ?? 'Motivo da verificare').join('; ')
    : 'Motivo non disponibile';
}
