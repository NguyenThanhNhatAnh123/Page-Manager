"""Two operators cannot overwrite a newer token configuration with an old form."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from pydantic import ValidationError

from conftest import FixtureBox
from page_manager.app import create_app
from page_manager.errors import AppError
from page_manager.inputs import ConnectionInput, ConnectionUpdate
from page_manager.service import PageManager
from page_manager.store import Store
from test_http_security import request, session


def manager_at(tmp_path):
    return PageManager(tmp_path, secret_box=FixtureBox(), graph_factory=lambda: (_ for _ in ()).throw(AssertionError('No Graph')))


def test_rename_system_user_changes_only_the_local_label_and_keeps_page_access(tmp_path):
    def forbidden_graph():
        pytest.fail('Renaming a local label cannot call Meta')

    app=create_app(tmp_path,secret_box=FixtureBox(),graph_factory=forbidden_graph)
    manager=app.state.manager
    headers=session(app)
    connection=manager.save_connection(ConnectionInput(label='Original',token_type='system_user',token='FixtureOriginal82',
                                                        app_id='111',business_id='222'))
    cid=connection['id']
    manager.store.sync(cid,1,[{'id':'123','name':'Fixture Page','sources':['assigned_pages'],
                                'encrypted_page_token':'fixture-derived-token'}],True,'working',None,{'id':'456','name':'Meta identity'})
    original=manager.store.connection(cid)
    url=f'/api/v1/connections/{cid}'
    body={'label':'  Nhóm áo  ', 'revision':connection['revision']}
    assert request(app,url,'PATCH',body,{'cookie':headers['cookie']})[0]==403
    assert request(app,url,'PATCH',{**body,'business_id':'333'},headers)[0]==422
    assert request(app,url,'PATCH',{**body,'label':'  '},headers)[0]==422
    status,_,renamed=request(app,url,'PATCH',body,headers)
    assert status==200
    assert renamed=={**manager.connection_public(original),'label':'Nhóm áo','revision':connection['revision']+1}
    current=manager.store.connection(cid)
    assert current=={**original,'label':'Nhóm áo','revision':connection['revision']+1,'updated_at':current['updated_at']}
    assert manager.store.source('123',cid)['encrypted_page_token']=='fixture-derived-token'
    assert manager.store.connection_options(search='nhóm áo')['items'][0]['id']==cid
    assert request(app,url,'PATCH',{**body,'label':'Stale edit'},headers)[2]['code']=='connection_revision_changed'
    assert manager.store.connection(cid)==current
    page=manager.save_connection(ConnectionInput(label='Page',token_type='page',token='FixturePage82'))
    assert request(app,f"/api/v1/connections/{page['id']}",'PATCH',body,headers)[0]==422


def test_stale_form_cannot_restore_old_scope_or_replace_new_token(tmp_path):
    manager=manager_at(tmp_path)
    first=manager.save_connection(ConnectionInput(label='Original',token_type='page',token='FixtureOriginal82',app_id='111'))
    current=manager.save_connection(ConnectionUpdate(label='New scope',token_type='page',token='FixtureReplacement82',
        app_id='222',revision=first['revision']),first['id'])
    before=manager.store.connection(first['id'])
    with pytest.raises(AppError) as issue:
        manager.save_connection(ConnectionUpdate(label='Old form renamed',token_type='page',token='FixtureStale82',
            app_id='111',revision=first['revision']),first['id'])
    assert issue.value.code=='connection_revision_changed' and issue.value.status_code==409
    assert manager.store.connection(first['id'])==before
    assert current['revision']==first['revision']+1
    assert manager.secrets.decrypt(before['encrypted_token'])=='FixtureReplacement82'


def test_two_concurrent_operators_with_same_revision_have_one_winner(tmp_path):
    manager=manager_at(tmp_path)
    first=manager.save_connection(ConnectionInput(label='Original',token_type='page',token='FixtureOriginal82'))
    barrier=threading.Barrier(2)
    def save(label):
        barrier.wait()
        try:
            manager.store.save_connection({'label':label,'token_type':'page','revision':first['revision']},None,first['id'])
            return 'saved'
        except AppError as error:return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(save,['Operator A','Operator B']))
    assert sorted(results)==['connection_revision_changed','saved']
    row=manager.store.connection(first['id'])
    assert row['revision']==2 and row['token_revision']==1
    assert row['label'] in ('Operator A','Operator B')


def test_stale_disconnect_cannot_clear_another_operators_new_token(tmp_path):
    manager=manager_at(tmp_path)
    first=manager.save_connection(ConnectionInput(label='Original',token_type='page',token='FixtureOriginal82'))
    saved=manager.save_connection(ConnectionUpdate(label='Updated',token_type='page',token='FixtureReplacement82',revision=first['revision']),first['id'])
    with pytest.raises(AppError) as issue:manager.disconnect(first['id'],revision=first['revision'])
    assert issue.value.code=='connection_revision_changed'
    before=manager.store.connection(first['id'])
    assert before['connected'] and manager.secrets.decrypt(before['encrypted_token'])=='FixtureReplacement82'
    manager.disconnect(first['id'],revision=saved['revision'])
    assert not manager.store.connection(first['id'])['connected']


@pytest.mark.parametrize('revision',[None,True,0,'1'])
def test_connection_update_requires_an_explicit_positive_integer_revision(revision):
    values={'label':'Fixture','token_type':'page'}
    if revision is not None:values['revision']=revision
    with pytest.raises(ValidationError):ConnectionUpdate(**values)


def test_disconnect_invalidates_open_edit_form_and_migration_preserves_existing_rows(tmp_path):
    manager=manager_at(tmp_path)
    first=manager.save_connection(ConnectionInput(label='Original',token_type='page',token='FixtureOriginal82'))
    original=manager.store.connection(first['id'])
    # Simulate the preceding released schema, then reopen through normal migration.
    with manager.store.connect() as db:db.execute('ALTER TABLE connections DROP COLUMN revision')
    reopened=Store(tmp_path)
    assert reopened.connection(first['id'])['revision']==1
    assert reopened.connection(first['id'])['encrypted_token']==original['encrypted_token']
    assert reopened.connection(first['id'])['token_revision']==original['token_revision']
    manager.disconnect(first['id'])
    assert manager.store.connection(first['id'])['revision']==2
    with pytest.raises(AppError) as issue:
        manager.save_connection(ConnectionUpdate(label='Reconnect old form',token_type='page',token='FixtureStale82',revision=1),first['id'])
    assert issue.value.code=='connection_revision_changed'
