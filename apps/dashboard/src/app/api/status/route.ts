import {proxyReadiness} from '@/lib/readiness-proxy';
import {deployment, transportHeaders, RemoteAccessRequired} from '@/lib/deployment';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: Request) {
  try {
    const config = deployment();
    return proxyReadiness(config.backendOrigin, fetch,
      {headers: transportHeaders(request, config), config});
  } catch (error) {
    return Response.json({error: 'status_unavailable'},
      {status: error instanceof RemoteAccessRequired ? 401 : 503,
        headers: {'Cache-Control': 'no-store'}});
  }
}
