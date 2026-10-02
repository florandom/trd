import type {HealthReadiness} from '@trd/shared-types';

export const STATUS_STALE_AFTER_MS = 30_000;
const FUTURE_CLOCK_TOLERANCE_MS = 5_000;
const UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/;

/** Reject unsupported modes and strip all non-public fields at the boundary. */
export function parseReadiness(value: unknown): HealthReadiness | null {
  if (typeof value !== 'object' || value === null) return null;
  const data = value as Record<string, unknown>;
  if (
    (data.status !== 'ready' && data.status !== 'not_ready') ||
    data.service !== 'api' || data.phase !== 1 || data.mode !== 'paper' ||
    data.automation_enabled !== false || typeof data.checked_at !== 'string' ||
    !UTC_TIMESTAMP.test(data.checked_at) || !Number.isFinite(Date.parse(data.checked_at))
  ) return null;

  return {
    status: data.status,
    service: 'api',
    phase: 1,
    mode: 'paper',
    automation_enabled: false,
    checked_at: data.checked_at,
  };
}

export function isReadinessStale(data: HealthReadiness, now: number): boolean {
  const age = now - Date.parse(data.checked_at);
  return age > STATUS_STALE_AFTER_MS || age < -FUTURE_CLOCK_TOLERANCE_MS;
}

export type ConnectionState = 'loading' | 'ready' | 'not_ready' | 'stale' | 'offline';

export function getConnectionState(
  data: HealthReadiness | null,
  unavailable: boolean,
  now: number,
): ConnectionState {
  if (unavailable) return 'offline';
  if (!data) return 'loading';
  if (isReadinessStale(data, now)) return 'stale';
  return data.status;
}
