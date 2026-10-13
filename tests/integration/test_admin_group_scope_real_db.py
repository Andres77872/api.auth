"""Real MySQL authorization, transaction, graph-lock, and migration regressions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pymysql
import pytest

from src.Util import db_config
from src.Util.admin_scope import resolve_admin_scope
from src.Util.admin_group_scope import group_project_ids, scoped_group_page
from src.Util.db.db_user_groups import create_user_group, assign_user_to_group
from src.Util.db.db_project_groups import create_project_group
from src.Util.db_transaction import group_transaction, current_connection, after_commit
from scripts.migrations.group_scope_upgrade import upgrade
from tests.integration.admin_scope_support import AUTH, router_client
from tests.integration.conftest import _REAL_DB_CONFIG

pytestmark = [pytest.mark.real_db, pytest.mark.usefixtures('patched_db_error_logger')]
UG, PG, BULK = 'src.routes.admin_user_groups', 'src.routes.admin_project_groups', 'src.routes.bulk_operations'


@pytest.fixture
def real_graph(real_factory, real_db_conn):
    root = real_factory.create_user(user_type='root')
    admin = real_factory.create_user(user_type='admin')
    member = real_factory.create_user()
    foreign_member = real_factory.create_user()
    a, b = real_factory.create_project(), real_factory.create_project()
    pa, pb = real_factory.create_project_group(), real_factory.create_project_group()
    ua, ub = real_factory.create_user_group(), real_factory.create_user_group()
    admin_group = real_factory.create_user_group()
    with real_db_conn.cursor() as cursor:
        cursor.execute('UPDATE user_groups SET group_name = %s WHERE id = %s', ('admin_' + a['id'], admin_group['id']))
        for table, group, project in [('user_groups', ua, a), ('user_groups', ub, b),
                                       ('project_groups', pa, a), ('project_groups', pb, b)]:
            cursor.execute(f'UPDATE {table} SET scope_project_id = %s WHERE id = %s', (project['id'], group['id']))
    real_db_conn.commit()
    real_factory.link_project_to_group(a['id'], pa['id'])
    real_factory.link_project_to_group(b['id'], pb['id'])
    real_factory.link_user_group_to_project_group(ua['id'], pa['id'])
    real_factory.link_user_group_to_project_group(ub['id'], pb['id'])
    real_factory.link_user_group_to_project_group(admin_group['id'], pa['id'])
    real_factory.link_user_to_group(admin['id'], admin_group['id'])
    real_factory.link_user_to_group(member['id'], ua['id'])
    real_factory.link_user_to_group(foreign_member['id'], ub['id'])
    session = SimpleNamespace(user_id=admin['id'], user_hash=admin['user_hash'], user_type='admin',
                              permissions=['admin', 'manage_users', 'manage_roles'], project_id=a['id'])
    return SimpleNamespace(**locals())


def _fresh_connection():
    config = dict(_REAL_DB_CONFIG)
    config.pop('cursorclass', None)
    return pymysql.connect(**config)


@pytest.fixture
def live_group_db(monkeypatch):
    """Production helpers borrow one actual connection; independent calls use a fresh one."""
    monkeypatch.setattr(db_config, 'get_connection', lambda: current_connection() or _fresh_connection())
    # Names imported before the patch need the same provider outside a transaction.
    modules = ['src.Util.admin_group_scope', 'src.Util.db.db_users', 'src.Util.db.db_user_groups',
               'src.Util.db.db_project_groups', 'src.Util.db.db_projects', 'src.Util.db.db_global_roles']
    for module in modules:
        monkeypatch.setattr(module + '.get_connection', lambda: current_connection() or _fresh_connection())


async def test_real_foreign_grants_and_bulk_write_nothing(real_graph, real_db_conn, live_group_db):
    g = real_graph
    with patch(UG + '.validate_session', return_value=g.session), patch(PG + '.validate_session', return_value=g.session), \
         patch(BULK + '.validate_session', return_value=g.session):
        async with router_client(UG, PG, BULK) as client:
            grant = await client.post(f'/admin/user-groups/{g.ua["group_hash"]}/project-groups', headers=AUTH,
                                      data={'project_group_hash': g.pb['group_hash']})
            attach = await client.post(f'/admin/project-groups/{g.pa["group_hash"]}/projects', headers=AUTH,
                                       data={'project_hash': g.b['project_hash']})
            bulk = await client.post(f'/admin/user-groups/{g.ua["group_hash"]}/members/bulk', headers=AUTH,
                                     json={'user_hashes': [g.member['user_hash'], g.foreign_member['user_hash']]})
    assert [grant.status_code, attach.status_code, bulk.status_code] == [403, 403, 403]
    real_db_conn.rollback()
    with real_db_conn.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM user_group_project_groups WHERE user_group_id=%s AND project_group_id=%s', (g.ua['id'], g.pb['id']))
        assert cursor.fetchone()['total'] == 0
        cursor.execute('SELECT COUNT(*) AS total FROM project_group_members WHERE project_group_id=%s AND project_id=%s', (g.pa['id'], g.b['id']))
        assert cursor.fetchone()['total'] == 0
        cursor.execute('SELECT COUNT(*) AS total FROM user_group_members WHERE user_group_id=%s AND user_id=%s', (g.ua['id'], g.foreign_member['id']))
        assert cursor.fetchone()['total'] == 0


@pytest.mark.parametrize('kind,module', [('user', UG), ('project', PG)])
async def test_real_creation_is_empty_and_bound(real_graph, real_factory, real_db_conn, live_group_db, kind, module):
    g = real_graph
    with patch(module + '.validate_session', return_value=g.session):
        async with router_client(module) as client:
            response = await client.post(f'/admin/{kind}-groups', headers=AUTH,
                data={'group_name': 'bound-' + uuid.uuid4().hex, 'project_hash': g.a['project_hash']})
    assert response.status_code == 200, response.text
    hash = response.json()[f'{kind}_group']['group_hash']
    with real_db_conn.cursor() as cursor:
        cursor.execute(f'SELECT id, scope_project_id FROM {kind}_groups WHERE group_hash=%s', (hash,))
        row = cursor.fetchone()
        assert row['scope_project_id'] == g.a['id']
        tracking = real_factory._created_user_groups if kind == 'user' else real_factory._created_project_groups
        tracking.append(row['id'])
        table, column = ('user_group_project_groups', 'user_group_id') if kind == 'user' else ('project_group_members', 'project_group_id')
        cursor.execute(f'SELECT COUNT(*) AS total FROM {table} WHERE {column}=%s', (row['id'],))
        assert cursor.fetchone()['total'] == 0


def test_creation_rolls_back_without_orphan_or_callback(real_graph, real_db_conn, live_group_db):
    name = 'rollback-' + uuid.uuid4().hex
    callbacks = []
    with pytest.raises(RuntimeError, match='deliberate'):
        with group_transaction(write=True):
            create_user_group(name, scope_project_id=real_graph.a['id'])
            after_commit(lambda: callbacks.append('committed'))
            raise RuntimeError('deliberate failure after create')
    with real_db_conn.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM user_groups WHERE group_name=%s', (name,))
        assert cursor.fetchone()['total'] == 0
    assert callbacks == []


def test_archived_and_inactive_foreign_projects_still_constrain_scope(real_graph, real_db_conn, real_factory, live_group_db):
    g = real_graph
    real_factory.link_project_to_group(g.b['id'], g.pa['id'])
    with real_db_conn.cursor() as cursor:
        cursor.execute('UPDATE projects SET archived=1, is_active=0 WHERE id=%s', (g.b['id'],))
    real_db_conn.commit()
    with group_transaction():
        assert group_project_ids('user', g.ua['id']) == frozenset({g.a['id'], g.b['id']})
        scope = resolve_admin_scope(g.admin['id'])
        groups, total = scoped_group_page('user', scope, 1, 0, 'group_name', 'asc', None)
        assert g.ua['group_hash'] not in {group.group_hash for group in groups}
        # admin_<A> also points to the now mixed project group and is hidden.
        assert total == 0


async def test_admin_assignment_edges_are_root_only_through_project_groups(real_graph, live_group_db):
    g = real_graph
    with patch(PG + '.validate_session', return_value=g.session):
        async with router_client(PG) as client:
            response = await client.delete(f'/admin/project-groups/{g.pa["group_hash"]}/projects/{g.a["project_hash"]}', headers=AUTH)
    assert response.status_code == 403, response.text


def test_direct_writer_waits_for_authorized_transaction(real_graph, real_db_conn, live_group_db):
    started, finished = Event(), Event()
    g = real_graph
    def writer():
        connection = _fresh_connection()
        try:
            started.set()
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO project_group_members (id,project_id,project_group_id) VALUES (%s,%s,%s)',
                               ('race-' + uuid.uuid4().hex, g.b['id'], g.pa['id']))
            connection.rollback()
            finished.set()
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with group_transaction(write=True):
            future = executor.submit(writer)
            assert started.wait(2)
            assert not finished.wait(.2), 'Graph trigger must hold the direct writer outside the checked snapshot'
            assert group_project_ids('project', g.pa['id']) == frozenset({g.a['id']})
        future.result(timeout=5)
    assert finished.is_set()


def test_migration_is_idempotent_and_keeps_graph_edges(real_graph, real_db_conn):
    # Installing triggers under MySQL binary logging requires the isolated DBA,
    # not the application account used by authorization tests.
    config = dict(_REAL_DB_CONFIG, user='root', password='test_root')
    connection = pymysql.connect(**config)
    try:
        first = upgrade(connection)
        second = upgrade(connection)
    finally:
        connection.close()
    assert first == second
    assert second['lock_triggers'] == 19


async def test_empty_create_link_and_member_workflow(real_graph, real_factory, real_db_conn, live_group_db):
    g = real_graph
    with patch(UG + '.validate_session', return_value=g.session), patch(PG + '.validate_session', return_value=g.session):
        async with router_client(UG, PG) as client:
            ug = await client.post('/admin/user-groups', headers=AUTH,
                data={'group_name': 'workflow-ug-' + uuid.uuid4().hex, 'project_hash': g.a['project_hash']})
            pg = await client.post('/admin/project-groups', headers=AUTH,
                data={'group_name': 'workflow-pg-' + uuid.uuid4().hex, 'project_hash': g.a['project_hash']})
            assert ug.status_code == pg.status_code == 200
            uh, ph = ug.json()['user_group']['group_hash'], pg.json()['project_group']['group_hash']
            project = await client.post(f'/admin/project-groups/{ph}/projects', headers=AUTH,
                data={'project_hash': g.a['project_hash']})
            grant = await client.post(f'/admin/user-groups/{uh}/project-groups', headers=AUTH,
                data={'project_group_hash': ph})
            member = await client.post(f'/admin/user-groups/{uh}/members', headers=AUTH,
                data={'user_hash': g.member['user_hash']})
    assert project.status_code == grant.status_code == member.status_code == 200, (project.text, grant.text, member.text)
    with real_db_conn.cursor() as cursor:
        cursor.execute('SELECT id FROM user_groups WHERE group_hash=%s', (uh,))
        real_factory._created_user_groups.append(cursor.fetchone()['id'])
        cursor.execute('SELECT id FROM project_groups WHERE group_hash=%s', (ph,))
        real_factory._created_project_groups.append(cursor.fetchone()['id'])


async def test_root_can_rebind_empty_legacy_group_without_metadata_changes(real_graph, real_factory, real_db_conn, live_group_db):
    g = real_graph
    empty = real_factory.create_user_group()
    session = SimpleNamespace(user_id=g.root['id'], user_hash=g.root['user_hash'], user_type='root', permissions=['admin'])
    with patch(UG + '.validate_session', return_value=session):
        async with router_client(UG) as client:
            response = await client.put(f'/admin/user-groups/{empty["group_hash"]}', headers=AUTH,
                                        data={'project_hash': g.a['project_hash']})
    assert response.status_code == 200, response.text
    real_db_conn.rollback()
    with real_db_conn.cursor() as cursor:
        cursor.execute('SELECT scope_project_id, group_name FROM user_groups WHERE id=%s', (empty['id'],))
        row = cursor.fetchone()
        assert row['scope_project_id'] == g.a['id']
        assert row['group_name'] == empty['group_name']


def test_scope_binding_failure_rolls_back_the_created_row(real_graph, real_db_conn, live_group_db):
    from src.Util.error_handler import AppException
    name = 'fk-rollback-' + uuid.uuid4().hex
    with pytest.raises(AppException):
        with group_transaction(write=True):
            create_user_group(name, scope_project_id='nonexistent-scope-project')
    real_db_conn.rollback()
    with real_db_conn.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM user_groups WHERE group_name=%s', (name,))
        assert cursor.fetchone()['total'] == 0


async def test_inactive_foreign_group_active_link_still_blocks_project_group_mutation(real_graph, real_factory, real_db_conn, live_group_db):
    g = real_graph
    pg = real_factory.create_project_group()
    real_factory.link_project_to_group(g.a['id'], pg['id'])
    real_factory.link_user_group_to_project_group(g.ub['id'], pg['id'])
    with real_db_conn.cursor() as cursor:
        cursor.execute('UPDATE project_groups SET scope_project_id=%s WHERE id=%s', (g.a['id'], pg['id']))
        cursor.execute('UPDATE user_groups SET is_active=0 WHERE id=%s', (g.ub['id'],))
    real_db_conn.commit()
    with patch(PG + '.validate_session', return_value=g.session):
        async with router_client(PG) as client:
            response = await client.post(f'/admin/project-groups/{pg["group_hash"]}/projects', headers=AUTH,
                                         data={'project_hash': g.a['project_hash']})
    assert response.status_code == 403, response.text


async def test_member_removal_revokes_lost_sessions_and_invalidates_api_key_cache(real_graph, real_db_conn, live_group_db, fake_redis):
    import json
    g = real_graph
    public_id = uuid.uuid4().hex[:12]
    with real_db_conn.cursor() as cursor:
        cursor.execute('''INSERT INTO user_project_api_keys
            (id, public_id, project_id, owner_user_id, name, secret_hash, fingerprint, secret_last4)
            VALUES (%s,%s,%s,%s,'scope cache test',%s,'000000000000','test')''',
            (uuid.uuid4().hex, public_id, g.a['id'], g.member['id'], b'x' * 32))
    real_db_conn.commit()
    fake_redis.set('apikey:' + public_id, 'cached authorization')
    jti, family = uuid.uuid4().hex, uuid.uuid4().hex
    fake_redis.sadd('user_sessions:' + g.member['id'], jti)
    fake_redis.set('session:' + jti, json.dumps({'user_id': g.member['id'], 'project_id': g.a['id'], 'family_id': family}))
    fake_redis.set('session_full:' + jti, 'cached session')
    fake_redis.set('refresh_family:' + family, json.dumps({'user_id': g.member['id'], 'project_id': g.a['id'], 'status': 'active'}))
    with patch(UG + '.validate_session', return_value=g.session):
        async with router_client(UG) as client:
            response = await client.delete(f'/admin/user-groups/{g.ua["group_hash"]}/members/{g.member["user_hash"]}', headers=AUTH)
    assert response.status_code == 200, response.text
    assert not fake_redis.exists('apikey:' + public_id)
    assert not fake_redis.exists('session:' + jti, 'session_full:' + jti)
    assert json.loads(fake_redis.get('refresh_family:' + family))['status'] == 'revoked'


def test_upgrade_from_legacy_schema_backfills_only_single_project_groups(real_db_conn, tmp_path):
    """Exercise ALTER/index/FK paths and ensure migration never changes the selected DB."""
    config = dict(_REAL_DB_CONFIG, user='root', password='test_root')
    connection = pymysql.connect(**config)
    scratch = 'scope_upgrade_' + uuid.uuid4().hex
    source = config['database']
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{scratch}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        connection.select_db(scratch)
        with connection.cursor() as cursor:
            for table in ('users', 'projects', 'user_groups', 'project_groups', 'user_group_members',
                          'project_group_members', 'user_group_project_groups'):
                cursor.execute(f'CREATE TABLE `{table}` LIKE `{source}`.`{table}`')
            for table in ('user_groups', 'project_groups'):
                cursor.execute(f'ALTER TABLE {table} DROP COLUMN scope_project_id')
            for id in ('A', 'B'):
                cursor.execute('INSERT INTO projects (id,project_hash,project_name) VALUES (%s,%s,%s)', (id,id,id))
            for table in ('user_groups', 'project_groups'):
                for id in ('single', 'mixed', 'empty'):
                    cursor.execute(f'INSERT INTO {table} (id,group_hash,group_name) VALUES (%s,%s,%s)', (id,id,id))
            for id, project, pg in [('one', 'A', 'single'), ('two', 'A', 'mixed'), ('three', 'B', 'mixed')]:
                cursor.execute('INSERT INTO project_group_members (id,project_id,project_group_id) VALUES (%s,%s,%s)', (id,project,pg))
            for id in ('single', 'mixed'):
                cursor.execute('INSERT INTO user_group_project_groups (id,user_group_id,project_group_id) VALUES (%s,%s,%s)', (id,id,id))
        connection.commit()
        report = upgrade(connection, backup_dir=tmp_path)
        assert (tmp_path / 'before.json').is_file()
        assert (tmp_path / 'after.json').is_file()
        assert report['lock_triggers'] == 19
        assert upgrade(connection) == report
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE() AS selected')
            assert cursor.fetchone()['selected'] == scratch
            for table in ('user_groups', 'project_groups'):
                cursor.execute(f'SELECT id, scope_project_id FROM {table}')
                assert {row['id']: row['scope_project_id'] for row in cursor.fetchall()} == {
                    'single': 'A', 'mixed': None, 'empty': None,
                }
                cursor.execute('''SELECT COUNT(*) AS total FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND REFERENCED_TABLE_NAME='projects'
                    AND COLUMN_NAME='scope_project_id' ''', (table,))
                assert cursor.fetchone()['total'] == 1
            # A rerun must consider project-group anchors as well as access edges.
            cursor.execute("UPDATE project_groups SET scope_project_id='A' WHERE id='empty'")
            cursor.execute("UPDATE project_groups SET scope_project_id='B' WHERE id='single'")
            cursor.execute("INSERT INTO user_groups (id,group_hash,group_name) VALUES ('anchor-mixed','anchor-mixed','anchor-mixed')")
            cursor.execute("INSERT INTO user_group_project_groups (id,user_group_id,project_group_id) VALUES ('empty','empty','empty')")
            cursor.execute("INSERT INTO user_group_project_groups (id,user_group_id,project_group_id) VALUES ('anchor-mixed','anchor-mixed','single')")
        connection.commit()
        upgrade(connection)
        with connection.cursor() as cursor:
            cursor.execute('SELECT id,scope_project_id FROM user_groups')
            bindings = {row['id']: row['scope_project_id'] for row in cursor.fetchall()}
            assert bindings['empty'] == 'A'
            assert bindings['anchor-mixed'] is None
            assert bindings['single'] == 'A', 'Existing bindings must survive a rerun'
    finally:
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS `{scratch}`')
        connection.close()
