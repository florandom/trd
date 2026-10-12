"""Private loopback paper routes. Absent when the explicit local gate is off."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from backend.domain.bridge import PATHS, ProtocolError


def bridge_router(gateway):
    router = APIRouter()

    async def exchange(request: Request):
        # Fixed literal paths and methods; never authenticate an alternate URL spelling.
        if (
            request.scope.get("raw_path") != request.url.path.encode("ascii")
            or request.url.query
            or request.headers.get("content-type") != "application/json"
            or "content-encoding" in request.headers
            or request.client is None
            or request.client.host not in {"127.0.0.1", "::1", "testclient"}
        ):
            return JSONResponse({"detail": "INVALID_TRANSPORT"}, status_code=400)
        raw_headers = request.scope["headers"]
        names = [name.lower() for name, _ in raw_headers if name.lower().startswith(b"x-trd-")]
        if (
            len(names) != len(set(names))
            or sum(name.lower() == b"content-type" for name, _ in raw_headers) != 1
        ):
            return JSONResponse({"detail": "AUTHENTICATION_FAILED"}, status_code=401)
        body = await request.body()
        try:
            status, result, headers = await asyncio.to_thread(
                gateway.handle, dict(request.headers), request.url.path, body
            )
        except ProtocolError:
            return JSONResponse(
                {"detail": "AUTHENTICATION_FAILED"},
                status_code=401,
                headers={"cache-control": "no-store"},
            )
        except Exception:
            # Unavailable database or signer means no response capable of authorizing a send.
            return JSONResponse(
                {"detail": "BRIDGE_UNAVAILABLE"},
                status_code=503,
                headers={"cache-control": "no-store"},
            )
        return Response(result, status_code=status, headers=headers)

    for path in sorted(PATHS):
        router.add_api_route(path, exchange, methods=["POST"], include_in_schema=False)
    return router
