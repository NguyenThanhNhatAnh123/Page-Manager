"""User status overrides and durable list removal share the publishing policy."""
import json
import sqlite3
from urllib.parse import urlsplit

import pytest

from page_manager.errors import AppError
from page_manager.store import Store
from test_http_security import request
from test_list_pagination import get
from test_page_information_status import catalog, receipt
from test_posting_policy import values


def write(app, url, method, headers, body=None):
    parsed = urlsplit(url)
    async def with_query(scope, receive, send):
        await app({**scope, 'query_string': parsed.query.encode()}, receive, send)
    return request(with_query, parsed.path, method, body, headers)


@pytest.mark.parametrize('prefix', ['/api/', '/api/v1/'])
def test_explicit_status_and_automatic_history_agree_in_lists_and_policy(tmp_path, prefix):
    app, headers, store = catalog(tmp_path, count=2)
    receipt(store, page_id='1001')
    path = prefix+'pages/1000'
    assert write(app, path, 'PATCH', headers, {'revision': 1, 'information_status': 'updated'})[0] == 200
    page = app.state.manager.page('1000')['page']
    assert page['information_status_override'] == 'updated' and page['can_publish']
    assert page['management_revision'] == 2 and store.ensure_posting_ready('1000')['can_publish']
    assert app.state.manager.pages(information_status='updated', posting_eligible_only=True, limit=10)['total'] == 2
    # A manual "not updated" blocks even a Page with accepted edit history.
    assert write(app, prefix+'pages/1001', 'PATCH', headers, {'revision': 1, 'information_status': 'not_updated'})[0] == 200
    assert not store.posting_eligibility('1001')['can_publish']
    assert app.state.manager.page('1001')['page']['information_status'] == 'not_updated'
    assert app.state.manager.pages(information_status='not_updated', limit=10)['total'] == 1
    receipt(store, page_id='1001', kind='cover')
    assert not store.posting_eligibility('1001')['can_publish'], 'New receipts do not overwrite a user decision'
    assert write(app, prefix+'pages/1001', 'PATCH', headers, {'revision': 2, 'information_status': 'automatic'})[0] == 200
    assert app.state.manager.page('1001')['page']['information_status_override'] is None
    assert store.posting_eligibility('1001')['can_publish']
    assert write(app, path, 'PATCH', headers, {'revision': 2, 'information_status': 'automatic'})[0] == 200
    assert not store.posting_eligibility('1000')['can_publish'], 'Automatic restores real history, without invented receipts'
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM page_edits').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM chrome_page_setup_receipts').fetchone()[0] == 0


def test_removal_survives_sync_restart_and_retains_history_for_restore(tmp_path):
    app, headers, store = catalog(tmp_path, count=12)
    receipt(store)
    # Create a saved job to prove deletion preserves its foreign keys and blocks new publication.
    payload = values(store, 1)
    payload.update(page_id='1000', page_name='Page 0000')
    job, _ = store.reel_create(payload)
    assert write(app, '/api/v1/pages/1000?revision=1', 'DELETE', headers)[0] == 200
    assert app.state.manager.pages(limit=10)['total'] == 11
    assert app.state.manager.overview()['stats']['pages'] == 11
    assert app.state.manager.connections()['items'][0]['page_count'] == 11
    assert not store.posting_eligibility('1000')['can_publish']
    assert not app.state.reels.public(store.reel_job(job['id']))['can_resume']
    with pytest.raises(AppError) as error:
        store.ensure_posting_ready('1000')
    assert error.value.code == 'page_information_required'
    assert get(app, '/api/pages?removed=true&posting_eligible_only=true&limit=10', headers)[2]['total'] == 0
    assert get(app, '/api/pages?removed=true&limit=10', headers)[2]['items'][0]['id'] == '1000'
    assert write(app, '/api/pages/1000', 'PATCH', headers, {'revision': 2, 'information_status': 'updated'})[2]['code'] == 'page_removed'
    store.sync(1, 1, [{'id': '1000', 'name': 'New name', 'sources': ['assigned_pages']}], False, 'working', None, {})
    restarted = Store(store.root)
    assert len(restarted.catalog()[0]) == 11
    assert not restarted.posting_eligibility('1000')['can_publish']
    assert app.state.manager.page('1000')['page']['removed_at']
    assert write(app, '/api/v1/pages/1000/restore', 'POST', headers, {'revision': 2})[0] == 200
    assert app.state.manager.pages(limit=10)['total'] == 12
    assert store.posting_eligibility('1000')['can_publish']
    assert store.reel_job(job['id'])['page_id'] == '1000'
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM page_edits').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM connection_pages WHERE page_id=?', ('1000',)).fetchone()[0] == 2


def test_local_writes_require_revision_csrf_valid_state_and_existing_id(tmp_path):
    app, headers, store = catalog(tmp_path)
    path = '/api/pages/1000'
    body = {'revision': 1, 'information_status': 'updated'}
    assert write(app, path, 'PATCH', {'cookie': headers['cookie']}, body)[0] == 403
    assert write(app, path, 'PATCH', headers, {**body, 'revision': True})[0] == 422
    assert write(app, path, 'PATCH', headers, {**body, 'information_status': 'active'})[0] == 422
    assert write(app, path, 'PATCH', headers, {**body, 'token': 'must-not-be-accepted'})[0] == 422
    assert write(app, path, 'DELETE', headers)[0] == 422
    assert write(app, '/api/pages/9999', 'PATCH', headers, body)[0] == 404
    assert write(app, path, 'PATCH', headers, body)[0] == 200
    assert write(app, path, 'PATCH', headers, {**body, 'information_status': 'not_updated'})[2]['code'] == 'page_revision_changed'
    assert write(app, path+'?revision=1', 'DELETE', headers)[2]['code'] == 'page_revision_changed'
    assert app.state.manager.page('1000')['page']['can_publish']
    public = json.dumps(app.state.manager.pages())
    assert 'private-fixture-token' not in public


def test_removed_filter_and_counts_are_applied_before_pagination(tmp_path):
    app, headers, store = catalog(tmp_path, count=31)
    for index in range(0, 31, 2):
        store.manage_page(str(1000+index), 1, information_status='updated')
        store.manage_page(str(1000+index), 2, removed=True)
    first = get(app, '/api/pages?removed=true&information_status=updated&limit=10', headers)[2]
    last = get(app, '/api/pages?removed=true&information_status=updated&limit=10&offset=10', headers)[2]
    assert first['total'] == last['total'] == 16
    assert len(first['items']) == 10 and len(last['items']) == 6
    assert not {p['id'] for p in first['items']} & {p['id'] for p in last['items']}
    assert all(not p['can_publish'] for p in first['items']+last['items'])
    assert app.state.manager.pages(limit=10)['total'] == 15


def test_existing_catalog_migration_preserves_pages_and_is_repeatable(tmp_path):
    directory = tmp_path/'data'
    directory.mkdir()
    with sqlite3.connect(directory/'page-manager.sqlite3') as db:
        db.execute("""CREATE TABLE pages(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT,link TEXT,
            details TEXT NOT NULL DEFAULT '{}',checked_at TEXT,error TEXT,posts_checked_at TEXT,
            posts_has_more INTEGER NOT NULL DEFAULT 0,posts_error TEXT,posts_oldest TEXT,
            posts_latest_ids TEXT NOT NULL DEFAULT '[]')""")
        db.execute('INSERT INTO pages(id,name) VALUES(?,?)', ('1000', 'Existing Page'))
    Store(tmp_path)
    store = Store(tmp_path)
    row, _ = store.page('1000')
    assert row['name'] == 'Existing Page' and row['management_revision'] == 1
    assert row['information_status_override'] is None and row['removed_at'] is None


def test_management_permissions_are_limited_to_admin_or_own_workspace():
    from via_auth.middleware import can_access
    for method, suffix in [('PATCH', ''), ('DELETE', ''), ('POST', '/restore')]:
        for prefix in ('/pages/api/', '/pages/api/v1/'):
            path = prefix+'pages/1000'+suffix
            assert can_access({'role': 'admin'}, method, path)
            assert can_access({'role': 'operator'}, method, path, workspace_owner=True)
            assert not can_access({'role': 'operator'}, method, path)
