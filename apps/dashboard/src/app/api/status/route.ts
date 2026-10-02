import {proxyReadiness} from '@/lib/readiness-proxy';

export const dynamic = 'force-dynamic';

export async function GET() {
  return proxyReadiness(process.env.API_INTERNAL_URL ?? 'http://127.0.0.1:8000');
}
