import {proxy} from '@/lib/backend-proxy';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
type Context = {params: Promise<{path: string[]}>};
async function handle(request: Request, context: Context) {
  return proxy(request, (await context.params).path.join('/'));
}
export const GET = handle;
export const POST = handle;
