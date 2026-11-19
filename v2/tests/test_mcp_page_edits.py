"""Exercise MCP -> PageManager -> synthetic Meta with disposable SQLite stores.

The gateway tests cover authentication of the trusted worker headers separately.
These fixtures never load server.env or connect to an operational database/Meta.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'meta-page-manager/backend'))

from page_manager.graph import GraphError, GraphMutationUncertain
from page_manager.inputs import ConnectionInput
from page_manager.service import PageManager


class EditGraph:
    def __init__(self, page_id):
        self.page_id = page_id
        self.calls = []
        self.mutations = []
        self.error = None
        self.wrong_identity = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def page_token(self, token, page_id):
        self.calls.append('page_token')
        assert page_id == self.page_id
        return 'SyntheticPageTokenForMCP'

    async def identity(self, token):
        self.calls.append('identity')
        return {'id': '999' if self.wrong_identity else self.page_id}

    async def edit_details(self, token, page_id):
        self.calls.append('read')
        return {'id': page_id, 'bio': 'Existing bio', 'website': 'https://example.test',
                'is_always_open': False, 'category_list': []}, []

    async def update_page(self, token, page_id, fields):
        self.calls.append('update')
        assert token == 'SyntheticPageTokenForMCP' and page_id == self.page_id
        self.mutations.append(deepcopy(fields))
        if self.error:
            raise self.error
        return True


@pytest.fixture
def edit_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv('PM_NATIVE_RUNTIME', '1')
    monkeypatch.setenv('PM_DEV_READ_ONLY', '0')
    from fastapi import FastAPI
    from worker.mcp import install

    workspaces = {}
    graphs = {}
    for owner, page_id in (('first', '555'), ('second', '777')):
        graph = EditGraph(page_id)
        manager = PageManager(tmp_path / owner, graph_factory=lambda graph=graph: graph)
        connection = manager.save_connection(ConnectionInput(
            label='Synthetic source', token_type='system_user', token='SyntheticSystemTokenForMCP'))
        manager.store.sync(connection['id'], manager.store.connection(connection['id'])['token_revision'],
                           [{'id': page_id, 'name': 'Synthetic Page', 'sources': ['assigned_pages']}],
                           True, 'working', None, {'id': '123'})
        workspaces[owner] = SimpleNamespace(manager=manager)
        graphs[owner] = graph

    async def unrelated(*_):
        raise AssertionError('Page edit must not invoke Reel operations')

    app = FastAPI()
    install(app, lambda request: workspaces[request.headers.get('x-pm-workspace', 'first')],
            unrelated, unrelated)
    return SimpleNamespace(app=app, workspaces=workspaces, graphs=graphs)


async def rpc(fixture, method, params=None, *, capability='write', owner='first'):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fixture.app), base_url='http://fixture') as client:
        response = await client.post('/mcp', headers={'x-pm-capability': capability, 'x-pm-workspace': owner},
                                     json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        assert response.status_code == 200
        return response.json()


async def call(fixture, name, arguments, **headers):
    return await rpc(fixture, 'tools/call', {'name': name, 'arguments': arguments}, **headers)


def change(**fields):
    return {'page_id': '555', 'connection_id': 1, 'request_id': str(uuid4()), **fields}


def content(envelope):
    return json.loads(envelope['result']['content'][0]['text'])


async def test_edit_schema_and_reader_capability_match_the_real_edit_fields(edit_mcp):
    tools = (await rpc(edit_mcp, 'tools/list'))['result']['tools']
    edit = next(tool for tool in tools if tool['name'] == 'pages_edit')
    schema = edit['inputSchema']
    assert {'page_id', 'connection_id', 'request_id'} <= set(schema['required'])
    assert {'bio', 'location', 'category_ids', 'website', 'is_always_open'} <= set(schema['properties'])
    assert schema['additionalProperties'] is False
    assert edit['annotations']['readOnlyHint'] is False and edit['annotations']['idempotentHint'] is True
    readers = (await rpc(edit_mcp, 'tools/list', capability='read'))['result']['tools']
    assert 'pages_edit' not in {tool['name'] for tool in readers}
    assert 'pages_edit_options' in {tool['name'] for tool in readers}
    denied = await call(edit_mcp, 'pages_edit', change(bio='Denied'), capability='read')
    assert 'error' in denied and edit_mcp.graphs['first'].calls == []


async def test_edit_options_reads_the_selected_page_without_mutation_or_token_leak(edit_mcp):
    result = await call(edit_mcp, 'pages_edit_options', {'page_id': '555', 'connection_id': 1}, capability='read')
    assert result['result']['isError'] is False
    data = content(result)
    assert data['page_id'] == '555' and data['connection_id'] == 1
    assert data['current']['is_always_open'] is False
    assert {'bio', 'location', 'website', 'category_ids', 'is_always_open'} <= set(data['supported_fields'])
    assert edit_mcp.graphs['first'].mutations == []
    assert 'SyntheticSystemTokenForMCP' not in json.dumps(result)
    assert 'SyntheticPageTokenForMCP' not in json.dumps(result)


@pytest.mark.parametrize('always_open', [False, True])
async def test_contact_edit_passes_only_explicit_fields_and_replays_once(edit_mcp, always_open):
    fields = {'location': {'street': '10 Test Street', 'city': 'Test City', 'country': 'United States'},
              'website': 'https://example.test/contact', 'is_always_open': always_open}
    arguments = change(**fields)
    manager = edit_mcp.workspaces['first'].manager
    before = manager.store.page('555')
    result = await call(edit_mcp, 'pages_edit', arguments)
    assert result['result']['isError'] is False
    assert content(result)['outcome'] == 'accepted' and content(result)['requires_refresh'] is True
    assert edit_mcp.graphs['first'].mutations == [fields]
    calls = list(edit_mcp.graphs['first'].calls)
    assert await call(edit_mcp, 'pages_edit', arguments) == result
    assert edit_mcp.graphs['first'].calls == calls
    assert manager.store.page('555') == before, 'An acknowledgement must not invent read-back data'
    conflicting = await call(edit_mcp, 'pages_edit', arguments | {'website': 'https://different.example.test'})
    assert conflicting['result']['isError'] is True
    assert edit_mcp.graphs['first'].calls == calls


@pytest.mark.parametrize('fields', [
    {}, {'bio': None}, {'bio': 'x' * 102}, {'location': {}}, {'location': {'street': None}},
    {'category_ids': ['1', '1']}, {'website': 'javascript:alert(1)'}, {'website': None},
    {'is_always_open': 1}, {'is_always_open': 'false'}, {'website': 'https://example.test', 'token': 'secret'},
    {'bio': 'Valid', 'workspace': 'second'},
])
async def test_invalid_edits_are_rejected_before_any_meta_request(edit_mcp, fields):
    result = await call(edit_mcp, 'pages_edit', change(**fields))
    assert result['result']['isError'] is True
    assert edit_mcp.graphs['first'].calls == []


async def test_selected_source_and_workspace_cannot_borrow_another_pages_token(edit_mcp):
    result = await call(edit_mcp, 'pages_edit', change(bio='Wrong workspace'), owner='second')
    assert result['result']['isError'] is True
    result = await call(edit_mcp, 'pages_edit', change(bio='Wrong source') | {'connection_id': 2})
    assert result['result']['isError'] is True
    assert all(graph.calls == [] for graph in edit_mcp.graphs.values())


@pytest.mark.parametrize('failure,expected', [('denied', 'failed'), ('uncertain', 'unknown'), ('identity', 'failed')])
async def test_unsuccessful_meta_edit_is_an_mcp_error_and_never_resubmitted(edit_mcp, failure, expected):
    graph = edit_mcp.graphs['first']
    if failure == 'denied':
        graph.error = GraphError('permission_limited', 200)
    elif failure == 'uncertain':
        graph.error = GraphMutationUncertain()
    else:
        graph.wrong_identity = True
    arguments = change(website='https://example.test')
    result = await call(edit_mcp, 'pages_edit', arguments)
    assert result['result']['isError'] is True
    assert content(result)['ok'] is False and content(result)['outcome'] == expected
    calls = list(graph.calls)
    assert await call(edit_mcp, 'pages_edit', arguments) == result
    assert graph.calls == calls
    assert len(graph.mutations) == (0 if failure == 'identity' else 1)


async def test_dev_read_only_retains_options_but_blocks_meta_edits(edit_mcp, monkeypatch):
    monkeypatch.setenv('PM_DEV_READ_ONLY', '1')
    denied = await call(edit_mcp, 'pages_edit', change(bio='Blocked in development'))
    assert 'error' in denied and edit_mcp.graphs['first'].calls == []
    options = await call(edit_mcp, 'pages_edit_options', {'page_id': '555', 'connection_id': 1})
    assert options['result']['isError'] is False
    assert edit_mcp.graphs['first'].mutations == []
