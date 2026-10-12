import 'server-only';
import {cookies} from 'next/headers';
import {redirect} from 'next/navigation';
import {backendOrigin} from './backend-proxy';
import type {SessionUser} from './dashboard-api';

export async function requireSession(): Promise<SessionUser> {
  const token = (await cookies()).get('trd_session')?.value;
  if (!token || !/^[A-Za-z0-9_-]{43}$/.test(token)) redirect('/login');
  let response: Response;
  try {
    response = await fetch(`${backendOrigin()}/auth/me`, {
      headers: {cookie: `trd_session=${token}`},
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.timeout(6000),
    });
  } catch {
    redirect('/login?unavailable=1');
  }
  if (response.status === 401) redirect('/login');
  if (!response.ok) redirect('/login?unavailable=1');
  return response.json();
}
