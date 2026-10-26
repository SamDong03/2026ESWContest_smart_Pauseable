

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
import re

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

RENDER_URL = 'https://pauseable-api.onrender.com'
MAX_REQUEST_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class LocalRenderSettings:
    patient_id: str
    upstream_token: str = field(repr=False)
    local_token: str = field(repr=False)
    port: int = 18108

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.patient_id):
            raise ValueError('Invalid patient ID')
        if not 1024 <= self.port <= 65535:
            raise ValueError('Use an unprivileged local port')
        for token in (self.upstream_token, self.local_token):
            if not token or any(character.isspace() for character in token):
                raise ValueError('A valid app credential is required')
        if secrets.compare_digest(self.upstream_token, self.local_token):
            raise ValueError('Local and Render credentials must be different')

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.port}'


def _local_request(connection, settings):
    return (
        connection.client is not None
        and connection.client.host in {'127.0.0.1', '::1'}
        and connection.headers.get('host') == f'127.0.0.1:{settings.port}'
        and connection.headers.get('origin', settings.origin) == settings.origin
        and connection.headers.get('sec-fetch-site') != 'cross-site'
    )


def _allowed_api(path, method, patient_id):
    if any(part in {'.', '..'} for part in path.split('/')) or '\\' in path:
        return False
    if re.fullmatch(rf'api/patients/{re.escape(patient_id)}/[A-Za-z0-9_/-]+', path):
        return method in {'GET', 'POST', 'PUT', 'DELETE'}
    if path == 'api/guardians/me/preferences':
        return method in {'GET', 'PUT'}
    if re.fullmatch(r'api/alerts/[A-Za-z0-9_-]+/(pause|resume)', path):
        return method == 'POST'
    if re.fullmatch(r'api/door-events(?:/[A-Za-z0-9_.:-]{1,96}(?:/(image|confirm))?)?', path):
        return method == 'GET' or (method == 'POST' and path.endswith('/confirm'))
    return (path in {'api/voice-training/clips', 'api/voice-messages'} and method == 'POST')


def create_local_render_proxy(
    settings: LocalRenderSettings,
    web_directory: Path,
    *,
    transport=None,
    websocket_connector=connect,
):
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            base_url=RENDER_URL,
            timeout=httpx.Timeout(90, connect=15),
            follow_redirects=False,
            transport=transport,
        ) as client:
            app.state.upstream = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def protect_loopback(request: Request, call_next):
        if not _local_request(request, settings):
            return JSONResponse({'detail': 'Local same-origin access only'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/local-render-status')
    def local_status():
        return {'mode': 'render-proxy', 'upstream': RENDER_URL}

    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
    async def proxy_api(path: str, request: Request):
        credentials = request.headers.get('authorization', '')
        if not secrets.compare_digest(credentials, f'Bearer {settings.local_token}'):
            raise HTTPException(401, 'Local preview session is required')
        full_path = f'api/{path}'
        if not _allowed_api(full_path, request.method, settings.patient_id):
            raise HTTPException(403, 'This route is not available in the Render preview')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_REQUEST_BYTES:
                raise HTTPException(413, 'Upload exceeds the local preview limit')
        headers = {'Authorization': f'Bearer {settings.upstream_token}'}
        for name in ('content-type', 'accept', 'range', 'if-none-match'):
            if name in request.headers:
                headers[name] = request.headers[name]
        try:
            upstream = await request.app.state.upstream.request(
                request.method, f'/{full_path}',
                params=request.query_params.multi_items(),
                headers=headers, content=bytes(body),
            )
        except httpx.HTTPError:
            raise HTTPException(502, 'Could not reach Render; retry shortly') from None
        if upstream.is_redirect:
            raise HTTPException(502, 'Render redirects are not followed')
        return Response(
            upstream.content, status_code=upstream.status_code,
            headers={name: upstream.headers[name] for name in
                     ('content-type', 'etag', 'content-range', 'accept-ranges')
                     if name in upstream.headers},
        )

    @app.websocket('/ws/alerts')
    async def proxy_alerts(websocket: WebSocket):
        if (
            not _local_request(websocket, settings)
            or websocket.query_params.get('patient_id') != settings.patient_id
            or set(websocket.query_params) != {'patient_id', 'ticket'}
            or not re.fullmatch(r'[A-Za-z0-9_-]{20,128}', websocket.query_params.get('ticket', ''))
        ):
            await websocket.close(code=4403)
            return
        url = httpx.URL(f'{RENDER_URL}/ws/alerts', params=websocket.query_params.multi_items())
        tasks = []
        try:
            async with websocket_connector(
                str(url).replace('https://', 'wss://', 1), open_timeout=30,
                max_size=1024 * 1024, close_timeout=5,
            ) as upstream:
                await websocket.accept()

                async def to_browser():
                    async for message in upstream:
                        if isinstance(message, str):
                            await websocket.send_text(message)
                        else:
                            await websocket.send_bytes(message)

                async def to_render():
                    while True:
                        message = await websocket.receive()
                        if message['type'] == 'websocket.disconnect':
                            return
                        if message.get('text') is not None:
                            await upstream.send(message['text'])
                        elif message.get('bytes') is not None:
                            await upstream.send(message['bytes'])

                tasks = [asyncio.create_task(to_browser()), asyncio.create_task(to_render())]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (OSError, TimeoutError, WebSocketException, WebSocketDisconnect):
            pass
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=1012)

    app.mount('/', StaticFiles(directory=web_directory, html=True), name='flutter-web')
    return app
