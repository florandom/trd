'use client';

import {useCallback, useEffect, useRef, useState} from 'react';
import type {HealthReadiness} from '@trd/shared-types';
import {getConnectionState, parseReadiness} from '@/lib/readiness';

const POLL_INTERVAL_MS = 10_000;

export function useReadiness() {
  const [data, setData] = useState<HealthReadiness | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [now, setNow] = useState<number | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(false);
  const request = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    const controller = new AbortController();
    request.current = controller;
    const timeout = setTimeout(() => controller.abort(), 4_000);
    if (mounted.current) setIsRefreshing(true);
    try {
      const response = await fetch('/api/status', {
        cache: 'no-store', signal: controller.signal, headers: {Accept: 'application/json'},
      });
      const parsed = parseReadiness(await response.json());
      if (!parsed || (response.status !== 200 && response.status !== 503)) {
        throw new Error('Status unavailable');
      }
      if (mounted.current && request.current === controller) {
        setData(parsed);
        setUnavailable(false);
      }
    } catch {
      if (mounted.current && request.current === controller) setUnavailable(true);
    } finally {
      clearTimeout(timeout);
      if (request.current === controller) {
        request.current = null;
        inFlight.current = false;
        if (mounted.current) {
          setIsRefreshing(false);
          setNow(Date.now());
        }
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const initial = setTimeout(() => void refresh(), 0);
    const poll = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    const clock = setInterval(() => setNow(Date.now()), 1_000);
    return () => {
      mounted.current = false;
      clearTimeout(initial);
      clearInterval(poll);
      clearInterval(clock);
      request.current?.abort();
      request.current = null;
      inFlight.current = false;
    };
  }, [refresh]);

  return {
    data,
    state: getConnectionState(data, unavailable, now ?? 0),
    isRefreshing,
    refresh,
  };
}
