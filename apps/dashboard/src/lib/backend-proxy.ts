// Fixed, allowlisted dashboard transport. Never relay arbitrary hosts, redirects or headers.
export function allowedRoute(path: string, method: string): boolean {
  if (method === 'GET')
    return /^(auth\/(csrf|me)|ops\/(settings|agents|risk|models|audit|status|positions|orders|signals|sources|costs|telegram-messages)(\/\b[0-9a-f-]{36})?)$/.test(
      path
    );
  return (
    method === 'POST' &&
    /^(auth\/(login|logout)|config\/(confirm|apply))$/.test(path)
  );
}

export function backendOrigin(value = process.env.API_INTERNAL_URL): string {
  if (!value) throw new Error('Backend unavailable');
  const url = new URL(value);
  if (
    !['http:', 'https:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  )
    throw new Error('Backend unavailable');
  return url.origin;
}

export async function boundedBody(request: Request): Promise<string> {
  const reader = request.body?.getReader();
  if (!reader) return '';
  const chunks: Uint8Array[] = [];
  let length = 0;
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    length += value.length;
    if (length > 16_384) {
      await reader.cancel();
      throw new Error('Request too large');
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return new TextDecoder('utf-8', {fatal: true}).decode(bytes);
}

export async function proxy(request: Request, path: string): Promise<Response> {
  if (!allowedRoute(path, request.method))
    return Response.json({detail: 'NOT_FOUND'}, {status: 404});
  const headers = new Headers({'Content-Type': 'application/json'});
  const cookie = request.headers.get('cookie');
  if (cookie) {
    const selected = cookie
      .split(';')
      .map((value) => value.trim())
      .filter((value) => /^trd_(session|login)=[A-Za-z0-9_-]{43}$/.test(value));
    if (selected.length) headers.set('cookie', selected.join('; '));
  }
  for (const key of ['origin', 'x-csrf-token']) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  let body: string | undefined;
  try {
    if (request.method === 'POST') body = await boundedBody(request);
  } catch {
    return Response.json({detail: 'INVALID_REQUEST'}, {status: 413});
  }
  try {
    const incoming = new URL(request.url);
    const query = new URLSearchParams();
    for (const key of ['offset', 'limit'])
      if (incoming.searchParams.has(key))
        query.set(key, incoming.searchParams.get(key)!);
    const upstream = await fetch(`${backendOrigin()}/${path}?${query}`, {
      method: request.method,
      headers,
      ...(body === undefined ? {} : {body}),
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.timeout(6000),
    });
    const resultHeaders = new Headers({
      'Cache-Control': 'no-store',
      'Content-Type': 'application/json',
    });
    for (const cookie of upstream.headers.getSetCookie()) {
      if (/^trd_(session|login)=/.test(cookie))
        resultHeaders.append('Set-Cookie', cookie);
    }
    const retry = upstream.headers.get('retry-after');
    if (retry && /^\d{1,3}$/.test(retry))
      resultHeaders.set('Retry-After', retry);
    // Only our own API can be addressed; driver errors are redacted at its boundary.
    return new Response(
      upstream.status === 204 ? null : await upstream.text(),
      {status: upstream.status, headers: resultHeaders}
    );
  } catch {
    return Response.json(
      {detail: 'SERVICE_UNAVAILABLE'},
      {status: 503, headers: {'Cache-Control': 'no-store'}}
    );
  }
}
