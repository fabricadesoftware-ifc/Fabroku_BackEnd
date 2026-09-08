import asyncio
import json

import httpx
import pytest
from asgiref.sync import async_to_sync

from config.asgi import application
from tests.factories.models import AppFactory, CLITokenFactory, ProjectFactory, UserFactory

MCP_HEADERS = {
    'content-type': 'application/json',
    'accept': 'application/json, text/event-stream',
}


class LifespanManager:
    """Drives the ASGI lifespan protocol Daphne runs in production, so tests hit the
    same `mcp.session_manager.run()` startup that makes the MCP endpoint work."""

    def __init__(self, app):
        self._app = app
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self._startup_complete = asyncio.Event()
        self._shutdown_complete = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def _receive(self):
        return await self._receive_queue.get()

    async def _send(self, message):
        if message['type'] == 'lifespan.startup.complete':
            self._startup_complete.set()
        elif message['type'] == 'lifespan.shutdown.complete':
            self._shutdown_complete.set()

    async def __aenter__(self):
        self._task = asyncio.create_task(self._app({'type': 'lifespan'}, self._receive, self._send))
        await self._receive_queue.put({'type': 'lifespan.startup'})
        await self._startup_complete.wait()
        return self

    async def __aexit__(self, *exc_info):
        await self._receive_queue.put({'type': 'lifespan.shutdown'})
        await self._shutdown_complete.wait()
        await self._task


def _initialize_payload() -> dict:
    return {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'initialize',
        'params': {
            'protocolVersion': '2025-06-18',
            'capabilities': {},
            'clientInfo': {'name': 'fabroku-test', 'version': '0'},
        },
    }


def _parse_response_json(response: httpx.Response) -> dict:
    """Streamable HTTP replies as SSE (`event: message\ndata: {...}`) or plain JSON."""
    if response.headers.get('content-type', '').startswith('text/event-stream'):
        for line in response.text.splitlines():
            if line.startswith('data:'):
                return json.loads(line[len('data:'):].strip())
        raise AssertionError(f'no data: line in SSE body: {response.text!r}')
    return response.json()


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_mcp_rejects_invalid_token():
    async def run():
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post(
                '/api/mcp/not-a-real-token/', json=_initialize_payload(), headers=MCP_HEADERS,
            )
            assert response.status_code == 401  # noqa: PLR2004

    async_to_sync(run)()


async def _initialize_session(client: httpx.AsyncClient, token: str) -> dict:
    """Runs the MCP initialize handshake and returns headers to reuse for later calls."""
    init_response = await client.post(f'/api/mcp/{token}/', json=_initialize_payload(), headers=MCP_HEADERS)
    assert init_response.status_code == 200, init_response.text  # noqa: PLR2004
    init_body = _parse_response_json(init_response)
    assert init_body['result']['serverInfo']['name'] == 'Fabroku'

    session_headers = dict(MCP_HEADERS)
    if 'mcp-session-id' in init_response.headers:
        session_headers['mcp-session-id'] = init_response.headers['mcp-session-id']

    await client.post(
        f'/api/mcp/{token}/',
        json={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        headers=session_headers,
    )
    return session_headers


async def _call_tool(client: httpx.AsyncClient, token: str, headers: dict, name: str, arguments: dict) -> dict:
    response = await client.post(
        f'/api/mcp/{token}/',
        json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}},
        headers=headers,
    )
    assert response.status_code == 200, response.text  # noqa: PLR2004
    return _parse_response_json(response)['result']


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_mcp_full_flow_and_cross_user_isolation():
    # `mcp.session_manager.run()` can only be entered once per process (see LifespanManager
    # docstring), so every scenario that needs a live MCP session shares this one test.
    user = UserFactory()
    project = ProjectFactory(users=[user])
    my_app = AppFactory(project=project, name='meu-app', status='RUNNING', domain='meu-app.example.com')
    token = CLITokenFactory(user=user).token

    outsider = UserFactory()
    ProjectFactory(users=[outsider])
    outsider_token = CLITokenFactory(user=outsider).token

    async def run():
        transport = httpx.ASGITransport(app=application)
        base_url = 'http://localhost:8000'
        async with LifespanManager(application), httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            session_headers = await _initialize_session(client, token)

            list_tools_response = await client.post(
                f'/api/mcp/{token}/',
                json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
                headers=session_headers,
            )
            assert list_tools_response.status_code == 200, list_tools_response.text  # noqa: PLR2004
            tool_names = {t['name'] for t in _parse_response_json(list_tools_response)['result']['tools']}
            assert {'list_apps', 'get_app_status', 'get_app_processes', 'get_runtime_logs'} <= tool_names

            result = await _call_tool(client, token, session_headers, 'list_apps', {})
            assert result['isError'] is False
            apps = result['structuredContent']['result']
            assert apps == [{
                'id': my_app.id,
                'name': 'meu-app',
                'status': 'RUNNING',
                'domain': 'meu-app.example.com',
                'branch': 'main',
                'project': project.name,
            }]

            outsider_headers = await _initialize_session(client, outsider_token)
            denied = await _call_tool(
                client, outsider_token, outsider_headers, 'get_app_status', {'app_id': my_app.id},
            )
            assert denied['isError'] is True
            assert 'não pertence ao usuário' in denied['content'][0]['text']

    async_to_sync(run)()
