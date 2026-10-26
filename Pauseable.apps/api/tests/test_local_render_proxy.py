import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.local_render_proxy import (
    LocalRenderSettings, MAX_REQUEST_BYTES, RENDER_URL, create_local_render_proxy,
)


class LocalRenderProxyTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.web = Path(directory.name)
        (self.web / 'index.html').write_text('<html>Flutter preview</html>', encoding='utf-8')
        self.settings = LocalRenderSettings('byunwoojin', 'render-private-test', 'local-only-test')
        self.requests = []

        def upstream(request):
            self.requests.append(request)
            if request.url.path.endswith('/redirect'):
                return httpx.Response(307, headers={'location': 'https://elsewhere.test/'})
            if request.url.path.endswith('/auth-failure'):
                return httpx.Response(401, json={'detail': 'Bearer token is required'})
            return httpx.Response(200, json={'from': 'Render'})

        self.transport = httpx.MockTransport(upstream)

    def client(self, **kwargs):
        app = create_local_render_proxy(self.settings, self.web, transport=self.transport, **kwargs)
        return TestClient(app, base_url=self.settings.origin, client=('127.0.0.1', 50123))

    @property
    def headers(self):
        return {'Authorization': 'Bearer local-only-test', 'Origin': self.settings.origin}

    def test_json_and_multipart_use_real_render_auth_only_on_upstream(self):
        with self.client() as client:
            url = '/api/patients/byunwoojin/home-environment'
            response = client.put(url, headers=self.headers, json={'region_code': '1111051500'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.requests[0].url.host, 'pauseable-api.onrender.com')
            self.assertEqual(self.requests[0].headers['authorization'], 'Bearer render-private-test')
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertNotIn('render-private-test', response.text)
            upload = client.post('/api/voice-training/clips', headers=self.headers,
                files={'file': ('S001.wav', b'RIFF-test-WAVE', 'audio/wav')},
                data={'patient_id': 'byunwoojin'})
            self.assertEqual(upload.status_code, 200)
            self.assertIn(b'RIFF-test-WAVE', self.requests[1].content)
            self.assertIn('multipart/form-data', self.requests[1].headers['content-type'])

    def test_local_session_and_same_origin_are_required(self):
        with self.client() as client:
            url = '/api/patients/byunwoojin/home-environment'
            self.assertEqual(client.get(url).status_code, 401)
            self.assertEqual(client.get(url, headers={
                **self.headers, 'Origin': 'https://malicious.test',
            }).status_code, 403)
            self.assertEqual(client.get(url, headers={
                **self.headers, 'Host': 'rebind.malicious.test',
            }).status_code, 403)
            self.assertEqual(client.get(url, headers={
                **self.headers, 'Sec-Fetch-Site': 'cross-site',
            }).status_code, 403)
            self.assertEqual(self.requests, [])

    def test_consent_receipts_use_the_same_private_patient_proxy(self):
        with self.client() as client:
            url = '/api/patients/byunwoojin/voice-training/consents'
            body = {'request_id': 'a' * 32, 'accepted': True, 'policy_version': '2026-10-24'}
            self.assertEqual(client.post(url, headers=self.headers, json=body).status_code, 200)
            self.assertEqual(client.get(url + '/voice-consent-' + 'a' * 32, headers=self.headers).status_code, 200)
            for request in self.requests:
                self.assertEqual(request.headers['authorization'], 'Bearer render-private-test')
                self.assertNotIn('render-private-test', str(request.url))

    def test_other_patient_device_events_and_demo_writes_are_blocked(self):
        with self.client() as client:
            for path in (
                '/api/patients/other/home-environment', '/api/events/decisions',
                '/api/events/ha', '/api/devices/pi5/door-events', '/api/demo/scenarios/wandering',
            ):
                self.assertEqual(client.post(path, headers=self.headers).status_code, 403)
            self.assertEqual(self.requests, [])

    def test_photos_alert_controls_and_status_stay_available_without_exposing_token(self):
        with self.client() as client:
            for method, path in (
                ('get', '/api/door-events/door-123'),
                ('get', '/api/door-events/door-123/image'),
                ('get', '/api/door-events/camera.20261023:001/image'),
                ('post', '/api/door-events/door-123/confirm'),
                ('post', '/api/alerts/alert-123/pause'),
            ):
                self.assertEqual(getattr(client, method)(path, headers=self.headers).status_code, 200)
            self.assertEqual(client.get('/').status_code, 200)
            status = client.get('/local-render-status')
            self.assertEqual(status.json(), {'mode': 'render-proxy', 'upstream': RENDER_URL})
            self.assertNotIn(self.settings.upstream_token, status.text)
            self.assertNotIn(self.settings.upstream_token, repr(self.settings))

    def test_redirects_and_authentication_failures_are_not_success(self):
        with self.client() as client:
            base = '/api/patients/byunwoojin/'
            self.assertEqual(client.get(base + 'redirect', headers=self.headers).status_code, 502)
            self.assertEqual(client.get(base + 'auth-failure', headers=self.headers).status_code, 401)
            response = client.post('/api/voice-training/clips', headers=self.headers,
                                   content=b'x' * (MAX_REQUEST_BYTES + 1))
            self.assertEqual(response.status_code, 413)
            self.assertEqual(len(self.requests), 2)

    def test_websocket_forwards_ready_and_live_alerts_without_app_token_in_url(self):
        captured = []

        class FakeSocket:
            def __aiter__(self):
                return self.messages()

            async def messages(self):
                yield '{"type":"ready"}'
                yield '{"type":"app_alert","data":{"id":"alert-123"}}'
                await asyncio.Future()

        @asynccontextmanager
        async def connector(url, **kwargs):
            captured.append(url)
            yield FakeSocket()

        with self.client(websocket_connector=connector) as client:
            path = '/ws/alerts?patient_id=byunwoojin&ticket=' + 'a' * 32
            ws_headers = {'Origin': self.settings.origin, 'Host': '127.0.0.1:18108'}
            with client.websocket_connect(path, headers=ws_headers) as socket:
                self.assertEqual(socket.receive_json()['type'], 'ready')
                self.assertEqual(socket.receive_json()['data']['id'], 'alert-123')
            self.assertTrue(captured[0].startswith('wss://pauseable-api.onrender.com/ws/alerts?'))
            self.assertNotIn(self.settings.upstream_token, captured[0])
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect(path, headers={
                    **ws_headers, 'Origin': 'https://malicious.test',
                }):
                    pass


if __name__ == '__main__':
    unittest.main()
